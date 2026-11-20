"""Normalización de precios en formato argentino (ARS).

Ejemplos soportados:
    "$ 340.869,00" -> 340869.0
    "$339.785"     -> 339785.0
    "ARS 418.299"  -> 418299.0
    "340869.00"    -> 340869.0   (formato JSON-LD / API)
    "1.234.567,5"  -> 1234567.5
"""
from __future__ import annotations

import re

_NUM_RE = re.compile(r"\d[\d.,]*")
# "$ 1.234", "$1.234,56", "ARS 1.234" (con espacios normales o no separables)
_CURRENCY_RE = re.compile(r"(?:\$|ARS)\s*(\d[\d.,]*)", re.IGNORECASE)

# Rango razonable para un monitor en ARS: evita confundir cuotas ("12"), porcentajes, etc.
MIN_PRICE = 1_000
MAX_PRICE = 100_000_000


def _normalize_token(tok: str) -> float | None:
    tok = tok.strip(".,")
    if not tok:
        return None
    has_dot, has_comma = "." in tok, "," in tok
    if has_dot and has_comma:
        # El separador que aparece último es el decimal.
        if tok.rfind(",") > tok.rfind("."):
            tok = tok.replace(".", "").replace(",", ".")
        else:
            tok = tok.replace(",", "")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        parts = tok.split(sep)
        if len(parts) > 2:
            # "1.234.567" -> miles
            tok = tok.replace(sep, "")
        else:
            # Un único separador: 3 dígitos después = miles ("339.785"),
            # 1-2 dígitos = decimales ("340869,5" / "340869.00").
            tok = tok.replace(sep, "") if len(parts[1]) == 3 else tok.replace(sep, ".")
    try:
        return float(tok)
    except ValueError:
        return None


def parse_ars(value: object) -> float | None:
    """Convierte un string/número de precio en ARS a float. Devuelve None si no hay precio."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value).replace("\xa0", " ").replace(" ", " ")
    # "340 869" (espacio como separador de miles) -> "340869"
    text = re.sub(r"(?<=\d) (?=\d{3}\b)", "", text)
    m = _CURRENCY_RE.search(text) or _NUM_RE.search(text)
    if not m:
        return None
    tok = m.group(1) if m.re is _CURRENCY_RE else m.group(0)
    val = _normalize_token(tok)
    return val if val and val > 0 else None


def extract_prices(text: str) -> list[float]:
    """Encuentra todos los montos precedidos por '$' o 'ARS' dentro de un texto libre."""
    if not text:
        return []
    text = text.replace("\xa0", " ").replace(" ", " ")
    out: list[float] = []
    for m in _CURRENCY_RE.finditer(text):
        v = _normalize_token(m.group(1))
        if v and MIN_PRICE <= v <= MAX_PRICE:
            out.append(v)
    return out


def is_plausible(price: float | None) -> bool:
    return price is not None and MIN_PRICE <= price <= MAX_PRICE
