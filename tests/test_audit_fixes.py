"""Regresiones de la auditoría de noviembre 2026."""
from datetime import datetime, timedelta, timezone

from services.db import Database
from services.summary import split_message


def ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(microsecond=0).isoformat()


def test_resumen_largo_se_parte_por_lineas():
    text = "\n".join(f"línea {i} " + "x" * 90 for i in range(100))
    parts = split_message(text)
    assert len(parts) > 1 and all(len(p) <= 3800 for p in parts)
    assert "\n".join(parts) == text                      # no se pierde ni se corta ninguna línea


def test_carga_manual_no_mueve_el_precio_de_mercado(tmp_path):
    db = Database(tmp_path / "a.db")
    for h, price, promo in ((50, 300000, None), (30, 300000, None), (2, 100000, "carga manual")):
        db.insert_snapshot("m", {"store": "x" if not promo else "mercadolibre", "url": f"u{h}",
                                 "price_cash": price, "in_stock": True, "scanned_at": ts(h), "promo": promo},
                           db.start_run("ci"))
    assert min(p["price"] for p in db.best_series("m")) == 300000


def test_ventanas_de_tiempo_en_formato_iso(tmp_path):
    db = Database(tmp_path / "a.db")
    db.spec_cache_put("K", {"a": 1})
    with db.connect() as con:      # guardado hace 25 h: con la comparación vieja ('T' > ' ') se colaba igual
        con.execute("UPDATE spec_cache SET fetched_at=?", (ts(25),))
    assert db.spec_cache_get(["K"], max_age_days=1) == {}
    assert db.spec_cache_get(["K"], max_age_days=2) == {"K": {"a": 1}}


def test_serie_del_descubrimiento_un_punto_por_dia(tmp_path):
    db = Database(tmp_path / "a.db")
    with db.connect() as con:
        for i, (day, price) in enumerate((("2026-11-26T03", 500), ("2026-11-26T09", 450), ("2026-11-27T03", 480))):
            con.execute("INSERT INTO discovery_prices VALUES (?, 'X', ?, 's', NULL, ?)", (i, price, day + ":00:00+00:00"))
    assert [p["price"] for p in db.discovery_series("X")] == [450, 480]


def test_spec_enrich_solo_cache_sin_cortar(tmp_path):
    from services.spec_enrich import enrich

    db = Database(tmp_path / "a.db")
    db.spec_cache_put("B", {"anti_glare": True})
    # "A" no está en caché: antes cortaba el bucle y "B" se perdía
    assert enrich(db, [("A", "A", None), ("B", "B", None)]) == {"B": {"anti_glare": True}}


def test_precio_viejo_se_muestra_pero_no_cuenta(monkeypatch, tmp_path):
    import app.main as m
    from services.targets import Target, TargetUrl

    db = Database(tmp_path / "a.db")
    t = Target(id="t", name="T", target_price=1, urls=[TargetUrl(store="fravega", url="https://f"), TargetUrl(store="hg", url="https://h")])
    db.insert_snapshot("t", {"store": "fravega", "url": "https://f", "price_cash": 100, "in_stock": True, "scanned_at": ts(5 * 24)},
                       db.start_run("local"))
    db.insert_snapshot("t", {"store": "hg", "url": "https://h", "price_cash": 200, "in_stock": True, "scanned_at": ts(1)},
                       db.start_run("ci"))
    monkeypatch.setattr(m, "db", db)
    monkeypatch.setattr(m, "load_targets", lambda path: [t])
    row = m.build_dashboard()[0]
    assert row["best"]["price_cash"] == 200
    assert next(o for o in row["offers"] if o["store"] == "fravega")["stale"] >= 5
