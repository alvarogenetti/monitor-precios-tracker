from datetime import datetime, timezone

from services.advice import buy_today, telegram_lines
from services.targets import Target

NOW = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)      # 3 días antes del Black Friday


def r(name, price, usb=False, real=0.0, level=None, kind="monitor", status="cumple"):
    t = Target(id=name, name=name, target_price=1, kind=kind)
    return {"target": t, "best": {"price_cash": price, "store": "tienda", "url": "u"}, "usb_c": "USB-C" if usb else None,
            "eval": {"status": status}, "real": real, "level": level}


def test_espera_si_no_hay_oferta_y_viene_un_evento():
    rows = [r("ASRock", 324000), r("BenQ", 679000, usb=True), r("Brazo", 87000, kind="accesorio"),
            r("Descartado", 100000, status="descartado")]
    models = [{"name": "Genérico", "status": "cumple", "generic": True, "best": {"price": 1, "store": "x"}},
              {"name": "Gigabyte GS27QA", "status": "cumple", "best": {"price": 319000, "store": "zonetech", "url": "z"}}]
    a = buy_today(rows, models, NOW)
    assert a["cheapest"]["name"] == "Gigabyte GS27QA" and not a["cheapest"]["tracked"]
    assert a["usbc"]["name"] == "BenQ" and a["usbc_extra"] == 679000 - 319000
    assert a["action"] == "esperar" and "Faltan 3 días para Black Friday" in a["verdict"]
    assert "Qué compraría hoy" in telegram_lines(a)[0]


def test_compra_si_hay_oferta_real():
    a = buy_today([r("ASRock", 324000), r("MSI", 300000, real=0.22, level="buena")], [], NOW)
    assert a["action"] == "comprar" and "MSI está 22 % debajo del mercado" in a["verdict"]


def test_sin_candidatos():
    assert buy_today([], [], NOW) is None and telegram_lines(None) == []
