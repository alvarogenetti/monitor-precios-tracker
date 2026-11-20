"""Eventos de descuentos (Hot Sale, Cyber Monday, Black Friday...): escaneo más frecuente.

GitHub Actions dispara el workflow cada hora; este módulo decide si esa corrida escanea:
  - durante un evento de config/events.json: todas las horas;
  - fuera de eventos: cada 3 horas (0, 3, 6, ... UTC), como siempre.

    python -m services.events should-run     # exit 0 = escanear, 1 = saltear
    python -m services.events active         # imprime el evento activo (si hay)
Sólo usa la librería estándar (corre antes de instalar dependencias).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "config" / "events.json"
AR = timezone(timedelta(hours=-3))


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


def should_run(now: datetime | None = None, events: list[dict] | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).hour % 3 == 0 or active_event(now, events) is not None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "active"
    if cmd == "should-run":
        ev = active_event()
        ok = should_run()
        print(f"{'Escanear' if ok else 'Saltear'}{f' (evento: {ev})' if ev else ''}")
        sys.exit(0 if ok else 1)
    print(active_event() or "")
