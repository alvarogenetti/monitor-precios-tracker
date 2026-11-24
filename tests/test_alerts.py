from scrapers.base import ScrapeResult
from services.db import Database
from services.targets import Target
from services.tracker import evaluate_alerts

T = Target(id="m", name="Monitor X", target_price=335000, keywords=["X"])
URL = "https://compragamer.com/producto/x_1"


def res(price, stock=True, error=None):
    return ScrapeResult(store="compragamer", url=URL, price_cash=price, in_stock=stock, error=error)


def kinds(db, r):
    out = [a.kind for a in evaluate_alerts(db, T, r, ref=(None, ""), notify_drops=True)]
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


def test_tiny_drop_under_1pct_does_not_alert(tmp_path):
    db = Database(tmp_path / "a.db")
    kinds(db, res(350000))
    assert kinds(db, res(348000)) == []            # -0,57 %: ruido
    assert kinds(db, res(340000)) == ["price_drop"]


def test_absurd_price_never_alerts(tmp_path):
    db = Database(tmp_path / "a.db")
    kinds(db, res(None, stock=False))
    # high = 335000 * 1.15 = 385000; x1.5 = 577500 -> un aviso "volvió el stock" a $999.990 se ignora
    assert kinds(db, res(999990)) == []


# ---- modo por defecto: sólo ofertas REALES contra el precio de mercado
def real(db, r, ref=400000):
    out = [a.kind for a in evaluate_alerts(db, T, r, ref=(ref, "test"), notify_drops=False)]
    db.insert_snapshot(T.id, r.to_dict())
    return out


def test_real_offers_levels_and_no_spam(tmp_path):
    db = Database(tmp_path / "a.db")
    assert real(db, res(395000)) == []                     # -1 %: nada (ya no avisa bajas chicas)
    assert real(db, res(380000)) == []                     # -5 %: nada
    assert real(db, res(340000)) == ["real_offer"]         # -15 %: buena oferta
    assert real(db, res(338000)) == []                     # mismo nivel, baja chica: no repite
    assert real(db, res(320000)) == ["real_offer", "target_reached"]  # 5 % más barato + cruza el objetivo manual
    assert real(db, res(275000)) == ["real_offer", "target_reached"]  # -31 %: excepcional + objetivo


def test_inflated_list_price_is_flagged(tmp_path):
    from services.market import describe, inflated
    # la tienda dice -50 % (lista 680k), pero el mercado está en 360k: real -5,6 %
    assert inflated(340000, 680000, 360000) is True
    assert "inflado" in describe(340000, 680000, 360000)
    assert inflated(250000, 380000, 360000) is False        # -34 % dicho, -31 % real: genuino


def test_market_reference_median():
    from datetime import datetime, timedelta, timezone
    from services.market import reference
    now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
    pts = [{"ts": (now - timedelta(days=d, hours=h)).isoformat(), "price": p}
           for d, h, p in [(5, 0, 350000), (4, 0, 340000), (3, 0, 345000), (2, 6, 360000),
                           (2, 0, 355000), (1, 6, 342000), (0, 2, 250000)]]   # la de hace 2 h no cuenta
    ref, src = reference(pts, seed=999999, now=now)
    assert ref == 347500 and "mediana" in src
    assert reference(pts[:3], seed=300000, now=now) == (300000, "precio de mercado inicial (relevamiento)")


def test_bundle_agrupa_y_ordena():
    from services.tracker import Alert, bundle

    al = [Alert("price_drop", "bajó"), Alert("real_offer", "oferta 18", score=0.18),
          Alert("real_offer", "oferta 25", score=0.25), Alert("pre_event_hike", "subió")]
    msgs = bundle(al, "🔔 4 avisos")
    assert len(msgs) == 1 and msgs[0].index("oferta 25") < msgs[0].index("oferta 18") < msgs[0].index("subió") < msgs[0].index("bajó")
    many = bundle([Alert("price_drop", "x" * 1000) for _ in range(10)], "H")
    assert len(many) >= 3 and all(len(m) <= 3800 for m in many) and many[1].startswith("H (sigue)")
