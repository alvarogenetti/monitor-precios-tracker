"""¿Toca el descubrimiento + resumen diario? Una vez por día, en la primera corrida de GitHub desde
las 12 UTC (9 de Argentina). No depende de que el cron caiga a una hora exacta.

Durante un evento (Black Friday, Cyber Monday...) el descubrimiento corre además cada ~3 h (sin
resumen): las ~75 tiendas cambian precios varias veces por día y los seguidos usan esos precios.

    python -m services.daily due [ruta/prices.db]           # resumen diario: 0 = toca, 1 = ya se hizo
    python -m services.daily discover-due [ruta/prices.db]  # descubrimiento extra de evento: 0 = toca
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOUR_UTC = 12
EVENT_DISCOVERY_GAP_H = 3


def due(db_path: Path | str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=HOUR_UTC, minute=0, second=0, microsecond=0)
    if now < start:
        return False
    if not Path(db_path).exists():
        return True
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT 1 FROM discovery_runs WHERE trigger='ci' AND started_at >= ? LIMIT 1",
                          (start.isoformat(),)).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        con.close()
    return row is None


def last_ci_discovery(db_path: Path | str) -> datetime | None:
    if not Path(db_path).exists():
        return None
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT MAX(started_at) FROM discovery_runs WHERE trigger='ci'").fetchone()
    except sqlite3.Error:
        row = None
    finally:
        con.close()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


def discovery_due(db_path: Path | str, now: datetime | None = None, events: list[dict] | None = None) -> bool:
    """Descubrimiento extra durante un evento: si pasaron >= 3 h desde el último de GitHub."""
    from services.events import active_event

    now = now or datetime.now(timezone.utc)
    if not active_event(now, events):
        return False
    last = last_ci_discovery(db_path)
    return last is None or now - last >= timedelta(hours=EVENT_DISCOVERY_GAP_H)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "due"
    path = sys.argv[2] if len(sys.argv) > 2 else "data/prices.db"
    if cmd == "discover-due":
        ok = discovery_due(path)
        print("Toca un descubrimiento extra (evento)" if ok else "No toca descubrimiento extra")
    else:
        ok = due(path)
        print("Toca el descubrimiento/resumen diario" if ok else "Ya se hizo hoy (o todavía no son las 12 UTC)")
    sys.exit(0 if ok else 1)
