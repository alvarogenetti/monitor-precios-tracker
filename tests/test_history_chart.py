"""Historial del gráfico grande: por día, más barato / más caro / promedio."""
from types import SimpleNamespace

from services.db import Database, merge_daily


def test_discovery_daily_series(tmp_path):
    db = Database(tmp_path / "p.db")
    run = db.start_discovery("cli")
    r = SimpleNamespace(key="K1", name="X", status="cumple", best={"price": 300.0, "store": "a", "seller": None},
                        spread={"max": 500.0, "avg": 400.0, "n": 3})
    db.upsert_discovered(run, [r])
    db.upsert_discovered(db.start_discovery("cli"), [SimpleNamespace(**{**r.__dict__, "best": {"price": 280.0, "store": "b", "seller": "S"}})])
    s = db.daily_series("m", "K1")
    assert len(s) == 1 and s[0]["lo"] == 280 and s[0]["hi"] == 500 and s[0]["where"] == "S"


def test_merge_daily_weights_average():
    a = [{"d": "2026-11-24", "lo": 300, "hi": 300, "avg": 300, "n": 1, "where": "a"}]
    b = [{"d": "2026-11-24", "lo": 250, "hi": 600, "avg": 450, "n": 3, "where": "b"},
         {"d": "2026-11-25", "lo": 260, "hi": None, "avg": None, "n": None, "where": "c"}]
    m = merge_daily(a, b)
    assert m[0] == {"d": "2026-11-24", "lo": 250, "hi": 600, "avg": (300 + 450 * 3) / 4, "n": 4, "where": "b"}
    assert m[1]["d"] == "2026-11-25" and m[1]["hi"] is None


def test_series_file_is_safe():
    from app.main import series_file
    assert series_file("m", "SAMSUNG~0HZ") == "series/m-SAMSUNG_0HZ.json"
