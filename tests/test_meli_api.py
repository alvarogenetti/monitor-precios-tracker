from scrapers.stores.mercadolibre import api_scrape
from services.meli_api import best_offer, classify_url, load_token, save_token
from services.targets import Target


def test_classify_url():
    assert classify_url("https://www.mercadolibre.com.ar/monitor-gigabyte/p/MLA25984583") == ("product", "MLA25984583")
    assert classify_url("https://www.mercadolibre.com.ar/monitor-gs27qa-3/up/MLAU3233183988") == ("user_product", "MLAU3233183988")
    assert classify_url("https://articulo.mercadolibre.com.ar/MLA-1513452021-monitor-asrock-_JM") == ("item", "MLA1513452021")
    assert classify_url("https://listado.mercadolibre.com.ar/asrock-pg27qft2a") == ("search", None)


def test_best_offer_prefers_new_and_cheapest():
    items = [{"price": 300000, "condition": "used"}, {"price": 350000, "condition": "new"},
             {"price": 340000, "condition": "new"}, {"price": None}]
    assert best_offer(items)["price"] == 340000
    assert best_offer([{"price": 1, "condition": "used"}])["price"] == 1
    assert best_offer([]) is None


def test_token_roundtrip(tmp_path):
    p = tmp_path / "t.enc"
    save_token(p, "secreto", {"refresh_token": "TG-abc"})
    assert b"TG-abc" not in p.read_bytes()            # queda cifrado
    assert load_token(p, "secreto")["refresh_token"] == "TG-abc"
    assert load_token(p, "otro") is None              # otra clave no lo abre


class FakeClient:
    def search_products(self, q, limit=10):
        return [{"id": "MLA1", "name": "Monitor Gamer AsRock PG27QFT2A 27 QHD"},
                {"id": "MLA2", "name": "Soporte para monitor"}]

    def product_items(self, pid):
        return {"MLA1": [{"price": 355000, "condition": "new", "seller_id": 9, "original_price": 400000,
                          "item_id": "MLA9", "international_delivery_mode": "none"},
                         {"price": 300000, "condition": "new", "seller_id": 5, "item_id": "MLA5",
                          "international_delivery_mode": "cbt"},
                         {"price": 349999, "condition": "new", "seller_id": 7, "item_id": "MLA77",
                          "international_delivery_mode": "none"}]}.get(pid, [])

    def seller_ok(self, uid):
        return uid != 9

    def nickname(self, uid):
        return {7: "ARMYTECH"}.get(uid, str(uid))

    def product(self, pid):
        return {"name": "x"}


def test_api_scrape_search():
    t = Target(id="a", name="ASRock", target_price=335000, keywords=["PG27QFT2A"])
    r = api_scrape(FakeClient(), "https://listado.mercadolibre.com.ar/asrock-pg27qft2a", t)
    assert (r.price_cash, r.in_stock, r.seller) == (349999, True, "ARMYTECH")   # el internacional no gana
    assert r.product_url == "https://articulo.mercadolibre.com.ar/MLA-77"


def test_best_offer_skips_untrusted_sellers():
    items = [{"price": 999990, "seller_id": 1}, {"price": 1169999, "seller_id": 2}]
    assert best_offer(items, seller_ok=lambda u: u == 2)["price"] == 1169999
    assert best_offer(items, seller_ok=lambda u: False) is None
