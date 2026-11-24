import os
import subprocess

from services import datastore
from services.db import Database


def snap(url, price, ts):
    return {"store": "x", "url": url, "price_cash": price, "in_stock": True, "scanned_at": ts}


def test_merge_from_adds_only_new_rows(tmp_path):
    a, b = Database(tmp_path / "a.db"), Database(tmp_path / "b.db")
    ra = a.start_run("cli")
    a.insert_snapshot("m", snap("u1", 100, "2026-11-20T10:00:00+00:00"), ra)
    # b = copia de a + un escaneo local nuevo
    b.path.write_bytes(a.path.read_bytes())
    rb = b.start_run("local")
    b.insert_snapshot("m", snap("u2", 90, "2026-11-20T10:30:00+00:00"), rb)
    b.insert_alert("m", "price_drop", "bajó", False)
    # mientras tanto a sumó su propio escaneo
    ra2 = a.start_run("cli")
    a.insert_snapshot("m", snap("u1", 95, "2026-11-20T11:00:00+00:00"), ra2)

    assert a.merge_from(b.path) == 3          # 1 corrida + 1 snapshot + 1 alerta
    assert a.merge_from(b.path) == 0          # idempotente
    rows = [(h["url"], h["price_cash"]) for h in reversed(a.history("m"))]
    assert rows == [("u1", 100), ("u1", 95), ("u2", 90)]
    assert a.best_series("m", days=100000)[-1]["price"] == 90


def test_push_pull_and_conflict_merge(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    clones = []
    for name in ("pc", "ci"):
        d = tmp_path / name
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "remote", "add", "origin", str(origin)], check=True)
        clones.append(d)
    pc, ci = clones

    monkeypatch.chdir(pc)
    db_pc = pc / "data" / "prices.db"
    assert datastore.pull(db_pc) is None                    # rama data todavía no existe
    d = Database(db_pc)
    d.insert_snapshot("m", snap("u1", 100, "2026-11-20T10:00:00+00:00"), d.start_run("cli"))
    datastore.push(db_pc)

    monkeypatch.chdir(ci)
    db_ci = ci / "data" / "prices.db"
    assert datastore.pull(db_ci)
    c = Database(db_ci)
    c.insert_snapshot("m", snap("u2", 80, "2026-11-20T11:00:00+00:00"), c.start_run("ci"))
    datastore.push(db_ci)                                    # ci publica primero

    monkeypatch.chdir(pc)                                    # pc tenía una base vieja
    d.insert_snapshot("m", snap("u3", 70, "2026-11-20T11:30:00+00:00"), d.start_run("local"))
    datastore.push(db_pc)                                    # lease falla -> fusiona -> publica

    monkeypatch.chdir(ci)
    datastore.pull(db_ci)
    urls = sorted(h["url"] for h in Database(db_ci).history("m"))
    assert urls == ["u1", "u2", "u3"]
    # la rama data siempre tiene un único commit (no acumula historia)
    out = subprocess.run(["git", "--git-dir", str(origin), "rev-list", "--count", "data"],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1"
    # un escaneo local sin publicar sobrevive a un pull (no lo pisa la base remota)
    c = Database(db_ci)
    c.insert_snapshot("m", snap("u4", 60, "2026-11-20T12:00:00+00:00"), c.start_run("cli"))
    datastore.pull(db_ci)
    assert "u4" in {h["url"] for h in Database(db_ci).history("m")}


def test_store_health(tmp_path):
    db = Database(tmp_path / "h.db")
    for srcs in ([{"store": "gerbio", "n": 10, "error": None}, {"store": "otecno", "n": 5, "error": None}],
                 [{"store": "gerbio", "n": 0, "error": "0 resultados"}, {"store": "otecno", "n": 7, "error": None}]):
        rid = db.start_discovery("ci")
        db.finish_discovery(rid, 1, [], [], srcs)
    h = {x["store"]: x for x in db.store_health()}
    assert h["gerbio"]["last"] == 0 and h["gerbio"]["error"] == "0 resultados" and h["gerbio"]["last_ok"]
    assert h["otecno"]["last"] == 7 and h["otecno"]["last_fail"] is None
    assert db.store_health()[0]["store"] == "gerbio"          # los que fallan, primero


def test_merge_from_also_merges_discovery_tables(tmp_path):
    a, b = Database(tmp_path / "a.db"), Database(tmp_path / "b.db")
    # b = GitHub: descubrimiento, referencias de evento, aviso de oferta y caché que a (la PC) no tiene
    rid = b.start_discovery("ci")
    b.finish_discovery(rid, 1, [{"key": "X"}], [], [{"store": "gerbio", "n": 3, "error": None}])
    with b.connect() as con:
        con.execute("INSERT INTO discovered_models VALUES ('X','X','cumple','2026-11-24T12:00:00+00:00',?, "
                    "'2026-11-24T12:00:00+00:00', 100, 90)", (rid,))
        con.execute("INSERT INTO discovery_prices VALUES (?, 'X', 100, 's', NULL, '2026-11-24T12:00:00+00:00')", (rid,))
    b.freeze_event_refs("BF|2026-11-26", {"m": (300000, 310000)})
    b.record_offer_alert("X", "buena", 100) if hasattr(b, "record_offer_alert") else None
    b.spec_cache_put("page:X", {"anti_glare": True})
    a.freeze_event_refs("BF|2026-11-26", {"m": (999, 999)})        # ya congelada en a: gana la de a
    n = a.merge_from(b.path)
    assert n >= 4 and a.merge_from(b.path) == 0                   # idempotente
    assert a.last_discovery()["results"][0]["key"] == "X"
    assert a.event_refs("BF|2026-11-26")["m"]["ref"] == 999
    assert a.spec_cache_get(["page:X"], 3650) == {"page:X": {"anti_glare": True}}
    assert a.has_discovered_models() and a.store_health()[0]["store"] == "gerbio"
