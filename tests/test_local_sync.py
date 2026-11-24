"""Lo escaneado en la PC se sube solo a la rama data; lo que quedó sin subir se sube al abrir."""
import services.datastore as ds
import services.tracker as tr


def test_local_scan_publishes(monkeypatch):
    calls = []

    async def fake_scan(trigger, target_ids, on_progress=None):
        return {"ok": 1}

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(tr, "run_scan", fake_scan)
    monkeypatch.setattr(tr, "publish_db", lambda msg: calls.append(msg))
    tr.run_scan_blocking("web")
    assert calls == ["escaneo local (web)"]


def test_ci_scan_does_not_publish_from_thread(monkeypatch):
    calls = []

    async def fake_scan(trigger, target_ids, on_progress=None):
        return {"ok": 1}

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(tr, "run_scan", fake_scan)
    monkeypatch.setattr(tr, "publish_db", lambda msg: calls.append(msg))
    tr.run_scan_blocking("scheduler")
    assert calls == []


def test_publish_db_sets_state(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "push", lambda db, msg: "abc")
    tr.publish_db("prueba")
    for t in __import__("threading").enumerate():
        if t.name == "publish-db":
            t.join(5)
    assert tr.STATE.sync == "ok" and tr.STATE.sync_at


def test_pull_pushes_pending_local_rows(monkeypatch, tmp_path):
    db = tmp_path / "prices.db"
    db.write_bytes(b"x")
    pushed = []

    def fake_fetch(dest):
        dest.write_bytes(b"remote")
        return "sha1"

    class FakeDB:
        def __init__(self, p): pass
        def merge_from(self, other): return 3

    monkeypatch.setattr(ds, "fetch_db", fake_fetch)
    monkeypatch.setattr("services.db.Database", FakeDB)
    monkeypatch.setattr(ds, "push", lambda d, m: pushed.append(m) or "sha2")
    assert ds.pull(db) == "sha2" and pushed
