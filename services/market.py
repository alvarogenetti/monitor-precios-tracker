"""Precio de mercado y descuento REAL.

La idea: una oferta no es "lo que la tienda dice que bajó", sino cuánto está por debajo del precio
al que ese modelo se vende normalmente en TODAS las tiendas.

  referencia = mediana del mejor precio de cada escaneo en los últimos 30 días, sin contar las
               últimas 24 h (así una baja de hoy se compara contra "antes").
               Mientras no haya historia suficiente se usa `market_price` del target (sembrado con
               el relevamiento inicial).
  descuento real = (referencia - precio) / referencia

Niveles: >= 15 % "buena oferta", >= 30 % "oferta excepcional".
Descuento inflado: la tienda muestra un "precio de lista" con, p. ej., -50 %, pero contra el mercado
la baja real es menos de la mitad de eso (o nula).
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

GOOD = 0.15
GREAT = 0.30
WINDOW_DAYS = 30
EXCLUDE_RECENT_H = 24
MIN_POINTS = 6          # escaneos mínimos en la ventana para confiar en la mediana
MIN_SPAN_DAYS = 2       # ...repartidos en al menos 2 días

LEVELS = {"excepcional": "🔥 Oferta excepcional", "buena": "💰 Buena oferta"}


def level(disc: float | None) -> str | None:
    if disc is None:
        return None
    return "excepcional" if disc >= GREAT else ("buena" if disc >= GOOD else None)


def median_reference(points: list[dict], now: datetime | None = None, min_points: int = MIN_POINTS,
                     min_span_days: int = MIN_SPAN_DAYS) -> tuple[float | None, int]:
    """points: [{ts, price}] (mejor precio por escaneo). Devuelve (mediana, n) o (None, n)."""
    now = now or datetime.now(timezone.utc)
    lo, hi = now - timedelta(days=WINDOW_DAYS), now - timedelta(hours=EXCLUDE_RECENT_H)
    pts = [(datetime.fromisoformat(p["ts"]), p["price"]) for p in points if p.get("price")]
    pts = [(t, v) for t, v in pts if lo <= t <= hi]
    if len(pts) < min_points or (max(t for t, _ in pts) - min(t for t, _ in pts)).days < min_span_days:
        return None, len(pts)
    return statistics.median(v for _, v in pts), len(pts)


def reference(points: list[dict], seed: float | None = None, now: datetime | None = None,
              **kw) -> tuple[float | None, str]:
    """(precio de referencia, de dónde sale) — la mediana de la historia, o el valor sembrado."""
    ref, n = median_reference(points, now, **kw)
    if ref:
        return ref, f"mediana de {n} escaneos (30 días)"
    if seed:
        return seed, "precio de mercado inicial (relevamiento)"
    return None, "sin historia suficiente todavía"


def real_discount(price: float | None, ref: float | None) -> float | None:
    if not price or not ref:
        return None
    return (ref - price) / ref


def claimed_discount(price: float | None, list_price: float | None) -> float | None:
    if not price or not list_price or list_price <= price:
        return None
    return (list_price - price) / list_price


def inflated(price: float | None, list_price: float | None, ref: float | None) -> bool:
    """La tienda anuncia un descuento grande que contra el mercado es menos de la mitad."""
    claimed = claimed_discount(price, list_price)
    real = real_discount(price, ref)
    return bool(claimed and claimed >= 0.20 and (real is None or real < claimed / 2))


def describe(price: float | None, list_price: float | None, ref: float | None) -> str | None:
    """Texto corto para el dashboard y las alertas."""
    real = real_discount(price, ref)
    claimed = claimed_discount(price, list_price)
    parts = []
    if real is not None:
        parts.append(f"{-real * 100:+.0f}% vs mercado")
    if claimed:
        tag = " (inflado)" if inflated(price, list_price, ref) else ""
        parts.append(f"la tienda dice -{claimed * 100:.0f}%{tag}")
    return " · ".join(parts) or None


# ------------------------------------------------------------------ cuotas sin interés
def installments(promo: str | None) -> int | None:
    """Cantidad de cuotas sin interés que informa la promo ("12 cuotas sin interés · ...")."""
    import re

    m = re.search(r"(\d{1,2})\s*cuotas\s+sin\s+inter", promo or "", re.I)
    n = int(m.group(1)) if m else None
    return n if n and n > 1 else None


def present_value(price: float, n: int, monthly_inflation: float) -> float:
    """Cuánto valen HOY n cuotas iguales sin interés (la primera al mes): con inflación, pagar en
    cuotas fijas es más barato que pagar el mismo precio de contado."""
    if not n or n <= 1 or monthly_inflation <= 0:
        return price
    cuota = price / n
    return sum(cuota / (1 + monthly_inflation) ** k for k in range(1, n + 1))


def monthly_inflation() -> float:
    """config/discovery.json -> finance.inflation_monthly (editable; 0 = no descontar)."""
    import json
    from pathlib import Path

    try:
        cfg = json.loads((Path(__file__).resolve().parent.parent / "config" / "discovery.json")
                         .read_text(encoding="utf-8"))
        return float((cfg.get("finance") or {}).get("inflation_monthly") or 0)
    except (OSError, ValueError):
        return 0.0

