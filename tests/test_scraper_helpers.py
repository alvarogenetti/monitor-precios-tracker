"""Tests de las heurísticas de scraping (sin red), con textos reales de tiendas argentinas."""
from scrapers.base import (
    availability_to_stock,
    detect_stock,
    matches_keywords,
    product_from_json_ld,
)
from scrapers.stores import get_scraper_class
from scrapers.stores.compragamer import PRODUCT_ID_RE, product_url
from scrapers.stores.generic import GenericScraper, cut_related, split_cash_list
from scrapers.stores.hardgamers import HardGamersScraper

MAXIMUS = """Monitor LED IPS 27" Raptor Hawk Eye
Efectivo / Transferencia / Depósito
MEJOR PRECIO
Hasta 11% off por medio de pago
$295.996
Precio s/imp. nac. $244.625
Con tarjeta débito / crédito
$331.500
Precio s/imp. nac. $273.967
6 CUOTAS SIN INTERÉS
6 x $55.250
SIN STOCK EN EL LOCAL
Productos recomendados
Combo Teclado y Mouse Logitech
$37.055
Efectivo / Transferencia
"""

SLOT_ONE = """Precio Slot One: $302.250
Por pago en efectivo o transferencia
Precio de Lista: $465.000
3 cuotas fijas de: $\xa0122.450
- $\xa0367.350
12 cuotas fijas de: $\xa038.750
- $\xa0465.000
 Envío gratis superando los $470.000
"""


def test_split_cash_list_maximus():
    assert split_cash_list(cut_related(MAXIMUS), 331500.0) == (295996.0, 331500.0)


def test_split_cash_list_unreliable_anchor_ignored():
    # un selector genérico agarró el precio de un producto relacionado (301.320)
    assert split_cash_list(SLOT_ONE, 301320.0, anchor_reliable=False) == (302250.0, 465000.0)


def test_split_cash_list_single_price():
    assert split_cash_list("Precio\n$ 418.299\nComprar", None) == (418299.0, None)


def test_detect_stock():
    assert detect_stock("SIN STOCK EN EL LOCAL\nSolo para compra presencial") is None
    assert detect_stock("Producto agotado") is False
    assert detect_stock("Publicación pausada") is False
    assert detect_stock("Agregar al carrito") is True


def test_availability():
    assert availability_to_stock("https://schema.org/InStock") is True
    assert availability_to_stock("http://schema.org/OutOfStock") is False
    assert availability_to_stock(None) is None


def test_matches_keywords():
    t = 'Monitor Gamer 27" Msi Mag 240Hz WQHD 0.5Ms 274QF X24'
    assert matches_keywords(t, ["274QF", "X24"])
    assert matches_keywords("LG MONITOR 27\" 27GS75Q-B IPS", ["27GS75Q"])
    assert not matches_keywords("Monitor PG27QFT2A - Usado en evento", ["PG27QFT2A"])
    assert not matches_keywords("Monitor GS27QA", [])


def test_json_ld_prefers_page_product():
    nodes = [
        {"@type": "Product", "name": "Relacionado", "url": "https://t.com/productos/otro/",
         "offers": {"@type": "Offer", "price": "100000", "priceCurrency": "ARS"}},
        {"@type": "Product", "name": "Principal", "url": "https://t.com/productos/este/",
         "offers": {"@type": "Offer", "price": "302250.00", "priceCurrency": "ARS",
                    "availability": "https://schema.org/InStock"}},
    ]
    got = product_from_json_ld(nodes, "https://t.com/productos/este/?utm=x")
    assert got == {"title": "Principal", "price": 302250.0, "in_stock": True}
    # ambiguo (varios Product, ninguno coincide) -> se descarta
    assert product_from_json_ld(nodes, "https://t.com/productos/nada/") is None


def test_compragamer_ids():
    url = "https://compragamer.com/producto/Monitor_Gamer_AsRock_PG27QFT2A_27_QHD_16400?x=1"
    assert PRODUCT_ID_RE.search("/producto/Monitor_Gamer_AsRock_PG27QFT2A_27_QHD_16400/").group(1) == "16400"
    assert product_url({"id_producto": 22426, "nombre": "Router Tp-Link Archer GE230"}) == \
        "https://compragamer.com/producto/Router_Tp_Link_Archer_GE230_22426"
    assert url  # noqa


def test_registry():
    assert get_scraper_class("hardgamers", "https://x.com") is HardGamersScraper
    assert get_scraper_class("maximus", "https://www.hardgamers.com.ar/search?text=a") is HardGamersScraper
    assert get_scraper_class("maximus", "https://www.maximus.com.ar/Producto/x") is GenericScraper
