import html
import json

from scrapers.stores.catalogs import parse_mallweb, parse_tiendanube


def test_parse_tiendanube_uses_transfer_price():
    variants = [{"price_number": 972000, "price_with_payment_discount_short": "$631.800,00",
                 "available": True}]
    page = f'''<div class="js-product-item-private product-item js-item-product mb-3" data-product-id="1"
      data-variants="{html.escape(json.dumps(variants))}">
      <a href="https://tienda.com.ar/productos/msi-274qpf/" title="Monitor MSI 274QPF">x</a>
      <div class="js-item-name item-name">Monitor Gamer MSI 27&quot; Mag 274QPF WQHD 320Hz</div></div>
      <div class="js-product-item-private product-item js-item-product" data-variants="{html.escape(json.dumps([{"price_number": 5, "available": False}]))}">
      <a href="https://tienda.com.ar/productos/agotado/">y</a><div class="item-name">Agotado</div></div>'''
    got = parse_tiendanube(page, "nickhard", "Nickhard")
    assert got == [{"store": "nickhard", "title": 'Monitor Gamer MSI 27" Mag 274QPF WQHD 320Hz',
                    "price": 631800.0, "list": 972000, "seller": "Nickhard",
                    "url": "https://tienda.com.ar/productos/msi-274qpf/"}]


def test_parse_mallweb_cash_price():
    page = '''<li><article class="x"><a href="/producto/24989"><img alt="m"></a>
      <a href="/producto/24989"><h3 class="t">Monitor Gamer Msi 27&quot; Mag 274QPF WQHD 320Hz</h3></a>
      <div><p class="a">Efectivo o transferencia</p><p class="b">$606.104</p></div></article></li>'''
    got = parse_mallweb(page)
    assert got[0]["price"] == 606104 and got[0]["url"] == "https://www.mallweb.com.ar/producto/24989"
    assert got[0]["title"].startswith('Monitor Gamer Msi 27"')


def test_parse_woocommerce_and_shopify():
    from scrapers.stores.catalogs import parse_shopify, parse_woocommerce

    woo = [{"name": "Monitor LG 27GS75Q-B", "permalink": "https://t/p/1", "is_in_stock": True,
            "prices": {"price": "45000000", "regular_price": "50000000", "currency_minor_unit": 2}},
           {"name": "Agotado", "permalink": "https://t/p/2", "is_in_stock": False,
            "prices": {"price": "1", "regular_price": "1", "currency_minor_unit": 0}}]
    got = parse_woocommerce(woo, "t", "T")
    assert got == [{"store": "t", "title": "Monitor LG 27GS75Q-B", "price": 450000.0, "list": 500000.0,
                    "seller": "T", "url": "https://t/p/1"}]
    shop = [{"title": "Monitor Gigabyte GS27QA", "handle": "gs27qa",
             "variants": [{"price": "399999.00", "compare_at_price": None, "available": True}]},
            {"title": "Mouse", "handle": "m", "variants": [{"price": "1000", "available": True}]}]
    got = parse_shopify(shop, "https://s.com.ar", "s", "S")
    assert len(got) == 1 and got[0]["price"] == 399999.0 and got[0]["url"] == "https://s.com.ar/products/gs27qa"


def test_parse_qloud_prestashop_tiendanegocio():
    from scrapers.stores.catalogs import parse_prestashop, parse_qloud, parse_tiendanegocio

    q = '''<div class="col-md-3 listado" data-marca="ARKHAM" data-id="1" data-nombre="MONITOR 27 ARKHAM QHD" data-precio="381766">
      <a href="https://gerbio.com.ar/monitores/monitor-27-arkham-1.html">x</a></div>'''
    assert parse_qloud(q, "gerbio", "Gerbio")[0]["price"] == 381766
    ps = ('dataLayer.push({"items":[{"item_name":"Monitor Gamer Asrock 27\\" Pg27qfw2a Qhd","item_id":"6605",'
          '"price":"771902.56","price_tax_exc":"1","quantity":12},{"item_name":"Agotado","item_id":"7",'
          '"price":"1000","quantity":0}]})')
    got = parse_prestashop(ps, "https://www.armytech.com.ar", "armytech", "Armytech")
    assert len(got) == 1 and got[0]["title"] == 'Monitor Gamer Asrock 27" Pg27qfw2a Qhd'
    assert got[0]["url"].endswith("id_product=6605")
    tn = ('<script id="1-state" type="application/json">{&q;x&q;:{&q;products&q;:[{&q;title&q;:&q;Monitor ARKHAM 27 QHD&q;,'
          '&q;price&q;:430562,&q;promo&q;:417509,&q;stock&q;:2,&q;status&q;:1,&q;hash&q;:&q;monitor-arkham&q;,'
          '&q;discount_min_price&q;:375758.1}]}}</script>')
    got = parse_tiendanegocio(tn, "https://otecno.com.ar", "otecno", "Otecno")
    assert got == [{"store": "otecno", "title": "Monitor ARKHAM 27 QHD", "price": 375758.1, "list": 417509.0,
                    "seller": "Otecno", "url": "https://otecno.com.ar/producto/monitor-arkham"}]
