"""Tiendas de electrónica sobre VTEX: Frávega, On City, Cetrogar, Carrefour, Pardo, Coppel, Naldo...

VTEX expone el buscador de su storefront como JSON público:
    https://<tienda>/api/catalog_system/pub/products/search?ft=<texto>&_from=0&_to=49
Es la misma API que usa la propia web para listar productos, así que no hace falta navegador.

Dos modos:
  - store = una tienda VTEX ("fravega", "oncity", ...): busca en esa tienda.
  - store = "electro": busca en TODAS las tiendas de ELECTRO_STORES y se queda con la más barata
    (`seller` = tienda; si es marketplace, "tienda · vendedor").
La búsqueda usa los keywords del target y se queda con la oferta más barata que los matchee.
También informa promociones (teasers de VTEX) y el % de descuento sobre el precio de lista.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, urlparse

import httpx

from scrapers.base import DEFAULT_EXCLUDE, BaseScraper, BlockedError, ScrapeError, ScrapeResult, matches_keywords
from services.price_parser import is_plausible

if TYPE_CHECKING:
    from services.targets import Target

log = logging.getLogger("scraper.vtex")

VTEX_STORES = {
    "fravega": ("Frávega", "www.fravega.com"),
    "oncity": ("On City", "www.oncity.com"),
    "cetrogar": ("Cetrogar", "www.cetrogar.com.ar"),
    "carrefour": ("Carrefour", "www.carrefour.com.ar"),
    "pardo": ("Pardo", "www.pardo.com.ar"),
    "coppel": ("Coppel", "www.coppel.com.ar"),
    "naldo": ("Naldo", "www.naldo.com.ar"),
    "jumbo": ("Jumbo", "www.jumbo.com.ar"),
    "samsung": ("Samsung Shop", "shop.samsung.com/ar"),
    "diamond": ("Diamond Computación", "diamondcomputacion.com.ar"),
    "provincia": ("Provincia Compras", "www.provinciacompras.com.ar"),
}
# "electro" agrupa estas (Frávega va aparte porque bloquea las IPs de GitHub Actions)
ELECTRO_STORES = ["oncity", "cetrogar", "carrefour", "pardo", "coppel", "naldo", "jumbo", "samsung",
                  "diamond", "provincia"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")


def search_url(store: str, query: str) -> str:
    """URL 'humana' de búsqueda (la que se abre desde el dashboard)."""
    if store == "electro":
        return f"https://electro.vtex/?q={quote(query)}"
    host = VTEX_STORES[store][1]
    if store == "fravega":
        return f"https://{host}/l/?keyword={quote(query)}"
    return f"https://{host}/{quote(query)}?_q={quote(query)}&map=ft"


def api_search(client: httpx.Client, host: str, query: str, size: int = 50) -> list[dict]:
    # VTEX espera los espacios como %20 (con "+" algunas tiendas responden 400)
    r = client.get(f"https://{host}/api/catalog_system/pub/products/search"
                   f"?ft={quote(query)}&_from=0&_to={size - 1}")
    if r.status_code in (403, 429):
        raise BlockedError(f"{host}: HTTP {r.status_code}")
    if r.status_code not in (200, 206):
        raise ScrapeError(f"{host}: HTTP {r.status_code}")
    return r.json() if r.content else []


def offers_from(products: list[dict], store: str) -> list[dict]:
    """Aplana productos VTEX en ofertas: una por (producto, vendedor) con stock."""
    label, host = VTEX_STORES[store]
    out = []
    for p in products:
        for it in p.get("items") or []:
            for s in it.get("sellers") or []:
                o = s.get("commertialOffer") or {}
                price = o.get("Price")
                if not is_plausible(price) or not o.get("AvailableQuantity"):
                    continue
                # Frávega devuelve Price SIN IVA en algunos vendedores del marketplace y el impuesto
                # aparte en Tax: lo que se paga (y lo que muestra la web y las cuotas) es la suma.
                # En las demás tiendas Tax viene en 0, así que sumarlo siempre es seguro.
                price = float(price) + float(o.get("Tax") or 0)
                lst = o.get("ListPrice") if (o.get("ListPrice") or 0) > price else None
                teasers = [t.get("Name") or t.get("name") for t in
                           (o.get("Teasers") or []) + (o.get("PromotionTeasers") or [])
                           + (o.get("DiscountHighLight") or []) if isinstance(t, dict)]
                promo = ", ".join(dict.fromkeys(t for t in teasers if t)) or None
                free = [i.get("NumberOfInstallments") or 0 for i in (o.get("Installments") or [])
                        if not i.get("InterestRate") and (i.get("NumberOfInstallments") or 0) > 1]
                cuotas = max(free) if free else None
                seller = s.get("sellerName") or ""
                link = product_url(store, p, it)
                out.append({
                    "store": store, "label": label, "title": p.get("productName") or "",
                    "brand": p.get("brand"), "price": float(price), "list": lst, "promo": promo,
                    "cuotas": cuotas,
                    "seller": label if not seller or seller.lower() in label.lower() or
                              host.split("/")[0].split(".")[1] in seller.lower() else f"{label} · {seller}",
                    "url": link, "description": p.get("description") or "",
                })
    return out


def product_url(store: str, p: dict, item: dict) -> str:
    """Link a la ficha. Frávega dejó VTEX para su web propia: el link de la API
    (fravega.com/<linkText>/p) abre una página vacía; las fichas reales son
    /p/<nombre del producto en slug>-<itemId>/ (el itemId del item, no el productId)."""
    if store == "fravega" and item.get("itemId"):
        name = unicodedata.normalize("NFKD", p.get("productName") or "").encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return f"https://www.fravega.com/p/{slug}-{item['itemId']}/"
    host = VTEX_STORES[store][1]
    return p.get("link") or f"https://{host}/{p.get('linkText', '')}/p"


def best_match(offers: list[dict], keywords: list[str], exclude) -> dict | None:
    hits = [o for o in offers if matches_keywords(o["title"], keywords, exclude)]
    if not hits:
        return None
    from services import fravega_check

    if hits[0]["store"] == "fravega" and fravega_check.enabled():
        # La API vieja de Frávega trae productos que la web nueva no tiene o no vende: se abre la ficha
        return fravega_check.first_valid(hits)
    return min(hits, key=lambda o: o["price"])


def promo_text(o: dict) -> str | None:
    parts = []
    if o.get("cuotas"):
        parts.append(f"{o['cuotas']} cuotas sin interés")
    if o.get("list"):
        parts.append(f"-{(o['list'] - o['price']) / o['list'] * 100:.0f}% sobre lista")
    if o.get("promo"):
        parts.append(o["promo"])
    return " · ".join(parts) or None


class VtexScraper(BaseScraper):
    """No usa el navegador: llama a la API JSON del storefront."""
    store = "vtex"
    domains = tuple(h.split("/")[0] for _, h in VTEX_STORES.values()) + ("electro.vtex",)
    uses_browser = False

    def __init__(self, session, retries: int = 3, store: str | None = None):
        super().__init__(session, retries)
        self.vtex_store = store

    async def scrape(self, url: str, target: "Target") -> ScrapeResult:
        return await asyncio.to_thread(self._scrape_sync, url, target)

    def _scrape_sync(self, url: str, target: "Target") -> ScrapeResult:
        store = self.vtex_store or self._store_from_url(url)
        query = " ".join(k.split("|")[0] for k in target.keywords) or self._query_from_url(url)
        keywords = target.keywords or query.split()
        exclude = target.exclude if target.exclude is not None else DEFAULT_EXCLUDE
        stores = ELECTRO_STORES if store == "electro" else [store]
        found, errors, checked = [], [], []
        with httpx.Client(timeout=20, headers={"User-Agent": UA, "Accept": "application/json"},
                          follow_redirects=True) as client:
            for st in stores:
                try:
                    o = best_match(offers_from(api_search(client, VTEX_STORES[st][1], query), st),
                                   keywords, exclude)
                    checked.append(VTEX_STORES[st][0])
                    if o:
                        found.append(o)
                except Exception as e:  # noqa: BLE001 — una tienda caída no corta las demás
                    errors.append(f"{VTEX_STORES[st][0]}: {e}")
        label = "electro" if store == "electro" else store
        if not checked:
            return ScrapeResult(store=label, url=url, error="; ".join(errors)[:300] or "sin respuesta")
        if not found:
            note = f"(no lo tiene: {', '.join(checked)})" if store == "electro" else \
                   f"(sin resultados para {query})"
            from services import fravega_check

            if store == "fravega" and fravega_check.REJECTED:
                note = "(la API lo muestra, pero en la web de Frávega no existe o no se puede comprar)"
            return ScrapeResult(store=label, url=url, in_stock=False, title=note)
        best = min(found, key=lambda o: o["price"])
        res = ScrapeResult(store=label, url=url, title=best["title"], price_cash=best["price"],
                           price_list=best["list"], in_stock=True, seller=best["seller"],
                           product_url=best["url"])
        res.promo = promo_text(best)
        return res

    @staticmethod
    def _store_from_url(url: str) -> str:
        host = urlparse(url).netloc.lower()
        if host == "electro.vtex":
            return "electro"
        return next((k for k, (_, h) in VTEX_STORES.items()
                     if host.endswith(h.split("/")[0].replace("www.", ""))), "electro")

    @staticmethod
    def _query_from_url(url: str) -> str:
        q = parse_qs(urlparse(url).query)
        for k in ("q", "keyword", "ft", "_q"):
            if q.get(k):
                return q[k][0]
        return re.sub(r"[-_/]+", " ", urlparse(url).path).strip()
