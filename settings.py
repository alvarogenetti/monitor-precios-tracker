"""Configuración central leída de variables de entorno / .env."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name) or default)
    return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class Settings:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    # Mercado Libre (API oficial): app propia en developers.mercadolibre.com.ar
    meli_client_id: str = os.getenv("ML_CLIENT_ID", "").strip()
    meli_client_secret: str = os.getenv("ML_CLIENT_SECRET", "").strip()
    meli_redirect_uri: str = os.getenv(
        "ML_REDIRECT_URI", "https://github.com/alvarogenetti/monitor-precios-tracker").strip()
    meli_token_path: Path = _path("ML_TOKEN_PATH", "data/meli_token.enc")
    # Alertas: baja mínima (%) para avisar, y tope de cordura respecto del rango "alto"
    alert_min_drop_pct: float = _float("ALERT_MIN_DROP_PCT", 1.0)
    alert_max_over_high: float = _float("ALERT_MAX_OVER_HIGH", 1.5)
    # false = sólo ofertas reales (>= 15 % vs mercado); true = también cada baja >= ALERT_MIN_DROP_PCT
    alert_price_drops: bool = os.getenv("ALERT_PRICE_DROPS", "false").strip().lower() in ("1", "true", "yes", "si")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(_float("PORT", 8000))
    scheduler_enabled: bool = _bool("SCHEDULER_ENABLED", False)
    scan_interval_minutes: int = int(_float("SCAN_INTERVAL_MINUTES", 180))
    headless: bool = _bool("HEADLESS", True)
    block_stylesheets: bool = _bool("BLOCK_STYLESHEETS", True)
    delay_min: float = _float("SCAN_DELAY_MIN", 2)
    delay_max: float = _float("SCAN_DELAY_MAX", 5)
    retries: int = int(_float("SCRAPE_RETRIES", 3))
    page_timeout_ms: int = int(_float("PAGE_TIMEOUT_MS", 45000))
    db_path: Path = _path("DB_PATH", "data/prices.db")
    targets_path: Path = _path("TARGETS_PATH", "config/targets.json")
    discovery_path: Path = _path("DISCOVERY_PATH", "config/discovery.json")
    specs_path: Path = _path("SPECS_PATH", "config/specs.json")
    overrides_path: Path = _path("OVERRIDES_PATH", "config/overrides.json")

    @property
    def meli_enabled(self) -> bool:
        # Mercado Libre bloqueó el acceso de desarrollador el 23/11/2026 (app de sólo lectura).
        # No se llama más a su API ni a su web: ML queda como links + carga manual (ver README).
        return False

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


settings = Settings()


def setup_logging(verbose: bool = False) -> None:
    # La consola de Windows (cp1252) no soporta emojis/flechas: forzamos UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Playwright/httpx/apscheduler son muy verbosos en DEBUG
    for noisy in ("asyncio", "httpx", "httpcore", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
