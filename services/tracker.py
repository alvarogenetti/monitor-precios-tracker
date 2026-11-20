"""Orquestador: recorre las URLs activas, guarda snapshots y dispara alertas."""
from __future__ import annotations

import asyncio
import html
import logging
import os
import random
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable

from scrapers.base import BrowserSession, ScrapeResult
from scrapers.stores import get_scraper_class
from services.db import Database, utcnow
from services.notifier import send_telegram
from services.targets import BANDS, Target, load_targets
from settings import settings

log = logging.getLogger(__name__)


def fmt_ars(v: float | None) -> str:
    return "-" if v is None else "$ " + f"{v:,.0f}".replace(",", ".")


# ------------------------------------------------------------------ alertas
@dataclass
class Alert:
    kind: str       # price_drop | target_reached | back_in_stock
    text: str       # HTML para Telegram


def evaluate_alerts(db: Database, target: Target, res: ScrapeResult) -> list[Alert]:
    """Compara el resultado nuevo contra el historial (antes de insertarlo)."""
    if not res.ok:
        return []
    alerts: list[Alert] = []
    prev_valid = db.last_snapshot(target.id, res.url, valid_price=True)
    prev_known = db.last_snapshot(target.id, res.url, known_stock=True)
    price = res.price_cash
    sellable = res.in_stock is not False and price is not None
    # Precio absurdo (muy por encima del rango "alto"): no se alerta nada, ni stock ni precio
    if price is not None and price > target.high * settings.alert_max_over_high:
        return []

    name = html.escape(target.name)
    where = html.escape(res.store + (f" ({res.seller})" if res.seller else ""))
    link = html.escape(res.product_url or res.url, quote=True)
    footer = f'\n🏪 {where}\n🔗 <a href="{link}">Ver producto</a>'

    # 1) Volvió el stock
    if res.in_stock is True and prev_known and prev_known["in_stock"] == 0:
        alerts.append(Alert("back_in_stock",
                            f"📦 <b>¡Volvió el stock!</b> {name}\nPrecio: <b>{fmt_ars(price)}</b>{footer}"))

    if sellable:
        prev_price = prev_valid["price_cash"] if prev_valid else None
        dropped = (prev_price is not None and price < prev_price
                   and (prev_price - price) / prev_price * 100 >= settings.alert_min_drop_pct)
        # 2) Bajó el precio respecto al último registro válido
        if dropped:
            pct = (prev_price - price) / prev_price * 100
            alerts.append(Alert(
                "price_drop",
                f"📉 <b>Bajó de precio</b> {name}\n{fmt_ars(prev_price)} → <b>{fmt_ars(price)}</b> "
                f"(-{pct:.1f}%)\nRango: <b>{BANDS[target.band(price)]}</b> · "
                f"objetivo {fmt_ars(target.target_price)}{footer}"))
        # 3) Precio <= objetivo. Para no spamear cada 3 h, sólo cuando recién cruza el objetivo,
        #    cuando además bajó, o cuando no había registro previo.
        if price <= target.target_price and (
            prev_price is None or prev_price > target.target_price or dropped
        ):
            alerts.append(Alert(
                "target_reached",
                f"🎯 <b>Precio objetivo alcanzado</b> {name}\n<b>{fmt_ars(price)}</b> "
                f"≤ objetivo {fmt_ars(target.target_price)}{footer}"))
    return alerts


# ------------------------------------------------------------------ estado (para la UI)
@dataclass
class ScanState:
    running: bool = False
    job: str | None = None          # scan | discover
    trigger: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    total: int = 0
    done: int = 0
    current: str | None = None
    last_summary: dict | None = None
    error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


STATE = ScanState()


