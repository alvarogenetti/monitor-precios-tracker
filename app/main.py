"""Servidor web: dashboard + API. Ejecutar con `python -m app.main`."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from services.db import Database
from services.discovery import STATUS_LABELS
from services.events import active_event
from services.market import describe, inflated, level, real_discount, reference
from services.targets import BANDS, Target, TargetUrl, load_targets, save_targets, slugify
from services.tracker import STATE, fmt_ars, start_scan_thread
from settings import settings, setup_logging

log = logging.getLogger("app")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["ars"] = fmt_ars

ML_MANUAL_DAYS = 3        # una carga manual de ML vale 3 días


def ml_search_url(name: str) -> str:
    """Búsqueda de Mercado Libre para abrir en el navegador (sólo un link: no se lee nada)."""
    return "https://listado.mercadolibre.com.ar/" + slugify(re.sub(r"\(.*?\)|/.*", " ", name or ""))


templates.env.filters["ml_search"] = ml_search_url


def ml_history_url(code: str) -> str:
    """Historial de precios de ML en MejoresCompras (sólo un link para abrir a mano; según su sitio
    usa la API oficial de ML). Se busca por el código del modelo."""
    from urllib.parse import quote

    toks = [t for t in re.split(r"[\s|]+", code or "") if sum(c.isdigit() for c in t) >= 2]
    return "https://mejorescompras.com.ar/buscar?q=" + quote(toks[0] if toks else (code or "").strip())


templates.env.filters["ml_history"] = ml_history_url

# Tiendas que no se leen automáticamente (bloqueo/antibot): link para mirar + carga manual "Lo vi a $"
MANUAL_STORES = {
    "mercadolibre": ("Mercado Libre", ml_search_url),
    "tiendabna": ("Tienda BNA", lambda name: "https://www.tiendabna.com.ar/"),
}
templates.env.globals["MANUAL_STORES"] = {k: v[0] for k, v in MANUAL_STORES.items()}
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
STALE_HOURS = 26          # un precio de hace más de esto (p. ej. PC apagada) se muestra pero no cuenta
DISCOVERY_FRESH_HOURS = 30


def _age_hours(iso: str | None) -> float:
    from datetime import datetime, timezone

    if not iso:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600


def _fresh_manual(snap: dict) -> bool:
    from datetime import datetime, timedelta, timezone

    if not (snap.get("promo") or "").startswith("carga manual"):
        return False
    return datetime.fromisoformat(snap["scanned_at"]) >= datetime.now(timezone.utc) - timedelta(days=ML_MANUAL_DAYS)


def add_installments(row: dict, infl: float) -> None:
    """Para cada oferta con cuotas sin interés: cuánto vale en pesos de hoy. Si pagar en cuotas en
    alguna tienda sale menos (en pesos de hoy) que la mejor oferta de contado, queda en row["cuotas"]."""
    from services.market import installments, present_value

    best = row["best"]["price_cash"] if row.get("best") else None
    top = None
    for o in row["offers"]:
        s = o.get("snap")
        n = installments(s.get("promo")) if s and s.get("price_cash") and not s.get("error") else None
        o["pv"] = round(present_value(s["price_cash"], n, infl), -2) if n and infl else None
        o["cuotas"] = n
        if o["pv"] and (top is None or o["pv"] < top["pv"]):
            top = {"pv": o["pv"], "n": n, "price": s["price_cash"], "store": s.get("seller") or o["store"],
                   "url": s.get("product_url") or o["url"]}
    row["cuotas"] = top if top and best and top["pv"] < best else None


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
        for o in offers:
            if o["store"] in MANUAL_STORES:
                o["ml"] = True     # tienda que se revisa a mano (ML, Tienda BNA): link + carga manual
                if o["snap"] and not _fresh_manual(o["snap"]):
                    o["snap"] = None      # el precio viejo de la API (o una carga vencida) no cuenta
            elif o["snap"] and _age_hours(o["snap"]["scanned_at"]) > STALE_HOURS:
                o["stale"] = round(_age_hours(o["snap"]["scanned_at"]) / 24, 1)   # días: se muestra, no cuenta
        valid = [o["snap"] for o in offers
                 if o["active"] and o["snap"] and not o.get("stale") and not o["snap"]["error"]
                 and o["snap"]["price_cash"] is not None and o["snap"]["in_stock"] != 0]
        best = min(valid, key=lambda s: s["price_cash"]) if valid else None
        known = [o["snap"]["in_stock"] for o in offers
                 if o["active"] and o["snap"] and not o.get("stale") and not o["snap"]["error"]
                 and o["snap"]["in_stock"] is not None]
        stock = "in" if 1 in known else ("out" if known else "unknown")
        last = max((o["snap"]["scanned_at"] for o in offers if o["snap"]), default=None)
        diff = ((best["price_cash"] - t.target_price) / t.target_price * 100) if best else None
        series = db.best_series(t.id)
        ref, ref_src = reference(series, seed=t.market_price)
        for o in offers:
            s = o["snap"]
            o["market"] = describe(s["price_cash"], s["price_list"], ref) if s and s["price_cash"] else None
            usual = db.url_median(t.id, o["url"]) if s and s["price_cash"] and o["active"] else None
            o["hike"] = round((s["price_cash"] / usual - 1) * 100) if usual and s["price_cash"] >= usual * 1.10 else None
        real = real_discount(best["price_cash"], ref) if best else None
        from services.events import current_or_next, event_key

        ev, _ = current_or_next(within_days=14)
        ev_ref = db.event_refs(event_key(ev)).get(t.id) if ev else None
        rows.append({"target": t, "offers": offers, "best": best, "hist": hist.get(t.id),
                     "stock": stock, "last": last, "diff": diff,
                     "band": t.band(best["price_cash"], ref) if best else None,
                     "ref": ref, "ref_src": ref_src, "real": real, "level": level(real),
                     "ev_ref": ev_ref, "ev_name": ev["name"] if ev else None,
                     "inflated": bool(best and inflated(best["price_cash"], best["price_list"], ref)),
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


def merge_discovery_offers(rows: list[dict], models: list[dict], finished_at: str | None,
                           max_age_h: float = 30) -> None:
    """Suma a cada seguido las ofertas que el descubrimiento encontró para ese mismo modelo en las
    otras ~90 tiendas (si el descubrimiento es reciente). Si alguna es más barata, pasa a ser la mejor
    oferta de la fila (precio, descuento real, banda), marcada como vista en Descubrimiento."""
    from datetime import datetime, timezone

    if not finished_at:
        return
    age = datetime.now(timezone.utc) - datetime.fromisoformat(finished_at)
    if age.total_seconds() > max_age_h * 3600:
        return
    found: dict[str, list[dict]] = {}
    for m in models:
        if m.get("tracked"):
            found.setdefault(m["tracked"], []).extend(m.get("offers") or [])
    for r in rows:
        t = r["target"]
        own = {o["url"] for o in r["offers"]} | {o["snap"].get("product_url") for o in r["offers"] if o["snap"]}
        extra, seen = [], set()
        for o in sorted(found.get(t.id, []), key=lambda o: o["price"]):
            if o["url"] in own or o["url"] in seen or not o.get("price"):
                continue
            seen.add(o["url"])
            title = re.sub(r"\s*\[.*\]$", "", o.get("title") or "")
            promo = re.search(r"\[(.*)\]$", o.get("title") or "")
            snap = {"store": o["store"], "url": o["url"], "product_url": o["url"], "title": title,
                    "seller": o.get("seller"), "price_cash": o["price"], "price_list": o.get("price_list"),
                    "in_stock": 1, "error": None, "scanned_at": finished_at,
                    "promo": promo.group(1) if promo else None}
            extra.append({"store": o["store"], "url": o["url"], "active": True, "via": "descubrimiento",
                          "note": "Visto en Descubrimiento", "snap": snap, "hike": None,
                          "market": describe(o["price"], o.get("price_list"), r["ref"])})
        if not extra:
            continue
        r["offers"] += extra[:5]
        cand = extra[0]["snap"]
        if r["best"] is None or cand["price_cash"] < r["best"]["price_cash"]:
            b = r["best"] = cand
            r["real"] = real_discount(b["price_cash"], r["ref"])
            r["level"] = level(r["real"])
            r["band"] = t.band(b["price_cash"], r["ref"])
            r["inflated"] = bool(inflated(b["price_cash"], b["price_list"], r["ref"]))
            r["hit"] = b["price_cash"] <= t.target_price
            r["diff"] = (b["price_cash"] - t.target_price) / t.target_price * 100
            r["stock"] = "in"
            r["best_via"] = "descubrimiento"


def recommendations(rows: list[dict], models: list[dict], limit: int = 5) -> list[dict]:
    """Modelos descubiertos que conviene empezar a seguir, con el motivo.

    Sólo marcas conocidas que cumplen todo y no seguís todavía, si: están en oferta real, son más
    baratos que todos tus seguidos que cumplen, o tienen USB-C y salen menos que tu opción USB-C."""
    ok_rows = [r for r in rows if r.get("eval", {}).get("status") == "cumple" and r["best"]]
    cheapest = min((r["best"]["price_cash"] for r in ok_rows), default=None)
    usbc = min((r["best"]["price_cash"] for r in ok_rows if r.get("usb_c")), default=None)
    out = []
    for m in models:
        if m.get("tracked") or m.get("generic") or m["status"] not in ("cumple", "oled_oferta"):
            continue
        price = m["best"]["price"]
        why = []
        if m.get("level"):
            why.append(f"oferta real ({m['real'] * 100:.0f}% debajo del mercado)")
        if cheapest and price < cheapest:
            why.append("más barato que todos tus seguidos que cumplen")
        if m.get("usb_c") and (usbc is None or price < usbc):
            why.append("tiene USB-C con carga y sale menos que tu opción USB-C actual" if usbc
                       else "tiene USB-C con carga (no seguís ninguno así)")
        if why:
            out.append({**m, "why": why})
    out.sort(key=lambda m: (not m.get("level"), m["best"]["price"]))
    return out[:limit]


def build_context(static: bool = False) -> dict:
    """Todo lo que necesita el dashboard (se usa igual en la web local y en GitHub Pages)."""
    from scrapers.base import matches_keywords
    from services.discovery import SpecCatalog, evaluate_target, load_json, tracked_by, usb_c_label

    cfg = load_json(settings.discovery_path, {})
    catalog = SpecCatalog(load_json(settings.specs_path, []))
    rows = build_dashboard()
    targets = [r["target"] for r in rows]
    for r in rows:
        if r["target"].kind != "monitor":
            r["eval"], r["usb_c"] = {"status": "accesorio"}, None
            continue
        snaps = [o["snap"] for o in r["offers"] if o["active"] and o["snap"]]
        ev = evaluate_target(r["target"], snaps, cfg, catalog)
        if ev:
            ml_specs_k = db.spec_cache_get([ev["key"]], 3650).get(ev["key"])
            if ml_specs_k:
                ev = evaluate_target(r["target"], snaps, cfg, catalog, {ev["key"]: ml_specs_k})
        r["eval"] = ev or {}
        r["usb_c"] = (ev or {}).get("usb_c")

    disc = db.last_discovery()
    models = []
    if disc:
        from services.discovery import reevaluate
        from services.overrides import load as load_overrides

        ovs = load_overrides(settings.overrides_path)
        from services.spec_enrich import combine

        keys = [m["key"] for m in disc["results"]]
        ml = db.spec_cache_get(keys, 3650)
        pages = {k[5:]: v for k, v in db.spec_cache_get(["page:" + k for k in keys], 3650).items()}
        ml = {k: combine(ml.get(k) or None, pages.get(k) or None) for k in set(ml) | set(pages)}
        generic = [g.lower() for g in cfg.get("generic_brands", [])]
        for m in disc["results"]:
            reevaluate(m, cfg, catalog, ml.get(m["key"]) or None, ovs.get(m["key"]))
            # ¿Lo seguís? (se recalcula en vivo: puede haberse agregado después del descubrimiento)
            m["tracked"] = tracked_by(m["key"], m["offers"], targets, catalog)
            m["usb_c"] = usb_c_label(m.get("spec"), m.get("badges") or [])
            m["generic"] = m.get("generic") or not m.get("brand") or any(g in (m["name"] + " " + (m.get("brand") or "")).lower()
                                                   for g in generic)
            models.append(m)

    merge_discovery_offers(rows, models, (disc or {}).get("finished_at"))
    from services.market import monthly_inflation

    infl = monthly_inflation()
    for r in rows:
        add_installments(r, infl)

    def best_ok(items, price):
        ok = [x for x in items if x[1] is not None]
        return min(ok, key=lambda x: x[1]) if ok else None

    # Para recomendar sólo se usa un descubrimiento reciente (si falló varios días, sus precios son viejos)
    fresh = models if disc and _age_hours(disc.get("finished_at")) <= DISCOVERY_FRESH_HOURS else []
    cheapest = best_ok([(m["name"], m["best"]["price"], m) for m in fresh if m["status"] == "cumple" and not m["generic"]]
                       + [(r["target"].name, r["best"]["price_cash"] if r["best"] else None, r)
                          for r in rows if r["eval"].get("status") == "cumple"], None)
    offers_now = [r for r in rows if r["level"]] + [m for m in fresh if m.get("level")]
    from services.events import load as load_events

    upcoming = None
    from datetime import date, datetime

    from services.events import AR
    for e in sorted(load_events(), key=lambda e: e["from"]):
        if date.fromisoformat(e["to"]) >= datetime.now(AR).date():   # fecha de Argentina (GitHub corre en UTC)
            upcoming = e
            break
    from services.segments import SEGMENTS
    from services.stores_info import STORES

    from services.advice import buy_today

    recs = recommendations(rows, fresh)
    rec_keys = {m["key"] for m in recs}
    for m in models:
        m["recommended"] = m["key"] in rec_keys
    return {
        "static": static, "rows": rows, "models": models, "discovery": disc,
        "recs": recs, "stores": STORES, "req": cfg.get("requirements", {}), "segments": SEGMENTS,
        "advice": buy_today(rows, fresh), "inflation": infl,
        "oled_max": cfg.get("oled_max_price"), "confirm_fields": ["acabado mate", "VESA", "panel", "Hz"],
        "health": store_health_rows(),
        "state": STATE.as_dict(), "last_run": db.last_run(), "alerts": db.recent_alerts(15),
        "telegram": settings.telegram_enabled, "scheduler": settings.scheduler_enabled or static,
        "interval": settings.scan_interval_minutes if not static else 180, "bands": BANDS,
        "event": active_event(), "upcoming": upcoming, "status_labels": STATUS_LABELS,
        "kpi": {"offers": len(offers_now), "cheapest": cheapest, "recs": len(recs),
                "tracked": len(rows), "cumple": sum(1 for m in models if m["status"] == "cumple")},
    }


# ------------------------------------------------------------------ páginas
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", build_context())


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
    segment: str | None = None
    why: str | None = None
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
        if body.segment is not None:
            from services.segments import SEGMENT_KEYS

            if body.segment not in SEGMENT_KEYS:
                raise HTTPException(422, f"Segmento desconocido: {body.segment}")
            t.segment = body.segment
        if body.why is not None:
            t.why = body.why.strip() or None
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
    from services.discovery import SpecCatalog, load_json, tracked_by

    already = tracked_by(m["key"], m["offers"], targets, SpecCatalog(load_json(settings.specs_path, [])))
    if already:
        raise HTTPException(409, f"Ya lo seguís ({already})")
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
    from services.discovery import usb_c_label
    from services.segments import auto_segment

    cheapest = min((r["best"]["price_cash"] for r in build_dashboard()
                    if r["best"] and r["target"].kind == "monitor"), default=None)
    usb = bool(usb_c_label(m.get("spec"), m.get("badges") or []))
    t = Target(id=new_id, name=m["name"][:90], target_price=round(best * 0.95, -3),
               price_high=round(best * 1.10, -3), market_price=round(best, -3), keywords=keywords,
               notes=notes, urls=urls, segment=auto_segment(best, usb, cheapest),
               why="Agregado desde Descubrimiento" + (" (tiene USB-C con carga)" if usb else ""))
    targets.append(t)
    save_targets(settings.targets_path, targets)
    return {"created": True, "target": t.model_dump()}


class ManualPrice(BaseModel):
    target_id: str
    store: str = "mercadolibre"
    price: float = Field(gt=0)
    url: str | None = None          # link a la publicación que viste
    seller: str | None = None


def store_label(store: str) -> str:
    from scrapers.stores.catalogs import LABELS
    from scrapers.stores.vtex import VTEX_STORES

    return LABELS.get(store) or (VTEX_STORES.get(store) or (None,))[0] or {
        "compragamer": "Compra Gamer", "hardgamers": "HardGamers (5 búsquedas)"}.get(store, store.capitalize())


def store_health_rows() -> list[dict]:
    return [{**h, "label": store_label(h["store"])} for h in db.store_health()]


def known_sellers() -> set[str]:
    """Tiendas que ya leemos por su cuenta (para avisar si un vendedor de ML no está cubierto)."""
    from scrapers.stores.catalogs import LABELS
    from scrapers.stores.vtex import VTEX_STORES

    names = set(LABELS) | set(LABELS.values()) | {v[0] for v in VTEX_STORES.values()} | set(VTEX_STORES)
    names |= {u.store for t in load_targets(settings.targets_path) for u in t.urls}
    disc = db.last_discovery() or {}
    names |= {o.get("seller") or "" for m in disc.get("results", []) for o in m.get("offers", [])}
    return {re.sub(r"[^a-z0-9]", "", n.lower()) for n in names if n and n.lower() != "mercadolibre"}


def seller_hint(seller: str | None) -> str | None:
    s = re.sub(r"[^a-z0-9]", "", (seller or "").lower().replace("www", "").replace("comar", ""))
    if len(s) < 3:
        return None
    if any(s in k or k in s for k in known_sellers() if len(k) >= 3):
        return None
    return (f"No seguimos la tienda propia de {seller}. Si tiene página propia, agregala: "
            "suele ser más barata que en Mercado Libre.")


@app.post("/api/manual-price")
def api_manual_price(body: ManualPrice):
    """"Lo vi en Mercado Libre a $X": entra al análisis como una oferta más durante 3 días."""
    t = next((t for t in load_targets(settings.targets_path) if t.id == body.target_id), None)
    if not t:
        raise HTTPException(404, "No existe ese seguido")
    if body.store not in MANUAL_STORES:
        raise HTTPException(422, f"Tienda sin carga manual: {body.store}")
    label, link = MANUAL_STORES[body.store]
    ml = next((u for u in t.urls if u.store == body.store), None)
    if ml is None:
        ml = TargetUrl(store=body.store, url=link(t.name), ci=False,
                       note=f"{label}: sólo link y carga manual (ver README)")
        t.urls.append(ml)
        targets = [x if x.id != t.id else t for x in load_targets(settings.targets_path)]
        save_targets(settings.targets_path, targets)
        from services import overrides

        overrides.push_async(settings.targets_path.parent.parent, [settings.targets_path],
                             f"config: link de {label} para {t.id} (carga manual)")
    from datetime import datetime, timezone

    snap = {"store": body.store, "url": ml.url, "title": t.name, "seller": body.seller or None,
            "product_url": (body.url or "").strip() or ml.url, "price_cash": body.price, "price_list": None,
            "in_stock": True, "error": None, "promo": "carga manual",
            "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    run_id = db.start_run("manual")
    db.insert_snapshot(t.id, snap, run_id)
    db.finish_run(run_id, 1, 0, 0)
    _push_db_async()
    return {"saved": True, "hint": seller_hint(body.seller) if body.store == "mercadolibre" else None}


def _push_db_async() -> None:
    """Publica la base en la rama data en segundo plano (así GitHub Pages ve la carga manual)."""
    import threading

    def run():
        try:
            from services import datastore

            datastore.push(settings.db_path, "carga manual de precio")
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo publicar la base: %s", e)

    threading.Thread(target=run, daemon=True).start()


class ConfirmRequest(BaseModel):
    key: str
    label: str | None = None       # "acabado mate", "VESA", "panel", "Hz", "peso" o motivo de descarte
    answer: str                    # si / no / discard / clear


@app.post("/api/confirm")
def api_confirm(body: ConfirmRequest):
    """Confirma a mano un dato de un modelo (o lo descarta). Se guarda en config/overrides.json y
    se pushea solo a GitHub para que Actions use lo mismo."""
    from services import overrides

    if body.answer not in ("si", "no", "discard", "clear"):
        raise HTTPException(422, "answer debe ser si / no / discard / clear")
    if body.answer in ("si", "no") and body.label not in overrides.FIELDS:
        raise HTTPException(422, f"Dato desconocido: {body.label}")
    ov = overrides.set_value(settings.overrides_path, body.key, body.label, body.answer)
    overrides.push_async(settings.targets_path.parent.parent, [settings.overrides_path],
                         f"config: confirmación manual de {body.key} ({body.label or body.answer})")
    return {"key": body.key, "override": ov}


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
