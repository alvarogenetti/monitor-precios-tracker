import asyncio
from datetime import datetime, timedelta, timezone

from app.main import _fresh_manual, ml_search_url
from scrapers.stores.mercadolibre import MercadoLibreScraper
from services.targets import Target
from settings import settings


def test_ml_api_is_off_and_scraper_never_reads_the_web():
    assert settings.meli_enabled is False
    t = Target(id="x", name="X", target_price=1)
    res = asyncio.run(MercadoLibreScraper(None, 0).scrape("https://listado.mercadolibre.com.ar/x", t))
    assert res.price_cash is None and "manual" in res.error


def test_manual_snapshot_expires_after_3_days():
    now = datetime.now(timezone.utc)
    assert _fresh_manual({"promo": "carga manual", "scanned_at": now.isoformat()})
    assert not _fresh_manual({"promo": "carga manual", "scanned_at": (now - timedelta(days=4)).isoformat()})
    assert not _fresh_manual({"promo": "-15% sobre lista", "scanned_at": now.isoformat()})  # API vieja


def test_ml_search_url():
    assert ml_search_url("Samsung S27FG500EL") == "https://listado.mercadolibre.com.ar/samsung-s27fg500el"
    assert ml_search_url("MSI MAG 275QF / MAG 274QF X24") == "https://listado.mercadolibre.com.ar/msi-mag-275qf"
