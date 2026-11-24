"""Descubrimiento: busca en todo el catálogo monitores que cumplan los requisitos obligatorios.

Recorre las fuentes de config/discovery.json → sources (~35: Compra Gamer, HardGamers, tiendas VTEX,
Dell/Megatone/Mallweb y lectores por plataforma: WooCommerce, Tiendanube, Qloud, PrestaShop,
TiendaNegocio, Shopify), agrupa las ofertas por modelo (nombre canónico Marca + Modelo, sin
duplicados) y evalúa cada modelo contra los requisitos:

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
import os
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
from scrapers.stores.hardgamers import CARDS_JS as HG_CARDS_JS
from scrapers.stores.vtex import VTEX_STORES
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
          "BGH", "COOLER MASTER", "REDRAGON", "GAMEMAX", "TCL", "HISENSE", "NZXT", "EVNIA", "INNOCN",
          "LEVEL UP", "E-VIEW"]


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

    def by_key(self, key: str) -> dict | None:
        k = norm(key)
        return next((e for kk, e in self._keys if kk == k), None)

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

    def match_variant(self, code: str, hz: int | None) -> dict | None:
        """Título con el código base pero sin el sufijo de la variante ("274QPF ... 320HZ" en vez
        de "274QPF X32"): si hay UNA sola variante catalogada con ese código y esos Hz, es esa."""
        c = norm(code)
        if not hz or len(c) < 4:
            return None
        same = [e for e in self.entries if norm(e.get("model_key", "")).startswith(c)
                and 0 < len(norm(e["model_key"])) - len(c) <= SUFFIX_MAX and e.get("hz_dp") == hz]
        return same[0] if len(same) == 1 else None


# Largo máximo del sufijo de variante (X24, X32, E2, M...) para unificar títulos que lo omiten
SUFFIX_MAX = 3   # X24, X32, E2...
MERGE_SUFFIX_MAX = 4   # dentro de un mismo descubrimiento, si además coincide el panel (ARK27340 / ARK27340QI8P)


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
    r"G-?SYNC\w*|QHD\w*|WQHD|1MS\w*|ELIMINAR|\d{3,4}X\d{3,4}\w*)$")


def brand_of(title: str) -> str | None:
    t = f" {title.upper()} "
    return next((b for b in BRANDS if f" {b} " in t or f" {b}-" in t), None)


# Cómo se escribe cada marca en los nombres (lo que no está acá va en Title Case)
BRAND_CASE = {"ASROCK": "ASRock", "MSI": "MSI", "LG": "LG", "BENQ": "BenQ", "AOC": "AOC", "HP": "HP",
              "KTC": "KTC", "TCL": "TCL", "BGH": "BGH", "NZXT": "NZXT", "ASUS": "ASUS",
              "X-MICRO": "X-Micro", "XMICRO": "X-Micro", "E-VIEW": "E-View", "VIEWSONIC": "ViewSonic",
              "AORUS": "Aorus", "LEVEL UP": "Level Up", "COOLER MASTER": "Cooler Master"}


def brand_label(brand: str | None) -> str:
    return BRAND_CASE.get((brand or "").upper(), (brand or "").title())


def canonical_name(spec: dict | None, brand: str | None, key: str, search: str, hz: int | None,
                   title: str = "") -> str:
    """Nombre único de cada monitor: "Marca Modelo" (MSI MAG 274QPF X32, ViewSonic VX2718), sin
    Hz, pulgadas ni frases de marketing. El catálogo curado manda; si no, marca + código del título.
    Si el título no trae código, marca + Hz (es lo único que lo distingue)."""
    if spec and spec.get("name"):
        return spec["name"]
    b = brand_label(brand)
    if "~" in key:
        if not b:   # ni marca ni código: el título limpio es lo único que lo identifica
            t = re.sub(r"\[.*?\]|\(.*?\)", " ", title)
            t = re.sub(r"(?i)^\s*(monitor\s+)?(gamer\s+|gaming\s+)?", "", t)
            return re.sub(r"\s+", " ", t).strip()[:60] or "Sin marca"
        return f"{b} {hz} Hz (sin código de modelo)" if hz else f"{b} (sin código de modelo)"
    return f"{b} {search}".strip()


def unique_names(results: list) -> None:
    """Si dos modelos distintos quedan con el mismo nombre, se agregan los Hz para distinguirlos."""
    by: dict[str, list] = {}
    for r in results:
        by.setdefault(r.name, []).append(r)
    for same in by.values():
        if len(same) > 1:
            for r in same:
                if r.facts.get("hz"):
                    r.name = f"{r.name} · {r.facts['hz']} Hz"


def _is_code(core: str) -> bool:
    return (sum(c.isdigit() for c in core) >= 2 and any(c.isalpha() for c in core)
            and not NOT_MODEL_RE.match(core) and not re.fullmatch(r"\d+X\d+", core)
            and len(norm(core)) >= 4)


def model_key(title: str, facts: TitleFacts,
              catalog: SpecCatalog) -> tuple[str, str, dict | None]:
    """(clave normalizada, código legible para buscar, specs). Prioriza el catálogo de specs."""
    spec = catalog.match(title)
    if spec:
        return norm(spec["model_key"]), spec.get("search") or spec["model_key"], spec
    for tok in TOKEN_RE.findall(title.upper()):
        core = tok.strip("-")
        # "VX2718-2KPC-MHD" / "XG27AQ-W": el sufijo después del guion es variante/color, no otro modelo
        head = core.split("-")[0]
        if "-" in core and _is_code(head):
            core = head
        if _is_code(core):
            spec = catalog.match_variant(core, facts.hz)
            if spec:
                return norm(spec["model_key"]), spec.get("search") or spec["model_key"], spec
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
    used: bool = False                 # outlet / usado / reacondicionado: se muestra, no cuenta como precio


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
    ref: float | None = None           # precio de mercado (mediana)
    real: float | None = None          # descuento real vs mercado (0.2 = 20 % abajo)
    level: str | None = None           # buena / excepcional
    generic: bool = False              # marca sin reseñas


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
    from scrapers.base import is_used

    for o in offers:
        o.used = is_used(o.title)
    new = [o for o in offers if not o.used]
    accept_used = req.get("accept_used", False)
    pool = offers if accept_used or not new else new      # el precio sale de las ofertas nuevas
    sellable = [o for o in pool if o.in_stock is not False] or pool
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
        fails.append("tamaño no informado")
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
    elif panel and re.search(r"\bVA\b", panel):
        fails.append("panel VA")
    elif not panel:
        missing.append("panel")
    elif "IPS" not in panel:
        fails.append(f"panel {panel}")

    check("IPS", None if not panel and not is_oled else ("IPS" in (panel or "") and not is_oled))
    # Datos que vienen del catálogo de ML (a veces cargados mal por los vendedores): si
    # descalifican, no descartan: quedan "a verificar".
    ml = set(s.get("_ml_fields") or [])
    if s.get("discard"):
        fails.append(f"descartado a mano: {s['discard']}")
    weight_required = req.get("weight_required", True)

    def fail_or_verify(field: str, reason: str) -> bool:
        if field == "weight_no_stand_kg" and field in ml and not weight_required:
            warns.append(f"{reason} según ML (dato dudoso)")
            return False
        if field in ml:
            warns.append(f"{reason} según ML (dato dudoso, verificar)")
            missing.append(reason)
            return False
        fails.append(reason)
        return True

    flat_bad = facts.curved or s.get("flat") is False
    if facts.curved:
        fails.append("curvo")
    elif s.get("flat") is False:
        flat_bad = fail_or_verify("flat", "curvo")
    check("plano", False if flat_bad else (True if s.get("flat") else None))

    if s.get("anti_glare") is False:
        fail_or_verify("anti_glare", "pantalla brillante (no mate)")
    elif s.get("anti_glare") is None and req.get("anti_glare", True) and not is_oled:
        missing.append("acabado mate")

    check("mate", None if (s.get("anti_glare") is False and "anti_glare" in ml) else s.get("anti_glare"))
    vesa = (s.get("vesa") or "").replace(" ", "").lower()
    if vesa in ("none", "no"):
        fail_or_verify("vesa", "sin VESA")
    elif vesa.startswith("sí") or vesa.startswith("si"):
        warns.append("VESA sin medida informada (casi siempre 75 o 100)")
    elif vesa:
        if vesa not in [v.lower() for v in req.get("vesa", ["75x75", "100x100"])]:
            fails.append(f"VESA {s['vesa']}")
    else:
        missing.append("VESA")

    check("VESA", None if not vesa else (vesa.startswith(("sí", "si"))
                                         or vesa in [v.lower() for v in req.get("vesa", [])]))
    w = s.get("weight_no_stand_kg")
    if w is None:
        if weight_required:
            missing.append("peso")
    elif w >= req.get("max_weight_kg", 8):
        if not fail_or_verify("weight_no_stand_kg", f"pesa {w:g} kg"):
            w = None   # peso dudoso de ML: queda como "?"

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
    if not new and not accept_used:
        fails.append("sólo outlet/usado")
    elif len(new) < len(offers):
        u = min((o for o in offers if o.used), key=lambda o: o.price)
        warns.append(f"también hay outlet/usado desde ${u.price:,.0f} (no cuenta)".replace(",", "."))
    importers = [i.lower() for i in cfg.get("import_sellers", [])]
    if best.seller and any(i in best.seller.lower() for i in importers):
        warns.append("vendedor de importados: verificar garantía local y 220 V")

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

    name = canonical_name(s, brand_of(best.title), key, search, facts.hz, best.title)
    stores = {o.seller or o.store for o in offers}
    return ModelResult(
        key=key, search=search, name=name, brand=brand_of(best.title), status=status,
        best=asdict(best), offers=[asdict(o) for o in sorted(offers, key=lambda o: o.price)[:12]],
        n_stores=len(stores), facts=asdict(facts), spec=spec, fails=fails, missing=missing,
        warnings=warns, badges=badges, checks=checks,
    )


def _load_overrides() -> dict[str, dict]:
    try:
        from services.overrides import load
        from settings import settings

        return load(settings.overrides_path)
    except Exception:  # noqa: BLE001
        return {}


def usb_c_label(spec: dict | None, badges: list[str]) -> str | None:
    pd = (spec or {}).get("usb_c_pd_w") or 0
    if pd >= 65:
        return f"USB-C {pd} W"
    return next((b for b in badges if b.startswith("USB-C")), None)


def evaluate_target(target, snaps: list[dict], cfg: dict, catalog: SpecCatalog,
                    ml_specs: dict[str, dict] | None = None) -> dict | None:
    """Evalúa un monitor seguido contra los requisitos (mismas reglas que el descubrimiento),
    usando los títulos que devolvieron sus tiendas."""
    from services.spec_enrich import merge

    offers = [Offer(s["store"], s["title"], s["price_cash"], s.get("product_url") or s["url"], s.get("seller"))
              for s in snaps if s and s.get("price_cash") and s.get("title") and not s["title"].startswith("(")]
    if not offers:
        offers = [Offer("config", target.name + " 27\" QHD IPS", 1, "")]
    key, search, spec = model_key(offers[0].title, title_facts(offers[0].title), catalog)
    spec = spec or catalog.match(target.name)
    if spec:
        key = norm(spec["model_key"])
    from services.overrides import apply as apply_override

    spec = apply_override(merge(spec, (ml_specs or {}).get(key)), _load_overrides().get(key))
    r = evaluate(offers, key, search, spec, cfg)
    return {"status": r.status, "missing": r.missing, "fails": r.fails, "warnings": r.warnings,
            "badges": r.badges, "checks": r.checks, "usb_c": usb_c_label(spec, r.badges),
            "spec_notes": (spec or {}).get("notes"), "key": key,
            "manual": (spec or {}).get("_manual") or []}


def reevaluate(m: dict, cfg: dict, catalog: SpecCatalog, ml_spec: dict | None,
               override: dict | None) -> dict:
    """Vuelve a evaluar un modelo guardado del último descubrimiento con las specs y confirmaciones
    actuales (así una confirmación manual se ve al instante, sin esperar al próximo descubrimiento)."""
    from services.overrides import apply as apply_override
    from services.spec_enrich import merge

    offers = [Offer(**{k: o.get(k) for k in ("store", "title", "price", "url", "seller", "price_list", "in_stock")})
              for o in m.get("offers") or []]
    if not offers:
        return m
    spec = catalog.match(offers[0].title) or catalog.by_key(m["key"])         or (m.get("spec") if (m.get("spec") or {}).get("model_key") else None)
    if not spec:
        _, _, spec = model_key(offers[0].title, title_facts(offers[0].title), catalog)
    spec = apply_override(merge(spec, ml_spec), override)
    r = evaluate(offers, m["key"], m["search"], spec, cfg)
    for k in ("status", "fails", "missing", "warnings", "badges", "checks", "spec", "name"):
        m[k] = getattr(r, k)
    m["manual"] = (spec or {}).get("_manual") or []
    return m


def _merge_variants(groups: dict[str, list], searches: dict[str, str], specs: dict) -> None:
    """Une el grupo "274QPF" (título sin sufijo) con "274QPFX32" si es la única variante con esos
    Hz. Así el mismo monitor no aparece dos veces ni dispara un aviso de "modelo nuevo"."""
    def hz(k: str) -> int | None:
        return _majority([title_facts(o.title).hz for o in groups[k]])

    def panel(k: str) -> str | None:
        return _majority([title_facts(o.title).panel for o in groups[k]])

    for k in sorted(groups, key=len):
        if k not in groups or "~" in k or len(k) < 4:
            continue
        h = hz(k)
        if not h:
            continue
        cands = [c for c in groups if c != k and "~" not in c and c.startswith(k) and hz(c) == h
                 and (0 < len(c) - len(k) <= SUFFIX_MAX
                      or (len(c) - len(k) <= MERGE_SUFFIX_MAX and panel(c) == panel(k)))]
        if len(cands) == 1:
            c = cands[0]
            groups[c].extend(groups.pop(k))
            specs[c] = specs.get(c) or specs.pop(k, None)
            specs.pop(k, None)
            searches.pop(k, None)

    # "SAMSUNG ODYSSEY G5 27 165HZ" (sin código) -> el único Samsung con código y 165 Hz del listado
    def brand(k: str) -> str | None:
        return _majority([brand_of(o.title) for o in groups[k]])

    def curved(k: str) -> bool:
        return any(title_facts(o.title).curved for o in groups[k])

    for k in [k for k in groups if "~" in k]:
        b, h = brand(k), hz(k)
        if not b or not h:
            continue
        cands = [c for c in groups if "~" not in c and brand(c) == b and hz(c) == h
                 and curved(c) == curved(k)]
        if len(cands) == 1:
            c = cands[0]
            groups[c].extend(groups.pop(k))
            specs.pop(k, None)
            searches.pop(k, None)


def tracked_by(key: str, offers: list[dict], targets: list, catalog: SpecCatalog | None = None) -> str | None:
    """id del seguido que ya cubre este modelo: por keywords en los títulos o por la misma clave de
    catálogo (así un seguido nunca aparece además como "nuevo" en el descubrimiento)."""
    from scrapers.base import matches_keywords

    for t in targets:
        if getattr(t, "kind", "monitor") != "monitor":
            continue
        if t.keywords and any(matches_keywords(o["title"], t.keywords, []) for o in offers):
            return t.id
        spec = catalog.match(t.name) if catalog else None
        if spec and norm(spec["model_key"]) == key:
            return t.id
    return None


def suspicious_pairs(results: list) -> list[tuple[str, str]]:
    """Control: pares de modelos que podrían ser el mismo (una clave contiene a la otra y tienen
    los mismos Hz). Se loguea en cada descubrimiento para revisarlos."""
    out = []
    for a in results:
        for b in results:
            if a.key < b.key and min(len(a.key), len(b.key)) >= 4 and "~" not in a.key + b.key                     and (a.key in b.key or b.key in a.key) and a.facts.get("hz") == b.facts.get("hz")                     and a.facts.get("curved") == b.facts.get("curved"):
                out.append((a.key, b.key))
    return out


def analyze(offers: list[Offer], cfg: dict, catalog: SpecCatalog,
            extra_specs: dict[str, dict] | None = None,
            overrides: dict[str, dict] | None = None) -> list[ModelResult]:
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
    _merge_variants(groups, searches, specs)
    from services.overrides import apply as apply_override
    from services.spec_enrich import merge

    extra_specs = extra_specs or {}
    overrides = overrides if overrides is not None else _load_overrides()
    results = [evaluate(g, k, searches[k],
                        apply_override(merge(specs[k], extra_specs.get(k)), overrides.get(k)), cfg)
               for k, g in groups.items()]
    results.sort(key=lambda r: (STATUS_ORDER[r.status], r.best["price"]))
    unique_names(results)
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


async def _collect_hardgamers(session: BrowserSession, url: str) -> list[Offer]:
    """HardGamers: tarjetas del listado de búsqueda (con navegador)."""
    page = await session.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(".Product-List", timeout=20000)
        except Exception:  # noqa: BLE001
            return []
        cards = await page.evaluate(HG_CARDS_JS)
    finally:
        await page.context.close()
    out = []
    for c in cards:
        price = parse_ars(c.get("price")) or parse_ars(c.get("priceText"))
        stock = availability_to_stock(c.get("availability"))
        if not is_plausible(price) or stock is False:
            continue
        out.append(Offer("hardgamers", re.sub(r"\s+", " ", c["name"]), price,
                         urljoin(url, c["href"]) if c.get("href") else url, c.get("store") or None))
    return out


def _collect_catalog(store: str, url: str | None = None, platform: str | None = None) -> list[Offer]:
    """Dell, Megatone, Mallweb y tiendas Tiendanube: listado de monitores leído del HTML."""
    from scrapers.stores.catalogs import fetch

    return [Offer(store, i["title"], i["price"], i["url"], i["seller"], i["list"], True)
            for i in fetch(store, url, platform)]


def _collect_vtex(store: str, url: str) -> list[Offer]:
    """Tiendas VTEX (Frávega, On City, Pardo, Carrefour...): API JSON del buscador."""
    import httpx

    from scrapers.stores.vtex import UA, VtexScraper, api_search, offers_from, promo_text

    query = VtexScraper._query_from_url(url)
    with httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as c:
        offers = offers_from(api_search(c, VTEX_STORES[store][1], query), store)
    out = []
    for o in offers:
        title = o["title"] + (f" [{promo_text(o)}]" if promo_text(o) else "")
        out.append(Offer(store, title, o["price"], o["url"], o["seller"], o["list"], True))
    return out


from scrapers.stores.catalogs import PLATFORMS  # noqa: E402


async def collect(session: BrowserSession, sources: list[dict],
                  on_progress: Callable[[int, int, str], None] | None = None,
                  stats: list[dict] | None = None) -> tuple[list[Offer], list[str]]:
    """stats (opcional): se le agrega {store, n, error} por fuente (estado de las tiendas)."""
    offers: list[Offer] = []
    errors: list[str] = []
    stats = stats if stats is not None else []
    if os.environ.get("GITHUB_ACTIONS") == "true":
        sources = [s for s in sources if s.get("ci", True)]
    for i, src in enumerate(sources):
        if on_progress:
            on_progress(i, len(sources), f"Descubriendo · {src['store']}")
        if i:
            await asyncio.sleep(random.uniform(2, 4))
        try:
            if src["store"] == "compragamer":
                got = await _collect_compragamer(session, src["url"])
            elif src["store"] in ("dell", "megatone", "mallweb") or src.get("platform") in PLATFORMS:
                got = await asyncio.to_thread(_collect_catalog, src["store"], src["url"], src.get("platform"))
            elif src["store"] in VTEX_STORES:
                got = await asyncio.to_thread(_collect_vtex, src["store"], src["url"])
            else:
                got = await _collect_hardgamers(session, src["url"])
            log.info("Descubrimiento %s: %d ofertas (%s)", src["store"], len(got), src["url"])
            if not got:   # la tienda cambió su página o el lector dejó de andar: que se note
                errors.append(f"{src['store']}: 0 resultados")
            stats.append({"store": src["store"], "n": len(got), "error": None if got else "0 resultados"})
            offers += got
        except Exception as e:  # noqa: BLE001
            log.warning("Descubrimiento: falló %s: %s", src["url"], e)
            errors.append(f"{src['store']}: {e}"[:200])
            stats.append({"store": src["store"], "n": 0, "error": str(e)[:160]})
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


def _apply_market(db, results: list[ModelResult], targets, cfg: dict) -> None:
    """Calcula referencia de mercado y descuento real de cada modelo descubierto."""
    from services.market import level, real_discount, reference
    from services.tracker import market_ref

    generic = [g.lower() for g in cfg.get("generic_brands", [])]
    by_id = {t.id: t for t in targets}
    for r in results:
        if r.tracked and r.tracked in by_id:          # el seguimiento tiene más historia: manda
            ref, _ = market_ref(db, by_id[r.tracked])
        else:                                           # descubrimiento: 1 punto por día (el mínimo)
            ref, _ = reference(db.discovery_series(r.key), min_points=4, min_span_days=3)
        r.ref = ref
        r.real = real_discount(r.best["price"], ref)
        r.generic = not r.brand or any(g in (r.name + " " + (r.brand or "")).lower() for g in generic)
        lvl = level(r.real)
        if lvl == "buena" and r.generic:                # sin reseñas: sólo ofertas excepcionales
            lvl = None
        r.level = lvl


async def _real_offers(db, results: list[ModelResult], targets, cfg: dict, send_alerts: bool) -> int:
    """Un solo mensaje con las ofertas reales (>= 15 % / >= 30 %) en modelos que cumplen."""
    from services.notifier import send_telegram
    from services.tracker import fmt_ars

    _apply_market(db, results, targets, cfg)
    by_id = {t.id: t for t in targets}

    def covered_by_tracker(r: ModelResult) -> bool:
        """El escaneo de seguidos ya avisa esta oferta (misma tienda): no repetirla acá."""
        t = by_id.get(r.tracked or "")
        if not t:
            return False
        from scrapers.stores.vtex import ELECTRO_STORES

        stores = {u.store for u in t.urls if u.active}
        if "electro" in stores:
            stores |= set(ELECTRO_STORES)
        return r.best["store"] in stores

    hits = [r for r in results if r.level and r.status in ("cumple", "oled_oferta", "a_confirmar")
            and not covered_by_tracker(r)
            and not db.offer_already_alerted(r.key, r.level, r.best["price"])]
    if not hits:
        return 0
    hits.sort(key=lambda r: (-(r.real or 0)))
    lines = [f"💰 <b>{len(hits)} oferta{'s' if len(hits) > 1 else ''} real{'es' if len(hits) > 1 else ''} "
             f"en monitores que cumplen tus requisitos</b>"]
    for r in hits[:10]:
        b = r.best
        tag = "🔥" if r.level == "excepcional" else "💰"
        extra = " · confirmar " + ", ".join(r.missing) if r.status == "a_confirmar" else ""
        lines.append(f'{tag} <a href="{html.escape(b["url"], quote=True)}">{html.escape(r.name[:70])}</a>: '
                     f"<b>{fmt_ars(b['price'])}</b> ({r.real * 100:.0f}% debajo de {fmt_ars(r.ref)})"
                     f" — {html.escape(b.get('seller') or b['store'])}{html.escape(extra)}")
    text = "\n".join(lines)
    sent = await send_telegram(text) if send_alerts else False
    db.insert_alert("discover", "real_offer", text, sent)
    for r in hits:
        db.record_offer_alert(r.key, r.level, r.best["price"])
    return len(hits)


def new_models_alert(models: list[ModelResult], limit: int = 8) -> str:
    if len(models) == 1:
        return new_model_alert(models[0])
    from services.tracker import fmt_ars

    models = sorted(models, key=lambda r: (STATUS_ORDER[r.status], r.best["price"]))
    lines = [f"🆕 <b>{len(models)} monitores nuevos que cumplen o podrían cumplir tus requisitos</b>"]
    for r in models[:limit]:
        b = r.best
        mark = {"cumple": "✅", "oled_oferta": "🟣", "a_confirmar": "❔"}[r.status]
        where = html.escape(b.get("seller") or b["store"])
        lines.append(f'{mark} <a href="{html.escape(b["url"], quote=True)}">{html.escape(r.name[:70])}</a>'
                     f" — <b>{fmt_ars(b['price'])}</b> ({where})")
    if len(models) > limit:
        lines.append(f"…y {len(models) - limit} más en el dashboard (sección Descubrir).")
    lines.append("✅ cumple todo · ❔ falta confirmar algo (mate, VESA, peso…)")
    return "\n".join(lines)


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
        stats: list[dict] = []
        offers, errors = await collect(session, cfg.get("sources", []), on_progress, stats)
    results = analyze(offers, cfg, catalog)
    # Lo que el título no dice (mate, VESA, peso...) se completa con el catálogo de ML
    pending = [(r.key, r.search, r.brand) for r in results if r.status == "a_confirmar"]
    if pending:
        from services.spec_enrich import enrich

        extra = enrich(db, pending)
        if extra:
            results = analyze(offers, cfg, catalog, extra)
        still = [r for r in results if r.status == "a_confirmar"]
        if still:
            from services import page_specs
            from services.spec_enrich import combine

            pages = page_specs.enrich(db, still)
            if pages:
                extra = {k: combine(extra.get(k), pages.get(k)) for k in set(extra) | set(pages)}
                results = analyze(offers, cfg, catalog, extra)


    targets = load_targets(settings.targets_path)
    for r in results:
        r.tracked = tracked_by(r.key, r.offers, targets, catalog)
    for a, b in suspicious_pairs(results):
        log.warning("Posible duplicado en el descubrimiento: %s / %s", a, b)

    baseline = not db.has_discovered_models()
    prev = db.last_discovery() or {}
    seen_urls = {o["url"] for m in prev.get("results", []) for o in m.get("offers", [])}
    new_keys = db.upsert_discovered(run_id, results)
    offers_alert = await _real_offers(db, results, targets, cfg, send_alerts)
    alerts = 0
    for r in results:
        # Nuevo de verdad: clave nunca vista Y ninguna de sus publicaciones estaba en la corrida
        # anterior (si sólo cambió cómo se agrupa un título, no es un monitor nuevo)
        r.is_new = (r.key in new_keys and not baseline
                    and not any(o["url"] in seen_urls for o in r.offers))
    new_ok = [r for r in results if r.is_new and not r.tracked
              and r.status in ("cumple", "a_confirmar", "oled_oferta")]
    if new_ok:
        # Un solo mensaje (si se suman tiendas nuevas pueden aparecer decenas de golpe)
        text = new_models_alert(new_ok)
        sent = await send_telegram(text) if send_alerts else False
        db.insert_alert("discover", "new_model", text, sent)
        alerts = len(new_ok)

    payload = [asdict(r) for r in results]
    counts = Counter(r.status for r in results)
    # varias búsquedas de la misma tienda (HardGamers x5, Frávega x2) se suman en una fila
    merged: dict[str, dict] = {}
    for s in stats:
        m = merged.setdefault(s["store"], {"store": s["store"], "n": 0, "error": None})
        m["n"] += s["n"]
        m["error"] = m["error"] or s["error"]
    for m in merged.values():
        if m["n"]:
            m["error"] = None if m["error"] == "0 resultados" else m["error"]
    db.finish_discovery(run_id, len(offers), payload, errors, list(merged.values()))
    summary = {"run_id": run_id, "offers": len(offers), "models": len(results),
               "counts": dict(counts), "alerts": alerts + offers_alert, "errors": errors,
               "baseline": baseline, "real_offers": offers_alert}
    log.info("Descubrimiento #%d: %d ofertas, %d modelos %s, %d alertas", run_id, len(offers),
             len(results), dict(counts), alerts)
    return {**summary, "results": payload}
