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


def market_ref(db: Database, target: Target) -> tuple[float | None, str]:
    """Precio de referencia de mercado del target (mediana 30 días o el sembrado)."""
    from services.market import reference

    return reference(db.best_series(target.id, days=31), seed=target.market_price)


_RANK = {None: 0, "buena": 1, "excepcional": 2}


def evaluate_alerts(db: Database, target: Target, res: ScrapeResult,
                    ref: tuple[float | None, str] | None = None,
                    notify_drops: bool | None = None) -> list[Alert]:
    """Compara el resultado nuevo contra el historial (antes de insertarlo).

    Por defecto avisa sólo OFERTAS REALES (>= 15 % / >= 30 % debajo del precio de mercado), el
    precio objetivo manual y la vuelta de stock de algo en oferta. Con notify_drops (o
    ALERT_PRICE_DROPS=true) también avisa cada baja >= 1 %.
    """
    from services.events import active_event
    from services.market import LEVELS, claimed_discount, inflated, level, real_discount

    if not res.ok:
        return []
    notify_drops = settings.alert_price_drops if notify_drops is None else notify_drops
    ref_price, ref_src = ref if ref is not None else market_ref(db, target)
    alerts: list[Alert] = []
    prev_valid = db.last_snapshot(target.id, res.url, valid_price=True)
    prev_known = db.last_snapshot(target.id, res.url, known_stock=True)
    price = res.price_cash
    sellable = res.in_stock is not False and price is not None
    # Precio absurdo (muy por encima del mercado o del rango "alto"): no se alerta nada
    cap = max(target.high, ref_price or 0) * settings.alert_max_over_high
    if price is not None and price > cap:
        return []

    ev = active_event()
    name = html.escape(target.name) + (f" · 🔥 {html.escape(ev)}" if ev else "")
    where = html.escape(res.store + (f" ({res.seller})" if res.seller else ""))
    link = html.escape(res.product_url or res.url, quote=True)
    promo = f"\n🏷️ {html.escape(res.promo)}" if res.promo else ""
    footer = f'{promo}\n🏪 {where}\n🔗 <a href="{link}">Ver producto</a>'

    prev_price = prev_valid["price_cash"] if prev_valid else None
    lvl = level(real_discount(price, ref_price)) if sellable else None
    prev_sellable = bool(prev_valid) and prev_valid.get("in_stock") != 0
    prev_lvl = level(real_discount(prev_price, ref_price)) if prev_sellable else None

    # 1) Oferta real: cuando aparece, sube de nivel, o baja 5 % más dentro del mismo nivel
    if lvl and (_RANK[lvl] > _RANK[prev_lvl] or (prev_price and price <= prev_price * 0.95)):
        real = real_discount(price, ref_price)
        claimed = claimed_discount(price, res.price_list)
        fake = ""
        if claimed:
            fake = (f"\n⚠️ La tienda anuncia -{claimed * 100:.0f}%: inflado"
                    if inflated(price, res.price_list, ref_price)
                    else f"\nLa tienda anuncia -{claimed * 100:.0f}%")
        alerts.append(Alert(
            "real_offer",
            f"{LEVELS[lvl]}: <b>{real * 100:.0f}% debajo del mercado</b>\n{name}\n"
            f"<b>{fmt_ars(price)}</b> (mercado {fmt_ars(ref_price)}: {html.escape(ref_src)}){fake}{footer}"))

    # 2) Volvió el stock (sólo si está en precio de oferta, salvo modo "todo")
    if res.in_stock is True and prev_known and prev_known["in_stock"] == 0 and (lvl or notify_drops):
        alerts.append(Alert("back_in_stock",
                            f"📦 <b>¡Volvió el stock!</b> {name}\nPrecio: <b>{fmt_ars(price)}</b>{footer}"))

    if sellable:
        dropped = (prev_price is not None and price < prev_price
                   and (prev_price - price) / prev_price * 100 >= settings.alert_min_drop_pct)
        # 3) Cada baja de precio (sólo en modo "todo")
        if dropped and notify_drops:
            pct = (prev_price - price) / prev_price * 100
            alerts.append(Alert(
                "price_drop",
                f"📉 <b>Bajó de precio</b> {name}\n{fmt_ars(prev_price)} → <b>{fmt_ars(price)}</b> "
                f"(-{pct:.1f}%)\nRango: <b>{BANDS[target.band(price, ref_price)]}</b>{footer}"))
        # 4) Precio <= objetivo manual: sólo cuando recién lo cruza (o baja más)
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
    refs: dict[str, tuple[float | None, str]] = {}
    n_ok = n_err = n_alerts = 0
    if not jobs:
        db.finish_run(run_id, 0, 0, 0)
        return {"run_id": run_id, "ok": 0, "errors": 0, "alerts": 0, "results": []}

    async with BrowserSession(settings.headless, settings.block_stylesheets,
                              settings.page_timeout_ms) as session:
        for i, (target, turl) in enumerate(jobs):
            cls = get_scraper_class(turl.store, turl.url)
            if i and cls.uses_browser:
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

            if target.id not in refs:
                refs[target.id] = market_ref(db, target)
            alerts = evaluate_alerts(db, target, res, refs[target.id])
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
