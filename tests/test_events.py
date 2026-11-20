from datetime import datetime, timezone

from services.discovery import ModelResult, new_models_alert
from services.events import active_event, should_run

EV = [{"name": "Cyber Monday", "from": "2026-11-02", "to": "2026-11-04"}]


def test_events_gate():
    inside = datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)      # 14 UTC: no es múltiplo de 3
    outside = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
    assert active_event(inside, EV) == "Cyber Monday"
    assert should_run(inside, EV) is True                          # en evento: cada hora
    assert should_run(outside, EV) is False
    assert should_run(datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc), EV) is True


def _m(name, status, price):
    return ModelResult(key=name, search=name, name=name, brand=None, status=status,
                       best={"price": price, "url": "https://x", "store": "s", "seller": "T"},
                       offers=[], n_stores=1, facts={}, spec=None)


def test_grouped_new_models_alert():
    text = new_models_alert([_m(f"M{i}", "a_confirmar", 400000 + i) for i in range(10)] +
                            [_m("Bueno", "cumple", 500000)])
    assert text.startswith("🆕 <b>11 monitores nuevos")
    assert text.index("Bueno") < text.index("M0")                  # los que cumplen, primero
    assert "…y 3 más" in text
