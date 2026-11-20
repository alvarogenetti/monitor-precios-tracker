from services.spec_enrich import attrs_to_spec, merge

ATTRS = {"PANEL_TYPE": "IPS", "IS_CURVED": "No", "DISPLAY_RESOLUTION": "2560 px x 1440 px",
         "MAX_REFRESH_RATE": "180 Hz", "IS_ANTI_GLARE": "Sí", "BRIGHTNESS": "300 cd/m²",
         "WITH_FLICKER_FREE": "Sí", "WITH_VESA_MOUNTING": "Sí", "WEIGHT_WITHOUT_STAND": "4.36 kg",
         "VOLTAGE": "220V"}


def test_attrs_to_spec():
    s = attrs_to_spec(ATTRS, "MLA41804944")
    assert s["flat"] is True and s["anti_glare"] is True and s["resolution"] == "2560x1440"
    assert (s["hz_dp"], s["brightness_nits"], s["weight_no_stand_kg"]) == (180, 300, 4.36)
    assert s["vesa"].startswith("sí")


def test_merge_curated_wins():
    curated = {"model_key": "X", "anti_glare": None, "vesa": "75x75", "weight_no_stand_kg": None}
    m = merge(curated, attrs_to_spec(ATTRS, "MLA1"))
    assert m["vesa"] == "75x75"                 # lo curado no se pisa
    assert m["anti_glare"] is True and m["weight_no_stand_kg"] == 4.36
    assert "Completado con el catálogo de ML" in m["notes"]
    assert merge(None, {"anti_glare": True})["confidence"] == "ML"
