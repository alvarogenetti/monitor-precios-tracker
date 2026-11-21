"""Resumen diario por Telegram: mejor precio de cada monitor y en qué rango está."""
from __future__ import annotations

import html

from services.tracker import fmt_ars

PAGES_URL = "https://alvarogenetti.github.io/monitor-precios-tracker/"
EMOJI = {"bajo": "🟢", "normal": "🔵", "alto": "🔴", None: "⚪"}


def build_summary() -> str:
    from app.main import build_dashboard, db

    rows = [r for r in build_dashboard() if r["target"].active]
    rows.sort(key=lambda r: (r["best"] is None, -(r.get("real") or -1)))
    lines = ["📊 <b>Resumen diario de precios</b>"]
    for r in rows:
        t, b = r["target"], r["best"]
        name = html.escape(t.name)
        if not b:
            lines.append(f"⚪ {name}: sin stock")
            continue
        where = html.escape(b["store"] + (f" · {b['seller']}" if b.get("seller") else ""))
        vs = (f"{round(-r['real'] * 100):+d}% vs mercado" if r.get("real") is not None
              else f"{round(r['diff']):+d}% vs objetivo")
        mark = {"excepcional": " 🔥", "buena": " 💰"}.get(r.get("level"), "")
        lines.append(f"{EMOJI[r['band']]} {name}: <b>{fmt_ars(b['price_cash'])}</b> ({vs}){mark} — {where}")
    from app.main import build_context

    recs = build_context()["recs"]
    if recs:
        lines.append("\n💡 <b>Conviene empezar a seguir:</b>")
        for m in recs[:3]:
            lines.append(f'• <a href="{html.escape(m["best"]["url"], quote=True)}">{html.escape(m["name"][:60])}</a> '
                         f"— {fmt_ars(m['best']['price'])} ({html.escape(m['why'][0])})")
    disc = db.last_discovery()
    if disc:
        n = sum(1 for m in disc["results"] if m["status"] == "cumple")
        lines.append(f"\n🔎 Descubrimiento: {n} modelos cumplen todos tus requisitos")
    lines.append("🟢 oferta real ≥15 % · 🔵 precio normal · 🔴 caro (+10 % sobre el mercado)")
    lines.append(f'<a href="{PAGES_URL}">Ver dashboard</a>')
    return "\n".join(lines)
