"""Mercado Libre Argentina.

Soporta:
  - Ficha de publicación / catálogo: articulo.mercadolibre.com.ar/MLA-... o mercadolibre.com.ar/.../p/MLA...
  - Listado de búsqueda: listado.mercadolibre.com.ar/<termino>  (el más barato que matchee keywords)

Mercado Libre suele redirigir a tráfico automatizado a una página de verificación
(`/gz/account-verification`). En ese caso el resultado se marca como "bloqueado" y NO se
intenta evadir el control: el resto de las tiendas sigue funcionando normalmente.
ML no tiene "precio transferencia": price_cash = precio actual, price_list = precio tachado.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from playwright.async_api import Page

from scrapers.base import (
    DEFAULT_EXCLUDE,
    BlockedError,
    ScrapeError,
    ScrapeResult,
    detect_stock,
    matches_keywords,
    meta_content,
    product_from_json_ld,
    read_json_ld,
)
from scrapers.stores.generic import GenericScraper
from services.price_parser import is_plausible, parse_ars

if TYPE_CHECKING:
    from services.targets import Target

import logging

log_ml = logging.getLogger("scraper.mercadolibre.api")

LISTING_JS = """
() => Array.from(document.querySelectorAll('li.ui-search-layout__item, div.poly-card')).map(it => {
  const q = s => it.querySelector(s);
  const title = q('.poly-component__title, .ui-search-item__title, h2, h3');
  const link = q('a.poly-component__title, a.ui-search-link, a[href*="mercadolibre.com.ar"]');
  const cur = q('.poly-price__current .andes-money-amount__fraction, .ui-search-price__second-line .andes-money-amount__fraction, .andes-money-amount__fraction');
  const prev = q('s .andes-money-amount__fraction, .andes-money-amount--previous .andes-money-amount__fraction');
  const seller = q('.poly-component__seller, .ui-search-official-store-label');
  return {
    title: title ? title.textContent.trim() : '',
    href: link ? link.href : null,
    price: cur ? cur.textContent.trim() : null,
    prev: prev ? prev.textContent.trim() : null,
    seller: seller ? seller.textContent.trim() : null,
  };
})
"""

OOS_PDP_SELECTORS = ".ui-pdp-stock-information, .ui-pdp-message, .ui-pdp-container__row--paused, .andes-message"


_CLIENT = None


def meli_client():
    """Cliente de la API oficial (uno por proceso), o None si no hay credenciales."""
    global _CLIENT
    from settings import settings

    if not settings.meli_enabled:
        return None
    if _CLIENT is None:
        from services.meli_api import MeliClient

        _CLIENT = MeliClient(settings.meli_client_id, settings.meli_client_secret,
                             settings.meli_token_path, settings.meli_redirect_uri)
    return _CLIENT


def api_scrape(client, url: str, target: "Target") -> ScrapeResult:
    """Precio vía API oficial. Para búsquedas usa el catálogo: /products/search + /products/{id}/items."""
    from services.meli_api import best_offer, classify_url

    kind, ident = classify_url(url)
    exclude = target.exclude if target.exclude is not None else DEFAULT_EXCLUDE
    if kind == "item":
        it = client.item(ident)
        sellable = it.get("status") == "active" and (it.get("available_quantity") or 0) > 0
        return ScrapeResult(store="mercadolibre", url=url, title=it.get("title"),
                            price_cash=it.get("price"), price_list=it.get("original_price"),
                            in_stock=sellable, product_url=it.get("permalink") or url,
                            seller=str(it.get("seller_id") or "") or None)

    if kind == "product":
        products = [{"id": ident, "name": None}]
    else:
        q = " ".join(k.split("|")[0] for k in target.keywords) or ident or target.name
        products = [p for p in client.search_products(q)
                    if matches_keywords(p.get("name", ""), target.keywords or q.split(), exclude)]
    best = None
    for p in products[:5]:
        try:
            items = client.product_items(p["id"])
        except Exception as e:  # noqa: BLE001 — producto sin vendedores activos, etc.
            log_ml.debug("ML %s sin items: %s", p["id"], e)
            continue
        o = best_offer(items)
        if o and (best is None or o["price"] < best[1]["price"]):
            best = (p, o)
    if not best:
        return ScrapeResult(store="mercadolibre", url=url, in_stock=False,
                            title=f"(sin publicaciones activas para {target.name})")
    p, o = best
    name = p.get("name") or client.product(p["id"]).get("name")
    return ScrapeResult(store="mercadolibre", url=url, title=name, price_cash=o["price"],
                        price_list=o.get("original_price"), in_stock=True,
                        seller=str(o.get("seller_id") or "") or None,
                        product_url=f"https://www.mercadolibre.com.ar/p/{p['id']}")


class MercadoLibreScraper(GenericScraper):
    store = "mercadolibre"
    domains = ("mercadolibre.com.ar", "mercadolibre.com", "mlstatic.com")

    async def scrape(self, url: str, target: "Target") -> ScrapeResult:
        client = meli_client()
        if client is None:
            return await super().scrape(url, target)  # sin credenciales: web (suele bloquear)
        import asyncio

        try:
            return await asyncio.to_thread(api_scrape, client, url, target)
        except Exception as e:  # noqa: BLE001
            return ScrapeResult(store=self.store, url=url, error=f"API ML: {e}"[:300])

    async def extract(self, page: Page, url: str, target: "Target") -> ScrapeResult:
        await self.goto(page, url, idle_ms=5000)
        if "account-verification" in page.url or "/gz/" in urlparse(page.url).path:
            raise BlockedError("Mercado Libre pidió verificación de cuenta/anti-bot")

        host = urlparse(page.url).netloc
        if host.startswith("listado.") or "/jm/search" in page.url:
            return await self._listing(page, url, target)
        return await self._pdp(page, url)

    async def _listing(self, page: Page, url: str, target: "Target") -> ScrapeResult:
        items = await page.evaluate(LISTING_JS)
        keywords = target.keywords or [urlparse(url).path.strip("/").split("_")[0].replace("-", " ")]
        exclude = target.exclude if target.exclude is not None else DEFAULT_EXCLUDE
        offers = []
        for it in items:
            price = parse_ars(it.get("price"))
            if is_plausible(price) and matches_keywords(it.get("title", ""), keywords, exclude):
                offers.append({**it, "price_num": price})
        if not items:
            raise ScrapeError("listado vacío (cambió el HTML o la página no cargó)")
        if not offers:
            return ScrapeResult(store=self.store, url=url, in_stock=False,
                                title=f"(sin resultados para {' '.join(keywords)})")
        best = min(offers, key=lambda o: o["price_num"])
        prev = parse_ars(best.get("prev"))
        return ScrapeResult(store=self.store, url=url, title=best["title"],
                            price_cash=best["price_num"],
                            price_list=prev if prev and prev > best["price_num"] else None,
                            in_stock=True, seller=best.get("seller"),
                            product_url=best.get("href") or url)

    async def _pdp(self, page: Page, url: str) -> ScrapeResult:
        res = ScrapeResult(store=self.store, url=url, product_url=page.url)
        ld = product_from_json_ld(await read_json_ld(page), page.url)
        if ld:
            res.title, res.price_cash, res.in_stock = ld["title"], ld["price"], ld["in_stock"]

        if res.price_cash is None:
            res.price_cash = parse_ars(await meta_content(page, 'meta[itemprop="price"]'))
        if res.price_cash is None:
            el = await page.query_selector(
                ".ui-pdp-price__second-line .andes-money-amount__fraction")
            res.price_cash = parse_ars(await el.inner_text()) if el else None

        prev = await page.query_selector(
            ".ui-pdp-price__original-value .andes-money-amount__fraction, "
            "s.andes-money-amount--previous .andes-money-amount__fraction")
        prev_val = parse_ars(await prev.inner_text()) if prev else None
        if prev_val and res.price_cash and prev_val > res.price_cash:
            res.price_list = prev_val

        if res.title is None:
            h1 = await page.query_selector("h1.ui-pdp-title, h1")
            res.title = (await h1.inner_text()).strip() if h1 else None

        msgs = " ".join([await e.inner_text() for e in await page.query_selector_all(OOS_PDP_SELECTORS)])
        stock_txt = detect_stock(msgs)
        if stock_txt is False:
            res.in_stock = False
        elif res.in_stock is None:
            buy = await page.query_selector("#buybox-form button, button.andes-button--loud")
            res.in_stock = True if buy else (True if res.price_cash else None)

        if res.price_cash is None and res.in_stock is not False:
            raise ScrapeError("no se encontró precio en la publicación")
        return res
