"""Completa specs que no figuran en los títulos usando el catálogo de Mercado Libre.

Los títulos de las tiendas casi nunca dicen si la pantalla es mate, si tiene VESA o cuánto pesa.
El catálogo de ML sí tiene esos datos como atributos estructurados (IS_ANTI_GLARE,
WITH_VESA_MOUNTING, WEIGHT_WITHOUT_STAND, IS_CURVED, BRIGHTNESS, WITH_FLICKER_FREE, VOLTAGE...).

Para cada modelo "a confirmar" se busca su producto de catálogo (que su MODEL / nombre contenga el
código del modelo), se traducen los atributos al formato de config/specs.json y se cachea 30 días
en la tabla spec_cache. Las specs curadas a mano (config/specs.json) siempre tienen prioridad:
ML sólo completa los campos que faltan.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)
CACHE_DAYS = 30


def _num(v: Any) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(v or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def _yes(v: Any) -> bool | None:
    s = str(v or "").strip().lower()
    return True if s in ("sí", "si", "yes") else (False if s in ("no",) else None)


def attrs_to_spec(attrs: dict[str, Any], product_id: str) -> dict:
    res = None
    m = re.search(r"(\d{3,4})\s*px\s*x\s*(\d{3,4})", str(attrs.get("DISPLAY_RESOLUTION") or ""))
    if m:
        res = f"{m.group(1)}x{m.group(2)}"
    vesa = _yes(attrs.get("WITH_VESA_MOUNTING"))
    curved = _yes(attrs.get("IS_CURVED"))
    hz = _num(attrs.get("MAX_REFRESH_RATE") or attrs.get("RECOMMENDED_REFRESH_RATE"))
    spec = {
        "panel": attrs.get("PANEL_TYPE"),
        "flat": None if curved is None else not curved,
        "resolution": res,
        "hz_dp": int(hz) if hz else None,
        "anti_glare": _yes(attrs.get("IS_ANTI_GLARE")),
        "brightness_nits": int(_num(attrs.get("BRIGHTNESS")) or 0) or None,
        "flicker_free": _yes(attrs.get("WITH_FLICKER_FREE")),
        "low_blue_light": _yes(attrs.get("WITH_BLUE_LIGHT_REDUCTION")),
        # ML sólo dice si tiene VESA, no la medida (75x75 / 100x100)
        "vesa": "sí (medida sin informar)" if vesa else ("none" if vesa is False else None),
        "weight_no_stand_kg": _num(attrs.get("WEIGHT_WITHOUT_STAND")),
        "psu_voltage": attrs.get("VOLTAGE"),
        "source": "mercadolibre",
        "sources": [f"https://www.mercadolibre.com.ar/p/{product_id}"],
    }
    return {k: v for k, v in spec.items() if v is not None}


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def lookup_ml(client, key: str, search: str, brand: str | None) -> dict | None:
    """Busca el producto de catálogo del modelo y devuelve sus specs (o None)."""
    q = " ".join(x for x in ("Monitor", brand or "", search) if x).strip()
    k = _norm(key.split("~")[0])
    if len(k) < 4:
        return None
    for p in client.search_products(q):
        if k in _norm(p.get("name", "")):
            break
    else:
        p = None
    if p is None:
        return None
    d = client.product(p["id"])
    attrs = {a["id"]: a.get("value_name") for a in d.get("attributes", [])}
    model = _norm(" ".join(str(attrs.get(x) or "") for x in ("MODEL", "ALPHANUMERIC_MODEL", "LINE")))
    if k not in model and k not in _norm(d.get("name", "")):
        return None
    return attrs_to_spec(attrs, p["id"])


def merge(curated: dict | None, auto: dict | None) -> dict | None:
    """Specs curadas primero; ML completa sólo lo que falta."""
    if not auto:
        return curated
    if not curated:
        return {**auto, "confidence": "ML"}
    out = dict(curated)
    filled = [k for k, v in auto.items() if out.get(k) is None and k not in ("source", "sources")]
    for k in filled:
        out[k] = auto[k]
    if filled:
        out["notes"] = (out.get("notes") or "") + f" Completado con el catálogo de ML: {', '.join(filled)}."
    return out


def enrich(db, keys: list[tuple[str, str, str | None]]) -> dict[str, dict]:
    """keys: (model_key, search, brand). Devuelve {model_key: spec_ML} usando caché + API."""
    from scrapers.stores.mercadolibre import meli_client

    out: dict[str, dict] = {}
    cache = db.spec_cache_get([k for k, _, _ in keys], max_age_days=CACHE_DAYS)
    client = None
    for key, search, brand in keys:
        if key in cache:
            if cache[key]:
                out[key] = cache[key]
            continue
        client = client or meli_client()
        if client is None:
            break
        try:
            spec = lookup_ml(client, key, search, brand)
        except Exception as e:  # noqa: BLE001
            log.debug("Specs ML %s: %s", key, e)
            continue
        db.spec_cache_put(key, spec or {})
        if spec:
            out[key] = spec
    log.info("Specs desde ML: %d de %d modelos", len(out), len(keys))
    return out

