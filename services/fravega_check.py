"""Chequeo de fichas de Frávega en un navegador real (sólo desde la PC).

Frávega dejó VTEX para su web propia, pero su API de VTEX (la que leemos) sigue devolviendo con stock
productos que en la web nueva no existen ("La página no existe") o no se pueden comprar (sin precio,
botones desactivados). En los datos de VTEX no hay nada que los distinga, así que antes de usar una
oferta de Frávega como mejor precio se abre su ficha, como lo haría una persona:

    ok           la ficha tiene precio y se puede comprar
    missing      "La página no existe"
    unavailable  existe pero sin precio, o "no se encuentra disponible para tu ubicación"
    unknown      no se pudo cargar (error de red): no se descarta la oferta

Se abre una ficha por oferta candidata (la más barata de cada seguido y de cada modelo del
descubrimiento), con pausa entre fichas. Los resultados se guardan en data/fravega_check.json:
`ok` vale 12 h y `missing`/`unavailable` 24 h. En GitHub Actions no se usa (Frávega bloquea a GitHub).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

CACHE = Path(__file__).resolve().parent.parent / "data" / "fravega_check.json"
TTL_H = {"ok": 12, "missing": 24, "unavailable": 24}
BAD = ("missing", "unavailable")
MAX_PER_RUN = 40
PAUSE_S = 2.0
WAIT_S = 15


def item_id(url: str) -> str | None:
    m = re.search(r"-(\d{5,})/?(?:\?.*)?$", url or "")
    return m.group(1) if m else None


def enabled() -> bool:
    return os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("FRAVEGA_CHECK", "1") != "0"


def _load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(cache: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("Frávega: no se pudo guardar la caché del chequeo: %s", e)


def _fresh(entry: dict | None) -> bool:
    if not entry or entry.get("status") not in TTL_H:
        return False
    age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["checked"])
    return age <= timedelta(hours=TTL_H[entry["status"]])


def classify(text: str, buy_enabled: bool) -> str:
    """Estado de una ficha a partir de su texto visible."""
    if "La página no existe" in text:
        return "missing"
    if "no se encuentra disponible" in text:
        return "unavailable"
    has_price = re.search(r"\$\s?\d{1,3}(?:\.\d{3})+", text) is not None
    return "ok" if has_price and buy_enabled else "unavailable"


def _check_pages(urls: list[str]) -> dict[str, str]:
    """Abre cada ficha en Chromium (Playwright) y la clasifica."""
    from playwright.sync_api import sync_playwright

    out: dict[str, str] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(locale="es-AR")
        try:
            for i, url in enumerate(urls):
                if i:
                    time.sleep(PAUSE_S)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    status, deadline = "unavailable", time.time() + WAIT_S
                    while time.time() < deadline:      # la ficha se arma con JavaScript: esperar
                        text = page.inner_text("body")
                        buttons = page.query_selector_all("button:has-text('Comprar')")
                        enabled_btn = any(b.is_enabled() for b in buttons)
                        status = classify(text, enabled_btn)
                        if status in ("ok", "missing") or "no se encuentra disponible" in text:
                            break
                        page.wait_for_timeout(1000)
                    out[url] = status
                except Exception as e:  # noqa: BLE001
                    log.warning("Frávega: no se pudo abrir %s: %s", url, e)
                    out[url] = "unknown"
        finally:
            browser.close()
    return out


def check(urls: list[str]) -> dict[str, str]:
    """Estado de cada link de Frávega (usa la caché; abre sólo lo que falta, hasta MAX_PER_RUN)."""
    if not enabled():
        return {u: "unknown" for u in urls}
    cache, out, todo = _load(), {}, []
    for u in dict.fromkeys(urls):
        iid = item_id(u)
        if iid and _fresh(cache.get(iid)):
            out[u] = cache[iid]["status"]
        elif iid:
            todo.append(u)
        else:
            out[u] = "unknown"
    if todo:
        try:
            got = _check_pages(todo[:MAX_PER_RUN])
        except Exception as e:  # noqa: BLE001 — si el navegador no arranca, no se descarta nada
            log.warning("Frávega: no se pudo hacer el chequeo de fichas: %s", e)
            got = {u: "unknown" for u in todo[:MAX_PER_RUN]}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for u, st in got.items():
            out[u] = st
            if st != "unknown":
                cache[item_id(u)] = {"status": st, "checked": now, "url": u}
        for u in todo[MAX_PER_RUN:]:
            out[u] = "unknown"
        _save(cache)
        bad = sum(1 for s in got.values() if s in BAD)
        log.info("Frávega: %d fichas revisadas, %d no válidas (no existen o no se pueden comprar)", len(got), bad)
    return out


def is_bad(url: str) -> bool:
    return check([url]).get(url) in BAD


REJECTED: list[str] = []      # links descartados en el último first_valid (para explicar el "sin stock")


def first_valid(offers: list[dict]) -> dict | None:
    """De ofertas de Frávega ordenables por precio, la más barata que pasa el chequeo (abre de a una)."""
    REJECTED.clear()
    for o in sorted(offers, key=lambda o: o["price"]):
        if not is_bad(o["url"]):
            return o
        log.info("Frávega: descarto %s ($%s): la ficha no existe o no se puede comprar", o["url"], o["price"])
        REJECTED.append(o["url"])
    return None
