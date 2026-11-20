"""Registro de adaptadores por tienda."""
from __future__ import annotations

from urllib.parse import urlparse

from scrapers.base import BaseScraper
from scrapers.stores.compragamer import CompraGamerScraper
from scrapers.stores.vtex import VTEX_STORES, VtexScraper
from scrapers.stores.generic import GenericScraper
from scrapers.stores.hardgamers import HardGamersScraper
from scrapers.stores.mercadolibre import MercadoLibreScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    "mercadolibre": MercadoLibreScraper,
    "compragamer": CompraGamerScraper,
    "hardgamers": HardGamersScraper,
    "electro": VtexScraper,
    **{k: VtexScraper for k in VTEX_STORES},   # fravega, oncity, cetrogar, carrefour, pardo...
    "generic": GenericScraper,
}


def get_scraper_class(store: str | None, url: str) -> type[BaseScraper]:
    """Por nombre de tienda; si no hay adaptador, por dominio; si no, el genérico."""
    if store and store.lower() in SCRAPERS:
        return SCRAPERS[store.lower()]
    host = urlparse(url).netloc.lower()
    for cls in SCRAPERS.values():
        if any(host == d or host.endswith("." + d) for d in cls.domains):
            return cls
    return GenericScraper


__all__ = ["SCRAPERS", "get_scraper_class"]
