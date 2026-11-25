import pytest


@pytest.fixture(autouse=True)
def _sin_navegador_para_fravega(monkeypatch):
    """Los tests nunca abren fichas reales de Frávega (services/fravega_check)."""
    monkeypatch.setenv("FRAVEGA_CHECK", "0")
