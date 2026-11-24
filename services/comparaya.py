"""ComparaYa (comparaya.net): comparador con 251 tiendas, incluido Mercado Libre (es afiliado de ML).

Su robots.txt permite las fichas de producto (/p/...) y prohíbe /api/ (de ahí cargan el buscador y
los listados), así que se leen SOLO fichas, armando la dirección desde la marca y el código:
monitor-<marca>-<código>-27. Lo que no se encuentra así se puede fijar a mano en
config/discovery.json → comparaya_slugs {"CLAVE": "slug"}.

De cada ficha se toman las ofertas **nuevas** y sólo de:
  - Mercado Libre (lo que nosotros no podemos leer), y
  - tiendas cuyo dominio no leímos directo en este descubrimiento (para no duplicar ni pisar precios
    propios, que son más frescos).

Una consulta por ficha cada ~1,5 s, una vez por descubrimiento. Las direcciones encontradas se
recuerdan 30 días y las que no existen se reintentan a los 7 (tabla spec_cache, clave "comparaya:...").
"""
from __future__ import annotations

import html as htmllib
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

BASE = "https://comparaya.net/p/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
STORE = "comparaya"
MAX_MODELS = 80
PAUSE_S = 1.5


def _txt(s: str) -> str:
    return htmllib.unescape(re.sub(r"<!-- -->", "", re.sub(r"<[^>]+>", "", s))).strip()


def _money(s: str | None) -> float | None:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return float(digits) if digits else None


def parse(page: str) -> list[dict]:
    """Ofertas nuevas de una ficha: [{shop, title, price, list, url, intl}]."""
    i = page.find("Precios por tienda")
    if i < 0:
        return []
    j = page.find("</ol>", i)
    block = page[i:j if j > 0 else None]
    out = []
    for li in re.findall(r"<li\b.*?</li>", block, re.S):
        shop = re.search(r"<span[^>]*>([^<]+)</span>", li)
        title = re.search(r'<p[^>]*title="([^"]*)"', li)
        price = re.search(r"<p[^>]*>\$(?:<!-- -->)?([\d.]+)</p>", li)
        lst = re.search(r"<span[^>]*>\$(?:<!-- -->)?([\d.]+)</span>", li)
        url = re.search(r'<a[^>]*href="(https?://[^"]+)"', li)
        if not (shop and price and url):
            continue
        p = _money(price.group(1))
        lp = _money(lst.group(1)) if lst else None
        out.append({"shop": _txt(shop.group(1)), "title": htmllib.unescape(title.group(1)) if title else "",
                    "price": p, "list": lp if lp and p and lp > p else None,
                    "url": htmllib.unescape(url.group(1)), "intl": ">Internacional<" in li})
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def is_ml(o: dict) -> bool:
    return "mercadolibre.com" in o["url"] or o["shop"].lower().startswith("mercado libre")


def host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def slug_candidates(brand: str | None, key: str, search: str | None) -> list[str]:
    b = re.sub(r"[^a-z0-9]+", "-", (brand or "").lower()).strip("-")
    if not b:
        return []
    codes = []
    for c in (key, search or ""):
        c = re.sub(r"[^a-z0-9]+", "-", c.lower()).strip("-")
        if c and "~" not in c and c not in codes and len(c) >= 4:
            codes.append(c)
    out = []
    for c in codes:
        out += [f"monitor-{b}-{c}-27", f"monitor-{b}-{c}"]
    return out


def _cache_key(key: str) -> str:
    return f"comparaya:{key}"


def find_page(client: httpx.Client, db, key: str, brand: str | None, search: str | None,
              manual: str | None) -> tuple[str | None, str | None]:
    """(slug, html) de la ficha del modelo, o (None, None). Usa la caché y la marca a mano."""
    cands = [manual] if manual else []
    cached = db.spec_cache_get([_cache_key(key)], max_age_days=30).get(_cache_key(key)) if db else None
    if cached and not manual:
        if cached.get("slug"):
            cands = [cached["slug"]]
        elif cached.get("checked", "") >= _days_ago(7):
            return None, None              # no existe: se vuelve a probar en unos días
    if not cands:
        cands = slug_candidates(brand, key, search)
    for slug in cands:
        r = client.get(BASE + slug)
        time.sleep(PAUSE_S)
        if r.status_code == 200 and "Precios por tienda" in r.text:
            if db:
                db.spec_cache_put(_cache_key(key), {"slug": slug, "checked": _now()})
            return slug, r.text
    if db:
        db.spec_cache_put(_cache_key(key), {"slug": None, "checked": _now()})
    return None, None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _days_ago(n: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat(timespec="seconds")


def _name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def known_shop(shop: str, own_names: set[str]) -> bool:
    """La tienda ya la leemos (directo o vía HardGamers/Seguimiento Gamer)? Compara por nombre:
    "Amonpul" = "Amonpul Team", "MyM" = "MyM Computación"."""
    n = _name(shop)
    return len(n) >= 3 and any(n == o or (len(o) >= 3 and (o.startswith(n) or n.startswith(o))) for o in own_names)


def collect(db, models: list[dict], own_hosts: set[str], manual: dict[str, str] | None = None,
            stats: list[dict] | None = None, own_names: set[str] | None = None) -> list[dict]:
    """models: [{key, brand, search}] (los que vale la pena mirar). Devuelve ofertas para el
    descubrimiento: {store, title, price, list, url, seller}."""
    manual = manual or {}
    out, found, err = [], 0, None
    try:
        with httpx.Client(timeout=30, follow_redirects=True,
                          headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"}) as c:
            for m in models[:MAX_MODELS]:
                slug, page = find_page(c, db, m["key"], m.get("brand"), m.get("search"), manual.get(m["key"]))
                if not page:
                    continue
                found += 1
                codes = {_norm(x) for x in (m["key"], m.get("search") or "") if len(_norm(x)) >= 4}
                for o in parse(page):
                    if not o["price"]:
                        continue
                    if not is_ml(o) and (host(o["url"]) in own_hosts or known_shop(o["shop"], own_names or set())):
                        continue      # esa tienda ya la leemos: su precio propio es más fresco
                    if not any(c in _norm(o["title"]) for c in codes):
                        continue      # la ficha junta "versiones": sólo el modelo exacto
                    where = o["shop"] + (" · Internacional" if o["intl"] else "")
                    out.append({"store": STORE, "title": o["title"] + (" [Internacional]" if o["intl"] else ""),
                                "price": o["price"], "list": o["list"], "url": o["url"],
                                "seller": f"{where} (vía ComparaYa)"})
    except Exception as e:  # noqa: BLE001
        log.warning("ComparaYa: %s", e)
        err = str(e)[:160]
    log.info("ComparaYa: %d fichas de %d modelos, %d ofertas (%d de Mercado Libre)", found,
             min(len(models), MAX_MODELS), len(out), sum(1 for o in out if "Mercado Libre" in o["seller"]))
    if stats is not None:
        stats.append({"store": STORE, "n": len(out), "error": err if err else (None if out else "0 resultados")})
    return out
