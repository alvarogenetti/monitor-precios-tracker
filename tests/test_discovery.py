from services.db import Database
from services.discovery import Offer, SpecCatalog, analyze, model_key, title_facts

CFG = {
    "requirements": {"size_in": 27, "min_hz": 120, "vesa": ["75x75", "100x100"],
                     "max_weight_kg": 8, "ideal_brightness_nits": 300, "anti_glare": True},
    "oled_max_price": 650000,
    "max_price": 1500000,
    "exclude_words": ["usado", "reacondicionado"],
}
SPECS = SpecCatalog([
    {"model_key": "PG27QFT1B", "name": "ASRock PG27QFT1B", "panel": "IPS", "flat": True,
     "resolution": "2560x1440", "hz_dp": 180, "hz_hdmi": 144, "anti_glare": True,
     "brightness_nits": 400, "vesa": "100x100", "weight_no_stand_kg": 5.8, "hdmi_ports": 2,
     "psu_voltage": "100-240V", "confidence": "high"},
    {"model_key": "GLOSSY27", "name": "Glossy 27", "panel": "IPS", "anti_glare": False,
     "vesa": "100x100", "weight_no_stand_kg": 5},
    {"model_key": "HEAVY27", "name": "Heavy 27", "panel": "IPS", "anti_glare": True,
     "vesa": "100x100", "weight_no_stand_kg": 8.4},
])


def test_title_facts_real_titles():
    f = title_facts('Monitor Gamer AsRock Phantom Gaming PG27QFT1B 27" QHD IPS 180Hz 1Ms FreeSync Premium')
    assert (f.size, f.res, f.hz, f.panel, f.curved) == (27, "qhd", 180, "IPS", False)
    f = title_facts('MONITOR GAMER KTC 27DQ721 27\\" QHD 2K 1440P HVA 144HZ FREESYNC PREMIUM')
    assert (f.size, f.panel) == (27, "VA")
    f = title_facts("Monitor Gamer AsRock Phantom PG27QRT1B 27\" Curvo 1500R QHD VA 180Hz")
    assert f.curved and f.panel == "VA"
    f = title_facts("MONITOR GAMER ARKHAM 2K 27 PULGADAS QHD IPS 210HZ 0.5MS 144HZ / 180HZ / 200HZ")
    assert (f.size, f.hz) == (27, 210)
    f = title_facts("Monitor Gamer Lenovo Legion 27Q-10 OLED 26.5\" QHD QD-OLED 240Hz")
    assert (f.size, f.panel) == (26.5, "OLED")
    f = title_facts("MONITOR TEROS TE-2754G IPS 2K 200HZ 1MS FICHA USA")
    assert f.us_plug
    f = title_facts("MONITOR 27 GIGABYTE M27U 4K 160HZ")
    assert f.res == "4k"


def test_model_key_prefers_catalog_then_token():
    t = 'Monitor Gamer AsRock Phantom Gaming PG27QFT1B 27" QHD IPS 180Hz'
    assert model_key(t, title_facts(t), SPECS)[0] == "PG27QFT1B"
    t = "MONITOR GAMER 27 ARKHAM 2K QHD 210HZ IPS 0.5MS ARK27210QI8P NEGRO"
    assert model_key(t, title_facts(t), SPECS)[0] == "ARK27210QI8P"
    t = "MONITOR RAPTOR HAWK EYE 27 FRAMELESS IPS QHD (2K) 1MS 200HZ"
    assert model_key(t, title_facts(t), SPECS)[0] == "RAPTOR~200HZ"


def offers(*rows):
    return [Offer(store, title, price, f"https://x/{i}", seller) for i, (store, title, price, seller)
            in enumerate(rows)]


