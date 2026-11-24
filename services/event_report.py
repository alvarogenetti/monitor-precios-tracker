"""Informe al terminar un evento (Black Friday, Cyber Monday...): ¿hubo ofertas reales?

Se agrega UNA vez al resumen diario, el primer día después de que termina el evento (hasta 3 días
después, por si GitHub saltea corridas). Por cada monitor seguido compara el mejor precio visto
durante el evento contra el precio de referencia congelado antes de empezar, y cuenta:
  - ofertas reales (>= 15 % debajo de esa referencia) y en qué tienda;
  - "descuentos" de lista inflados (la tienda anunciaba más de lo que de verdad bajó);
  - subas en las 2 semanas previas (avisos "Subió antes de...").
"""
from __future__ import annotations

import html
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from services.events import AR, event_key, load
from services.market import GOOD, inflated, real_discount
from services.tracker import fmt_ars

REPORT_KIND = "event_report"


def finished_event(today: date, events: list[dict] | None = None, within_days: int = 3) -> dict | None:
    """El evento que terminó ayer (o hasta `within_days` días antes)."""
    for ev in sorted(events if events is not None else load(), key=lambda e: e["to"], reverse=True):
        end = date.fromisoformat(ev["to"])
        if 1 <= (today - end).days <= within_days:
            return ev
    return None


def _bounds(ev: dict) -> tuple[str, str]:
    start = datetime.combine(date.fromisoformat(ev["from"]), time(0), AR)
    end = datetime.combine(date.fromisoformat(ev["to"]) + timedelta(days=1), time(0), AR)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def build(db, targets: list, ev: dict) -> list[str]:
    key = event_key(ev)
    refs = db.event_refs(key)
    start, end = _bounds(ev)
    with db.connect() as con:
        snaps = con.execute("""SELECT target_id, store, seller, price_cash, price_list, product_url, url
                               FROM snapshots WHERE price_cash IS NOT NULL AND error IS NULL
                               AND scanned_at >= ? AND scanned_at < ?""", (start, end)).fetchall()
        hike_start = (datetime.fromisoformat(start) - timedelta(days=14)).isoformat()
        hikes = con.execute("""SELECT target_id FROM alerts WHERE kind='pre_event_hike'
                               AND created_at >= ? AND created_at < ?""", (hike_start, start)).fetchall()
    names = {t.id: t.name for t in targets if getattr(t, "kind", "monitor") == "monitor"}
    best: dict[str, dict] = {}
    fake = Counter()
    for s in snaps:
        tid = s["target_id"]
        if tid not in names:
            continue
        ref = (refs.get(tid) or {}).get("ref")
        if ref and s["price_list"] and inflated(s["price_cash"], s["price_list"], ref):
            fake[s["seller"] or s["store"]] += 1
        if tid not in best or s["price_cash"] < best[tid]["price"]:
            best[tid] = {"price": s["price_cash"], "store": s["seller"] or s["store"], "ref": ref}
    offers = []
    for tid, b in best.items():
        real = real_discount(b["price"], b["ref"]) if b["ref"] else None
        b["real"] = real
        if real is not None and real >= GOOD:
            offers.append((tid, b))
    offers.sort(key=lambda x: -x[1]["real"])

    lines = [f"📋 <b>Cómo fue {html.escape(ev['name'])}</b> ({ev['from'][8:10]}/{ev['from'][5:7]} al "
             f"{ev['to'][8:10]}/{ev['to'][5:7]})"]
    if offers:
        lines.append(f"Hubo <b>{len(offers)}</b> oferta{'s' if len(offers) > 1 else ''} real{'es' if len(offers) > 1 else ''} "
                     "(15 % o más debajo del precio de antes del evento):")
        for tid, b in offers[:6]:
            lines.append(f"• {html.escape(names[tid])}: <b>{fmt_ars(b['price'])}</b> en {html.escape(b['store'])} "
                         f"(-{b['real'] * 100:.0f}% vs {fmt_ars(b['ref'])})")
    else:
        lines.append("<b>Ninguna oferta real</b>: ningún seguido bajó 15 % o más contra su precio de antes.")
        near = sorted(((tid, b) for tid, b in best.items() if b.get("real") is not None),
                      key=lambda x: -x[1]["real"])[:3]
        for tid, b in near:
            lines.append(f"• {html.escape(names[tid])}: mejor {fmt_ars(b['price'])} "
                         f"({-b['real'] * 100:+.0f}% vs antes) en {html.escape(b['store'])}")
    if fake:
        top = ", ".join(f"{html.escape(k)} ({v})" for k, v in fake.most_common(4))
        lines.append(f"⚠️ Descuentos de lista inflados (anunciaban más de lo que bajó): {top}")
    if hikes:
        lines.append(f"📈 Subas en las 2 semanas previas: {len(hikes)} aviso{'s' if len(hikes) > 1 else ''} "
                     f"({len({h['target_id'] for h in hikes})} monitores)")
    return lines + [""]


def report_block(db, targets: list, today: date | None = None, events: list[dict] | None = None) -> list[str]:
    """Bloque para el resumen diario (una sola vez por evento)."""
    today = today or datetime.now(AR).date()
    ev = finished_event(today, events)
    if not ev:
        return []
    key = event_key(ev)
    with db.connect() as con:
        done = con.execute("SELECT 1 FROM alerts WHERE kind=? AND target_id=? LIMIT 1",
                           (REPORT_KIND, key)).fetchone()
    if done:
        return []
    lines = build(db, targets, ev)
    db.insert_alert(key, REPORT_KIND, "\n".join(lines), True)
    return lines
