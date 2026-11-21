from datetime import datetime, timedelta, timezone

from services.daily import due
from services.db import Database
from services.discovery import ModelResult, new_models_alert
from services.events import active_event, last_ci_scan, should_run

EV = [{"name": "Cyber Monday", "from": "2026-11-02", "to": "2026-11-04"}]
UTC = timezone.utc


def test_gate_by_time_since_last_ci_scan():
    inside = datetime(2026, 11, 3, 14, 10, tzinfo=UTC)
    outside = datetime(2026, 11, 10, 14, 10, tzinfo=UTC)
    assert active_event(inside, EV) == "Cyber Monday"
    assert should_run(outside, EV, last=None) is True                       # nunca escaneó
    assert should_run(outside, EV, last=outside - timedelta(hours=1)) is False
    assert should_run(outside, EV, last=outside - timedelta(hours=3)) is True  # se perdieron corridas
    assert should_run(inside, EV, last=inside - timedelta(minutes=50)) is True  # en evento: ~cada hora


def test_last_ci_scan_and_daily(tmp_path):
    db = Database(tmp_path / "p.db")
    assert last_ci_scan(db.path) is None
    db.start_run("cli")
    assert last_ci_scan(db.path) is None                                    # los locales no cuentan
    db.start_run("ci")
    assert last_ci_scan(db.path) is not None
    noon = datetime.now(UTC).replace(hour=13, minute=0)
    assert due(db.path, noon) is True
    rid = db.start_discovery("ci")
    with db.connect() as c:
        c.execute("UPDATE discovery_runs SET started_at=? WHERE id=?", (noon.isoformat(), rid))
    assert due(db.path, noon + timedelta(hours=2)) is False
    assert due(db.path, noon.replace(hour=9)) is False                      # antes de las 12 UTC


def _m(name, status, price):
    return ModelResult(key=name, search=name, name=name, brand=None, status=status,
                       best={"price": price, "url": "https://x", "store": "s", "seller": "T"},
                       offers=[], n_stores=1, facts={}, spec=None)


def test_grouped_new_models_alert():
    text = new_models_alert([_m(f"M{i}", "a_confirmar", 400000 + i) for i in range(10)] +
                            [_m("Bueno", "cumple", 500000)])
    assert text.startswith("🆕 <b>11 monitores nuevos")
    assert text.index("Bueno") < text.index("M0")
    assert "…y 3 más" in text
