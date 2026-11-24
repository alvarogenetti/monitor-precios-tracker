"""Mercado Libre: sin lectura automática.

Mercado Libre bloqueó el acceso de desarrollador el 23/11/2026 (la app sólo leía precios) y sus
términos prohíben leer el sitio con robots. Este adaptador existe sólo para que un link de ML en
config/targets.json no rompa nada: nunca hace un request y devuelve "sólo manual". Los precios de ML
entran por la carga manual del dashboard ("Lo vi a $"). Ver README, sección 7.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from scrapers.base import BaseScraper, ScrapeResult

if TYPE_CHECKING:
    from services.targets import Target


class MercadoLibreScraper(BaseScraper):
    store = "mercadolibre"
    domains = ("mercadolibre.com.ar", "mercadolibre.com", "mlstatic.com")
    uses_browser = False

    async def scrape(self, url: str, target: "Target") -> ScrapeResult:
        return ScrapeResult(store=self.store, url=url, error="Mercado Libre: sólo links y carga manual")

    async def extract(self, page, url: str, target: "Target") -> ScrapeResult:  # pragma: no cover
        raise NotImplementedError("Mercado Libre no se lee automáticamente")
