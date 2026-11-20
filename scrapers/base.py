"""Infraestructura común de scraping con Playwright.

- BrowserSession: un Chromium headless compartido por todo el escaneo; cada scrape usa un
  contexto nuevo (cookies aisladas + User-Agent rotado) y bloquea image/media/font
  (y opcionalmente stylesheets + dominios de tracking) para ahorrar RAM y ancho de banda.
- BaseScraper: reintentos con backoff exponencial + jitter.
- Helpers: extracción JSON-LD / OpenGraph, detección de stock y matching de títulos.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Iterable
from urllib.parse import urlparse

from playwright.async_api import Browser, Page, Route, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from services.db import utcnow
from services.price_parser import is_plausible, parse_ars

if TYPE_CHECKING:
    from services.targets import Target

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

BLOCKED_TYPES = {"image", "media", "font"}
# Analytics / ads: no aportan nada al precio y suman muchos requests.
BLOCKED_HOST_PARTS = (
    "google-analytics.com", "googletagmanager.com", "doubleclick.net", "googleadservices.com",
    "facebook.net", "facebook.com/tr", "hotjar.com", "hotjar.io", "clarity.ms", "tiktok.com",
    "criteo", "taboola", "outbrain", "newrelic", "nr-data.net", "sentry.io",
)

OUT_OF_STOCK_RE = re.compile(
    r"sin\s+stock(?!\s+en\s+(?:el\s+)?(?:local|sucursal|tienda\s+f[ií]sica|showroom))|agotad[oa]s?|pausad[oa]|sin\s+disponibilidad|no\s+disponible|"
    r"fuera\s+de\s+stock|publicaci[oó]n\s+finalizada|out\s+of\s+stock|sold\s+out|"
    r"avisame\s+cuando\s+(?:haya|llegue)|notificarme\s+cuando",
    re.IGNORECASE,
)
BUY_RE = re.compile(
    r"agregar\s+al\s+carrito|añadir\s+al\s+carrito|sumar\s+al\s+carrito|comprar\s+ahora|"
    r"\bcomprar\b|add\s+to\s+cart",
    re.IGNORECASE,
)
CASH_LABEL_RE = re.compile(
    r"transferencia|efectivo|contado|dep[oó]sito|especial|un\s+pago|1\s+pago", re.IGNORECASE
)
LIST_LABEL_RE = re.compile(
    r"precio\s+de\s+lista|lista|cuotas|tarjeta|precio\s+regular|financiado", re.IGNORECASE
)

DEFAULT_EXCLUDE = ["usado", "reacondicionado", "refurbished", "open box", "openbox"]


# ------------------------------------------------------------------ modelos
@dataclass
class ScrapeResult:
    store: str
    url: str
    title: str | None = None
    price_cash: float | None = None
    price_list: float | None = None
    in_stock: bool | None = None
    seller: str | None = None
    product_url: str | None = None
    error: str | None = None
    scanned_at: str = field(default_factory=utcnow)

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def short(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        stock = {True: "con stock", False: "SIN STOCK", None: "stock ?"}[self.in_stock]
        cash = f"${self.price_cash:,.0f}".replace(",", ".") if self.price_cash else "-"
        lst = f" / lista ${self.price_list:,.0f}".replace(",", ".") if self.price_list else ""
        who = f" @ {self.seller}" if self.seller else ""
        return f"{cash}{lst} ({stock}){who}"


class ScrapeError(Exception):
    """Error recuperable: se reintenta."""


class BlockedError(ScrapeError):
    """La tienda bloqueó el acceso (captcha / verificación). No se reintenta."""


# ------------------------------------------------------------------ browser
class BrowserSession:
    """Chromium compartido; abrir con `async with BrowserSession() as s:`."""

    def __init__(self, headless: bool = True, block_stylesheets: bool = True,
                 timeout_ms: int = 45_000):
        self.headless = headless
        self.block_stylesheets = block_stylesheets
        self.timeout_ms = timeout_ms
        self.blocked_requests = 0
        self._pw = None
        self.browser: Browser | None = None

    async def __aenter__(self) -> "BrowserSession":
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
                  "--disable-extensions", "--mute-audio"],
        )
        log.info("Chromium iniciado (headless=%s, bloqueo CSS=%s)", self.headless,
                 self.block_stylesheets)
        return self

    async def __aexit__(self, *exc) -> None:
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()
        log.info("Chromium cerrado. Requests bloqueados en la sesión: %d", self.blocked_requests)

    async def _route(self, route: Route) -> None:
        req = route.request
        rtype = req.resource_type
        if (
            rtype in BLOCKED_TYPES
            or (self.block_stylesheets and rtype == "stylesheet")
            or any(h in req.url for h in BLOCKED_HOST_PARTS)
        ):
            self.blocked_requests += 1
            await route.abort()
        else:
            await route.continue_()

    async def new_page(self) -> Page:
        assert self.browser, "BrowserSession no iniciada"
        ua = random.choice(USER_AGENTS)
        ctx = await self.browser.new_context(
            user_agent=ua,
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            viewport={"width": random.choice([1280, 1366, 1440, 1536]), "height": 800},
            extra_http_headers={"Accept-Language": "es-AR,es;q=0.9,en;q=0.7"},
        )
        ctx.set_default_timeout(self.timeout_ms)
        await ctx.route("**/*", self._route)
        return await ctx.new_page()


# ------------------------------------------------------------------ scraper base
class BaseScraper:
    store: str = "generic"
    domains: tuple[str, ...] = ()

    def __init__(self, session: BrowserSession, retries: int = 3):
        self.session = session
        self.retries = max(1, retries)
        self.log = logging.getLogger(f"scraper.{self.store}")

    async def scrape(self, url: str, target: "Target") -> ScrapeResult:
        last_err = "desconocido"
        for attempt in range(1, self.retries + 1):
            page = await self.session.new_page()
            try:
                res = await self.extract(page, url, target)
                res.store = res.store or self.store
                return res
            except BlockedError as e:
                self.log.warning("%s bloqueado: %s", url, e)
                return ScrapeResult(store=self.store, url=url, error=f"bloqueado: {e}")
            except (ScrapeError, PlaywrightTimeout, PlaywrightError) as e:
                last_err = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                self.log.warning("Intento %d/%d falló para %s -> %s", attempt, self.retries,
                                 url, last_err)
            finally:
                await page.context.close()
            if attempt < self.retries:
                await asyncio.sleep(min(30, 2 ** attempt) + random.uniform(0, 1.5))
        return ScrapeResult(store=self.store, url=url, error=last_err)

    async def extract(self, page: Page, url: str, target: "Target") -> ScrapeResult:
        raise NotImplementedError

    # -------------------------------------------------------------- utilidades
    @staticmethod
    async def goto(page: Page, url: str, *, idle_ms: int = 6000) -> None:
        resp = await page.goto(url, wait_until="domcontentloaded")
        if resp is not None and resp.status >= 500:
            raise ScrapeError(f"HTTP {resp.status}")
        if resp is not None and resp.status in (403, 429):
            raise BlockedError(f"HTTP {resp.status}")
        if resp is not None and resp.status == 404:
            raise BlockedError("HTTP 404 (la URL ya no existe)")
        try:
            await page.wait_for_load_state("networkidle", timeout=idle_ms)
        except PlaywrightTimeout:
            pass  # SPAs con long-polling nunca llegan a networkidle: seguimos igual


# ------------------------------------------------------------------ JSON-LD / meta
async def read_json_ld(page: Page) -> list[dict]:
    raw: list[str] = await page.eval_on_selector_all(
        'script[type="application/ld+json"]', "els => els.map(e => e.textContent || '')"
    )
    nodes: list[dict] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            for o in obj:
                walk(o)
        elif isinstance(obj, dict):
            nodes.append(obj)
            if "@graph" in obj:
                walk(obj["@graph"])

    for txt in raw:
        try:
            walk(json.loads(txt.strip(), strict=False))
        except (json.JSONDecodeError, ValueError):
            continue
    return nodes


def _has_type(node: dict, name: str) -> bool:
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.lower().endswith(name.lower()) for x in types)


def availability_to_stock(value: Any) -> bool | None:
    if not value:
        return None
    v = str(value).lower()
    if any(k in v for k in ("outofstock", "soldout", "discontinued", "out of stock")):
        return False
    if any(k in v for k in ("instock", "limitedavailability", "onlineonly", "in stock",
                            "preorder", "presale", "backorder")):
        return True
    return None


def _offer_summary(node: dict) -> dict | None:
    offers = node.get("offers") or []
    offers = offers if isinstance(offers, list) else [offers]
    flat: list[dict] = []
    for o in offers:
        if isinstance(o, dict) and _has_type(o, "AggregateOffer") and o.get("offers"):
            inner = o["offers"]
            flat.extend(inner if isinstance(inner, list) else [inner])
        if isinstance(o, dict):
            flat.append(o)
    best_price, stock = None, None
    for o in flat:
        if not isinstance(o, dict):
            continue
        cur = str(o.get("priceCurrency") or "ARS").upper()
        if cur not in ("ARS", "$"):
            continue
        spec = o.get("priceSpecification")
        spec_price = spec.get("price") if isinstance(spec, dict) else None
        price = parse_ars(o.get("price") or o.get("lowPrice") or spec_price)
        if is_plausible(price) and (best_price is None or price < best_price):
            best_price = price
        s = availability_to_stock(o.get("availability"))
        stock = s if stock is None else (stock or bool(s))
    if best_price is None and stock is None:
        return None
    return {"title": node.get("name"), "price": best_price, "in_stock": stock}


def _node_urls(node: dict) -> list[str]:
    out = [node.get("url"), node.get("@id")]
    meop = node.get("mainEntityOfPage")
    out.append(meop.get("@id") if isinstance(meop, dict) else meop)
    return [u for u in out if isinstance(u, str)]


def _same_page(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return pa.path.rstrip("/").lower() == pb.path.rstrip("/").lower() and pa.path not in ("", "/")


def product_from_json_ld(nodes: Iterable[dict], page_url: str | None = None,
                         title_hint: str | None = None) -> dict | None:
    """Devuelve {'title', 'price', 'in_stock'} del nodo Product que corresponde a la página.

    Muchas tiendas (p.ej. Tiendanube) incluyen además JSON-LD de productos relacionados:
    se prioriza el Product cuya URL coincide con la página o cuyo nombre coincide con el H1.
    Si hay varios Product y ninguno coincide, se descarta el JSON-LD por ambiguo.
    """
    products = [n for n in nodes if _has_type(n, "Product")]
    if not products:
        return None
    chosen: dict | None = None
    if page_url:
        chosen = next((n for n in products
                       if any(_same_page(u, page_url) for u in _node_urls(n))), None)
    if chosen is None and title_hint:
        th = _norm(title_hint)
        chosen = next((n for n in products if th and _norm(str(n.get("name", ""))) == th), None)
    if chosen is None:
        if len({_norm(str(n.get("name", ""))) for n in products}) > 1:
            return None
        chosen = products[0]
    return _offer_summary(chosen)


async def meta_content(page: Page, selector: str) -> str | None:
    el = await page.query_selector(selector)
    return (await el.get_attribute("content")) if el else None


# ------------------------------------------------------------------ texto / matching
def detect_stock(text: str) -> bool | None:
    if not text:
        return None
    if OUT_OF_STOCK_RE.search(text):
        return False
    if BUY_RE.search(text):
        return True
    return None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def matches_keywords(title: str, keywords: Iterable[str],
                     exclude: Iterable[str] = DEFAULT_EXCLUDE) -> bool:
    """True si el título contiene TODOS los keywords y ninguno de los excluidos.

    Se comparan versiones sin espacios ni símbolos: "27GS75Q-B" matchea "27gs75q b".
    Un keyword con "|" acepta alternativas: "274QF|275QF" matchea cualquiera de los dos.
    """
    t = _norm(title)
    groups = [[_norm(a) for a in k.split("|") if _norm(a)] for k in keywords]
    groups = [g for g in groups if g]
    if not groups:
        return False
    if not all(any(a in t for a in g) for g in groups):
        return False
    # Para excluir sí respetamos palabras (con espacios), en minúscula y sin acentos.
    lowered = unicodedata.normalize("NFKD", (title or "").lower()).encode("ascii", "ignore").decode()
    return not any(re.search(rf"\b{re.escape(e.lower())}\b", lowered) for e in exclude if e)
