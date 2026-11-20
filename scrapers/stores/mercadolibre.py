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


class MercadoLibreScraper(GenericScraper):
    store = "mercadolibre"
    domains = ("mercadolibre.com.ar", "mercadolibre.com", "mlstatic.com")

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
