from datetime import date

from services import event_report
from services.db import Database
from services.events import event_key
from services.targets import Target

BF = {"name": "Black Friday", "from": "2026-11-26", "to": "2026-11-30"}
TS = [Target(id="a", name="ASRock PG27QFT1B", target_price=1), Target(id="g", name="Gigabyte GS27QA", target_price=1),
      Target(id="brazo", name="Ironstek", target_price=1, kind="accesorio")]


def snap(db, tid, price, ts, lst=None, store="x"):
    db.insert_snapshot(tid, {"store": store, "url": f"u-{tid}-{store}", "price_cash": price, "price_list": lst,
                             "in_stock": True, "scanned_at": ts}, db.start_run("ci"))


def test_informe_con_ofertas_e_inflados(tmp_path):
    db = Database(tmp_path / "r.db")
    db.freeze_event_refs(event_key(BF), {"a": (330000, 330000), "g": (340000, 340000)})
    snap(db, "a", 270000, "2026-11-27T15:00:00+00:00", store="gerbio")          # -18 %: oferta real
    snap(db, "g", 330000, "2026-11-28T15:00:00+00:00", lst=660000, store="fakestore")  # "-50%" falso
    snap(db, "a", 200000, "2026-11-20T15:00:00+00:00")                          # fuera del evento
    db.insert_alert("g", "pre_event_hike", "subió", True)
    with db.connect() as con:
        con.execute("UPDATE alerts SET created_at='2026-11-20T10:00:00+00:00'")
    assert event_report.finished_event(date(2026, 11, 30), [BF]) is None        # todavía en curso
    lines = event_report.report_block(db, TS, date(2026, 12, 1), [BF])
    txt = "\n".join(lines)
    assert "Cómo fue Black Friday" in txt and "1</b> oferta real" in txt
    assert "ASRock PG27QFT1B" in txt and "gerbio" in txt and "-18%" in txt
    assert "inflados" in txt and "fakestore (1)" in txt and "Subas en las 2 semanas previas: 1 aviso" in txt
    assert event_report.report_block(db, TS, date(2026, 12, 2), [BF]) == []      # una sola vez


def test_informe_sin_ofertas(tmp_path):
    db = Database(tmp_path / "r.db")
    db.freeze_event_refs(event_key(BF), {"a": (330000, 330000)})
    snap(db, "a", 320000, "2026-11-27T15:00:00+00:00")
    txt = "\n".join(event_report.report_block(db, TS, date(2026, 12, 1), [BF]))
    assert "Ninguna oferta real" in txt and "-3% vs antes" in txt
