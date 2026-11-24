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
LABELS = {"dell": "Dell", "megatone": "Megatone", "nickhard": "Nickhard", "mallweb": "Mallweb",
          "comeros": "Comeros", "isinet": "ISInet", "auragamer": "Aura Gamer", "espaciotek": "Espaciotek",
          "zonetech": "Zonetech", "hardcore": "Hardcore Computación", "decaba": "DeCaba",
          "shopgamer": "Shopgamer", "dualkey": "Dualkey", "electrotics": "Electrotics", "gerbio": "Gerbio",
          "pcregistrada": "PC Registrada", "armytech": "Armytech", "otecno": "Otecno",
          "redsur": "Red Sur Insumos", "ultracomputacion": "Ultra Computación", "citygadgets": "City Gadgets",
          "novaonline": "Nova Online", "clanco": "Clanco", "710tech": "710 Technology",
          "pcstore": "PC Store", "supportoficial": "Support Oficial", "bestinformatica": "Best Informática",
          "huntergaming": "Hunter Gaming", "ngtechnologies": "NG Technologies", "westsolution": "West Solution",
          "hardloots": "HardLoots", "astrohard": "Astro Hard", "libreopcion": "Libre Opción",
          "seguimientogamer": "Seguimiento Gamer"}


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
        if url and name and not m:
            # Otros temas: sin data-variants, el precio va en data-product-price (en centavos)
            pp = re.search(r'data-product-price="(\d+)"', chunk)
            lab = re.search(r'data-label="Sin stock"[^>]*style="([^"]*)"', chunk)
            no_stock = bool(lab) and "display:none" not in lab.group(1).replace(" ", "").lower()
            if pp and not no_stock:
                price = int(pp.group(1)) / 100
                if is_plausible(price):
                    out.append({"store": store, "title": htmllib.unescape(name.group(1)), "price": price,
                                "list": None, "seller": label, "url": url.group(1)})
            continue
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


# ------------------------------------------------------------------ WooCommerce (Store API pública)
def parse_woocommerce(items: list[dict], store: str, label: str) -> list[dict]:
    out = []
    for p in items:
        if p.get("is_in_stock") is False or p.get("is_purchasable") is False:
            continue
        pr = p.get("prices") or {}
        div = 10 ** int(pr.get("currency_minor_unit") or 0)
        try:
            price = int(pr.get("price") or 0) / div
            regular = int(pr.get("regular_price") or 0) / div
        except ValueError:
            continue
        if not is_plausible(price):
            continue
        out.append({"store": store, "title": htmllib.unescape(p.get("name") or ""), "price": price,
                    "list": regular if regular > price else None, "seller": label,
                    "url": p.get("permalink") or ""})
    return out


def fetch_woocommerce(client: httpx.Client, url: str, store: str, pages: int = 4) -> list[dict]:
    """url = https://tienda/wp-json/wc/store/v1/products?search=monitor%2027 (se pagina con &page=N)."""
    label = LABELS.get(store, store.capitalize())
    out: list[dict] = []
    sep = "&" if "?" in url else "?"
    for page in range(1, pages + 1):
        r = client.get(f"{url}{sep}per_page=100&page={page}")
        if r.status_code != 200:
            break
        items = r.json()
        if not items:
            break
        out += parse_woocommerce(items, store, label)
        if len(items) < 100:
            break
    return out


# ------------------------------------------------------------------ Shopify (products.json público)
def parse_shopify(products: list[dict], base: str, store: str, label: str, word: str = "monitor") -> list[dict]:
    out = []
    for p in products:
        title = p.get("title") or ""
        if word not in title.lower():
            continue
        avail = [v for v in p.get("variants") or [] if v.get("available", True)]
        if not avail:
            continue
        v = min(avail, key=lambda v: float(v.get("price") or 1e18))
        price, cmp = float(v.get("price") or 0), float(v.get("compare_at_price") or 0)
        if is_plausible(price):
            out.append({"store": store, "title": title, "price": price,
                        "list": cmp if cmp > price else None, "seller": label,
                        "url": f"{base}/products/{p.get('handle')}"})
    return out


