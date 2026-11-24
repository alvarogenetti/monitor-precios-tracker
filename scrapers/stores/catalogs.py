"""Tiendas que publican su catálogo de monitores en el HTML: Dell, Megatone, Mallweb y tiendas
Tiendanube (Nickhard...).

Se lee la categoría de monitores (pocas páginas) con un request HTTP normal y se filtra por los
keywords del target. Sin navegador.

  - Dell Argentina: https://www.dell.com/es-ar/shop/computer-monitors/ar/computer-monitors?page=N
    Cada tarjeta trae un atributo `data-product-detail` con JSON (título, precio, URL).
  - Megatone: https://www.megatone.net/listado/tecnologia/informatica/monitores/ (y monitor-gamer)
    El JSON-LD `ItemList` trae los primeros 20 productos de cada categoría (el resto lo carga JS).
"""
from __future__ import annotations

import asyncio
import html as htmllib
import json
import logging
import re
from typing import TYPE_CHECKING

import httpx

from scrapers.base import DEFAULT_EXCLUDE, BaseScraper, ScrapeResult, matches_keywords
from services.price_parser import is_plausible, parse_ars

if TYPE_CHECKING:
    from services.targets import Target

log = logging.getLogger("scraper.catalogs")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")
DELL_URL = "https://www.dell.com/es-ar/shop/computer-monitors/ar/computer-monitors?page={page}"
MEGATONE_URLS = ["https://www.megatone.net/listado/tecnologia/informatica/monitores/",
                 "https://www.megatone.net/listado/tecnologia/videojuegos/monitor-gamer/"]
LABELS = {"dell": "Dell", "megatone": "Megatone", "nickhard": "Nickhard", "mallweb": "Mallweb"}


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True,
                        headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"})


def parse_dell(page_html: str) -> list[dict]:
    seen: dict[str, dict] = {}
    raws = re.findall(r"data-product-detail='([^']+)'", page_html) + \
        re.findall(r'data-product-detail="([^"]+)"', page_html)
    for raw in raws:
        try:
            data = json.loads(htmllib.unescape(raw))
        except ValueError:
            continue
        for kv in data if isinstance(data, list) else [data]:
            v = kv.get("Value", kv) if isinstance(kv, dict) else {}
            price = parse_ars(v.get("dellPrice"))
            if not v.get("productId") or not is_plausible(price):
                continue
            lst = parse_ars(v.get("marketPrice"))
            url = v.get("pdUrl") or ""
            seen[v["productId"]] = {
                "store": "dell", "title": htmllib.unescape(v.get("title") or ""), "price": price,
                "list": lst if lst and lst > price else None, "seller": "Dell",
                "url": url if url.startswith("http") else f"https://www.dell.com{url}",
            }
    return list(seen.values())


def fetch_dell(client: httpx.Client, pages: int = 6) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        r = client.get(DELL_URL.format(page=page))
        if r.status_code != 200:
            break
        got = parse_dell(r.text)
        if not got:
            break
        out += got
    return out


