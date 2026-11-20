from services.db import Database


def _snap(**kw):
    base = {"store": "compragamer", "url": "https://x/1", "price_cash": 100000.0,
            "price_list": 110000.0, "in_stock": True}
    base.update(kw)
    return base


def test_snapshots_and_queries(tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_snapshot("mon", _snap(price_cash=300000))
    db.insert_snapshot("mon", _snap(price_cash=None, error="timeout"))
    db.insert_snapshot("mon", _snap(price_cash=280000, in_stock=False))
    db.insert_snapshot("mon", _snap(url="https://x/2", store="hardgamers", price_cash=290000))

    last_valid = db.last_snapshot("mon", "https://x/1", valid_price=True)
    assert last_valid["price_cash"] == 280000 and last_valid["in_stock"] == 0

    latest = {r["url"]: r for r in db.latest_per_url()}
    assert latest["https://x/1"]["price_cash"] == 280000
    assert latest["https://x/2"]["store"] == "hardgamers"

    # el mínimo histórico ignora el registro sin stock
    assert db.historical_min()["mon"]["price_cash"] == 290000


def test_runs_and_alerts(tmp_path):
    db = Database(tmp_path / "t.db")
    rid = db.start_run("cli")
    db.insert_alert("mon", "price_drop", "bajó", sent=False)
    db.finish_run(rid, 3, 1, 1)
    run = db.last_run()
    assert run["n_ok"] == 3 and run["finished_at"]
    assert db.recent_alerts()[0]["kind"] == "price_drop"
