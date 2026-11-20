"""Compra Gamer (SPA Angular).

La SPA descarga al iniciar un catálogo JSON (static.compragamer.com/productos) con todos los
productos vendibles, incluyendo `precioEspecial` (transferencia/depósito) y `precioLista`.
En lugar de pelear con el DOM renderizado, interceptamos esa respuesta desde Playwright.

URLs soportadas:
  - Ficha:    https://compragamer.com/producto/<Nombre_Del_Producto>_<id>
  - Búsqueda: https://compragamer.com/productos?criterio=GS27QA   (filtra por keywords del target)
Si el producto no figura en el catálogo, Compra Gamer no lo tiene a la venta -> sin stock.
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Page, Response

from scrapers.base import DEFAULT_EXCLUDE, BaseScraper, ScrapeError, ScrapeResult, matches_keywords
from services.price_parser import extract_prices, parse_ars

if TYPE_CHECKING:
    from services.targets import Target

CATALOG_URL_RE = re.compile(r"^https://static\.compragamer\.com/productos/?(?:\?.*)?$")
PRODUCT_ID_RE = re.compile(r"/producto/[^/?#]*?_(\d+)(?:[/?#]|$)")


def product_url(item: dict) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", item.get("nombre", "")).strip("_")
    return f"https://compragamer.com/producto/{slug}_{item['id_producto']}"


def item_in_stock(item: dict) -> bool:
    return bool(item.get("vendible")) and (item.get("stock") or 0) > 0


class CompraGamerScraper(BaseScraper):
    store = "compragamer"
    domains = ("compragamer.com",)

    async def extract(self, page: Page, url: str, target: "Target") -> ScrapeResult:
        catalog_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

        async def on_response(resp: Response) -> None:
            if catalog_future.done() or not CATALOG_URL_RE.match(resp.url) or resp.status != 200:
                return
            try:
                catalog_future.set_result(await resp.json())
            except Exception as e:  # noqa: BLE001
                if not catalog_future.done():
                    catalog_future.set_exception(ScrapeError(f"catálogo inválido: {e}"))

        page.on("response", on_response)
        await self.goto(page, url, idle_ms=4000)

        try:
            catalog = await asyncio.wait_for(catalog_future, timeout=25)
        except asyncio.TimeoutError:
            return await self._dom_fallback(page, url)

        if not isinstance(catalog, list) or not catalog:
            raise ScrapeError("catálogo vacío o con formato inesperado")
        self.log.debug("Catálogo Compra Gamer: %d productos", len(catalog))

        m = PRODUCT_ID_RE.search(urlparse(url).path + "/")
        if m:
            pid = int(m.group(1))
            item = next((x for x in catalog if x.get("id_producto") == pid), None)
            if item is None:
                return ScrapeResult(store=self.store, url=url, in_stock=False, product_url=url,
                                    title=await self._dom_title(page))
            return self._from_item(url, item)

        # Página de búsqueda / categoría: elegimos el más barato que matchee los keywords
        keywords = target.keywords or self._criterio_tokens(url)
        exclude = target.exclude if target.exclude is not None else DEFAULT_EXCLUDE
        matches = [x for x in catalog
                   if matches_keywords(x.get("nombre", ""), keywords, exclude)
                   and not x.get("es_outlet")]
        if not matches:
            return ScrapeResult(store=self.store, url=url, in_stock=False,
                                title=f"(sin resultados para {' '.join(keywords)})")
        in_stock = [x for x in matches if item_in_stock(x)] or matches
        best = min(in_stock, key=lambda x: x.get("precioEspecial") or float("inf"))
        return self._from_item(url, best)

    def _from_item(self, url: str, item: dict) -> ScrapeResult:
        return ScrapeResult(
            store=self.store,
            url=url,
            title=item.get("nombre"),
            price_cash=parse_ars(item.get("precioEspecial")),
            price_list=parse_ars(item.get("precioLista")),
            in_stock=item_in_stock(item),
            product_url=product_url(item),
        )

    @staticmethod
    def _criterio_tokens(url: str) -> list[str]:
        q = parse_qs(urlparse(url).query).get("criterio", [""])[0]
        return [t for t in re.split(r"\s+", q) if t]

    @staticmethod
    async def _dom_title(page: Page) -> str | None:
        el = await page.query_selector("h1")
        return (await el.inner_text()).strip() if el else None

    async def _dom_fallback(self, page: Page, url: str) -> ScrapeResult:
        """Si no pudimos interceptar el catálogo, leemos la ficha renderizada."""
        if not PRODUCT_ID_RE.search(urlparse(url).path + "/"):
            raise ScrapeError("no se interceptó el catálogo y la URL no es una ficha")
        try:
            await page.wait_for_selector("h1", timeout=15000)
        except Exception as e:  # noqa: BLE001
            raise ScrapeError("la ficha no terminó de renderizar") from e
        text = await page.inner_text("body")
        prices = extract_prices(text[:6000])
        if not prices:
            raise ScrapeError("ficha sin precios visibles")
        # En la ficha CG muestra primero el precio especial y luego el de lista (más alto)
        cash = min(prices[:4])
        lst = max(prices[:4])
        return ScrapeResult(store=self.store, url=url, title=await self._dom_title(page),
                            price_cash=cash, price_list=lst if lst > cash else None,
                            in_stock="sin stock" not in text.lower(), product_url=page.url)
