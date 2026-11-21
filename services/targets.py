"""Carga/guardado de config/targets.json (fuente de verdad de los productos a seguir)."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

_lock = threading.Lock()


class TargetUrl(BaseModel):
    store: str = "generic"
    url: str
    active: bool = True
    # False = no se escanea en GitHub Actions (tiendas que bloquean IPs de datacenter con 403)
    ci: bool = True
    note: str | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^https?://", v):
            raise ValueError("la URL debe empezar con http:// o https://")
        return v

    @field_validator("store")
    @classmethod
    def _norm_store(cls, v: str) -> str:
        return (v or "generic").strip().lower()


# Si no se define price_high, "Alto" arranca un 15 % arriba del objetivo.
DEFAULT_HIGH_FACTOR = 1.15

BANDS = {
    "bajo": "Bajo · comprá",
    "normal": "Normal",
    "alto": "Alto",
}


class Target(BaseModel):
    id: str
    name: str
    # Precio "Bajo": a este valor o menos conviene comprar (dispara la alerta de objetivo).
    target_price: float = Field(gt=0)
    # Por encima de este valor el precio se considera "Alto". Entre ambos es "Normal".
    price_high: float | None = Field(default=None, gt=0)
    # Precio de mercado inicial (relevamiento). Se usa como referencia hasta tener ~2 días de historia;
    # después manda la mediana real de los últimos 30 días.
    market_price: float | None = Field(default=None, gt=0)
    # Nota libre (de dónde salen los rangos, specs a confirmar, etc.)
    notes: str | None = None
    # Palabras que DEBEN aparecer en el título (para páginas de búsqueda / listados).
    keywords: list[str] = Field(default_factory=list)
    # Palabras que descartan un resultado (si se omite se usan: usado, reacondicionado, ...).
    exclude: list[str] | None = None
    active: bool = True
    urls: list[TargetUrl] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_range(self) -> "Target":
        if self.price_high is not None and self.price_high <= self.target_price:
            raise ValueError("price_high tiene que ser mayor que target_price")
        return self

    @property
    def high(self) -> float:
        return self.price_high or round(self.target_price * DEFAULT_HIGH_FACTOR, -3)

    def band(self, price: float | None, ref: float | None = None) -> str | None:
        """'bajo' (comprá), 'normal' o 'alto'.

        Con precio de referencia de mercado: bajo = descuento real >= 15 % (o <= objetivo manual),
        alto = más de 10 % arriba del mercado. Sin referencia: rangos manuales (objetivo / alto)."""
        if price is None:
            return None
        if price <= self.target_price:
            return "bajo"
        if ref:
            if price <= ref * 0.85:
                return "bajo"
            return "alto" if price > ref * 1.10 else "normal"
        return "alto" if price > self.high else "normal"


class TargetsFile(BaseModel):
    targets: list[Target] = Field(default_factory=list)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "target"


def load_targets(path: Path) -> list[Target]:
    with _lock:
        data = json.loads(path.read_text(encoding="utf-8"))
    return TargetsFile.model_validate(data).targets


def save_targets(path: Path, targets: list[Target]) -> None:
    payload = TargetsFile(targets=targets).model_dump(mode="json", exclude_none=True)
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
