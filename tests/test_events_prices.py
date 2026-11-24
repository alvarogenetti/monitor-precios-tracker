from datetime import date, datetime, timedelta, timezone

import services.events as events
from scrapers.base import ScrapeResult
from services.db import Database
from services.targets import Target
from services.tracker import evaluate_alerts, market_ref

T = Target(id="m", name="Monitor X", target_price=200000, keywords=["X"], market_price=300000)
URL = "https://tienda/x"


def _ev(days_from_today: int, length: int = 3) -> list[dict]:
    start = datetime.now(events.AR).date() + timedelta(days=days_from_today)   # fecha de Argentina, como el código
    return [{"name": "Black Friday", "from": start.isoformat(), "to": (start + timedelta(days=length)).isoformat()}]


def _hist(db, price, days_ago):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(microsecond=0).isoformat()
    db.insert_snapshot("m", {"store": "x", "url": URL, "price_cash": price, "in_stock": True, "scanned_at": ts},
                       db.start_run("ci"))


def test_current_or_next():
    assert events.current_or_next(events=_ev(5))[1] == 5
    assert events.current_or_next(events=_ev(-1))[1] == 0
    assert events.current_or_next(events=_ev(20)) == (None, None)


def test_pre_event_hike_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "load", lambda path=events.PATH: _ev(5))
    db = Database(tmp_path / "a.db")
    for d in (10, 8, 6, 4, 2):
        _hist(db, 300000, d)
    res = ScrapeResult(store="x", url=URL, price_cash=345000, in_stock=True)
    kinds = [a.kind for a in evaluate_alerts(db, T, res, ref=(300000, "t"), notify_drops=False)]
    assert kinds == ["pre_event_hike"]


def test_frozen_reference_during_event(tmp_path, monkeypatch):
    db = Database(tmp_path / "a.db")
    monkeypatch.setattr(events, "load", lambda path=events.PATH: _ev(-1))
    db.freeze_event_refs(events.event_key(_ev(-1)[0]), {"m": (280000, 290000)})
    ref, src = market_ref(db, T)
    assert ref == 280000 and "antes de Black Friday" in src
