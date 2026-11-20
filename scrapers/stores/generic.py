"""Fallback para fichas de producto de tiendas sin adaptador propio
(Maximus, Mexx, FullH4rd, TryHardware, Slot One, Frávega, tiendas Tiendanube/WooCommerce...).

Orden de extracción del precio "ancla":
  1. JSON-LD (schema.org Product/Offer) del producto de la página
  2. Meta tags (OpenGraph product:price, itemprop=price)
  3. Selectores comunes (WooCommerce, Tiendanube, VTEX, Magento, PrestaShop, custom)
Después se leen los precios del bloque principal de la ficha: en Argentina el precio
transferencia/efectivo es siempre el más bajo y el de lista/cuotas el más alto, así que
price_cash = mínimo y price_list = máximo (ignorando valores de cuota, precios sin impuestos
y productos relacionados).
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from playwright.async_api import Page

from scrapers.base import (
    BaseScraper,
    ScrapeError,
    ScrapeResult,
    detect_stock,
    meta_content,
    product_from_json_ld,
    read_json_ld,
)
from services.price_parser import extract_prices, is_plausible, parse_ars

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from services.targets import Target

PRODUCT_CONTAINERS = [
    ".product-info-main",          # Magento
    ".summary.entry-summary",      # WooCommerce
    "#single-product",             # Tiendanube
    ".js-product-container",
    ".product-detail", ".product-details", ".product_detail", "#product", ".product-page",
    ".vtex-flex-layout-0-x-flexRow--product-main", ".product-main",
    '[itemtype*="schema.org/Product"]',
    "main", "body",
]

PRICE_SELECTORS = [
    '[itemprop="price"]',
    ".summary .price ins .amount", ".summary .price .amount",   # WooCommerce
    "#price_display", ".js-price-display",                       # Tiendanube
    ".vtex-product-price-1-x-sellingPriceValue",                 # VTEX
    ".price-final_price .price",                                 # Magento
    ".current-price span", ".product-price",                     # PrestaShop / varios
    ".price-special", ".precio-especial", ".price", "[class*='price']", "[class*='precio']",
]

# A partir de acá empiezan los productos relacionados / recomendados: se corta el texto.
SECTION_END_RE = re.compile(
    r"productos?\s+(?:recomendados|relacionados|similares|destacados)|"
    r"tambi[eé]n\s+te\s+(?:puede|podr[ií]a)n?\s+interesar|quienes\s+vieron|"
    r"otros\s+productos|complet[aá]\s+tu\s+compra|te\s+puede\s+interesar|"
    r"art[ií]culos\s+relacionados|clientes\s+tambi[eé]n",
    re.IGNORECASE,
)
# Líneas cuyos montos no son "el precio" del producto.
SKIP_LINE_RE = re.compile(
    r"impuesto|imp\.|s/\s*imp|sin\s+imp|cuotas?\s+(?:fijas\s+)?de\b|cuotas?\s+sin\s+inter[eé]s\s+de|"
    r"\d+\s*x\s*\$|env[ií]o|superando|m[ií]nimo|ahorr[aá]s|ahorro|descuento\s+de|cuota\s+de|"
    r"desde\s+\$|hasta\s+\$|pagando\s+\$",
    re.IGNORECASE,
)


class GenericScraper(BaseScraper):
    store = "generic"

    async def extract(self, page: Page, url: str, target: "Target") -> ScrapeResult:
        await self.goto(page, url)
        await wait_for_prices(page)
        res = ScrapeResult(store=self.store, url=url, product_url=page.url)
        h1 = await self._h1(page)

        # 1) JSON-LD
        anchor: float | None = None
        anchor_reliable = True
        ld = product_from_json_ld(await read_json_ld(page), page.url, h1)
        if ld:
            res.title = ld.get("title")
            anchor = ld.get("price")
            res.in_stock = ld.get("in_stock")

        # 2) Meta tags
        if anchor is None:
            for sel in ('meta[property="product:price:amount"]', 'meta[property="og:price:amount"]',
                        'meta[itemprop="price"]'):
                anchor = parse_ars(await meta_content(page, sel))
                if is_plausible(anchor):
                    break
                anchor = None

        # 3) Selectores comunes
        region_text = cut_related(await self._region_text(page))
        if h1 and h1 in region_text:
            region_text = region_text[region_text.index(h1):]  # descarta menús/nav previos al título
        if anchor is None:
            anchor = await self._price_from_selectors(page)
            anchor_reliable = False  # un selector genérico puede caer en un producto relacionado

        res.title = h1 or res.title or await self._og_title(page)
        self.log.debug("ancla=%s líneas con $: %s", anchor,
                       [ln.strip() for ln in region_text.splitlines() if "$" in ln][:14])
        res.price_cash, res.price_list = split_cash_list(region_text, anchor, anchor_reliable)

        if res.in_stock is None:
            res.in_stock = detect_stock(region_text[:5000])
            if res.in_stock is None and res.price_cash is not None:
                res.in_stock = True  # hay precio y nada indica falta de stock
        elif res.in_stock is True and detect_stock(region_text[:2500]) is False:
            res.in_stock = False  # el JSON-LD a veces queda desactualizado frente al cartel visible

        if res.price_cash is None and res.in_stock is not False and re.search(r"\$\s*NaN", region_text):
            # Mexx (y otras) muestran "$NaN" cuando el producto no tiene precio publicado / sin stock
            res.in_stock = False
        if res.price_cash is None and res.in_stock is not False:
            raise ScrapeError("no se encontró precio en la página")
        return res

    # ------------------------------------------------------------------ helpers
    @staticmethod
    async def _region_text(page: Page) -> str:
        for sel in PRODUCT_CONTAINERS:
            el = await page.query_selector(sel)
            if not el:
                continue
            try:
                txt = await el.inner_text()
            except Exception as e:  # noqa: BLE001 — p.ej. el nodo se desmontó durante un re-render
                log.debug("No se pudo leer %s: %s", sel, e)
                continue
            if "$" in txt or sel == "body":
                return txt
        return ""

    @staticmethod
    async def _price_from_selectors(page: Page) -> float | None:
        for sel in PRICE_SELECTORS:
            for el in (await page.query_selector_all(sel))[:5]:
                raw = await el.get_attribute("content") or await el.inner_text()
                val = parse_ars(raw)
                if is_plausible(val):
                    return val
        return None

    @staticmethod
    async def _h1(page: Page) -> str | None:
        el = await page.query_selector("h1")
        if el:
            txt = (await el.inner_text()).strip()
            if txt:
                return re.sub(r"\s+", " ", txt)[:300]
        return None

    @staticmethod
    async def _og_title(page: Page) -> str | None:
        return await meta_content(page, "meta[property='og:title']") or (await page.title()) or None


async def wait_for_prices(page: Page, timeout_ms: int = 10_000) -> None:
    """Muchas fichas pintan el precio por JS después de networkidle: esperamos a ver un monto."""
    try:
        await page.wait_for_function(
            r"() => document.body && /(\$|ARS)\s?\d{1,3}[.,]?\d{3}/.test(document.body.innerText)",
            timeout=timeout_ms,
        )
        await page.wait_for_timeout(700)  # margen para que terminen de pintarse los demás precios
    except Exception:  # noqa: BLE001 — si no aparece, seguimos con JSON-LD/meta
        pass


def cut_related(text: str) -> str:
    m = SECTION_END_RE.search(text or "")
    return text[: m.start()] if m else (text or "")


def split_cash_list(text: str, anchor: float | None, anchor_reliable: bool = True,
                    max_lines: int = 14) -> tuple[float | None, float | None]:
    """Devuelve (price_cash, price_list) a partir del texto del bloque principal.

    Toma los montos de las primeras `max_lines` líneas con precio (descartando cuotas, precios
    sin impuestos, envíos) dentro de un rango razonable alrededor del precio ancla.
    """
    candidates: list[float] = []
    n = 0
    for line in (text or "").splitlines():
        line = line.strip()
        if "$" not in line and "ARS" not in line.upper():
            continue
        n += 1
        if n > max_lines:
            break
        if SKIP_LINE_RE.search(line):
            continue
        candidates.extend(extract_prices(line))

    extra: list[float] = []
    if candidates and (anchor is None or not anchor_reliable):
        # sin ancla confiable, el primer monto del bloque principal es la mejor referencia
        anchor = candidates[0]
    elif anchor is not None:
        extra = [anchor]
    if anchor is None:
        return None, None
    lo, hi = 0.6 * anchor, 1.8 * anchor
    pool = [p for p in candidates if lo <= p <= hi] + extra
    cash, lst = min(pool), max(pool)
    return cash, (lst if lst > cash * 1.01 else None)
