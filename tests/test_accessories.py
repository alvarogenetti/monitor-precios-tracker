"""Accesorios que dicen "monitor" en el título (transformadores, soportes, cables...) no son monitores."""
import pytest

from services.discovery import ACCESSORY_RE, Offer, SpecCatalog, _lower, analyze

CFG = {"requirements": {"size_in": 27, "min_hz": 120}}


@pytest.mark.parametrize("title", [
    "TRANSFORMADOR MONITOR ALTERNATIVO 14V 4A 56W SAMSUNG",
    "ADAPTADOR CARGADOR 5.5X2.5MM A 6.5X4.4MM MONITORES LG SONY SAMSUNG",
    "FUENTE PARA MONITOR - 19V 2AH - PLUG OUT 6.5MM X IN 4.4MM - PROBATTERY",
    "Soporte Monitor Escritorio De 13 A 27 Brazo Mesa Articulado",
    "SOPORTE ADAPTADOR INTELAID PARA MONITOR SIN VESA 13/27 IT-DSX",
    "Combo ASUS Phoenix GeForce GT 1030 OC Edition 2 GB + Monitor Curvo ASUS TUF",
    "PC Ecovision Intel I5 12400 + 8 GB + 256 GB + Monitor 19",
    "Bafle Monitor x 2 Apogee Studio 6 Activo 6",
    "Monitores Estudio Kolt Mk4 Bluetooth Activo 30w Home Studio KOLT",
    "Cable Vga Noga 2mts Pc Monitor Notebook",
])
def test_accessories_are_filtered(title):
    assert ACCESSORY_RE.search(_lower(title))


@pytest.mark.parametrize("title", [
    'Monitor Samsung 27" QHD con panel IPS ViewFinity S6',
    'Monitor Gamer LG UltraGear 27GS75Q-B 27" QHD 180Hz',
    'Monitor Gamer Asus TUF VG27AQL3A 27" QHD 180Hz IPS',
    'Monitor Gamer Level Up 27 1440p 180Hz Altura regulable y giro 90',
    'Monitor Philips 27" con base ajustable',
])
def test_monitors_are_kept(title):
    assert not ACCESSORY_RE.search(_lower(title))


def test_charger_does_not_join_samsung_monitor():
    offers = [Offer("westsolution", "TRANSFORMADOR MONITOR 14V 3A 6.5X4.4MM 42W SAMSUNG", 59000, "https://w/1"),
              Offer("carrefour", 'Monitor Samsung 27" QHD con panel IPS ViewFinity S6', 1299999, "https://c/1")]
    results = analyze(offers, CFG, SpecCatalog([]))
    assert all(o["price"] > 100000 for r in results for o in r.offers)
