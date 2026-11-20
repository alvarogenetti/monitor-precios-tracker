"""Descubrimiento: busca en todo el catálogo monitores que cumplan los requisitos obligatorios.

Recorre fuentes "amplias" (catálogo completo de Compra Gamer, búsquedas genéricas de HardGamers y
Frávega), agrupa las ofertas por modelo y evalúa cada modelo contra config/discovery.json:

  - Lo que se puede leer del título (27", QHD, Hz, IPS/VA/OLED, curvo, usado) se verifica siempre.
  - Lo que NO figura en los títulos (acabado mate, VESA, peso, brillo, Hz por HDMI, fuente 220 V,
    USB-C PD) sale del catálogo de specs verificadas config/specs.json. Si un modelo no está ahí,
    queda "a confirmar" con la lista de lo que falta revisar.

Estados: cumple · a_confirmar · oled_oferta (OLED por debajo de oled_max_price) · descartado.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from scrapers.base import BrowserSession, availability_to_stock
from scrapers.stores.compragamer import CATALOG_URL_RE, item_in_stock, product_url
from scrapers.stores.fravega import CARDS_JS as FRAVEGA_CARDS_JS
from scrapers.stores.fravega import SELLER_RE, card_prices
from scrapers.stores.hardgamers import CARDS_JS as HG_CARDS_JS
from services.price_parser import is_plausible, parse_ars

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "cumple": "Cumple todo",
    "a_confirmar": "A confirmar",
    "oled_oferta": "OLED en oferta",
    "descartado": "Descartado",
}
STATUS_ORDER = {"cumple": 0, "oled_oferta": 1, "a_confirmar": 2, "descartado": 3}

BRANDS = ["ASROCK", "GIGABYTE", "AORUS", "MSI", "LG", "BENQ", "SAMSUNG", "KTC", "ARKHAM", "RAPTOR",
          "VALKYRIE", "X-MICRO", "XMICRO", "TEROS", "VIEWSONIC", "ASUS", "ACER", "AOC", "PHILIPS",
          "DELL", "LENOVO", "XIAOMI", "HP", "SOLARMAX", "KOORUI", "HIKVISION", "NOGA", "PHILCO",
          "BGH", "COOLER MASTER", "REDRAGON", "GAMEMAX", "TCL", "HISENSE", "NZXT", "EVNIA", "INNOCN"]


# ------------------------------------------------------------------ config
def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _lower(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


class SpecCatalog:
    """config/specs.json: lista de modelos con specs verificadas (fuente + confianza)."""

    def __init__(self, entries: list[dict]):
        self.entries = entries
        self._keys: list[tuple[str, dict]] = []
        for e in entries:
            for k in [e.get("model_key", "")] + list(e.get("aliases") or []):
                if norm(k):
                    self._keys.append((norm(k), e))
        self._keys.sort(key=lambda kv: -len(kv[0]))   # primero la clave más específica

    def match(self, title: str) -> dict | None:
        """Entrada cuyo código de modelo aparece en el título."""
        t = norm(title)
        return next((e for k, e in self._keys if k in t), None)

    def match_brand_hz(self, title: str) -> dict | None:
        """Para títulos SIN código de modelo ("MONITOR VALKYRIE 27 QHD 200HZ IPS"): si hay una sola
        entrada de esa marca con esos Hz, y el título no contradice el panel, es ese modelo."""
        f = title_facts(title)
        brand, hz = brand_of(title), f.hz
        if not brand or not hz or f.curved or f.panel not in (None, "IPS") or f.res not in (None, "qhd"):
            return None
        same = [e for e in self.entries
                if brand_of(e.get("name", "")) == brand and e.get("hz_dp") == hz]
        return same[0] if len(same) == 1 else None


# ------------------------------------------------------------------ hechos desde el título
SIZE_QUOTE_RE = re.compile(r"(?<![\d.,])(\d{2}(?:[.,]\d)?)\s*\\?(?:\"|”|″|''|pulgadas|pulg\b|inch)")
SIZE_BARE_RE = re.compile(r"(?<![\w.,])([2-4]\d)(?:[.,](\d))?(?![\w.,%])(?!\s*(?:hz|ms|w\b|cd|nits))")


@dataclass
class TitleFacts:
    size: float | None = None
    res: str | None = None          # qhd / fhd / 4k
    hz: int | None = None
    panel: str | None = None        # IPS / VA / OLED
    curved: bool = False
    usb_c: bool = False
    us_plug: bool = False
    outlet: bool = False


def title_facts(title: str) -> TitleFacts:
    t = _lower(title)
    f = TitleFacts()
    m = SIZE_QUOTE_RE.search(t)
    if m:
        f.size = float(m.group(1).replace(",", "."))
    else:
        m = SIZE_BARE_RE.search(t)
        if m:
            f.size = float(m.group(1) + (f".{m.group(2)}" if m.group(2) else ""))
    if re.search(r"\b(4k|uhd|2160p?|3840)\b", t):
        f.res = "4k"
    elif re.search(r"w?qhd|\b2k\b|1440p?|2560", t):
        f.res = "qhd"
    elif re.search(r"\b(fhd|full\s*hd|1080p?|1920)\b", t):
        f.res = "fhd"
    hz = [int(x) for x in re.findall(r"(\d{2,3})\s*hz", t)]
    f.hz = max(hz) if hz else None
    if "oled" in t:
        f.panel = "OLED"
    elif re.search(r"\b(h?va|mva)\b", t):
        f.panel = "VA"
    elif "ips" in t:
        f.panel = "IPS"
    f.curved = bool(re.search(r"curv|\b1[0-9]00r\b", t))
    f.usb_c = bool(re.search(r"usb[\s-]?c\b|type[\s-]?c\b", t))
    f.us_plug = "ficha usa" in t
    f.outlet = "outlet" in t
    return f


TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9\-]{3,}")
NOT_MODEL_RE = re.compile(
    r"^(\d+(HZ|MS|P|K|W|R|GB|NITS|CD|X\d+)?|HDR\d+|DCI\w*|SRGB\w*|HDMI\w*|USB\w*|DP\d\w*|"
    r"G-?SYNC\w*|QHD\w*|WQHD|1MS\w*|ELIMINAR)$")


def brand_of(title: str) -> str | None:
    t = f" {title.upper()} "
    return next((b for b in BRANDS if f" {b} " in t or f" {b}-" in t), None)


def model_key(title: str, facts: TitleFacts,
              catalog: SpecCatalog) -> tuple[str, str, dict | None]:
    """(clave normalizada, código legible para buscar, specs). Prioriza el catálogo de specs."""
    spec = catalog.match(title)
    if spec:
        return norm(spec["model_key"]), spec.get("search") or spec["model_key"], spec
    for tok in TOKEN_RE.findall(title.upper()):
        core = tok.strip("-")
        if (sum(c.isdigit() for c in core) >= 2 and any(c.isalpha() for c in core)
                and not NOT_MODEL_RE.match(core) and not re.fullmatch(r"\d+X\d+", core)
                and len(norm(core)) >= 4):
            return norm(core), core, None
    spec = catalog.match_brand_hz(title)
    if spec:
        return norm(spec["model_key"]), spec.get("search") or spec["model_key"], spec
    brand = brand_of(title) or norm(title)[:16]
    return f"{norm(brand)}~{facts.hz or 0}HZ", brand.title(), None


# ------------------------------------------------------------------ evaluación
@dataclass
class Offer:
    store: str
    title: str
    price: float
    url: str
    seller: str | None = None
    price_list: float | None = None
    in_stock: bool | None = True


@dataclass
class ModelResult:
    key: str
    search: str
    name: str
    brand: str | None
    status: str
    best: dict
    offers: list[dict]
    n_stores: int
    facts: dict
    spec: dict | None
    fails: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)   # requisito -> ok / fail / ?
    is_new: bool = False
    tracked: str | None = None


def _majority(values: list) -> Any:
    vals = [v for v in values if v is not None]
    return Counter(vals).most_common(1)[0][0] if vals else None


def evaluate(offers: list[Offer], key: str, search: str, spec: dict | None, cfg: dict) -> ModelResult:
    req = cfg.get("requirements", {})
    facts_list = [title_facts(o.title) for o in offers]
    facts = TitleFacts(
        size=_majority([f.size for f in facts_list]),
        res=_majority([f.res for f in facts_list]),
        hz=max((f.hz for f in facts_list if f.hz), default=None),
        panel=_majority([f.panel for f in facts_list]),
        curved=any(f.curved for f in facts_list),
        usb_c=any(f.usb_c for f in facts_list),
        us_plug=any(f.us_plug for f in facts_list),
        outlet=all(f.outlet for f in facts_list),
    )
    sellable = [o for o in offers if o.in_stock is not False] or offers
    best = min(sellable, key=lambda o: o.price)
    s = spec or {}
    fails: list[str] = []
    missing: list[str] = []
    warns: list[str] = []
    badges: list[str] = []
    checks: dict[str, str] = {}

    def check(name: str, ok: bool | None) -> None:
        checks[name] = "?" if ok is None else ("ok" if ok else "fail")

    size = facts.size
    if size is None:
        missing.append("tamaño")
    elif abs(size - req.get("size_in", 27)) > 0.3:
        fails.append(f'{size:g}" (no es 27")')
    check('27"', None if size is None else abs(size - req.get("size_in", 27)) <= 0.3)

    res = {"2560x1440": "qhd", "3840x2160": "4k", "1920x1080": "fhd"}.get(s.get("resolution") or "", facts.res)
    if res is None:
        # Los QHD casi siempre lo anuncian (QHD/2K/1440); si el título no lo dice suele ser Full HD.
        # Si en realidad es QHD, agregalo a specs.json con "resolution": "2560x1440".
        fails.append("resolución no informada (probable Full HD)")
    elif res != "qhd":
        fails.append({"4k": "4K", "fhd": "Full HD"}.get(res, res))
    check("QHD", None if res is None else res == "qhd")

    hz = max([h for h in (facts.hz, s.get("hz_dp")) if h] or [0]) or None
    min_hz = req.get("min_hz", 120)
    if hz is None:
        missing.append("Hz")
    elif hz < min_hz:
        fails.append(f"{hz} Hz (< {min_hz})")
    check(f"≥{min_hz} Hz", None if hz is None else hz >= min_hz)
    hz_hdmi = s.get("hz_hdmi")
    if hz_hdmi and hz_hdmi < min_hz:
        warns.append(f"por HDMI sólo {hz_hdmi} Hz")

    panel = (s.get("panel") or "").upper() or facts.panel
    is_oled = "OLED" in (panel or "") or facts.panel == "OLED"
    if is_oled:
        if best.price > cfg.get("oled_max_price", 0):
            fails.append("OLED (caro)")
    elif panel and re.search(r"VA", panel):
        fails.append("panel VA")
    elif not panel:
        missing.append("panel")
    elif "IPS" not in panel:
        fails.append(f"panel {panel}")

    check("IPS", None if not panel and not is_oled else ("IPS" in (panel or "") and not is_oled))
    if facts.curved or s.get("flat") is False:
        fails.append("curvo")
    check("plano", False if (facts.curved or s.get("flat") is False) else (True if s.get("flat") else None))

    if s.get("anti_glare") is False:
        fails.append("pantalla brillante (no mate)")
    elif s.get("anti_glare") is None and req.get("anti_glare", True) and not is_oled:
        missing.append("acabado mate")

    check("mate", s.get("anti_glare"))
    vesa = (s.get("vesa") or "").replace(" ", "").lower()
    if vesa in ("none", "no"):
        fails.append("sin VESA")
    elif vesa:
        if vesa not in [v.lower() for v in req.get("vesa", ["75x75", "100x100"])]:
            fails.append(f"VESA {s['vesa']}")
    else:
        missing.append("VESA")

    check("VESA", None if not vesa else vesa in [v.lower() for v in req.get("vesa", [])])
    w = s.get("weight_no_stand_kg")
    if w is None:
        missing.append("peso")
    elif w >= req.get("max_weight_kg", 8):
        fails.append(f"pesa {w:g} kg")

    check("<8 kg", None if w is None else w < req.get("max_weight_kg", 8))
    if s.get("hdmi_ports") == 0:
        fails.append("sin HDMI")

    nits = s.get("brightness_nits")
    if nits and nits < req.get("ideal_brightness_nits", 300):
        warns.append(f"brillo {nits} nits")
    if s.get("flicker_free") is False:
        warns.append("sin flicker-free")
    psu = s.get("psu_voltage") or ""
    if psu and "240" not in psu and "220" not in psu:
        warns.append(f"fuente {psu}: verificar 220 V")
    if facts.us_plug:
        warns.append("ficha USA (usar cable/adaptador)")
    if facts.outlet:
        warns.append("outlet")

    pd = s.get("usb_c_pd_w") or 0
    if pd >= 65:
        badges.append(f"USB-C {pd} W")
    elif facts.usb_c:
        badges.append("USB-C")
    if hz:
        badges.append(f"{hz} Hz")
    if s.get("confidence"):
        badges.append(f"specs {s['confidence']}")

    if fails:
        status = "descartado"
    elif is_oled:
        status = "oled_oferta"
    elif missing:
        status = "a_confirmar"
    else:
        status = "cumple"

    name = (s.get("name") or re.sub(r"\s+", " ", best.title)).strip()
    stores = {o.seller or o.store for o in offers}
    return ModelResult(
        key=key, search=search, name=name, brand=brand_of(best.title), status=status,
        best=asdict(best), offers=[asdict(o) for o in sorted(offers, key=lambda o: o.price)[:12]],
        n_stores=len(stores), facts=asdict(facts), spec=spec, fails=fails, missing=missing,
        warnings=warns, badges=badges, checks=checks,
    )


def analyze(offers: list[Offer], cfg: dict, catalog: SpecCatalog) -> list[ModelResult]:
    exclude = [e.lower() for e in cfg.get("exclude_words", [])]
    max_price = cfg.get("max_price") or float("inf")
    ignore = {norm(k) for k in cfg.get("ignore_models", [])}
    groups: dict[str, list[Offer]] = {}
    searches: dict[str, str] = {}
    specs: dict[str, dict | None] = {}
    for o in offers:
        low = _lower(o.title)
        if any(re.search(rf"\b{re.escape(e)}\b", low) for e in exclude) or o.price > max_price:
            continue
        if "monitor" not in low:
            continue
        facts = title_facts(o.title)
        # Pre-filtro barato: sólo 27" QHD (o sin dato) para no evaluar cientos de monitores
        if facts.size is not None and abs(facts.size - 27) > 0.6:
            continue
        if facts.res not in (None, "qhd"):
            continue
        key, search, spec = model_key(o.title, facts, catalog)
        if key in ignore:
            continue
        groups.setdefault(key, []).append(o)
        searches.setdefault(key, search)
        specs[key] = specs.get(key) or spec
    results = [evaluate(g, k, searches[k], specs[k], cfg) for k, g in groups.items()]
    results.sort(key=lambda r: (STATUS_ORDER[r.status], r.best["price"]))
    return results


# ------------------------------------------------------------------ recolección
async def _collect_compragamer(session: BrowserSession, url: str) -> list[Offer]:
    page = await session.new_page()
    fut: asyncio.Future = asyncio.get_running_loop().create_future()

    async def on_resp(resp):
        if not fut.done() and CATALOG_URL_RE.match(resp.url) and resp.status == 200:
            try:
                fut.set_result(await resp.json())
            except Exception as e:  # noqa: BLE001
                if not fut.done():
                    fut.set_exception(e)

    page.on("response", on_resp)
    try:
        await page.goto(url, wait_until="domcontentloaded")
        catalog = await asyncio.wait_for(fut, 30)
    finally:
        await page.context.close()
    out = []
    for x in catalog:
        price = parse_ars(x.get("precioEspecial"))
        if not is_plausible(price) or not item_in_stock(x):
            continue
        title = x.get("nombre", "")
        if x.get("es_outlet"):
            title += " - OUTLET"
        out.append(Offer("compragamer", title, price, product_url(x), None,
                         parse_ars(x.get("precioLista")), True))
    return out


async def _collect_cards(session: BrowserSession, url: str, store: str) -> list[Offer]:
    page = await session.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        sel = ".Product-List" if store == "hardgamers" else 'article[data-test-id="result-item"]'
        try:
            await page.wait_for_selector(sel, timeout=20000)
        except Exception:  # noqa: BLE001
            return []
        cards = await page.evaluate(HG_CARDS_JS if store == "hardgamers" else FRAVEGA_CARDS_JS)
    finally:
        await page.context.close()
    out = []
    for c in cards:
        if store == "hardgamers":
            price = parse_ars(c.get("price")) or parse_ars(c.get("priceText"))
            stock = availability_to_stock(c.get("availability"))
            if not is_plausible(price) or stock is False:
                continue
            out.append(Offer("hardgamers", re.sub(r"\s+", " ", c["name"]), price,
                             urljoin(url, c["href"]) if c.get("href") else url,
                             c.get("store") or None))
        else:
            cash, lst = card_prices(c.get("text", ""))
            if not is_plausible(cash):
                continue
            m = SELLER_RE.search(c.get("text", ""))
            out.append(Offer("fravega", c["name"].strip(), cash,
                             urljoin(url, c["href"]) if c.get("href") else url,
                             m.group(1).strip() if m else "Frávega", lst))
    return out


async def collect(session: BrowserSession, sources: list[dict],
                  on_progress: Callable[[int, int, str], None] | None = None) -> tuple[list[Offer], list[str]]:
    offers: list[Offer] = []
    errors: list[str] = []
    for i, src in enumerate(sources):
        if on_progress:
            on_progress(i, len(sources), f"Descubriendo · {src['store']}")
        if i:
            await asyncio.sleep(random.uniform(2, 4))
        try:
            if src["store"] == "compragamer":
                got = await _collect_compragamer(session, src["url"])
            else:
                got = await _collect_cards(session, src["url"], src["store"])
            log.info("Descubrimiento %s: %d ofertas (%s)", src["store"], len(got), src["url"])
            offers += got
        except Exception as e:  # noqa: BLE001
            log.warning("Descubrimiento: falló %s: %s", src["url"], e)
            errors.append(f"{src['store']}: {e}"[:200])
    if on_progress:
        on_progress(len(sources), len(sources), "")
    # Deduplicar (la misma oferta aparece en varias búsquedas)
    uniq = {(o.store, o.seller, o.url, o.price): o for o in offers}
    return list(uniq.values()), errors


# ------------------------------------------------------------------ orquestación
def new_model_alert(r: ModelResult) -> str:
    b = r.best
    where = html.escape(b["store"] + (f" ({b['seller']})" if b.get("seller") else ""))
    extra = f"\nFalta confirmar: {html.escape(', '.join(r.missing))}" if r.missing else ""
    from services.tracker import fmt_ars

    return (f"🆕 <b>Nuevo monitor que {'cumple' if r.status == 'cumple' else 'podría cumplir'} "
            f"tus requisitos</b>\n{html.escape(r.name)}\nDesde <b>{fmt_ars(b['price'])}</b> · "
            f"{STATUS_LABELS[r.status]}{extra}\n🏪 {where}\n"
            f'🔗 <a href="{html.escape(b["url"], quote=True)}">Ver producto</a>')


async def run_discovery(trigger: str = "cli", send_alerts: bool = True,
                        on_progress: Callable[[int, int, str], None] | None = None) -> dict:
    from scrapers.base import matches_keywords
    from services.db import Database
    from services.notifier import send_telegram
    from services.targets import load_targets
    from settings import settings

    cfg = load_json(settings.discovery_path, {})
    catalog = SpecCatalog(load_json(settings.specs_path, []))
    db = Database(settings.db_path)
    run_id = db.start_discovery(trigger)
    async with BrowserSession(settings.headless, settings.block_stylesheets,
                              settings.page_timeout_ms) as session:
        offers, errors = await collect(session, cfg.get("sources", []), on_progress)
    results = analyze(offers, cfg, catalog)

    targets = load_targets(settings.targets_path)
    for r in results:
        r.tracked = next((t.id for t in targets if t.keywords and any(
            matches_keywords(o["title"], t.keywords, []) for o in r.offers)), None)

    baseline = not db.has_discovered_models()
    new_keys = db.upsert_discovered(run_id, results)
    alerts = 0
    for r in results:
        r.is_new = r.key in new_keys and not baseline
        if r.is_new and r.status in ("cumple", "a_confirmar", "oled_oferta") and not r.tracked:
            text = new_model_alert(r)
            sent = await send_telegram(text) if send_alerts else False
            db.insert_alert(f"discover:{r.key}", "new_model", text, sent)
            alerts += 1

    payload = [asdict(r) for r in results]
    counts = Counter(r.status for r in results)
    db.finish_discovery(run_id, len(offers), payload, errors)
    summary = {"run_id": run_id, "offers": len(offers), "models": len(results),
               "counts": dict(counts), "alerts": alerts, "errors": errors, "baseline": baseline}
    log.info("Descubrimiento #%d: %d ofertas, %d modelos %s, %d alertas", run_id, len(offers),
             len(results), dict(counts), alerts)
    return {**summary, "results": payload}
