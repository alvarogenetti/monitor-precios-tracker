"""«Qué compraría hoy»: una recomendación corta a partir de lo que cumple todos los requisitos.

Mira los seguidos y los modelos del descubrimiento (marcas conocidas) que cumplen todo y responde:
cuál es el más barato, cuál es la opción USB-C más barata (y cuánto más sale) y si conviene comprar
ahora (hay oferta real) o esperar (no hay oferta y se viene un evento).
"""
from __future__ import annotations

from datetime import datetime

from services.tracker import fmt_ars


def _cands(rows: list[dict], models: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        b = r.get("best")
        if r["target"].kind != "monitor" or not b or (r.get("eval") or {}).get("status") != "cumple":
            continue
        out.append({"name": r["target"].name, "price": b["price_cash"], "store": b.get("seller") or b["store"],
                    "url": b.get("product_url") or b.get("url"), "usb_c": bool(r.get("usb_c")),
                    "real": r.get("real"), "level": r.get("level"), "tracked": True,
                    "cuotas": r.get("cuotas")})
    for m in models:
        if m.get("tracked") or m.get("generic") or m.get("status") != "cumple":
            continue
        b = m["best"]
        out.append({"name": m["name"], "price": b["price"], "store": b.get("seller") or b["store"],
                    "url": b.get("url"), "usb_c": bool(m.get("usb_c")), "real": m.get("real"),
                    "level": m.get("level"), "tracked": False})
    return sorted(out, key=lambda c: c["price"])


def buy_today(rows: list[dict], models: list[dict], now: datetime | None = None) -> dict | None:
    from services.events import current_or_next

    cands = _cands(rows, models)
    if not cands:
        return None
    cheapest = cands[0]
    usbc = next((c for c in cands if c["usb_c"]), None)
    offers = sorted((c for c in cands if c["level"]), key=lambda c: -(c["real"] or 0))
    ev, days = current_or_next(now, within_days=14)
    if offers:
        o = offers[0]
        verdict = (f"Comprá: {o['name']} está {o['real'] * 100:.0f} % debajo del mercado "
                   f"({fmt_ars(o['price'])} en {o['store']}).")
        action = "comprar"
    elif ev and days == 0:
        verdict = (f"{ev['name']} en curso y todavía ninguno está 15 % o más debajo del mercado: "
                   "esperá, se revisa cada hora.")
        action = "esperar"
    elif ev:
        verdict = (f"Ninguno está en oferta real. Faltan {days} día{'s' if days != 1 else ''} para "
                   f"{ev['name']}: conviene esperar.")
        action = "esperar"
    else:
        verdict = "Ninguno está en oferta real. No hay apuro: avisa cuando alguno baje 15 % o más."
        action = "esperar"
    return {"cheapest": cheapest, "usbc": usbc,
            "usbc_extra": usbc["price"] - cheapest["price"] if usbc and usbc is not cheapest else 0,
            "offers": offers[:3], "verdict": verdict, "action": action}


def telegram_lines(adv: dict | None) -> list[str]:
    import html

    if not adv:
        return []
    c, u = adv["cheapest"], adv["usbc"]
    lines = ["🧭 <b>Qué compraría hoy</b>",
             f"• Más barato que cumple todo: {html.escape(c['name'])} — <b>{fmt_ars(c['price'])}</b> "
             f"({html.escape(c['store'])})"]
    if u and u is not c:
        cq = u.get("cuotas")
        lines.append(f"• Con USB-C: {html.escape(u['name'])} — {fmt_ars(u['price'])} "
                     f"(+{fmt_ars(adv['usbc_extra'])})"
                     + (f"; en {cq['n']} cuotas ≈ {fmt_ars(cq['pv'])} de hoy" if cq else ""))
    lines.append(f"→ {html.escape(adv['verdict'])}")
    return lines + [""]
