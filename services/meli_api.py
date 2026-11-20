"""Mercado Libre por su API oficial (api.mercadolibre.com), en vez de scrapear la web.

La web de ML manda a los navegadores automatizados a una verificación anti-bot, y desde 2025 la
API pública (/sites/MLA/search, /items) responde 403 sin token. La vía legítima es registrar una
aplicación propia en https://developers.mercadolibre.com.ar y llamar a la API con su token.

Autenticación (en este orden):
  1. client_credentials con ML_CLIENT_ID / ML_CLIENT_SECRET (token de la app, sin usuario).
  2. refresh_token: `python scan.py --meli-login` hace una vez el login OAuth con tu cuenta y
     guarda el refresh token CIFRADO en data/meli_token.enc (clave derivada de ML_CLIENT_SECRET).
     ML rota el refresh token en cada uso; el archivo se actualiza y GitHub Actions lo commitea.

Endpoints usados:
  /products/search?site_id=MLA&q=...   productos de catálogo que matchean una búsqueda
  /products/{id}/items                 publicaciones (vendedores) de un producto de catálogo
  /items/{id}                          una publicación puntual
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

API = "https://api.mercadolibre.com"
AUTH_URL = "https://auth.mercadolibre.com.ar/authorization"
log = logging.getLogger(__name__)


class MeliError(Exception):
    pass


class MeliAuthError(MeliError):
    pass


# ------------------------------------------------------------------ token cifrado
def _fernet(secret: str):
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(("meli-token:" + secret).encode()).digest())
    return Fernet(key)


def load_token(path: Path, secret: str) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(_fernet(secret).decrypt(path.read_bytes()))
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo descifrar %s (¿cambió ML_CLIENT_SECRET?): %s", path, e)
        return None


def save_token(path: Path, secret: str, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_fernet(secret).encrypt(json.dumps(data).encode()))


# ------------------------------------------------------------------ cliente
class MeliClient:
    def __init__(self, client_id: str, client_secret: str, token_path: Path,
                 redirect_uri: str = "", timeout: float = 20):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_path = token_path
        self.redirect_uri = redirect_uri
        self._access: str | None = None
        self._expires = 0.0
        self.http = httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        self.mode: str | None = None

    # ---- auth
    def login_url(self) -> str:
        q = {"response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri}
        return f"{AUTH_URL}?{urlencode(q)}"

    def _token_request(self, data: dict) -> dict:
        r = self.http.post(f"{API}/oauth/token", data={
            "client_id": self.client_id, "client_secret": self.client_secret, **data})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200:
            raise MeliAuthError(f"oauth/token {data.get('grant_type')}: HTTP {r.status_code} "
                                f"{body.get('error') or ''} {body.get('message') or r.text[:120]}")
        return body

    def exchange_code(self, code: str) -> dict:
        body = self._token_request({"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": self.redirect_uri})
        self._store(body)
        return body

    def _store(self, body: dict) -> None:
        self._access = body["access_token"]
        self._expires = time.time() + int(body.get("expires_in", 21600)) - 120
        if body.get("refresh_token"):
            save_token(self.token_path, self.client_secret,
                       {"refresh_token": body["refresh_token"], "user_id": body.get("user_id"),
                        "saved_at": int(time.time())})

    def token(self) -> str:
        if self._access and time.time() < self._expires:
            return self._access
        # 1) Token de aplicación
        if self.mode in (None, "client_credentials"):
            try:
                body = self._token_request({"grant_type": "client_credentials"})
                self._access = body["access_token"]
                self._expires = time.time() + int(body.get("expires_in", 21600)) - 120
                self.mode = "client_credentials"
                return self._access
            except MeliAuthError as e:
                log.info("client_credentials no disponible (%s); pruebo refresh_token", e)
        # 2) Refresh token guardado por --meli-login
        saved = load_token(self.token_path, self.client_secret)
        if not saved:
            raise MeliAuthError("Sin token: corré `python scan.py --meli-login` una vez")
        body = self._token_request({"grant_type": "refresh_token",
                                    "refresh_token": saved["refresh_token"]})
        self.mode = "refresh_token"
        self._store(body)  # ML rota el refresh token: hay que guardar el nuevo
        return self._access  # type: ignore[return-value]

    # ---- requests
    def get(self, path: str, **params: Any) -> Any:
        r = self.http.get(f"{API}{path}", params=params,
                          headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code == 401:  # token vencido antes de tiempo
            self._access = None
            r = self.http.get(f"{API}{path}", params=params,
                              headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code != 200:
            raise MeliError(f"GET {path}: HTTP {r.status_code} {r.text[:160]}")
        return r.json()

    def search_products(self, q: str, limit: int = 10) -> list[dict]:
        return self.get("/products/search", status="active", site_id="MLA", q=q,
                        limit=limit).get("results", [])

    def product(self, product_id: str) -> dict:
        return self.get(f"/products/{product_id}")

    def product_items(self, product_id: str, limit: int = 50) -> list[dict]:
        return self.get(f"/products/{product_id}/items", limit=limit).get("results", [])

    def item(self, item_id: str) -> dict:
        return self.get(f"/items/{item_id}")


# ------------------------------------------------------------------ helpers de URLs
PRODUCT_RE = re.compile(r"/p/(MLA\d+)", re.I)
ITEM_RE = re.compile(r"(MLA)-?(\d{6,})", re.I)
USER_PRODUCT_RE = re.compile(r"/up/(MLAU\d+)", re.I)


def classify_url(url: str) -> tuple[str, str | None]:
    """('product', 'MLA123') | ('user_product', 'MLAU..') | ('item', 'MLA123') | ('search', None)."""
    if m := PRODUCT_RE.search(url):
        return "product", m.group(1).upper()
    if m := USER_PRODUCT_RE.search(url):
        return "user_product", m.group(1).upper()
    if "listado." not in url and (m := ITEM_RE.search(url)):
        return "item", f"MLA{m.group(2)}"
    return "search", None


def best_offer(items: list[dict]) -> dict | None:
    """La publicación nueva más barata (si no hay nuevas, la más barata)."""
    priced = [i for i in items if isinstance(i.get("price"), (int, float)) and i["price"] > 0]
    new = [i for i in priced if (i.get("condition") or "new") == "new"]
    pool = new or priced
    return min(pool, key=lambda i: i["price"]) if pool else None