def test_analyze_statuses():
    res = analyze(offers(
        ("compragamer", 'Monitor AsRock PG27QFT1B 27" QHD IPS 180Hz', 321218, None),
        ("hardgamers", "MONITOR ASROCK PG27QFT1B 27 QHD IPS 180HZ", 438290, "BLACK"),
        ("hardgamers", 'MONITOR GAMER ARKHAM 27" 210HZ QHD IPS ARK27210QI8', 285230, "SilverHard"),
        ("compragamer", 'Monitor KTC 27DQ721 27" QHD 1440p HVA 144Hz', 235650, None),
        ("compragamer", 'Monitor Glossy GLOSSY27 27" QHD IPS 180Hz', 300000, None),
        ("compragamer", 'Monitor Heavy HEAVY27 27" QHD IPS 180Hz', 300000, None),
        ("compragamer", 'Monitor Samsung OLED G5 27" QHD QD-OLED 180Hz S27FG500SL', 901500, None),
        ("compragamer", 'Monitor Barato QDX99 OLED 27" QHD 240Hz', 600000, None),
        ("compragamer", 'Monitor Viejo 27" QHD IPS 75Hz MODELO75', 250000, None),
        ("compragamer", 'Monitor ASUS 24" FHD IPS 180Hz VG249Q', 200000, None),
        ("hardgamers", 'MONITOR ASROCK PG27QFT1B 27 QHD IPS 180HZ USADO', 100000, "X"),
    ), CFG, SPECS)
    by = {r.key: r for r in res}
    assert by["PG27QFT1B"].status == "cumple"
    assert by["PG27QFT1B"].best["price"] == 321218       # el usado de $100k se excluye
    assert by["PG27QFT1B"].n_stores == 2
    assert by["ARK27210QI8"].status == "a_confirmar"
    assert set(by["ARK27210QI8"].missing) == {"acabado mate", "VESA", "peso"}
    assert by["27DQ721"].status == "descartado" and "panel VA" in by["27DQ721"].fails
    assert by["GLOSSY27"].status == "descartado"
    assert by["HEAVY27"].status == "descartado"
    assert by["S27FG500SL"].status == "descartado"        # OLED caro
    assert by["QDX99"].status == "oled_oferta"              # OLED barato
    assert by["MODELO75"].status == "descartado"
    assert "VG249Q" not in by                               # 24" FHD: ni se evalúa
    assert res[0].key == "PG27QFT1B"                        # "cumple" primero


def test_discovered_models_tracks_new(tmp_path):
    db = Database(tmp_path / "d.db")
    r1 = analyze(offers(("compragamer", 'Monitor AsRock PG27QFT1B 27" QHD IPS 180Hz', 321218, None)),
                 CFG, SPECS)
    run = db.start_discovery("cli")
    assert not db.has_discovered_models()
    assert db.upsert_discovered(run, r1) == {"PG27QFT1B"}
    run2 = db.start_discovery("cli")
    r2 = analyze(offers(("compragamer", 'Monitor AsRock PG27QFT1B 27" QHD IPS 180Hz', 315000, None),
                        ("compragamer", 'Monitor X ARK27210QI8 27" QHD IPS 210Hz', 290000, None)),
                 CFG, SPECS)
    assert db.upsert_discovered(run2, r2) == {"ARK27210QI8"}
    from dataclasses import asdict
    db.finish_discovery(run2, 2, [asdict(r) for r in r2], [])
    last = db.last_discovery()
    m = next(x for x in last["results"] if x["key"] == "PG27QFT1B")
    assert m["min_price"] == 315000 and len(m["series"]) == 2


def test_brand_hz_fallback_only_without_code_and_compatible_panel():
    cat = SpecCatalog([
        {"model_key": "VH2714", "name": "Valkyrie VH2714", "panel": "IPS", "hz_dp": 200},
        {"model_key": "S27FG500EL", "name": "Samsung Odyssey G5 S27FG500EL", "panel": "IPS", "hz_dp": 180},
        {"model_key": "GS27QA", "name": "Gigabyte GS27QA", "panel": "SS IPS", "hz_dp": 180},
    ])
    def key(t):
        return model_key(t, title_facts(t), cat)[0]
    assert key('MONITOR VALKYRIE 27" QHD 1440P 200HZ 1MS IPS') == "VH2714"
    assert key('Monitor Samsung Odyssey G5 27  Qhd Oled 180hz Black') != "S27FG500EL"
    assert key('MONITOR 27 GIGABYTE GS27FA GAMING IPS 180HZ HDMI') == "GS27FA"
    assert key('MONITOR GAMER GIGABYTE 27" 180HZ QHD 1440P 1MS CURVO VA') != "GS27QA"


def test_discovery_real_offers_with_history(tmp_path):
    import asyncio
    from datetime import datetime, timedelta, timezone
    from services.discovery import _real_offers

    db = Database(tmp_path / "d.db")
    now = datetime.now(timezone.utc)
    with db.connect() as c:                       # 5 días de historia a ~$320k
        for d in range(1, 6):
            c.execute("INSERT INTO discovery_prices (run_id, model_key, price, store, seller, scanned_at)"
                      " VALUES (?,?,?,?,?,?)", (d, "PG27QFT1B", 320000 + d * 1000, "cg", None,
                                                (now - timedelta(days=d)).isoformat()))
            c.execute("INSERT INTO discovery_prices (run_id, model_key, price, store, seller, scanned_at)"
                      " VALUES (?,?,?,?,?,?)", (d, "ARK27210QI8", 290000, "hg", None,
                                                (now - timedelta(days=d)).isoformat()))
    res = analyze(offers(("compragamer", 'Monitor AsRock PG27QFT1B 27" QHD IPS 180Hz', 260000, None),
                         ("hardgamers", 'MONITOR ARKHAM 27" 210HZ QHD IPS ARK27210QI8', 240000, "X")),
                  CFG, SPECS)
    cfg = {**CFG, "generic_brands": ["Arkham"]}
    n = asyncio.run(_real_offers(db, res, [], cfg, send_alerts=False))
    by = {r.key: r for r in res}
    assert by["PG27QFT1B"].level == "buena" and round(by["PG27QFT1B"].real, 2) == 0.20
    assert by["ARK27210QI8"].generic and by["ARK27210QI8"].level is None   # -17 % en genérica: no alcanza
    assert n == 1
    assert asyncio.run(_real_offers(db, res, [], cfg, send_alerts=False)) == 0   # no repite la misma oferta