def fetch_shopify(client: httpx.Client, url: str, store: str, pages: int = 8) -> list[dict]:
    """url = https://tienda (o cualquier página): recorre /products.json y se queda con los monitores."""
    base = "/".join(url.split("/")[:3])
    label = LABELS.get(store, store.capitalize())
    out: list[dict] = []
    for page in range(1, pages + 1):
        r = client.get(f"{base}/products.json?limit=250&page={page}")
        if r.status_code != 200:
            break
        prods = r.json().get("products") or []
        if not prods:
            break
        out += parse_shopify(prods, base, store, label)
    return out


# ------------------------------------------------------------------ Qloud / GlobalDrop (Microglobal)
def parse_qloud(page_html: str, store: str, label: str) -> list[dict]:
    """Tarjetas `<div ... data-nombre="..." data-precio="...">` con el link al producto adentro."""
    out = []
    parts = re.split(r'(?=<div[^>]*\bdata-nombre=")', page_html)[1:]
    for chunk in parts:
        name = re.search(r'data-nombre="([^"]+)"', chunk)
        price = re.search(r'data-precio="(\d+(?:\.\d+)?)"', chunk)
        url = re.search(r'href="(https?://[^"]+\.html)"', chunk)
        if not (name and price and url) or re.search(r"(?i)sin stock|agotado", chunk[:4000]):
            continue
        p = float(price.group(1))
        if is_plausible(p):
            out.append({"store": store, "title": htmllib.unescape(name.group(1)), "price": p,
                        "list": None, "seller": label, "url": url.group(1)})
    return out


def fetch_qloud(client: httpx.Client, url: str, store: str) -> list[dict]:
    r = client.get(url)
    return parse_qloud(r.text, store, LABELS.get(store, store.capitalize())) if r.status_code == 200 else []


# ------------------------------------------------------------------ PrestaShop (dataLayer de GA4)
def parse_prestashop(page_html: str, base: str, store: str, label: str) -> list[dict]:
    """Los resultados de búsqueda vienen en el dataLayer (item_name, item_id, price, quantity)."""
    out, seen = [], set()
    for m in re.finditer(r'\{"item_name":"((?:[^"\\]|\\.)*)","item_id":"(\d+)","price":"([\d.]+)"(.*?)\}', page_html):
        name, pid, price, rest = m.groups()
        q = re.search(r'"quantity":(\d+)', rest)
        if pid in seen or (q and int(q.group(1)) <= 0):
            continue
        seen.add(pid)
        p = float(price)
        if is_plausible(p):
            out.append({"store": store, "title": json.loads(f'"{name}"'), "price": p, "list": None,
                        "seller": label, "url": f"{base}/index.php?controller=product&id_product={pid}"})
    return out


def fetch_prestashop(client: httpx.Client, url: str, store: str, pages: int = 4) -> list[dict]:
    base = "/".join(url.split("/")[:3])
    label = LABELS.get(store, store.capitalize())
    out: list[dict] = []
    for page in range(1, pages + 1):
        r = client.get(url if page == 1 else f"{url}&page={page}")
        if r.status_code != 200:
            break
        got = [x for x in parse_prestashop(r.text, base, store, label) if x["url"] not in {o["url"] for o in out}]
        if not got:
            break
        out += got
    return out


