from services import overrides
from services.discovery import Offer, SpecCatalog, analyze

CAT = SpecCatalog([{"model_key": "XY27Q", "name": "Marca XY27Q", "panel": "IPS", "flat": True,
                    "vesa": "100x100", "anti_glare": None}])
CFG = {"requirements": {"min_hz": 120, "vesa": ["75x75", "100x100"], "max_weight_kg": 8,
                        "weight_required": False}, "oled_max_price": 650000}
OFF = [Offer("cg", 'Monitor Marca XY27Q 27" QHD IPS 180Hz', 300000, "u")]


def test_confirm_mate_and_discard(tmp_path):
    path = tmp_path / "ov.json"
    r = analyze(OFF, CFG, CAT, overrides={})[0]
    assert r.status == "a_confirmar" and r.missing == ["acabado mate"]     # el peso ya no es obligatorio

    overrides.set_value(path, "XY27Q", "acabado mate", "si")
    r = analyze(OFF, CFG, CAT, overrides=overrides.load(path))[0]
    assert r.status == "cumple"

    overrides.set_value(path, "XY27Q", "acabado mate", "no")
    assert analyze(OFF, CFG, CAT, overrides=overrides.load(path))[0].status == "descartado"

    overrides.set_value(path, "XY27Q", None, "clear")
    overrides.set_value(path, "XY27Q", "muy caro", "discard")
    r = analyze(OFF, CFG, CAT, overrides=overrides.load(path))[0]
    assert r.status == "descartado" and "descartado a mano: muy caro" in r.fails
