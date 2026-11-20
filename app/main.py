"""Servidor web: dashboard + API. Ejecutar con `python -m app.main`."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from services.db import Database
from services.discovery import STATUS_LABELS
from services.events import active_event
from services.targets import BANDS, Target, TargetUrl, load_targets, save_targets, slugify
from services.tracker import STATE, fmt_ars, start_scan_thread
from settings import settings, setup_logging

log = logging.getLogger("app")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["ars"] = fmt_ars
db = Database(settings.db_path)


# ------------------------------------------------------------------ scheduler
@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler = None
    if settings.scheduler_enabled:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")
        scheduler.add_job(lambda: start_scan_thread("scheduler"), "interval",
                          minutes=settings.scan_interval_minutes, id="scan",
                          max_instances=1, coalesce=True)
        scheduler.start()
        log.info("Scheduler activo: escaneo cada %d min", settings.scan_interval_minutes)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Monitor de precios AR", lifespan=lifespan)


# ------------------------------------------------------------------ datos del dashboard
def build_dashboard() -> list[dict]:
    targets = load_targets(settings.targets_path)
    latest = {(r["target_id"], r["url"]): r for r in db.latest_per_url()}
    hist = db.historical_min()
    rows = []
    for t in targets:
        offers = []
        for u in t.urls:
            snap = latest.get((t.id, u.url))
            offers.append({"store": u.store, "url": u.url, "active": u.active, "note": u.note,
                           "snap": snap})
        valid = [o["snap"] for o in offers
                 if o["active"] and o["snap"] and not o["snap"]["error"]
                 and o["snap"]["price_cash"] is not None and o["snap"]["in_stock"] != 0]
        best = min(valid, key=lambda s: s["price_cash"]) if valid else None
        known = [o["snap"]["in_stock"] for o in offers
                 if o["active"] and o["snap"] and not o["snap"]["error"]
                 and o["snap"]["in_stock"] is not None]
        stock = "in" if 1 in known else ("out" if known else "unknown")
        last = max((o["snap"]["scanned_at"] for o in offers if o["snap"]), default=None)
        diff = ((best["price_cash"] - t.target_price) / t.target_price * 100) if best else None
        series = db.best_series(t.id)
        rows.append({"target": t, "offers": offers, "best": best, "hist": hist.get(t.id),
                     "stock": stock, "last": last, "diff": diff,
                     "band": t.band(best["price_cash"]) if best else None,
                     "high": t.high,
                     "series": [{"ts": p["ts"], "price": p["price"],
                                 "where": p["store"] + (f" · {p['seller']}" if p["seller"] else "")}
                                for p in series],
                     "stats": series_stats([p["price"] for p in series]),
                     "hit": bool(best and best["price_cash"] <= t.target_price)})
    return rows


def series_stats(prices: list[float]) -> dict | None:
    if not prices:
        return None
    srt = sorted(prices)
    n = len(srt)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    return {"n": n, "min": srt[0], "max": srt[-1], "median": median}


# ------------------------------------------------------------------ páginas
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "rows": build_dashboard(),
        "state": STATE.as_dict(),
        "last_run": db.last_run(),
        "alerts": db.recent_alerts(10),
        "telegram": settings.telegram_enabled,
        "scheduler": settings.scheduler_enabled,
        "interval": settings.scan_interval_minutes,
        "bands": BANDS,
        "event": active_event(),
        "discovery": db.last_discovery(),
        "status_labels": STATUS_LABELS,
    })


# ------------------------------------------------------------------ API
class ScanRequest(BaseModel):
    target_ids: list[str] | None = None


@app.post("/api/scan", status_code=202)
def api_scan(body: ScanRequest | None = None):
    if not start_scan_thread("web", body.target_ids if body else None):
        return JSONResponse({"started": False, "detail": "Ya hay un escaneo en curso",
                             "state": STATE.as_dict()}, status_code=409)
    return {"started": True}


@app.get("/api/status")
def api_status():
    return {"state": STATE.as_dict(), "last_run": db.last_run()}


@app.get("/api/dashboard")
def api_dashboard():
    out = []
    for r in build_dashboard():
        out.append({**{k: v for k, v in r.items() if k != "target"},
                    "target": r["target"].model_dump()})
    return out


@app.get("/api/targets")
def api_targets():
    return [t.model_dump() for t in load_targets(settings.targets_path)]


class TargetUpsert(BaseModel):
    """Crea un target nuevo o edita uno existente.

    - Con `target_id` existente: actualiza los campos enviados y/o agrega `url`.
    - Sin `target_id` (o inexistente) + `name` + `target_price`: crea el target.
    """
    target_id: str | None = None
    name: str | None = None
    target_price: float | None = Field(default=None, gt=0)
    price_high: float | None = Field(default=None, gt=0)
    keywords: list[str] | None = None
    active: bool | None = None
    store: str | None = None
    url: str | None = None


@app.post("/api/targets")
def api_targets_upsert(body: TargetUpsert):
    targets = load_targets(settings.targets_path)
    t = next((x for x in targets if x.id == body.target_id), None) if body.target_id else None

    if t is None:
        if not body.name or not body.target_price:
            raise HTTPException(422, "Para crear un producto hacen falta name y target_price")
        new_id = body.target_id or slugify(body.name)
        if any(x.id == new_id for x in targets):
            raise HTTPException(409, f"Ya existe un producto con id '{new_id}'")
        try:
            t = Target(id=new_id, name=body.name, target_price=body.target_price,
                       price_high=body.price_high, keywords=body.keywords or [])
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        targets.append(t)
        created = True
    else:
        created = False
        if body.name:
            t.name = body.name
        if body.target_price or body.price_high:
            try:  # revalida que price_high > target_price
                idx = targets.index(t)
                t = targets[idx] = Target.model_validate({
                    **t.model_dump(),
                    "target_price": body.target_price or t.target_price,
                    "price_high": body.price_high or t.price_high,
                })
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
        if body.keywords is not None:
            t.keywords = [k for k in body.keywords if k.strip()]
        if body.active is not None:
            t.active = body.active

    if body.url:
        try:
            new_url = TargetUrl(store=body.store or "generic", url=body.url)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        if any(u.url == new_url.url for u in t.urls):
            raise HTTPException(409, "Esa URL ya está cargada para este producto")
        t.urls.append(new_url)

    save_targets(settings.targets_path, targets)
    return {"created": created, "target": t.model_dump()}


class UrlToggle(BaseModel):
    url: str
    active: bool | None = None
    delete: bool = False


@app.post("/api/targets/{target_id}/urls")
def api_target_url(target_id: str, body: UrlToggle):
    targets = load_targets(settings.targets_path)
    t = next((x for x in targets if x.id == target_id), None)
    if not t:
        raise HTTPException(404, "Producto inexistente")
    u = next((x for x in t.urls if x.url == body.url), None)
    if not u:
        raise HTTPException(404, "URL inexistente")
    if body.delete:
        t.urls.remove(u)
    elif body.active is not None:
        u.active = body.active
    save_targets(settings.targets_path, targets)
    return {"target": t.model_dump()}


@app.get("/api/history/{target_id}/best")
def api_history_best(target_id: str, days: int = 365):
    """Mejor precio de cada escaneo (la curva del gráfico)."""
    return db.best_series(target_id, days)


@app.get("/api/history/{target_id}.csv", response_class=PlainTextResponse)
def api_history_csv(target_id: str):
    import csv
    import io

    buf = io.StringIO()
    cols = ["scanned_at", "store", "seller", "price_cash", "price_list", "in_stock", "error", "url"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(reversed(db.history(target_id, 100000)))
    return PlainTextResponse(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="historial-{target_id}.csv"'})


# ------------------------------------------------------------------ descubrimiento
@app.post("/api/discover", status_code=202)
def api_discover():
    if not start_scan_thread("web", job="discover"):
        return JSONResponse({"started": False, "detail": "Ya hay un escaneo en curso",
                             "state": STATE.as_dict()}, status_code=409)
    return {"started": True}


@app.get("/api/discover")
def api_discover_results():
    return db.last_discovery() or {}


class TrackRequest(BaseModel):
    key: str


@app.post("/api/discover/track")
def api_discover_track(body: TrackRequest):
    """Pasa un modelo descubierto a seguimiento (crea el producto con links de búsqueda)."""
    from urllib.parse import quote

    last = db.last_discovery() or {}
    m = next((x for x in last.get("results", []) if x["key"] == body.key), None)
    if not m:
        raise HTTPException(404, "Ese modelo no está en el último descubrimiento")
    targets = load_targets(settings.targets_path)
    new_id = slugify(m["name"])[:50].strip("-")
    if any(t.id == new_id for t in targets):
        raise HTTPException(409, f"Ya existe un producto con id '{new_id}'")
    search = m["search"]
    best = m["best"]["price"]
    keywords = [search] if "~" not in m["key"] else [w for w in search.split() if w]
    urls = [
        TargetUrl(store="compragamer", url=f"https://compragamer.com/productos?criterio={quote(search)}"),
        TargetUrl(store="hardgamers", url=f"https://www.hardgamers.com.ar/search?text={quote(search)}"),
    ]
    if any(o["store"] == "fravega" for o in m["offers"]):
        urls.append(TargetUrl(store="fravega", url=f"https://www.fravega.com/l/?keyword={quote(search)}"))
    notes = "Agregado desde Descubrir."
    if m.get("missing"):
        notes += " Falta confirmar: " + ", ".join(m["missing"]) + "."
    t = Target(id=new_id, name=m["name"][:90], target_price=round(best * 0.95, -3),
               price_high=round(best * 1.10, -3), keywords=keywords, notes=notes, urls=urls)
    targets.append(t)
    save_targets(settings.targets_path, targets)
    return {"created": True, "target": t.model_dump()}


# Va después de las rutas .csv y /best para que {target_id} no se las trague
@app.get("/api/history/{target_id}")
def api_history(target_id: str, limit: int = 500):
    return db.history(target_id, limit)


def main() -> None:
    import uvicorn

    setup_logging()
    log.info("Dashboard en http://%s:%d", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