# ------------------------------------------------------------------ TiendaNegocio (estado de Angular)
def parse_tiendanegocio(page_html: str, base: str, store: str, label: str) -> list[dict]:
    m = re.search(r'<script[^>]*id="[^"]*-state"[^>]*>(.*?)</script>', page_html, re.S)
    if not m:
        return []
    try:
        state = json.loads(m.group(1).replace("&q;", '"').replace("&a;", "&").replace("&l;", "<")
                           .replace("&g;", ">").replace("&s;", "'"))
    except ValueError:
        return []
    out = []
    for key, val in state.items():
        prods = val.get("products") if isinstance(val, dict) else None
        for p in prods or []:
            if not p.get("status") or (p.get("stock") is not None and p["stock"] <= 0):
                continue
            lst = p.get("promo") or p.get("price")
            cash = p.get("discount_min_price") or lst
            if is_plausible(cash):
                out.append({"store": store, "title": p.get("title") or "", "price": float(cash),
                            "list": float(lst) if lst and lst > cash else None, "seller": label,
                            "url": f"{base}/producto/{p.get('hash')}"})
    return out


def fetch_tiendanegocio(client: httpx.Client, url: str, store: str) -> list[dict]:
    r = client.get(url)
    base = "/".join(url.split("/")[:3])
    return parse_tiendanegocio(r.text, base, store, LABELS.get(store, store.capitalize())) if r.status_code == 200 else []


# ------------------------------------------------------------------ Libre Opción (marketplace, API JSON)
def parse_libreopcion(data: dict, store: str) -> list[dict]:
    """Marketplace con varios vendedores (Gears Store, STORE GS, BsAsPC...): una oferta por ítem."""
    out = []
    for it in data.get("items") or []:
        pr = it.get("price") or {}
        price, lst = pr.get("finalPrice"), pr.get("listPrice")
        if not is_plausible(price):
            continue
        out.append({"store": store, "title": it.get("description") or "", "price": float(price),
                    "list": float(lst) if lst and lst > price else None,
                    "seller": f"Libre Opción · {it.get('sellerName')}" if it.get("sellerName") else "Libre Opción",
                    "url": f"https://libreopcion.com.ar/p-P{it.get('id')}?catalogue=1"})
    return out


def fetch_libreopcion(client: httpx.Client, url: str, store: str) -> list[dict]:
    r = client.get(url + ("&" if "?" in url else "?") + "limit=60")
    return parse_libreopcion(r.json(), store) if r.status_code == 200 else []


# ------------------------------------------------------------------ Seguimiento Gamer (comparador, JSON)
def parse_seguimientogamer(data: dict, store: str) -> list[dict]:
    """categoria-monitores.json: t = tiendas [clave, nombre]; p = [id, título, i_tienda, _, precio,
    variación %, 0 si hoy está disponible (si no, la fecha en que dejó de estarlo)]."""
    stores = data.get("t") or []
    out = []
    for p in data.get("p") or []:
        try:
            pid, title, si, _, price, _, gone = p[:7]
            key, name = stores[si]
        except (ValueError, IndexError, TypeError):
            continue
        if gone or not is_plausible(price):
            continue
        out.append({"store": store, "title": title, "price": float(price), "list": None,
                    "seller": f"{name} (vía Seguimiento Gamer)",
                    "url": f"https://seguimientogamer.com.ar/producto/{key}/{pid}/"})
    return out


def fetch_seguimientogamer(client: httpx.Client, url: str, store: str) -> list[dict]:
    r = client.get(url)
    return parse_seguimientogamer(r.json(), store) if r.status_code == 200 else []


PLATFORMS = ("tiendanube", "woocommerce", "shopify", "qloud", "prestashop", "tiendanegocio",
             "libreopcion", "seguimientogamer")


def fetch(store: str, url: str | None = None, platform: str | None = None) -> list[dict]:
    with _client() as c:
        if platform == "woocommerce":
            return fetch_woocommerce(c, url, store)
        if platform == "qloud":
            return fetch_qloud(c, url, store)
        if platform == "libreopcion":
            return fetch_libreopcion(c, url, store)
        if platform == "seguimientogamer":
            return fetch_seguimientogamer(c, url, store)
        if platform == "prestashop":
            return fetch_prestashop(c, url, store)
        if platform == "tiendanegocio":
            return fetch_tiendanegocio(c, url, store)
        if platform == "shopify":
            return fetch_shopify(c, url, store)
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
