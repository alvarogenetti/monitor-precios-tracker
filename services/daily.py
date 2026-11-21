"""¿Toca el descubrimiento + resumen diario? Una vez por día, en la primera corrida de GitHub desde
las 12 UTC (9 de Argentina). No depende de que el cron caiga a una hora exacta.

    python -m services.daily due [ruta/prices.db]    # exit 0 = toca, 1 = ya se hizo hoy
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HOUR_UTC = 12


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


if __name__ == "__main__":
    path = sys.argv[2] if len(sys.argv) > 2 else "data/prices.db"
    ok = due(path)
    print("Toca el descubrimiento/resumen diario" if ok else "Ya se hizo hoy (o todavía no son las 12 UTC)")
    sys.exit(0 if ok else 1)
