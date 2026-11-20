import pytest

from services.price_parser import extract_prices, is_plausible, parse_ars


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$ 340.869,00", 340869.0),
        ("$339.785", 339785.0),
        ("ARS 418.299", 418299.0),
        ("ars 418.299", 418299.0),
        ("$\xa0465.103", 465103.0),
        ("340869.00", 340869.0),
        ("340869", 340869.0),
        ("1.234.567", 1234567.0),
        ("1.234.567,50", 1234567.5),
        ("1,234,567.50", 1234567.5),
        ("$ 340 869", 340869.0),
        ("Precio especial: $ 627.763 transferencia", 627763.0),
        (340869, 340869.0),
        (340869.5, 340869.5),
        ("12,5", 12.5),
    ],
)
def test_parse_ars(raw, expected):
    assert parse_ars(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "Sin stock", "$", 0, -5, True])
def test_parse_ars_none(raw):
    assert parse_ars(raw) is None


def test_extract_prices_skips_small_numbers():
    text = "$ 784.700- $ 156.937\n$ 627.763 · 12 cuotas de $ 65.394"
    assert extract_prices(text) == [784700.0, 156937.0, 627763.0, 65394.0]
    assert extract_prices("Hasta 12 cuotas sin interés") == []


def test_is_plausible():
    assert is_plausible(335000)
    assert not is_plausible(12)
    assert not is_plausible(None)