def parse_megatone(page_html: str) -> list[dict]:
    out = []
    for block in re.findall(r"<script[^>]*ld\+json[^>]*>(.*?)</script>", page_html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if data.get("@type") != "ItemList":
            continue
        for el in data.get("itemListElement") or []:
            item = el.get("item") or {}
            offer = item.get("offers") or {}
            price = parse_ars(offer.get("price"))
            if not is_plausible(price) or "InStock" not in str(offer.get("availability", "InStock")):
                continue
            out.append({"store": "megatone", "title": (item.get("name") or "").rstrip(". "),
                        "price": price, "list": None, "seller": "Megatone",
                        "url": (offer.get("url") or item.get("url") or "").split("?psc=")[0]})
    return out


def fetch_megatone(client: httpx.Client) -> list[dict]:
    out: list[dict] = []
    for url in MEGATONE_URLS:
        r = client.get(url)
        if r.status_code == 200:
            out += parse_megatone(r.text)
    return out


# ------------------------------------------------------------------ Tiendanube (Nickhard, ...)
TN_ITEM_SPLIT = re.compile(r'(?=<div[^>]*class="[^"]*\bjs-item-product\b)')


def parse_tiendanube(page_html: str, store: str, label: str) -> list[dict]:
    """Listado de una tienda Tiendanube: cada tarjeta trae `data-variants` (JSON con el precio de
    lista y el precio con descuento por transferencia), el nombre y el link."""
    out = []
    for chunk in TN_ITEM_SPLIT.split(page_html)[1:]:
        m = re.search(r'data-variants="([^"]*)"', chunk)
        url = re.search(r'href="([^"]*/productos/[^"]*)"', chunk)
        name = re.search(r'item-name[^>]*>\s*([^<]+?)\s*<', chunk) or re.search(r'title="([^"]+)"', chunk)
        if not (m and url and name):
            continue
        try:
            variants = json.loads(htmllib.unescape(m.group(1)))
        except ValueError:
            continue
        avail = [v for v in variants if v.get("available")]
        if not avail:
            continue
        v = min(avail, key=lambda v: v.get("price_number") or 1e18)
        lst = v.get("price_number")
        cash = parse_ars(v.get("price_with_payment_discount_short")) or lst
        if not is_plausible(cash):
            continue
        out.append({"store": store, "title": htmllib.unescape(name.group(1)), "price": cash,
                    "list": lst if lst and lst > cash else None, "seller": label,
                    "url": url.group(1)})
    return out


def fetch_tiendanube(client: httpx.Client, url: str, store: str, pages: int = 6) -> list[dict]:
    """url = búsqueda de la tienda (https://tienda/search/?q=monitor+27); recorre /search/page/N/."""
    base, _, query = url.partition("?")
    root = base.split("/search")[0]
    label = LABELS.get(store, store.capitalize())
    out: list[dict] = []
    for page in range(1, pages + 1):
        r = client.get(url if page == 1 else f"{root}/search/page/{page}/?{query}")
        if r.status_code != 200:
            break
        got = parse_tiendanube(r.text, store, label)
        if not got:
            break
        out += got
    return out


# ------------------------------------------------------------------ Mallweb
MALLWEB_URL = "https://www.mallweb.com.ar/categoria/monitores"


def parse_mallweb(page_html: str) -> list[dict]:
    """Categoría de monitores (toda en una página): tarjetas con link, nombre y precio en efectivo."""
    out = []
    for chunk in page_html.split("<article")[1:]:
        url = re.search(r'href="(/producto/\d+)"', chunk)
        name = re.search(r"<h3[^>]*>([^<]+)</h3>", chunk)
        price = re.search(r"Efectivo o transferencia</p>\s*<p[^>]*>([^<]+)</p>", chunk)
        if not (url and name and price) or re.search(r"sin stock|agotado", chunk, re.I):
            continue
        cash = parse_ars(price.group(1))
        if is_plausible(cash):
            out.append({"store": "mallweb", "title": htmllib.unescape(name.group(1)).strip(),
                        "price": cash, "list": None, "seller": "Mallweb",
                        "url": "https://www.mallweb.com.ar" + url.group(1)})
    return out


def fetch_mallweb(client: httpx.Client) -> list[dict]:
    r = client.get(MALLWEB_URL)
    return parse_mallweb(r.text) if r.status_code == 200 else []


def fetch(store: str, url: str | None = None, platform: str | None = None) -> list[dict]:
    with _client() as c:
        if platform == "tiendanube":
            return fetch_tiendanube(c, url, store)
        if store == "mallweb":
            return fetch_mallweb(c)
        return fetch_dell(c) if store == "dell" else fetch_megatone(c)


class CatalogScraper(BaseScraper):
    store = "catalog"
    domains = ("dell.com", "megatone.net")
    uses_browser = False

    async def scrape(self, url: str, target: "Target") -> ScrapeResult:
        return await asyncio.to_thread(self._scrape_sync, url, target)

    def _scrape_sync(self, url: str, target: "Target") -> ScrapeResult:
        store = "dell" if "dell.com" in url else "megatone"
        try:
            items = fetch(store)
        except Exception as e:  # noqa: BLE001
            return ScrapeResult(store=store, url=url, error=f"{LABELS[store]}: {e}"[:300])
        exclude = target.exclude if target.exclude is not None else DEFAULT_EXCLUDE
        hits = [i for i in items if matches_keywords(i["title"], target.keywords, exclude)]
        if not hits:
            return ScrapeResult(store=store, url=url, in_stock=False,
                                title=f"(no lo tiene; {len(items)} monitores en catálogo)")
        b = min(hits, key=lambda i: i["price"])
        return ScrapeResult(store=store, url=url, title=b["title"], price_cash=b["price"],
                            price_list=b["list"], in_stock=True, seller=b["seller"], product_url=b["url"])
