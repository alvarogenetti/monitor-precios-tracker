"""Sincroniza data/prices.db con la rama `data` del repo, sin inflar el historial de git.

La rama `data` tiene UN solo commit (sin padre) con `prices.db` en la raíz. Cada publicación lo
reemplaza con push --force-with-lease, así git no acumula una copia de la base por corrida (el
historial de precios vive adentro de la base, no en git).

Si otro proceso publicó en el medio (GitHub Actions vs. el escaneo local de tu PC), el lease falla:
se baja la base remota, se le FUSIONAN las filas nuevas de la local y se reintenta.

    python -m services.datastore pull     # baja la base de la rama data (si existe)
    python -m services.datastore push     # publica la base local en la rama data
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BRANCH = "data"
FILE = "prices.db"
log = logging.getLogger("datastore")

BOT_ENV = {
    "GIT_AUTHOR_NAME": "price-watch-bot",
    "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
}
BOT_ENV |= {"GIT_COMMITTER_NAME": BOT_ENV["GIT_AUTHOR_NAME"],
            "GIT_COMMITTER_EMAIL": BOT_ENV["GIT_AUTHOR_EMAIL"]}


def git(*args: str, input: bytes | None = None, check: bool = True, env: dict | None = None) -> bytes:
    r = subprocess.run(["git", *args], input=input, capture_output=True,
                       env={**os.environ, **(env or {})})
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def remote_sha() -> str | None:
    """SHA actual de origin/data, o None si la rama todavía no existe."""
    out = git("ls-remote", "origin", f"refs/heads/{BRANCH}").decode().split()
    return out[0] if out else None


def fetch_db(dest: Path) -> str | None:
    """Baja prices.db de la rama data a `dest`. Devuelve el SHA bajado (None si no hay rama)."""
    sha = remote_sha()
    if not sha:
        return None
    git("fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{BRANCH}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(git("cat-file", "blob", f"{sha}:{FILE}"))  # binario, sin pasar por la consola
    return sha


def _sha_file(db: Path) -> Path:
    return db.with_name(".data_sha")


def pull(db: Path) -> str | None:
    sha = fetch_db(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    _sha_file(db).write_text(sha or "", encoding="utf-8")
    log.info("Base bajada de la rama %s (%s)", BRANCH, sha[:7] if sha else "rama nueva")
    return sha


def push(db: Path, message: str | None = None, attempts: int = 3) -> str:
    from services.db import Database

    expected = _sha_file(db).read_text(encoding="utf-8").strip() if _sha_file(db).exists() else ""
    message = message or f"snapshot de precios {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
    for attempt in range(1, attempts + 1):
        Database(db).compact()
        blob = git("hash-object", "-w", str(db)).decode().strip()
        tree = git("mktree", input=f"100644 blob {blob}\t{FILE}\n".encode()).decode().strip()
        commit = git("commit-tree", tree, "-m", message, env=BOT_ENV).decode().strip()
        r = subprocess.run(["git", "push", "--quiet", f"--force-with-lease=refs/heads/{BRANCH}:{expected}",
                            "origin", f"{commit}:refs/heads/{BRANCH}"], capture_output=True)
        if r.returncode == 0:
            _sha_file(db).write_text(commit, encoding="utf-8")
            log.info("Base publicada en la rama %s (%s)", BRANCH, commit[:7])
            return commit
        # Alguien publicó en el medio: fusionamos nuestras filas sobre la base remota y reintentamos
        log.warning("Push rechazado (intento %d): %s", attempt, r.stderr.decode(errors="replace").strip())
        with tempfile.TemporaryDirectory() as tmp:
            remote = Path(tmp) / FILE
            expected = fetch_db(remote) or ""
            merged = Database(remote)
            n = merged.merge_from(db)
            log.info("Fusionadas %d filas locales sobre la base remota", n)
            del merged
            db.write_bytes(remote.read_bytes())
    raise RuntimeError("No se pudo publicar la base después de varios intentos")


def main() -> int:
    from settings import settings, setup_logging

    setup_logging()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        pull(settings.db_path)
    elif cmd == "push":
        push(settings.db_path)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
