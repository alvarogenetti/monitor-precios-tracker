"""Specs que no figuran en los títulos, desde atributos del catálogo de Mercado Libre (caché).

Los títulos casi nunca dicen si la pantalla es mate, si tiene VESA o cuánto pesa; el catálogo de ML
sí lo tenía como atributos (IS_ANTI_GLARE, WITH_VESA_MOUNTING, WEIGHT_WITHOUT_STAND...). Hasta el
23/11/2026 se consultaba su API y se guardaba en la tabla spec_cache; desde que ML bloqueó el acceso
sólo se lee esa caché. Las specs curadas (config/specs.json) y tus confirmaciones siempre mandan:
ML y la ficha de la tienda (services/page_specs.py) sólo completan lo que falta.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
CACHE_DAYS = 3650   # sin vencimiento práctico: la caché ya no se renueva


def combine(ml: dict | None, page: dict | None) -> dict | None:
    """ML (estructurado) primero; la ficha de la tienda completa lo que ML no tiene."""
    if not page:
        return ml
    if not ml:
        return page
    out = dict(page)
    out.update({k: v for k, v in ml.items() if v is not None and k not in ("source", "sources")})
    out["source"] = "el catálogo de Mercado Libre y la ficha de la tienda"
    out["sources"] = list(ml.get("sources") or []) + list(page.get("sources") or [])
    return out


def merge(curated: dict | None, auto: dict | None) -> dict | None:
    """Specs curadas primero; ML completa sólo lo que falta."""
    if not auto:
        return curated
    if not curated:
        fields = [k for k in auto if k not in ("source", "sources")]
        src = auto.get("source") or "el catálogo de Mercado Libre"
        return {**auto, "confidence": "ML", "_ml_fields": fields,
                "notes": f"Fuente: {src} (sin verificar a mano): {', '.join(fields)}."}
    out = dict(curated)
    filled = [k for k, v in auto.items() if out.get(k) is None and k not in ("source", "sources")]
    for k in filled:
        out[k] = auto[k]
    out["_ml_fields"] = filled
    if filled:
        src = auto.get("source") or "el catálogo de Mercado Libre"
        out["notes"] = (out.get("notes") or "") + f" Completado con {src}: {', '.join(filled)}."
    return out


def enrich(db, keys: list[tuple[str, str, str | None]]) -> dict[str, dict]:
    """keys: (model_key, search, brand). Devuelve {model_key: spec_ML} desde la caché.

    La API de Mercado Libre ya no se consulta (acceso bloqueado el 23/11/2026): se usan los atributos
    guardados hasta entonces, sin límite de antigüedad (las specs de un modelo no cambian)."""
    cache = db.spec_cache_get([k for k, _, _ in keys], max_age_days=CACHE_DAYS)
    out = {k: v for k, v in cache.items() if v}
    log.info("Specs de ML (caché): %d de %d modelos", len(out), len(keys))
    return out
