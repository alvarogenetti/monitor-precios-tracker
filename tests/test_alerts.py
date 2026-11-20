from scrapers.base import ScrapeResult
from services.db import Database
from services.targets import Target
from services.tracker import evaluate_alerts

T = Target(id="m", name="Monitor X", target_price=335000, keywords=["X"])
URL = "https://compragamer.com/producto/x_1"


def res(price, stock=True, error=None):
    return ScrapeResult(store="compragamer", url=URL, price_cash=price, in_stock=stock, error=error)


def kinds(db, r):
    out = [a.kind for a in evaluate_alerts(db, T, r)]
    db.insert_snapshot(T.id, r.to_dict())
    return out


def test_alert_sequence(tmp_path):
    db = Database(tmp_path / "a.db")
    assert kinds(db, res(350000)) == []                       # primer registro, sobre objetivo
    assert kinds(db, res(345000)) == ["price_drop"]           # bajó
    assert kinds(db, res(345000)) == []                       # igual: nada
    assert kinds(db, res(None, error="timeout")) == []        # error: se ignora
    assert kinds(db, res(334000)) == ["price_drop", "target_reached"]  # cruza el objetivo
    assert kinds(db, res(334000)) == []                       # sigue bajo objetivo: no spamea
    assert kinds(db, res(None, stock=False)) == []            # se agotó
    assert kinds(db, res(334000)) == ["back_in_stock"]        # volvió, mismo precio
    assert kinds(db, res(330000)) == ["price_drop", "target_reached"]


def test_first_snapshot_under_target(tmp_path):
    db = Database(tmp_path / "a.db")
    assert kinds(db, res(300000)) == ["target_reached"]


def test_out_of_stock_price_does_not_alert(tmp_path):
    db = Database(tmp_path / "a.db")
    kinds(db, res(350000))
    assert kinds(db, res(300000, stock=False)) == []
