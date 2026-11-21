import sqlite3

import pytest

from scrapers.base import matches_keywords
from services.db import Database
from services.targets import Target


def test_bands_with_explicit_high():
    t = Target(id="a", name="A", target_price=335000, price_high=375000)
    assert t.band(330000) == "bajo"
    assert t.band(335000) == "bajo"          # el objetivo cuenta como "comprá"
    assert t.band(350000) == "normal"
    assert t.band(375000) == "normal"
    assert t.band(375001) == "alto"
    assert t.band(None) is None


def test_band_default_high_is_15_percent():
    t = Target(id="a", name="A", target_price=400000)
    assert t.high == 460000
    assert t.band(460000) == "normal" and t.band(461000) == "alto"


def test_high_must_be_above_target():
    with pytest.raises(ValueError):
        Target(id="a", name="A", target_price=400000, price_high=390000)


def test_keyword_alternatives():
    kws = ["MAG", "274QF|275QF"]
    assert matches_keywords("Monitor MSI MAG 275QF 27 WQHD 180Hz", kws)
    assert matches_keywords("MSI MAG 274QF X24 Rapid IPS", kws)
    assert not matches_keywords("MSI MAG 274F 27 FHD", kws)
    assert not matches_keywords("MSI PRO MP275Q", kws)


def _snap(price, store="hardgamers", stock=True, error=None, ts="2026-11-20T12:00:00+00:00"):
    return {"store": store, "url": f"https://x/{store}", "price_cash": price,
            "in_stock": stock, "error": error, "scanned_at": ts, "seller": None}


def test_best_series_takes_min_in_stock_per_run(tmp_path):
    db = Database(tmp_path / "h.db")
    r1 = db.start_run("cli")
    db.insert_snapshot("m", _snap(350000, "compragamer"), r1)
    db.insert_snapshot("m", _snap(340000, "hardgamers"), r1)
    db.insert_snapshot("m", _snap(300000, "maximus", stock=False), r1)   # sin stock: no cuenta
    db.insert_snapshot("m", _snap(None, "mexx", error="timeout"), r1)
    r2 = db.start_run("cli")
    db.insert_snapshot("m", _snap(345000, "compragamer"), r2)
    db.insert_snapshot("otro", _snap(1000, "x"), r2)

    s = db.best_series("m", days=100000)
    assert [(p["run_id"], p["price"], p["store"]) for p in s] == [
        (r1, 340000, "hardgamers"), (r2, 345000, "compragamer")]


def test_migration_backfills_run_id(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT NOT NULL,
            store TEXT NOT NULL, url TEXT NOT NULL, title TEXT, seller TEXT, product_url TEXT,
            price_cash REAL, price_list REAL, in_stock INTEGER, error TEXT, scanned_at TEXT NOT NULL);
        CREATE TABLE scan_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, n_ok INTEGER DEFAULT 0,
            n_error INTEGER DEFAULT 0, n_alerts INTEGER DEFAULT 0);
        INSERT INTO scan_runs (trigger, started_at, finished_at)
            VALUES ('cli', '2026-11-19T10:00:00+00:00', '2026-11-19T10:05:00+00:00'),
                   ('cli', '2026-11-20T10:00:00+00:00', '2026-11-20T10:05:00+00:00');
        INSERT INTO snapshots (target_id, store, url, price_cash, in_stock, scanned_at) VALUES
            ('m', 'cg', 'u', 1000, 1, '2026-11-19T10:01:00+00:00'),
            ('m', 'cg', 'u', 900, 1, '2026-11-20T10:02:00+00:00');
    """)
    con.commit()
    con.close()

    db = Database(path)
    with db.connect() as c:
        assert [r[0] for r in c.execute("SELECT run_id FROM snapshots ORDER BY id")] == [1, 2]


def test_fravega_card_prices():
    from scrapers.stores.fravega import card_prices
    text = ("Monitor Gamer BenQ EW270Q LED 27 QHD 200Hz USB C\n\nVendido por Glic\n\n$943.695\n28\n"
            "$679.460\n\nPrecio s/imp. nac. $561.537\n\nEnvío GRATIS\nComparar")
    assert card_prices(text) == (679460, 943695)
    assert card_prices("Monitor X\n$500.000\nPrecio s/imp. nac. $413.223") == (500000, None)


def test_fravega_registered():
    from scrapers.stores import get_scraper_class
    from scrapers.stores.vtex import VtexScraper as FravegaScraper
    assert get_scraper_class("venex", "https://www.fravega.com/l/?keyword=x") is FravegaScraper
    assert get_scraper_class(None, "https://www.fravega.com/p/algo-123/") is FravegaScraper


def test_vtex_offers_and_promo():
    from scrapers.stores.vtex import best_match, offers_from, promo_text
    products = [{"productName": "Monitor LG 27GS75Q B 27 QHD 180Hz IPS", "link": "https://www.fravega.com/x/p",
                 "items": [{"sellers": [
                     {"sellerName": "Glic", "commertialOffer": {"Price": 594557.0, "ListPrice": 825773.0,
                      "AvailableQuantity": 100, "Teasers": [{"Name": "3 cuotas sin interés"}]}},
                     {"sellerName": "Frávega", "commertialOffer": {"Price": 500000.0, "ListPrice": 500000.0,
                      "AvailableQuantity": 0}}]}]},
                {"productName": "Soporte monitor", "items": [{"sellers": [{"commertialOffer": {
                    "Price": 10000.0, "AvailableQuantity": 5}}]}]}]
    o = best_match(offers_from(products, "fravega"), ["27GS75Q"], [])
    assert (o["price"], o["seller"]) == (594557.0, "Frávega · Glic")      # el sin stock no cuenta
    assert promo_text(o) == "-28% sobre lista · 3 cuotas sin interés"


def test_dell_and_megatone_parsers():
    from scrapers.stores.catalogs import parse_dell, parse_megatone
    dell = ('<div data-product-detail=\'[{"Key":"x","Value":{"productId":"s2725dsm","title":"Monitor QHD Dell S 27 - S2725DSM",'
            '"dellPrice":"$ 497.805,62","marketPrice":null,"pdUrl":"/es-ar/shop/s2725dsm"}}]\'></div>')
    d = parse_dell(dell)[0]
    assert (d["price"], d["url"]) == (497805.62, "https://www.dell.com/es-ar/shop/s2725dsm")
    mega = ('<script type="application/ld+json">{"@type":"ItemList","itemListElement":[{"item":{"name":"Monitor Gamer 27\\" Hawkeye 200Hz Qhd...",'
            '"offers":{"price":"636479","availability":"https://schema.org/InStock","url":"https://www.megatone.net/p/1?psc=1"}}}]}</script>')
    m = parse_megatone(mega)[0]
    assert (m["price"], m["url"]) == (636479, "https://www.megatone.net/p/1")


def test_samsung_vtex_store_from_url():
    from scrapers.stores import get_scraper_class
    from scrapers.stores.vtex import VtexScraper
    assert get_scraper_class(None, "https://shop.samsung.com/ar/monitor/p") is VtexScraper
    assert VtexScraper._store_from_url("https://shop.samsung.com/ar/x") == "samsung"
