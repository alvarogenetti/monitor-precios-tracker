"""HardGamers: comparador de precios de tiendas de hardware argentinas.

Con una sola búsqueda (https://www.hardgamers.com.ar/search?text=PG27QFT2A) obtenemos las
ofertas de todas las tiendas que lo publican; nos quedamos con la más barata que matchee los
keywords del target. `seller` guarda el nombre de la tienda que ofrece ese precio.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.async_api import Page

from scrapers.base import (
    DEFAULT_EXCLUDE,
    ScrapeError,
    ScrapeResult,
    availability_to_stock,
    matches_keywords,
)
from scrapers.stores.generic import GenericScraper
from services.price_parser import is_plausible, parse_ars

if TYPE_CHECKING:
    from services.targets import Target

# Sólo las cards hijas directas del listado: así ignoramos el bloque "Ofertas Destacadas".
CARDS_JS = """
() => Array.from(document.querySelectorAll('.Product-List > article')).map(a => {
  const price = a.querySelector('[itemprop="price"]');
  const avail = a.querySelector('[itemprop="availability"]');
  const link = a.querySelector('a[href*="/product/"]');
  const q = s => (a.querySelector(s)?.textContent || '').trim();
  return {
    name: q('.product-name') || q('[itemprop="name"]'),
    store: q('.store'),
    price: price ? (price.getAttribute('content') || price.textContent) : null,
    priceText: q('.product-price'),
    availability: avail ? avail.getAttribute('href') : null,
    href: link ? link.getAttribute('href') : null,
  };
})
"""


class HardGamersScraper(GenericScraper):
    store = "hardgamers"
    domains = ("hardgamers.com.ar",)

    async def extract(self, page: Page, url: str, target: "Target") -> ScrapeResult:
        if "/product/" in urlparse(url).path:
            # Ficha individual: tiene microdata/JSON-LD estándar
            res = await super().extract(page, url, target)
            res.store = self.store
            return res

        await self.goto(page, url, idle_ms=4000)
        try:
            await page.wait_for_selector(".Product-List", timeout=15000)
        except Exception as e:  # noqa: BLE001
            raise ScrapeError("no apareció el listado de productos") from e

        cards = await page.evaluate(CARDS_JS)
        keywords = target.keywords or self._query_tokens(url)
        exclude = target.exclude if target.exclude is not None else DEFAULT_EXCLUDE
        offers = []
        for c in cards:
            price = parse_ars(c.get("price")) or parse_ars(c.get("priceText"))
            if not is_plausible(price) or not matches_keywords(c.get("name", ""), keywords, exclude):
                continue
            offers.append({**c, "price_num": price,
                           "in_stock": availability_to_stock(c.get("availability"))})

        self.log.debug("HardGamers: %d cards, %d matchean %s", len(cards), len(offers), keywords)
        if not offers:
            return ScrapeResult(store=self.store, url=url, in_stock=False,
                                title=f"(sin resultados para {' '.join(keywords)})")

        available = [o for o in offers if o["in_stock"] is not False] or offers
        best = min(available, key=lambda o: o["price_num"])
        return ScrapeResult(
            store=self.store,
            url=url,
            title=re.sub(r"\s+", " ", best["name"]).strip(),
            price_cash=best["price_num"],
            in_stock=best["in_stock"] if best["in_stock"] is not None else True,
            seller=best.get("store") or None,
            product_url=urljoin(url, best["href"]) if best.get("href") else url,
        )

    @staticmethod
    def _query_tokens(url: str) -> list[str]:
        q = parse_qs(urlparse(url).query).get("text", [""])[0]
        return [t for t in re.split(r"\s+", q) if t]
