"""Frávega: ofertas de la API vieja que la web nueva no tiene o no vende se descartan."""
from services import fravega_check as fc
from services.discovery import Offer, SpecCatalog, _drop_fravega_ghosts, analyze


def test_item_id():
    assert fc.item_id("https://www.fravega.com/p/monitor-dell-s2725dc-27-22878258/") == "22878258"
    assert fc.item_id("https://www.fravega.com/l/?keyword=x") is None


def test_classify():
    assert fc.classify("La página no existe\nNavegá por...", False) == "missing"
    assert fc.classify("Este producto no se encuentra disponible para tu ubicación", False) == "unavailable"
    assert fc.classify("Monitor Dell\nComprar\nAgregar al carrito", False) == "unavailable"   # sin precio
    assert fc.classify("Vendido por Glic\n$960.579\n$691.617\nComprar", True) == "ok"


def test_first_valid_skips_ghosts(monkeypatch):
    monkeypatch.setattr(fc, "check", lambda urls: {u: ("missing" if "fantasma" in u else "ok") for u in urls})
    offers = [{"price": 100, "url": "https://f/p/fantasma-11111/"}, {"price": 200, "url": "https://f/p/real-22222/"}]
    assert fc.first_valid(offers)["price"] == 200 and fc.REJECTED == ["https://f/p/fantasma-11111/"]


def test_discovery_drops_fravega_ghost(monkeypatch):
    monkeypatch.setenv("FRAVEGA_CHECK", "1")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)     # en GitHub el chequeo está apagado a propósito
    monkeypatch.setattr(fc, "check", lambda urls: {u: ("missing" if "fantasma" in u else "ok") for u in urls})
    cfg = {"requirements": {"size_in": 27, "min_hz": 120}}
    t = 'Monitor ASUS VG27AQL3A 27" QHD 180Hz IPS'
    offers = [Offer("fravega", t, 300000, "https://www.fravega.com/p/fantasma-22755673/", "Frávega · Glic"),
              Offer("compragamer", t, 450000, "https://cg/p/1")]
    cat = SpecCatalog([])
    offers2, results = _drop_fravega_ghosts(offers, analyze(offers, cfg, cat), cfg, cat)
    best = next(r for r in results if r.key == "VG27AQL3A").best
    assert best["store"] == "compragamer" and len(offers2) == 1


def test_check_failure_never_drops(monkeypatch, tmp_path):
    """Si el navegador no arranca (o Playwright se queja), no se descarta ninguna oferta."""
    monkeypatch.setenv("FRAVEGA_CHECK", "1")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(fc, "CACHE", tmp_path / "c.json")

    def boom(urls):
        raise RuntimeError("Playwright Sync API inside the asyncio loop")
    monkeypatch.setattr(fc, "_check_pages", boom)
    assert fc.check(["https://www.fravega.com/p/x-22755673/"]) == {"https://www.fravega.com/p/x-22755673/": "unknown"}


def test_check_is_off_in_github_actions(monkeypatch):
    """En GitHub Actions no se abre ninguna ficha (Frávega bloquea a GitHub): no se descarta nada."""
    monkeypatch.setenv("FRAVEGA_CHECK", "1")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert not fc.enabled()
    assert fc.check(["https://www.fravega.com/p/x-22755673/"]) == {"https://www.fravega.com/p/x-22755673/": "unknown"}
