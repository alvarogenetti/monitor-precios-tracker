"""Ensayo general del Black Friday 2026 (config/events.json real) con fechas fijas."""
from datetime import datetime, timedelta, timezone

import services.events as events
from services import daily
from services.db import Database
from services.summary import ml_block, pre_event_block
from services.targets import Target, TargetUrl
from services.tracker import market_ref

UTC = timezone.utc
BF = next(e for e in events.load() if e["name"].startswith("Black Friday") and e["from"].startswith("2026"))
T = Target(id="m", name="Samsung S27FG500EL", target_price=350000, market_price=430000,
           urls=[TargetUrl(store="mercadolibre", url="https://listado.mercadolibre.com.ar/samsung-s27fg500el")])


def row(price=430000):
    return {"target": T, "best": {"price_cash": price}}


def test_black_friday_dates():
    assert BF["from"] == "2026-11-26" and BF["to"] == "2026-11-30"


def test_dos_dias_antes_congela_referencias_y_manda_links_de_ml(tmp_path):
    db = Database(tmp_path / "p.db")
    now = datetime(2026, 11, 24, 12, 30, tzinfo=UTC)            # 9:30 AR del 24/11
    lines = pre_event_block(db, [row()], now)
    assert "Black Friday" in lines[0] and "empieza en 2 días" in lines[0]
    assert db.event_refs(events.event_key(BF))["m"]["ref"] == 430000   # semilla market_price
    assert pre_event_block(db, [row()], now) == []                  # una sola vez
    ml = ml_block([row()], now)
    assert "revisá Mercado Libre" in ml[0] and "samsung-s27fg500el" in ml[1]
    assert ml_block([row()], datetime(2026, 11, 20, 12, tzinfo=UTC)) == []   # 6 días antes: nada


def test_durante_el_evento(tmp_path, monkeypatch):
    db = Database(tmp_path / "p.db")
    db.freeze_event_refs(events.event_key(BF), {"m": (430000, 430000)})
    monkeypatch.setattr(events, "load", lambda path=events.PATH: [BF])
    t = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    # seguidos: cada 45 min (en vez de 2 h 45)
    assert events.should_run(t, [BF], last=t - timedelta(minutes=50))
    assert not events.should_run(datetime(2026, 11, 22, 15, tzinfo=UTC), [BF],
                                 last=datetime(2026, 11, 22, 14, tzinfo=UTC))
    # ofertas medidas contra la referencia congelada
    monkeypatch.setattr(events, "active_event", lambda now=None, evs=None: BF["name"])
    monkeypatch.setattr(events, "current_or_next", lambda now=None, evs=None, within_days=14: (BF, 0))
    ref, src = market_ref(db, T)
    assert ref == 430000 and "antes de Black Friday" in src


def test_descubrimiento_cada_3_horas_en_eventos(tmp_path):
    p = tmp_path / "p.db"
    db = Database(p)
    rid = db.start_discovery("ci")
    db.finish_discovery(rid, 0, [], [])
    last = daily.last_ci_discovery(p)
    during, outside = last.replace(year=2026, month=11, day=27), last.replace(year=2026, month=11, day=20)
    with db.connect() as con:
        con.execute("UPDATE discovery_runs SET started_at=?", (during.isoformat(),))
    assert not daily.discovery_due(p, during + timedelta(hours=2), [BF])
    assert daily.discovery_due(p, during + timedelta(hours=3, minutes=5), [BF])
    assert not daily.discovery_due(p, outside + timedelta(hours=5), [BF])   # fuera de evento: sólo el diario
