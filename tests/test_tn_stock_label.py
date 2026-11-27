"""Tiendanube sin data-variants (tema de NG Technologies): la etiqueta "Sin stock" existe en todas las
tarjetas; con stock va oculta (style="display:none") y sin stock va visible, SIN atributo style.
Bug del 27/11/2026: el patrón exigía un style, así que un producto sin stock se daba por disponible
(un ASUS OLED a $351.146 que ya no existía llegó a ser "OLED en oferta")."""
import pytest

from scrapers.stores.catalogs import parse_tiendanube
from services.discovery import Offer, SpecCatalog, analyze


def card(name, cents, label_attrs):
    return (f'<div class="js-item-product col"><a href="https://t.com.ar/productos/{name}/" title="{name}">x</a>'
            f'<span class="js-stock-label-private label js-stock-label" data-store="product-item-label-stock" '
            f'data-label="Sin stock" {label_attrs}></span>'
            f'<div class="js-price-display item-price" data-product-price="{cents}">$ x</div></div>')


@pytest.mark.parametrize("attrs, expected", [
    ('style="display: none;"', 1),       # con stock: etiqueta oculta
    ('style="display:none"', 1),
    ('', 0),                             # sin stock: etiqueta visible y sin style  <- el caso del bug
    ('style="color:red"', 0),            # visible con otro estilo
])
def test_stock_label_states(attrs, expected):
    out = parse_tiendanube(card("monitor-a", 35114625, attrs), "ng", "NG")
    assert len(out) == expected
    if expected:
        assert out[0]["price"] == 351146.25


def test_card_without_label_counts_as_in_stock():
    html = ('<div class="js-item-product"><a href="https://t.com.ar/productos/m/" title="M">x</a>'
            '<div class="js-price-display" data-product-price="50000000"></div></div>')
    assert len(parse_tiendanube(html, "ng", "NG")) == 1


def test_suspiciously_cheap_best_gets_a_warning():
    t = 'Monitor ASUS VG27AQL3A 27" QHD 180Hz IPS'
    offers = [Offer("a", t, 150000, "https://a/1"), Offer("b", t, 600000, "https://b/1"),
              Offer("c", t, 620000, "https://c/1"), Offer("d", t, 640000, "https://d/1")]
    cfg = {"requirements": {"size_in": 27, "min_hz": 120}}
    m = next(r for r in analyze(offers, cfg, SpecCatalog([])) if r.key == "VG27AQL3A")
    assert any("por debajo del resto" in w for w in m.warnings)


def test_normal_spread_has_no_warning():
    t = 'Monitor ASUS VG27AQL3A 27" QHD 180Hz IPS'
    offers = [Offer("a", t, 520000, "https://a/1"), Offer("b", t, 600000, "https://b/1"),
              Offer("c", t, 620000, "https://c/1"), Offer("d", t, 640000, "https://d/1")]
    cfg = {"requirements": {"size_in": 27, "min_hz": 120}}
    m = next(r for r in analyze(offers, cfg, SpecCatalog([])) if r.key == "VG27AQL3A")
    assert not any("por debajo del resto" in w for w in m.warnings)
