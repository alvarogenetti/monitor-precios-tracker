"""Persistencia SQLite: snapshots de precio/stock, corridas de escaneo y alertas."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL,
    store       TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT,
    seller      TEXT,
    product_url TEXT,
    price_cash  REAL,
    price_list  REAL,
    in_stock    INTEGER,            -- 1 / 0 / NULL (desconocido)
    error       TEXT,
    scanned_at  TEXT NOT NULL,       -- ISO-8601 UTC
    run_id      INTEGER              -- scan_runs.id (agrupa los snapshots de un mismo escaneo)
);
CREATE INDEX IF NOT EXISTS ix_snap_target_url ON snapshots(target_id, url, id);

CREATE TABLE IF NOT EXISTS scan_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger     TEXT NOT NULL,       -- cli / web / scheduler
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    n_ok        INTEGER DEFAULT 0,
    n_error     INTEGER DEFAULT 0,
    n_alerts    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger     TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    n_offers    INTEGER DEFAULT 0,
    n_models    INTEGER DEFAULT 0,
    errors      TEXT,                -- JSON
    results     TEXT                 -- JSON: modelos evaluados de esa corrida
);

CREATE TABLE IF NOT EXISTS discovered_models (
    model_key   TEXT PRIMARY KEY,
    name        TEXT,
    status      TEXT,
    first_seen  TEXT NOT NULL,
    first_run   INTEGER,
    last_seen   TEXT NOT NULL,
    last_price  REAL,
    min_price   REAL
);

CREATE TABLE IF NOT EXISTS discovery_prices (
    run_id      INTEGER NOT NULL,
    model_key   TEXT NOT NULL,
    price       REAL NOT NULL,
    store       TEXT,
    seller      TEXT,
    scanned_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_disc_prices ON discovery_prices(model_key, run_id);

CREATE TABLE IF NOT EXISTS spec_cache (
    model_key   TEXT PRIMARY KEY,
    data        TEXT NOT NULL,       -- JSON ({} = buscado y no encontrado)
    fetched_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_alerts (
    model_key   TEXT NOT NULL,
    level       TEXT NOT NULL,
    price       REAL NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_refs (
    event       TEXT NOT NULL,       -- "Black Friday|2026-11-26"
    target_id   TEXT NOT NULL,
    ref         REAL,                -- precio de mercado congelado antes del evento
    best        REAL,                -- mejor precio en ese momento
    created_at  TEXT NOT NULL,
    PRIMARY KEY (event, target_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,       -- price_drop / target_reached / back_in_stock
    message     TEXT NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
            self._migrate(con)

    @staticmethod
    def _migrate(con: sqlite3.Connection) -> None:
        dcols = {r["name"] for r in con.execute("PRAGMA table_info(discovery_runs)")}
        if "sources" not in dcols:   # ofertas por fuente en cada descubrimiento (estado de las tiendas)
            con.execute("ALTER TABLE discovery_runs ADD COLUMN sources TEXT")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(snapshots)")}
        if "promo" not in cols:
            con.execute("ALTER TABLE snapshots ADD COLUMN promo TEXT")
        if "run_id" not in cols:
            con.execute("ALTER TABLE snapshots ADD COLUMN run_id INTEGER")
            # Bases viejas: asignamos cada snapshot al escaneo dentro de cuyo intervalo cayó
            con.execute("""UPDATE snapshots SET run_id = (
                               SELECT r.id FROM scan_runs r
                               WHERE snapshots.scanned_at >= r.started_at
                                 AND snapshots.scanned_at <= COALESCE(r.finished_at, '9999')
                               ORDER BY r.id DESC LIMIT 1)""")
        con.execute("CREATE INDEX IF NOT EXISTS ix_snap_target_run ON snapshots(target_id, run_id)")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # journal_mode por defecto (DELETE): un único archivo .db, ideal para commitearlo en Git.
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ---------------------------------------------------------------- escritura
    def insert_snapshot(self, target_id: str, r: dict, run_id: int | None = None) -> int:
        in_stock = r.get("in_stock")
        with self.connect() as con:
            cur = con.execute(
                """INSERT INTO snapshots (target_id, store, url, title, seller, product_url,
                       price_cash, price_list, in_stock, error, scanned_at, run_id, promo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    target_id, r["store"], r["url"], r.get("title"), r.get("seller"),
                    r.get("product_url"), r.get("price_cash"), r.get("price_list"),
                    None if in_stock is None else int(bool(in_stock)),
                    r.get("error"), r.get("scanned_at") or utcnow(), run_id, r.get("promo"),
                ),
            )
            return int(cur.lastrowid)

    def start_run(self, trigger: str) -> int:
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO scan_runs (trigger, started_at) VALUES (?, ?)", (trigger, utcnow())
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, n_ok: int, n_error: int, n_alerts: int) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE scan_runs SET finished_at=?, n_ok=?, n_error=?, n_alerts=? WHERE id=?",
                (utcnow(), n_ok, n_error, n_alerts, run_id),
            )

    def insert_alert(self, target_id: str, kind: str, message: str, sent: bool) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO alerts (target_id, kind, message, sent, created_at) VALUES (?,?,?,?,?)",
                (target_id, kind, message, int(sent), utcnow()),
            )

    # ---------------------------------------------------------------- mantenimiento
    def compact(self) -> None:
        """Achica la base antes de publicarla: sólo la última corrida de descubrimiento guarda el
        detalle completo (el precio de cada modelo igual queda en discovery_prices) + VACUUM."""
        with self.connect() as con:
            con.execute("""UPDATE discovery_runs SET results=NULL WHERE results IS NOT NULL AND id <
                           (SELECT MAX(id) FROM discovery_runs WHERE finished_at IS NOT NULL)""")
        con = sqlite3.connect(self.path)
        try:
            con.execute("VACUUM")
        finally:
            con.close()

    def merge_from(self, other: Path | str) -> int:
        """Agrega a esta base las filas de `other` que no tiene (escaneos hechos en otro lado).

        Claves naturales: corridas (trigger, started_at); snapshots (target_id, url, scanned_at);
        alertas (target_id, kind, created_at); descubrimientos (trigger, started_at); precios del
        descubrimiento (model_key, scanned_at); avisos de oferta (model_key, level, created_at);
        referencias de evento (event, target_id: gana la primera congelada); caché de specs (la más
        nueva); modelos descubiertos (se combinan primera/última vez y precio mínimo)."""
        n = 0
        with self.connect() as con:
            con.execute("ATTACH DATABASE ? AS o", (str(other),))
            run_map: dict[int, int] = {}
            for r in con.execute("SELECT * FROM o.scan_runs ORDER BY id").fetchall():
                row = con.execute("SELECT id FROM scan_runs WHERE trigger=? AND started_at=?",
                                  (r["trigger"], r["started_at"])).fetchone()
                if row:
                    run_map[r["id"]] = row["id"]
                    continue
                cur = con.execute(
                    """INSERT INTO scan_runs (trigger, started_at, finished_at, n_ok, n_error, n_alerts)
                       VALUES (?,?,?,?,?,?)""",
                    (r["trigger"], r["started_at"], r["finished_at"], r["n_ok"], r["n_error"], r["n_alerts"]))
                run_map[r["id"]] = cur.lastrowid
                n += 1
            for s in con.execute("SELECT * FROM o.snapshots ORDER BY id").fetchall():
                if con.execute("SELECT 1 FROM snapshots WHERE target_id=? AND url=? AND scanned_at=?",
                               (s["target_id"], s["url"], s["scanned_at"])).fetchone():
                    continue
                con.execute(
                    """INSERT INTO snapshots (target_id, store, url, title, seller, product_url,
                       price_cash, price_list, in_stock, error, scanned_at, run_id, promo)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (s["target_id"], s["store"], s["url"], s["title"], s["seller"], s["product_url"],
                     s["price_cash"], s["price_list"], s["in_stock"], s["error"], s["scanned_at"],
                     run_map.get(s["run_id"]), s["promo"] if "promo" in s.keys() else None))
                n += 1
            for a in con.execute("SELECT * FROM o.alerts ORDER BY id").fetchall():
                if con.execute("SELECT 1 FROM alerts WHERE target_id=? AND kind=? AND created_at=?",
                               (a["target_id"], a["kind"], a["created_at"])).fetchone():
                    continue
                con.execute("""INSERT INTO alerts (target_id, kind, message, sent, created_at)
                               VALUES (?,?,?,?,?)""",
                            (a["target_id"], a["kind"], a["message"], a["sent"], a["created_at"]))
                n += 1
            n += self._merge_discovery(con)
            con.commit()
            con.execute("DETACH DATABASE o")
        return n

    @staticmethod
    def _merge_discovery(con: sqlite3.Connection) -> int:
        n = 0
        dmap: dict[int, int] = {}
        ocols = {r["name"] for r in con.execute("PRAGMA o.table_info(discovery_runs)")}
        for r in con.execute("SELECT * FROM o.discovery_runs ORDER BY id").fetchall():
            row = con.execute("SELECT id FROM discovery_runs WHERE trigger=? AND started_at=?",
                              (r["trigger"], r["started_at"])).fetchone()
            if row:
                dmap[r["id"]] = row["id"]
                continue
            cur = con.execute(
                """INSERT INTO discovery_runs (trigger, started_at, finished_at, n_offers, n_models,
                   errors, results, sources) VALUES (?,?,?,?,?,?,?,?)""",
                (r["trigger"], r["started_at"], r["finished_at"], r["n_offers"], r["n_models"],
                 r["errors"], r["results"], r["sources"] if "sources" in ocols else None))
            dmap[r["id"]] = cur.lastrowid
            n += 1
        for p in con.execute("SELECT * FROM o.discovery_prices").fetchall():
            if con.execute("SELECT 1 FROM discovery_prices WHERE model_key=? AND scanned_at=?",
                           (p["model_key"], p["scanned_at"])).fetchone():
                continue
            con.execute("""INSERT INTO discovery_prices (run_id, model_key, price, store, seller, scanned_at)
                           VALUES (?,?,?,?,?,?)""",
                        (dmap.get(p["run_id"], p["run_id"]), p["model_key"], p["price"], p["store"],
                         p["seller"], p["scanned_at"]))
            n += 1
        for m in con.execute("SELECT * FROM o.discovered_models").fetchall():
            cur = con.execute("SELECT * FROM discovered_models WHERE model_key=?", (m["model_key"],)).fetchone()
            if cur is None:
                con.execute("""INSERT INTO discovered_models (model_key, name, status, first_seen, first_run,
                               last_seen, last_price, min_price) VALUES (?,?,?,?,?,?,?,?)""",
                            (m["model_key"], m["name"], m["status"], m["first_seen"],
                             dmap.get(m["first_run"], m["first_run"]), m["last_seen"], m["last_price"],
                             m["min_price"]))
                n += 1
                continue
            newer = m["last_seen"] > cur["last_seen"]
            con.execute("""UPDATE discovered_models SET first_seen=MIN(first_seen, ?),
                           min_price=MIN(COALESCE(min_price, ?), ?), last_seen=MAX(last_seen, ?),
                           name=?, status=?, last_price=? WHERE model_key=?""",
                        (m["first_seen"], m["min_price"], m["min_price"], m["last_seen"],
                         m["name"] if newer else cur["name"], m["status"] if newer else cur["status"],
                         m["last_price"] if newer else cur["last_price"], m["model_key"]))
        for a in con.execute("SELECT * FROM o.offer_alerts").fetchall():
            if con.execute("SELECT 1 FROM offer_alerts WHERE model_key=? AND level=? AND created_at=?",
                           (a["model_key"], a["level"], a["created_at"])).fetchone():
                continue
            con.execute("INSERT INTO offer_alerts (model_key, level, price, created_at) VALUES (?,?,?,?)",
                        (a["model_key"], a["level"], a["price"], a["created_at"]))
            n += 1
        n += con.execute("""INSERT OR IGNORE INTO event_refs (event, target_id, ref, best, created_at)
                            SELECT event, target_id, ref, best, created_at FROM o.event_refs""").rowcount
        n += con.execute("""INSERT OR REPLACE INTO spec_cache (model_key, data, fetched_at)
                            SELECT o.model_key, o.data, o.fetched_at FROM o.spec_cache AS o
                            LEFT JOIN spec_cache AS m ON m.model_key = o.model_key
                            WHERE m.model_key IS NULL OR o.fetched_at > m.fetched_at""").rowcount
        return n

    def spec_cache_get(self, keys: list[str], max_age_days: int = 30) -> dict[str, dict]:
        with self.connect() as con:
            rows = con.execute(
                f"""SELECT model_key, data FROM spec_cache WHERE fetched_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?)
                    AND model_key IN ({','.join('?' * len(keys)) or "''"})""",
                (f"-{int(max_age_days)} days", *keys)).fetchall()
        return {r["model_key"]: json.loads(r["data"]) for r in rows}

    def spec_cache_put(self, key: str, data: dict) -> None:
        with self.connect() as con:
            con.execute("INSERT OR REPLACE INTO spec_cache (model_key, data, fetched_at) VALUES (?,?,?)",
                        (key, json.dumps(data, ensure_ascii=False), utcnow()))

    # ---------------------------------------------------------------- descubrimiento
    def start_discovery(self, trigger: str) -> int:
        with self.connect() as con:
            return int(con.execute("INSERT INTO discovery_runs (trigger, started_at) VALUES (?, ?)",
                                   (trigger, utcnow())).lastrowid)

    def finish_discovery(self, run_id: int, n_offers: int, results: list[dict],
                         errors: list[str], sources: list[dict] | None = None) -> None:
        with self.connect() as con:
            con.execute(
                """UPDATE discovery_runs SET finished_at=?, n_offers=?, n_models=?, errors=?,
                   results=?, sources=? WHERE id=?""",
                (utcnow(), n_offers, len(results), json.dumps(errors, ensure_ascii=False),
                 json.dumps(results, ensure_ascii=False),
                 json.dumps(sources, ensure_ascii=False) if sources is not None else None, run_id))

    def store_health(self, runs: int = 30) -> list[dict]:
        """Por fuente: ofertas en el último descubrimiento, cuándo trajo algo por última vez y
        cuándo falló por última vez (de los últimos `runs` descubrimientos)."""
        with self.connect() as con:
            rows = con.execute("""SELECT started_at, sources FROM discovery_runs
                                  WHERE sources IS NOT NULL AND finished_at IS NOT NULL
                                  ORDER BY id DESC LIMIT ?""", (runs,)).fetchall()
        out: dict[str, dict] = {}
        for i, r in enumerate(rows):
            for s in json.loads(r["sources"]):
                h = out.setdefault(s["store"], {"store": s["store"], "last": None, "last_ok": None,
                                                "last_fail": None, "error": None})
                if i == 0 and h["last"] is None:
                    h["last"], h["error"] = s.get("n", 0), s.get("error")
                if s.get("n") and h["last_ok"] is None:
                    h["last_ok"] = r["started_at"]
                if (s.get("error") or not s.get("n")) and h["last_fail"] is None:
                    h["last_fail"] = r["started_at"]
        return sorted(out.values(), key=lambda h: (bool(h["last"]), h["store"]))

    def has_discovered_models(self) -> bool:
        with self.connect() as con:
            return con.execute("SELECT 1 FROM discovered_models LIMIT 1").fetchone() is not None

    def upsert_discovered(self, run_id: int, results: list) -> set[str]:
        """Guarda modelos y precio de esta corrida. Devuelve las claves vistas por primera vez."""
        now = utcnow()
        new: set[str] = set()
        with self.connect() as con:
            for r in results:
                price, best = r.best["price"], r.best
                row = con.execute("SELECT min_price FROM discovered_models WHERE model_key=?",
                                  (r.key,)).fetchone()
                if row is None:
                    new.add(r.key)
                    con.execute(
                        """INSERT INTO discovered_models (model_key, name, status, first_seen,
                           first_run, last_seen, last_price, min_price) VALUES (?,?,?,?,?,?,?,?)""",
                        (r.key, r.name, r.status, now, run_id, now, price, price))
                else:
                    con.execute(
                        """UPDATE discovered_models SET name=?, status=?, last_seen=?, last_price=?,
                           min_price=MIN(COALESCE(min_price, ?), ?) WHERE model_key=?""",
                        (r.name, r.status, now, price, price, price, r.key))
                con.execute(
                    """INSERT INTO discovery_prices (run_id, model_key, price, store, seller,
                       scanned_at) VALUES (?,?,?,?,?,?)""",
                    (run_id, r.key, price, best["store"], best.get("seller"), now))
        return new

    def discovery_series(self, model_key: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("""SELECT MIN(price) AS price, MAX(scanned_at) AS ts FROM discovery_prices
                                  WHERE model_key=? GROUP BY substr(scanned_at, 1, 10)
                                  ORDER BY ts""", (model_key,)).fetchall()
        return [dict(r) for r in rows]

    def offer_already_alerted(self, model_key: str, level: str, price: float, days: int = 7) -> bool:
        """True si en los últimos `days` ya se avisó este modelo con igual o mejor nivel y un precio
        no más de 5 % más caro (evita repetir la misma oferta todos los días)."""
        rank = {"buena": 1, "excepcional": 2}
        with self.connect() as con:
            rows = con.execute("""SELECT level, price FROM offer_alerts WHERE model_key=?
                                  AND created_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?)""",
                               (model_key, f"-{int(days)} days")).fetchall()
        return any(rank[r["level"]] >= rank[level] and price >= r["price"] * 0.95 for r in rows)

    def record_offer_alert(self, model_key: str, level: str, price: float) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO offer_alerts (model_key, level, price, created_at) VALUES (?,?,?,?)",
                        (model_key, level, price, utcnow()))

    def last_discovery(self) -> dict | None:
        with self.connect() as con:
            row = con.execute("""SELECT * FROM discovery_runs WHERE finished_at IS NOT NULL
                                 ORDER BY id DESC LIMIT 1""").fetchone()
            if not row:
                return None
            d = dict(row)
            d["results"] = json.loads(d["results"] or "[]")
            d["errors"] = json.loads(d["errors"] or "[]")
            meta = {r["model_key"]: dict(r) for r in con.execute("SELECT * FROM discovered_models")}
            series: dict[str, list] = {}
            for r in con.execute("""SELECT model_key, price, scanned_at FROM discovery_prices
                                    ORDER BY run_id"""):
                series.setdefault(r["model_key"], []).append(
                    {"ts": r["scanned_at"], "price": r["price"], "where": ""})
        for m in d["results"]:
            info = meta.get(m["key"], {})
            m["first_seen"] = info.get("first_seen")
            m["min_price"] = info.get("min_price")
            m["series"] = series.get(m["key"], [])
        return d

    # ---------------------------------------------------------------- lectura
    def last_snapshot(self, target_id: str, url: str, *, valid_price: bool = False,
                      known_stock: bool = False) -> dict | None:
        """Último snapshot sin error para (target, url).

        valid_price: exige price_cash no nulo. known_stock: exige in_stock no nulo.
        """
        cond = ["target_id=?", "url=?", "error IS NULL"]
        if valid_price:
            cond.append("price_cash IS NOT NULL")
        if known_stock:
            cond.append("in_stock IS NOT NULL")
        sql = "SELECT * FROM snapshots WHERE " + " AND ".join(cond) + " ORDER BY id DESC LIMIT 1"
        with self.connect() as con:
            row = con.execute(sql, (target_id, url)).fetchone()
        return dict(row) if row else None

    def latest_per_url(self) -> list[dict]:
        """Último snapshot (con o sin error) de cada (target, url)."""
        with self.connect() as con:
            rows = con.execute(
                """SELECT s.* FROM snapshots s
                   JOIN (SELECT target_id, url, MAX(id) AS mid FROM snapshots
                         GROUP BY target_id, url) m ON s.id = m.mid"""
            ).fetchall()
        return [dict(r) for r in rows]

    def historical_min(self) -> dict[str, dict]:
        """Precio cash mínimo histórico por target (sólo registros válidos y no marcados sin stock)."""
        with self.connect() as con:
            rows = con.execute(
                """SELECT target_id, store, seller, price_cash, scanned_at FROM (
                       SELECT *, ROW_NUMBER() OVER (PARTITION BY target_id
                                                    ORDER BY price_cash ASC, id ASC) AS rn
                       FROM snapshots
                       WHERE error IS NULL AND price_cash IS NOT NULL
                         AND (in_stock IS NULL OR in_stock = 1))
                   WHERE rn = 1"""
            ).fetchall()
        return {r["target_id"]: dict(r) for r in rows}

    def history(self, target_id: str, limit: int = 500) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                """SELECT store, seller, url, price_cash, price_list, in_stock, error, promo, scanned_at
                   FROM snapshots WHERE target_id=? ORDER BY id DESC LIMIT ?""",
                (target_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def best_series(self, target_id: str, days: int = 365, stale_hours: int = 26) -> list[dict]:
        """Mejor precio del mercado en cada escaneo: la curva de historial.

        Cada punto usa el último precio conocido de CADA link del producto en ese momento (de las
        últimas `stale_hours`), no sólo los links escaneados en esa corrida. Así un escaneo parcial
        (p. ej. el local, que sólo mira Frávega y Venex) no produce picos falsos.
        store/seller son los de la tienda que tenía el mejor precio en ese momento.
        """
        from datetime import datetime, timedelta

        with self.connect() as con:
            rows = con.execute(
                """SELECT run_id, url, store, seller, price_cash, in_stock, error, scanned_at
                   FROM snapshots WHERE target_id=? AND run_id IS NOT NULL
                     AND COALESCE(promo, '') NOT LIKE 'carga manual%'
                     AND scanned_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?)
                   ORDER BY scanned_at, id""",
                (target_id, f"-{int(days) + 2} days"),
            ).fetchall()
        latest: dict[str, dict] = {}       # url -> último snapshot sin error
        out: list[dict] = []
        cur_run, cur_ts = None, None

        def emit() -> None:
            if cur_run is None:
                return
            now = datetime.fromisoformat(cur_ts)
            valid = [r for r in latest.values()
                     if r["price_cash"] is not None and r["in_stock"] != 0
                     and now - datetime.fromisoformat(r["scanned_at"]) <= timedelta(hours=stale_hours)]
            if valid:
                b = min(valid, key=lambda r: r["price_cash"])
                out.append({"run_id": cur_run, "price": b["price_cash"], "store": b["store"],
                            "seller": b["seller"], "ts": cur_ts})

        for r in rows:
            if r["run_id"] != cur_run:
                emit()
                cur_run = r["run_id"]
            cur_ts = r["scanned_at"]
            if r["error"] is None:
                latest[r["url"]] = dict(r)
        emit()
        return out

    def url_median(self, target_id: str, url: str, days: int = 30, exclude_hours: int = 24) -> float | None:
        """Precio habitual de UN link (mediana de 30 días sin las últimas 24 h)."""
        import statistics

        with self.connect() as con:
            rows = con.execute(
                """SELECT price_cash FROM snapshots WHERE target_id=? AND url=? AND error IS NULL
                   AND price_cash IS NOT NULL AND (in_stock IS NULL OR in_stock = 1)
                   AND scanned_at >= strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?) AND scanned_at <= strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?)""",
                (target_id, url, f"-{int(days)} days", f"-{int(exclude_hours)} hours")).fetchall()
        prices = [r[0] for r in rows]
        return statistics.median(prices) if len(prices) >= 3 else None

    def event_refs(self, event: str) -> dict[str, dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM event_refs WHERE event=?", (event,)).fetchall()
        return {r["target_id"]: dict(r) for r in rows}

    def freeze_event_refs(self, event: str, refs: dict[str, tuple[float | None, float | None]]) -> None:
        with self.connect() as con:
            for tid, (ref, best) in refs.items():
                con.execute("""INSERT OR IGNORE INTO event_refs (event, target_id, ref, best, created_at)
                               VALUES (?,?,?,?,?)""", (event, tid, ref, best, utcnow()))

    def last_run(self) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM scan_runs WHERE trigger != 'manual' ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def recent_alerts(self, limit: int = 20) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
