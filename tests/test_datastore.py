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
