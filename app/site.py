"""Genera la versión pública (estática, de sólo lectura) del dashboard para GitHub Pages.

    python -m app.site            # escribe site/index.html
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.main import STATUS_LABELS, BANDS, build_dashboard, db, templates
from services.events import active_event
from settings import settings, setup_logging


class _Req:
    """Jinja2Templates pide un request; para el render estático alcanza con esto."""
    url = "/"


def build(out_dir: Path) -> Path:
    tpl = templates.get_template("index.html")
    html = tpl.render(
        request=_Req(), static=True,
        rows=build_dashboard(), state={"running": False}, last_run=db.last_run(),
        alerts=db.recent_alerts(10), telegram=settings.telegram_enabled,
        scheduler=True, interval=180, bands=BANDS, event=active_event(),
        discovery=db.last_discovery(), status_labels=STATUS_LABELS,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return out_dir / "index.html"


if __name__ == "__main__":
    setup_logging()
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else settings.db_path.parent.parent / "site")
    print(f"Sitio generado en {out}")
