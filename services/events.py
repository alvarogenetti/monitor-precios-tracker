"""Eventos de descuentos (Hot Sale, Cyber Monday, Black Friday...) y "¿toca escanear?".

GitHub Actions dispara el workflow cada 30 minutos, pero su cron NO es confiable: en horas pico
descarta o atrasa corridas. Por eso la decisión no mira la hora del reloj sino **cuánto pasó desde
el último escaneo de GitHub** (leído de la base de la rama `data`):
  - fuera de eventos: escanea si pasaron >= 2 h 45 min;
  - durante un evento de config/events.json: si pasaron >= 45 min.
Si una corrida se pierde, la siguiente la compensa.

    python -m services.events should-run [ruta/prices.db]   # exit 0 = escanear, 1 = saltear
    python -m services.events active                         # evento activo (si hay)
Sólo usa la librería estándar (corre antes de instalar dependencias).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "config" / "events.json"
AR = timezone(timedelta(hours=-3))
NORMAL_GAP = timedelta(hours=2, minutes=45)
EVENT_GAP = timedelta(minutes=45)
CI_TRIGGER = "ci"


def load(path: Path = PATH) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("events", [])
    except FileNotFoundError:
        return []


def active_event(now: datetime | None = None, events: list[dict] | None = None) -> str | None:
    today = (now or datetime.now(AR)).astimezone(AR).date()
    for ev in events if events is not None else load():
        if date.fromisoformat(ev["from"]) <= today <= date.fromisoformat(ev["to"]):
            return ev["name"]
    return None


def event_key(ev: dict) -> str:
    return f"{ev['name']}|{ev['from']}"


def current_or_next(now: datetime | None = None, events: list[dict] | None = None,
                    within_days: int = 14) -> tuple[dict | None, int | None]:
    """(evento, días hasta que empieza): el que está en curso (0) o el próximo dentro de
    `within_days` días. (None, None) si no hay ninguno."""
    today = (now or datetime.now(AR)).astimezone(AR).date()
    for ev in sorted(events if events is not None else load(), key=lambda e: e["from"]):
        start, end = date.fromisoformat(ev["from"]), date.fromisoformat(ev["to"])
        if start <= today <= end:
            return ev, 0
        if 0 < (start - today).days <= within_days:
            return ev, (start - today).days
    return None, None


def last_ci_scan(db_path: Path | str | None) -> datetime | None:
    if not db_path or not Path(db_path).exists():
        return None
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT MAX(started_at) FROM scan_runs WHERE trigger=?", (CI_TRIGGER,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


def should_run(now: datetime | None = None, events: list[dict] | None = None,
               last: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if last is None:
        return True
    gap = EVENT_GAP if active_event(now, events) else NORMAL_GAP
    return now - last >= gap


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "active"
    if cmd == "should-run":
        last = last_ci_scan(sys.argv[2] if len(sys.argv) > 2 else None)
        ev = active_event()
        ok = should_run(last=last)
        ago = f"último escaneo hace {(datetime.now(timezone.utc) - last)}" if last else "sin escaneos previos"
        print(f"{'Escanear' if ok else 'Saltear'} ({ago}{f'; evento: {ev}' if ev else ''})")
        sys.exit(0 if ok else 1)
    print(active_event() or "")
