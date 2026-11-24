from datetime import datetime, timedelta, timezone

from app.main import merge_discovery_offers
from services.targets import Target


def row(price):
    t = Target(id="samsung", name="Samsung S27FG500EL", target_price=350000, market_price=430000)
    snap = {"store": "hardgamers", "url": "https://hg/s", "product_url": "https://hg/s/1", "seller": "X",
            "price_cash": price, "price_list": None, "in_stock": 1, "error": None, "scanned_at": "x"}
    return {"target": t, "offers": [{"store": "hardgamers", "url": "https://hg/s", "active": True, "snap": snap}],
            "best": snap, "ref": 430000, "real": 0.0, "level": None, "band": "normal", "inflated": False,
            "hit": False, "diff": 0, "stock": "in"}


def models():
    return [{"tracked": "samsung", "offers": [
        {"store": "gerbio", "title": "MONITOR SAMSUNG S27FG500EL [3 cuotas]", "price": 360000.0,
         "url": "https://gerbio/s", "seller": "Gerbio", "price_list": None},
        {"store": "hardgamers", "title": "MONITOR SAMSUNG", "price": 380000.0, "url": "https://hg/s/1",
         "seller": "X", "price_list": None}]},
        {"tracked": None, "offers": [{"store": "z", "title": "otro", "price": 1.0, "url": "https://z"}]}]


def test_cheaper_discovery_offer_becomes_best():
    now = datetime.now(timezone.utc).isoformat()
    r = row(430000)
    merge_discovery_offers([r], models(), now)
    assert r["best"]["store"] == "gerbio" and r["best"]["price_cash"] == 360000
    assert r["best"]["title"] == "MONITOR SAMSUNG S27FG500EL" and r["best"]["promo"] == "3 cuotas"
    assert r["best_via"] == "descubrimiento" and round(r["real"], 3) == round(1 - 360000 / 430000, 3)
    assert [o["store"] for o in r["offers"]] == ["hardgamers", "gerbio"]   # la de HG ya estaba (misma URL)


def test_old_discovery_or_more_expensive_does_not_replace():
    old = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
    r = row(430000)
    merge_discovery_offers([r], models(), old)
    assert r["best"]["store"] == "hardgamers" and len(r["offers"]) == 1
    r = row(300000)
    merge_discovery_offers([r], models(), datetime.now(timezone.utc).isoformat())
    assert r["best"]["store"] == "hardgamers" and len(r["offers"]) == 2