# ------------------------------------------------------------------ escaneo
async def run_scan(trigger: str = "cli", target_ids: list[str] | None = None,
                   send_alerts: bool = True, only_local: bool = False,
                   on_progress: Callable[[int, int, str], None] | None = None) -> dict:
    db = Database(settings.db_path)
    targets = [t for t in load_targets(settings.targets_path) if t.active]
    if target_ids:
        targets = [t for t in targets if t.id in target_ids]
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    jobs = [(t, u) for t in targets for u in t.urls if u.active and (u.ci or not in_ci)]
    if only_local:  # escaneo-local.ps1: sólo lo que GitHub Actions no puede leer
        jobs = [(t, u) for t, u in jobs if not u.ci]
    run_id = db.start_run(trigger)
    log.info("Escaneo #%d (%s): %d URLs en %d productos", run_id, trigger, len(jobs), len(targets))

    results: list[dict] = []
    n_ok = n_err = n_alerts = 0
    if not jobs:
        db.finish_run(run_id, 0, 0, 0)
        return {"run_id": run_id, "ok": 0, "errors": 0, "alerts": 0, "results": []}

    async with BrowserSession(settings.headless, settings.block_stylesheets,
                              settings.page_timeout_ms) as session:
        for i, (target, turl) in enumerate(jobs):
            if i:
                await asyncio.sleep(random.uniform(settings.delay_min, settings.delay_max))
            label = f"{target.name} @ {turl.store}"
            if on_progress:
                on_progress(i, len(jobs), label)
            scraper = get_scraper_class(turl.store, turl.url)(session, settings.retries)
            try:
                res = await scraper.scrape(turl.url, target)
            except Exception as e:  # noqa: BLE001 — un fallo inesperado no debe cortar el escaneo
                log.exception("Fallo inesperado en %s", turl.url)
                res = ScrapeResult(store=turl.store, url=turl.url, error=f"inesperado: {e}")
            res.store = turl.store  # etiqueta configurada (p.ej. "maximus" usando el genérico)

            alerts = evaluate_alerts(db, target, res)
            db.insert_snapshot(target.id, res.to_dict(), run_id)
            for a in alerts:
                sent = await send_telegram(a.text) if send_alerts else False
                db.insert_alert(target.id, a.kind, a.text, sent)
            n_alerts += len(alerts)
            n_ok += res.ok
            n_err += not res.ok
            log.info("[%d/%d] %-40s %s%s", i + 1, len(jobs), label[:40], res.short(),
                     f"  ⚑ {len(alerts)} alerta(s)" if alerts else "")
            results.append({"target_id": target.id, "target": target.name,
                            "alerts": [a.kind for a in alerts], **res.to_dict()})
        if on_progress:
            on_progress(len(jobs), len(jobs), "")

    db.finish_run(run_id, n_ok, n_err, n_alerts)
    summary = {"run_id": run_id, "ok": n_ok, "errors": n_err, "alerts": n_alerts,
               "results": results}
    log.info("Escaneo #%d terminado: %d ok, %d errores, %d alertas", run_id, n_ok, n_err, n_alerts)
    return summary


def run_scan_blocking(trigger: str, target_ids: list[str] | None = None,
                      job: str = "scan") -> dict | None:
    """Corre un escaneo en un event loop propio (pensado para threads: web y scheduler).

    Usar un loop dedicado aísla a Playwright del loop de uvicorn; en Windows se fuerza
    ProactorEventLoop, que es el que soporta subprocesos (necesario para lanzar Chromium).
    """
    with STATE._lock:
        if STATE.running:
            log.warning("Ya hay un escaneo en curso; se ignora el disparo '%s'", trigger)
            return None
        STATE.running, STATE.trigger, STATE.error, STATE.job = True, trigger, None, job
        STATE.started_at, STATE.finished_at = utcnow(), None
        STATE.done, STATE.total, STATE.current = 0, 0, None

    def progress(done: int, total: int, label: str) -> None:
        STATE.done, STATE.total, STATE.current = done, total, label or None

    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        if job == "discover":
            from services.discovery import run_discovery

            coro = run_discovery(trigger, on_progress=progress)
        else:
            coro = run_scan(trigger, target_ids, on_progress=progress)
        summary = loop.run_until_complete(coro)
        STATE.last_summary = {k: v for k, v in summary.items() if k != "results"}
        return summary
    except Exception as e:  # noqa: BLE001
        log.exception("El escaneo falló")
        STATE.error = str(e)
        return None
    finally:
        loop.close()
        STATE.running, STATE.finished_at, STATE.current = False, utcnow(), None


def start_scan_thread(trigger: str, target_ids: list[str] | None = None,
                      job: str = "scan") -> bool:
    """Lanza un escaneo (o un descubrimiento) en un thread. False si ya hay uno en curso."""
    if STATE.running:
        return False
    threading.Thread(target=run_scan_blocking, args=(trigger, target_ids, job),
                     name=f"{job}-{trigger}", daemon=True).start()
    return True
