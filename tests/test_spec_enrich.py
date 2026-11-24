from services.spec_enrich import merge

ML_SPEC = {"panel": "IPS", "flat": True, "resolution": "2560x1440", "hz_dp": 180, "anti_glare": True,
           "brightness_nits": 300, "vesa": "sí (medida sin informar)", "weight_no_stand_kg": 4.36,
           "source": "el catálogo de Mercado Libre", "sources": ["https://www.mercadolibre.com.ar/p/MLA1"]}


def test_merge_curated_wins():
    curated = {"model_key": "X", "anti_glare": None, "vesa": "75x75", "weight_no_stand_kg": None}
    m = merge(curated, ML_SPEC)
    assert m["vesa"] == "75x75"                 # lo curado no se pisa
    assert m["anti_glare"] is True and m["weight_no_stand_kg"] == 4.36
    assert "Completado con el catálogo de Mercado Libre" in m["notes"]
    assert merge(None, {"anti_glare": True})["confidence"] == "ML"


def test_ml_disqualifying_data_is_soft():
    from services.discovery import Offer, SpecCatalog, analyze
    cat = SpecCatalog([{"model_key": "M27T6S", "name": "KTC M27T6S", "panel": "IPS", "flat": True,
                        "anti_glare": True, "vesa": "100x100"}])
    cfg = {"requirements": {"min_hz": 120, "vesa": ["75x75", "100x100"], "max_weight_kg": 8},
           "oled_max_price": 650000}
    offs = [Offer("compragamer", 'Monitor KTC M27T6S 27" QHD Fast IPS Mini LED 200Hz', 498550, "u")]
    r = analyze(offs, cfg, cat, {"M27T6S": {"weight_no_stand_kg": 9.0}})[0]
    assert r.status == "a_confirmar"                       # no descartado por un peso dudoso de ML
    assert any("según ML" in w for w in r.warnings)


def test_specs_from_store_text():
    from services.page_specs import page_text, specs_from_text
    html = "<div><h1>Monitor X</h1><script>var a='glossy'</script><p>Pantalla antirreflejo. Montaje VESA 100 x 100 mm.</p></div>"
    assert specs_from_text(page_text(html)) == {"anti_glare": True, "vesa": "100x100"}
    assert specs_from_text("Panel IPS con acabado brillante (glossy)")["anti_glare"] is False
    assert specs_from_text("Compatible con soporte VESA")["vesa"].startswith("sí")
    assert specs_from_text("Monitor sin VESA") == {"vesa": "none"}


def test_combine_ml_and_page():
    from services.spec_enrich import combine
    c = combine({"anti_glare": None, "panel": "IPS", "sources": ["ml"]}, {"anti_glare": True, "vesa": "75x75", "sources": ["p"]})
    assert c["anti_glare"] is True and c["panel"] == "IPS" and c["vesa"] == "75x75"
