"""Completa datos "a confirmar" leyendo el texto de la ficha de la tienda.

Muchas publicaciones (Frávega, On City, Pardo, Mexx, Maximus, Dell...) traen en su descripción
"pantalla antirreflejo", "VESA 100x100", etc. Se baja la página con un request HTTP normal (sin
navegador), se le saca el HTML y se buscan esas frases. Es un dato "blando": si descalifica, el
modelo queda a verificar (igual que los datos de Mercado Libre). Se cachea 30 días.
"""
from __future__ import annotations

import html as htmllib
import logging
import re

import httpx

log = logging.getLogger(__name__)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")
CACHE_PREFIX = "page:"
# Tiendas cuya ficha trae texto en el HTML (las SPA como Compra Gamer no sirven)
TEXT_STORES = ("fravega", "oncity", "pardo", "carrefour", "cetrogar", "coppel", "naldo", "jumbo",
               "samsung", "dell", "megatone")

ANTI_GLARE_YES = re.compile(r"anti[\s-]?(?:reflej|reflect|glare|brillo)|antirreflej|non[\s-]?glare|\bmate\b|\bmatte\b|\bopaca\b", re.I)
ANTI_GLARE_NO = re.compile(r"\bglossy\b|pantalla brillante|acabado brillante|superficie brillante", re.I)
VESA_SIZE = re.compile(r"vesa[^0-9]{0,25}(75|100)\s*(?:mm)?\s*[x×]\s*(75|100)", re.I)
VESA_ANY = re.compile(r"\bvesa\b", re.I)
VESA_NO = re.compile(r"sin\s+(?:soporte\s+)?vesa|no\s+(?:es\s+)?compatible\s+con\s+vesa|vesa:?\s*no\b", re.I)


def page_text(page_html: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page_html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t))


def specs_from_text(text: str) -> dict:
    out: dict = {}
    if ANTI_GLARE_NO.search(text):
        out["anti_glare"] = False
    elif ANTI_GLARE_YES.search(text):
        out["anti_glare"] = True
    m = VESA_SIZE.search(text)
    if m:
        out["vesa"] = f"{m.group(1)}x{m.group(2)}"
    elif VESA_NO.search(text):
        out["vesa"] = "none"
    elif VESA_ANY.search(text):
        out["vesa"] = "sí (medida sin informar)"
    return out


def fetch_specs(url: str, client: httpx.Client) -> dict:
    r = client.get(url)
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        return {}
    return specs_from_text(page_text(r.text)[:300_000])


def enrich(db, models: list, limit: int = 25) -> dict[str, dict]:
    """models: ModelResult "a confirmar". Devuelve {model_key: specs} (caché + páginas)."""
    keys = [m.key for m in models][:limit]
    cached = db.spec_cache_get([CACHE_PREFIX + k for k in keys], max_age_days=30)
    out: dict[str, dict] = {}
    with httpx.Client(timeout=20, follow_redirects=True,
                      headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"}) as client:
        for m in models[:limit]:
            ck = CACHE_PREFIX + m.key
            if ck in cached:
                if cached[ck]:
                    out[m.key] = cached[ck]
                continue
            found: dict = {}
            urls = [o["url"] for o in m.offers if o.get("store") in TEXT_STORES and o.get("url")][:2]
            for url in urls:
                try:
                    for k, v in fetch_specs(url, client).items():
                        found.setdefault(k, v)
                except Exception as e:  # noqa: BLE001
                    log.debug("Ficha %s: %s", url, e)
            if found:
                found["source"] = "la ficha de la tienda"
                found["sources"] = urls
            db.spec_cache_put(ck, found)
            if found:
                out[m.key] = found
    log.info("Specs desde fichas de tiendas: %d de %d modelos", len(out), len(keys))
    return out
