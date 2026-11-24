"""Outlet / usado / reacondicionado: se muestran marcados, pero el precio y el "cumple" salen de los nuevos."""
from scrapers.base import is_used, matches_keywords
from services.discovery import Offer, evaluate

SPEC = {"resolution": "2560x1440", "panel": "IPS", "refresh_hz": 180, "anti_glare": True, "vesa": "100x100",
        "weight_no_stand_kg": 4, "hdmi_ports": 2, "psu_voltage": "100-240V", "flat": True}
CFG = {"requirements": {"size_in": 27, "min_hz": 120, "max_weight_kg": 8}}
OUTLET = 'Monitor Gamer Asus 27" Tuf Vg27aql3a-j Qhd 180hz 1ms 2k (OUTLET)'
NEW = 'Monitor Asus TUF VG27AQL3A 27" QHD 180Hz IPS'


def test_is_used():
    assert is_used(OUTLET)
    assert is_used("Monitor Samsung usado") and is_used("Monitor en exhibición")
    assert is_used("Monitor con 2 píxeles quemados") and is_used("Monitor Reacondicionado")
    assert not is_used(NEW) and not is_used("Monitor Outletcito")


def test_best_price_ignores_outlet():
    offers = [Offer("armytech", OUTLET, 300000, "https://a/1"), Offer("nickhard", NEW, 450000, "https://b/2")]
    r = evaluate(offers, "VG27AQL3A", "VG27AQL3A", SPEC, CFG)
    assert r.best["price"] == 450000 and r.status != "descartado"
    assert any(o["used"] for o in r.offers)                 # sigue visible, marcada
    assert any("outlet/usado" in w and "300.000" in w for w in r.warnings)


def test_only_outlet_is_discarded():
    r = evaluate([Offer("armytech", OUTLET, 300000, "https://a/1")], "VG27AQL3A", "VG27AQL3A", SPEC, CFG)
    assert r.status == "descartado" and "sólo outlet/usado" in r.fails


def test_accept_used_switch():
    cfg = {"requirements": {**CFG["requirements"], "accept_used": True}}
    offers = [Offer("armytech", OUTLET, 300000, "https://a/1"), Offer("nickhard", NEW, 450000, "https://b/2")]
    assert evaluate(offers, "VG27AQL3A", "VG27AQL3A", SPEC, cfg).best["price"] == 300000


def test_tracked_never_take_outlet():
    assert not matches_keywords(OUTLET, ["VG27AQL3A"])
    assert matches_keywords(NEW, ["VG27AQL3A"])
