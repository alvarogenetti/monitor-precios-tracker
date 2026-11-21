"""Confirmaciones hechas a mano desde el dashboard (config/overrides.json).

Cuando un dato falta o es dudoso ("A confirmar: acabado mate"), podés confirmarlo vos (lo viste en
la ficha del fabricante, en una reseña, en la caja...). Esa confirmación pisa cualquier otro dato
(catálogo curado o Mercado Libre). También se puede **descartar** un modelo.

    {"models": {"27GS75Q": {"anti_glare": true, "vesa": "100x100", "discard": "no me gusta"}}}

Como el archivo es parte de la config del repo, el dashboard local lo commitea y pushea solo, así
GitHub Actions usa las mismas confirmaciones.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)
_lock = threading.Lock()

# Qué se guarda al tocar "sí" / "no" en cada dato a confirmar
FIELDS = {
    "acabado mate": ("anti_glare", True, False),
    "VESA": ("vesa", "100x100", "none"),
    "panel": ("panel", "IPS", "VA"),
    "Hz": ("hz_dp", 144, 60),
    "peso": ("weight_no_stand_kg", 5.0, 9.0),
}


def load(path: Path) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("models", {})
    except FileNotFoundError:
        return {}


def save(path: Path, models: dict[str, dict]) -> None:
    with _lock:
        data = {"_info": "Confirmaciones hechas a mano desde el dashboard: pisan cualquier otro dato.",
                "models": models}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


def apply(spec: dict | None, override: dict | None) -> dict | None:
    """La confirmación manual gana sobre todo lo demás."""
    if not override:
        return spec
    out = dict(spec or {})
    for k, v in override.items():
        out[k] = v
    out["_ml_fields"] = [f for f in out.get("_ml_fields", []) if f not in override]
    out["_manual"] = sorted(k for k in override if k != "discard")
    return out


def set_value(path: Path, key: str, label: str | None, answer: str) -> dict:
    """answer: 'si' / 'no' para un dato, 'discard' para descartar, 'clear' para borrar todo."""
    models = load(path)
    ov = models.get(key, {})
    if answer == "clear":
        models.pop(key, None)
    elif answer == "discard":
        ov["discard"] = label or "descartado a mano"
        models[key] = ov
    else:
        field, yes, no = FIELDS[label]
        ov[field] = yes if answer == "si" else no
        models[key] = ov
    save(path, models)
    return models.get(key, {})


def push_async(repo: Path, files: list[Path], message: str) -> None:
    """Commitea y pushea la config en segundo plano (si falla, queda local y se avisa en el log)."""
    def run() -> None:
        def git(*a: str) -> subprocess.CompletedProcess:
            return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
        try:
            git("add", *[str(f) for f in files])
            if git("diff", "--cached", "--quiet").returncode == 0:
                return
            git("commit", "-m", message, "--", *[str(f) for f in files])
            if git("pull", "--rebase", "--autostash", "--quiet").returncode != 0:
                git("rebase", "--abort")
            r = git("push", "--quiet")
            if r.returncode != 0:
                log.warning("No se pudo pushear la config: %s", r.stderr.strip())
            else:
                log.info("Config pusheada a GitHub: %s", message)
        except Exception as e:  # noqa: BLE001
            log.warning("Sync de config falló: %s", e)
    threading.Thread(target=run, daemon=True, name="config-push").start()
