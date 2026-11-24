"""Resumen diario por Telegram: mejor precio de cada monitor y en qué rango está."""
from __future__ import annotations

import html

from services.tracker import fmt_ars

PAGES_URL = "https://alvarogenetti.github.io/monitor-precios-tracker/"
EMOJI = {"bajo": "🟢", "normal": "🔵", "alto": "🔴", None: "⚪"}


def pre_event_block(db, rows, now=None) -> list[str]:
    """Si un evento empieza en <= 2 días (o ya empezó y no se congeló), guarda el precio de mercado
    de cada seguido como referencia del evento y devuelve el bloque para el resumen (una sola vez)."""
    from services.events import current_or_next, event_key
    from services.market import reference

    ev, days = current_or_next(now, within_days=2)
    if not ev or db.event_refs(event_key(ev)):
        return []
    refs = {}
    for r in rows:
        t = r["target"]
        ref, _ = reference(db.best_series(t.id, days=31), seed=t.market_price)
        refs[t.id] = (ref, r["best"]["price_cash"] if r["best"] else None)
    db.freeze_event_refs(event_key(ev), refs)
    when = "hoy" if days == 0 else ("mañana" if days == 1 else f"en {days} días")
    lines = [f"📌 <b>{html.escape(ev['name'])} empieza {when}</b>: estos son los precios de referencia. "
             f"Durante el evento, una oferta real tiene que estar 15 % o más por debajo."]
    for r in rows:
        ref, best = refs[r["target"].id]
        if ref:
            lines.append(f"• {html.escape(r['target'].name)}: mercado <b>{fmt_ars(ref)}</b>"
                         + (f" (hoy {fmt_ars(best)})" if best else " (sin stock hoy)"))
    return lines + [""]


def split_message(text: str, limit: int = 3800) -> list[str]:
    """Telegram corta a 4096 caracteres: parte el resumen por líneas en varios mensajes."""
    parts, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    return parts + ([cur] if cur else [])


def ml_block(rows, now=None) -> list[str]:
    """Durante un evento (y los 2 días previos): links a Mercado Libre para revisarlo a mano desde el
    celular (ML no se lee automáticamente; ver README)."""
    from app.main import ml_search_url
    from services.events import current_or_next

    ev, _ = current_or_next(now, within_days=2)
    if not ev:
        return []
    out = [f"\n🛒 <b>{html.escape(ev['name'])}: revisá Mercado Libre a mano</b>"]
    for r in rows:
        t = r["target"]
        if t.kind != "monitor":
            continue
        url = next((u.url for u in t.urls if u.store == "mercadolibre"), None) or ml_search_url(t.name)
        out.append(f'• <a href="{html.escape(url, quote=True)}">{html.escape(t.name)}</a>')
    out.append("Si ves algo bueno, cargalo en el dashboard (\"Lo vi a $\") y entra al análisis.")
    return out


def build_summary() -> str:
    from app.main import build_context, db

    ctx = build_context()      # incluye las ofertas de las ~75 tiendas del descubrimiento
    rows = [r for r in ctx["rows"] if r["target"].active]
    rows.sort(key=lambda r: (r["best"] is None, -(r.get("real") or -1)))
    from services.advice import telegram_lines

    from services.event_report import report_block

    lines = (report_block(db, [r["target"] for r in rows]) + pre_event_block(db, rows)
             + telegram_lines(ctx.get("advice")) + ["📊 <b>Resumen diario de precios</b>"])
    for r in rows:
        t, b = r["target"], r["best"]
        name = html.escape(t.name)
        if not b:
            lines.append(f"⚪ {name}: sin stock")
            continue
        seller = b.get("seller") or ""
        where = html.escape(seller if b["store"].lower()[:5] in seller.lower().replace("á", "a")
                            else b["store"] + (f" · {seller}" if seller else ""))
        vs = (f"{round(-r['real'] * 100):+d}% vs mercado" if r.get("real") is not None
              else f"{round(r['diff']):+d}% vs objetivo")
        mark = {"excepcional": " 🔥", "buena": " 💰"}.get(r.get("level"), "")
        lines.append(f"{EMOJI[r['band']]} {name}: <b>{fmt_ars(b['price_cash'])}</b> ({vs}){mark} — {where}")
    recs = ctx["recs"]
    if recs:
        lines.append("\n💡 <b>Conviene empezar a seguir:</b>")
        for m in recs[:3]:
            lines.append(f'• <a href="{html.escape(m["best"]["url"], quote=True)}">{html.escape(m["name"][:60])}</a> '
                         f"— {fmt_ars(m['best']['price'])} ({html.escape(m['why'][0])})")
    disc = db.last_discovery()
    if disc:
        n = sum(1 for m in disc["results"] if m["status"] == "cumple")
        lines.append(f"\n🔎 Descubrimiento: {n} modelos cumplen todos tus requisitos")
        bad = [h["store"] for h in db.store_health(1) if h["error"]]
        if bad:
            lines.append("⚠️ Tiendas sin resultados o con error: " + html.escape(", ".join(bad)))
    lines += ml_block(rows)
    lines.append("🟢 oferta real ≥15 % · 🔵 precio normal · 🔴 caro (+10 % sobre el mercado)")
    lines.append(f'<a href="{PAGES_URL}">Ver dashboard</a>')
    return "\n".join(lines)
