"""Alertas por Telegram Bot API (opcional)."""
from __future__ import annotations

import logging

import httpx

from settings import settings

log = logging.getLogger(__name__)


async def send_telegram(text: str) -> bool:
    """Envía un mensaje HTML. Devuelve True si se envió; False si no está configurado o falló."""
    if not settings.telegram_enabled:
        log.info("[alerta sin Telegram] %s", text.replace("\n", " | "))
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload)
        if r.status_code == 200 and r.json().get("ok"):
            return True
        log.error("Telegram respondió %s: %s", r.status_code, r.text[:300])
    except httpx.HTTPError as e:
        log.error("No se pudo enviar a Telegram: %s", e)
    return False
