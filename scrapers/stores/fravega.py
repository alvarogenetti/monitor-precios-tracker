"""Frávega: retailer grande (LG, Samsung, BenQ...) que no indexa en HardGamers.

URLs soportadas:
  - Búsqueda: https://www.fravega.com/l/?keyword=EW270Q   (el más barato que matchee keywords)
  - Ficha:    https://www.fravega.com/p/<slug>-<id>/        (adaptador genérico)
Muchas publicaciones son de vendedores del marketplace ("Vendido por X"): se guarda en `seller`.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.async_api import Page

from scrapers.base import DEFAULT_EXCLUDE, ScrapeResult, matches_keywords
from scrapers.stores.generic import GenericScraper
from services.price_parser import extract_prices

if TYPE_CHECKING:
    from services.targets import Target

CARDS_JS = """
() => Array.from(document.querySelectorAll('article[data-test-id="result-item"]')).map(a => ({
  name: (a.querySelector('[data-test-id="article-title"] span') || {}).textContent || '',
  text: a.innerText,
  href: (a.querySelector('a[href*="/p/"]') || {}).getAttribute?.('href') || null,
}))
"""
SELLER_RE = re.compile(r"Vendido por\s+(.+)", re.I)


def card_prices(text: str) -> tuple[float | None, float | None]:
    """Precio actual y precio tachado de una card. Ignora 'Precio s/imp. nac.' y las cuotas."""
    prices: list[float] = []
    for line in text.splitlines():
        if re.search(r"s/\s*imp|sin\s+imp|cuota", line, re.I):
            continue
        prices += extract_prices(line)
    if not prices:
        return None, None
    return min(prices), (max(prices) if max(prices) > min(prices) else None)


class FravegaScraper(GenericScraper):
    store = "fravega"
    domains = ("fravega.com",)

    async def extract(self, page: Page, url: str, target: "Target") -> ScrapeResult:
        if "/p/" in urlparse(url).path:
            res = await super().extract(page, url, target)
            res.store = self.store
            return res

        await self.goto(page, url, idle_ms=4000)
        try:
            await page.wait_for_selector('article[data-test-id="result-item"]', timeout=12000)
        except Exception:  # noqa: BLE001 — sin cards = sin resultados
            pass
        cards = await page.evaluate(CARDS_JS)
        keywords = target.keywords or parse_qs(urlparse(url).query).get("keyword", [""])[0].split()
        exclude = target.exclude if target.exclude is not None else DEFAULT_EXCLUDE
        offers = []
        for c in cards:
            if not matches_keywords(c["name"], keywords, exclude):
                continue
            cash, lst = card_prices(c["text"])
            if cash:
                m = SELLER_RE.search(c["text"])
                offers.append({**c, "cash": cash, "list": lst,
                               "seller": m.group(1).strip() if m else "Frávega"})
        self.log.debug("Frávega: %d cards, %d matchean %s", len(cards), len(offers), keywords)
        if not offers:
            return ScrapeResult(store=self.store, url=url, in_stock=False,
                                title=f"(sin resultados para {' '.join(keywords)})")
        best = min(offers, key=lambda o: o["cash"])
        return ScrapeResult(
            store=self.store, url=url, title=best["name"].strip(),
            price_cash=best["cash"], price_list=best["list"], in_stock=True,
            seller=best["seller"],
            product_url=urljoin(url, best["href"]) if best["href"] else url,
        )
