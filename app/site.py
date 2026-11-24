"""Genera la versión pública (estática, de sólo lectura) del dashboard para GitHub Pages.

    python -m app.site            # escribe site/index.html
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.main import templates
from settings import settings, setup_logging


class _Req:
    """Jinja2Templates pide un request; para el render estático alcanza con esto."""
    url = "/"


def build(out_dir: Path) -> Path:
    import json

    from app.main import build_context, db, series_file

    tpl = templates.get_template("index.html")
    ctx = build_context(static=True)
    html = tpl.render(request=_Req(), **ctx)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    # Historial de cada seguido y modelo: se baja recién al abrir su gráfico (la página no engorda)
    items = [("t", r["target"].id, db.tracked_series(r["target"].id, (r["eval"] or {}).get("key")))
             for r in ctx["rows"]]
    items += [("m", m["key"], db.daily_series("m", m["key"])) for m in ctx["models"]]
    (out_dir / "series").mkdir(parents=True, exist_ok=True)
    for kind, key, data in items:
        (out_dir / series_file(kind, key)).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return out_dir / "index.html"


if __name__ == "__main__":
    setup_logging()
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else settings.db_path.parent.parent / "site")
    print(f"Sitio generado en {out}")