def test_title_without_variant_suffix_joins_its_variant():
    # Catalogado: "274QPF ... 320HZ" es el 274QPF X32 (única variante con 320 Hz)
    cat = SpecCatalog([{"model_key": "274QPFX32", "name": "MSI MAG 274QPF X32", "hz_dp": 320},
                       {"model_key": "274QPFX24", "name": "MSI MAG 274QPF X24", "hz_dp": 240}])
    t = 'MONITOR 27" MSI MAG 274QPF WQHD 320HZ 0.5MS FLAT 2XHDMI + 1XDP'
    assert model_key(t, title_facts(t), cat)[0] == "274QPFX32"
    t2 = 'MONITOR 27" MSI MAG 274QPF WQHD 144HZ'       # Hz que no coinciden: queda aparte
    assert model_key(t2, title_facts(t2), cat)[0] == "274QPF"
    # Con catálogo, en el mismo descubrimiento: los dos títulos quedan en un solo modelo
    res = analyze(offers(
        ("hardgamers", "MONITOR GAMER MSI 27 RAPID IPS MAG 274QPF X32 WQHD 320HZ", 522920, "Enjoy"),
        ("hardgamers", 'MONITOR 27" MSI MAG 274QPF WQHD 320HZ 0.5MS FLAT', 691148, "BLACK"),
        ("hardgamers", "MONITOR 27 MSI MAG 274QP QD-OLED X24 WQHD 240HZ", 941667, "Crosshair"),
    ), CFG, cat, overrides={})
    assert sorted(r.key for r in res) == ["274QP", "274QPFX32"]
    assert len(next(r for r in res if r.key == "274QPFX32").offers) == 2


def test_merge_variants_without_catalog():
    from services.discovery import _merge_variants

    groups = {"ABC12": [Offer("x", "MONITOR ABC12 27 QHD 200HZ", 1, "")],
              "ABC12M": [Offer("x", "MONITOR ABC12M 27 QHD 200HZ", 1, "")],
              "ABC12X": [Offer("x", "MONITOR ABC12X 27 QHD 144HZ", 1, "")]}
    _merge_variants(groups, {k: k for k in groups}, {})
    assert sorted(groups) == ["ABC12M", "ABC12X"] and len(groups["ABC12M"]) == 2


def test_hyphen_suffix_and_resolution_tokens_are_not_new_models():
    res = analyze(offers(
        ("hardgamers", 'MONITOR GAMER 27" VIEWSONIC CURVO 180HZ 1MS VX2718-2KPC-MHD', 345949, "A"),
        ("hardgamers", "MONITOR 27 CURVO 2KPC VIEWSONIC VX2718 QHD 1440P 180HZ 1MS", 351216, "B"),
        ("hardgamers", 'Monitor Gamer 27" Level Up QHD 2K 2560x1440px IPS 200Hz Blanco', 300000, "C"),
        ("hardgamers", 'MONITOR GAMER 27" LEVEL UP CON ROTACION QHD 200HZ 1MS BLANCO 27-UP6590R', 310000, "D"),
    ), CFG, SpecCatalog([]), overrides={})
    assert sorted(r.key for r in res) == ["27UP6590R", "VX2718"]
    assert all(len(r.offers) == 2 for r in res)


def test_tracked_by_keywords_or_catalog_key():
    from services.discovery import tracked_by
    from services.targets import Target

    t = Target(id="asrock", name="ASRock PG27QFT1B", target_price=1, keywords=["NOEXISTE"])
    brazo = Target(id="brazo", name="Brazo", target_price=1, kind="accesorio", keywords=["PG27QFT1B"])
    offs = [{"title": "Monitor ASRock 27 QHD"}]
    assert tracked_by("PG27QFT1B", offs, [brazo, t], SPECS) == "asrock"   # por clave de catálogo
    assert tracked_by("OTRO", [{"title": "x NOEXISTE"}], [t]) == "asrock"  # por keyword
    assert tracked_by("OTRO", offs, [brazo, t], SPECS) is None


def test_suspicious_pairs_same_hz_only():
    from services.discovery import suspicious_pairs

    class R:
        def __init__(self, key, hz, curved=False):
            self.key, self.facts = key, {"hz": hz, "curved": curved}
    assert suspicious_pairs([R("274QPFX32", 320), R("274QP", 240)]) == []
    assert suspicious_pairs([R("ABC123", 180), R("ABC123W", 180)]) == [("ABC123", "ABC123W")]
