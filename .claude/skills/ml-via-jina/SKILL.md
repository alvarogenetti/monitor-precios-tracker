---
name: ml-via-jina
description: Plan pendiente (no implementado) para leer precios de Mercado Libre vía Jina Reader en el tracker. Usar cuando el dueño pida retomar "ML con Jina", "leer ML automático" o volver a probar si ML se puede leer solo.
---

# Mercado Libre vía Jina Reader (pendiente, NO implementado)

Estado al 2026-11-24: **no funciona**. ML redirige a Jina a
`/gz/account-verification` ("Para continuar, ingresá a tu cuenta"), así que no llega ningún precio.
Hoy ML es manual: links **Ver en ML** / **Historial** y carga **Lo vi a $** (README, sección 7).

El dueño decidió que, si algún día vuelve a funcionar, se use. Reglas fijas:
- Sólo los seguidos de `config/targets.json` (~10 fichas), una consulta por ficha cada ~3 h, con pausa de 4 s entre fichas.
- Sin login, sin cookies, sin IPs residenciales, sin reintentos para "pasar" la verificación.
- Si ML pide verificación, se corta ahí y queda la carga manual. No buscar formas de eludirla.

## Paso 0: volver a probar (siempre primero)

```bash
curl -s -m 90 "https://r.jina.ai/https://www.mercadolibre.com.ar/p/MLA74960236" | head -20
curl -s -m 90 -H "X-Return-Format: html" "https://r.jina.ai/https://www.mercadolibre.com.ar/p/MLA74960236" \
  | grep -c -iE 'account-verification|para continuar'
```

- Si `Final URL` dice `account-verification` o el grep da > 0: **sigue bloqueado**. Avisar al dueño y no implementar nada.
- Si aparece el título y un `<script type="application/ld+json">` con `"@type":"Product"` y `offers.price`: seguir.

Clave opcional: `JINA_API_KEY` (gratis en jina.ai) en `.env` y como secret de GitHub. Sube el límite de consultas; no cambia el bloqueo.

## Paso 1: links de catálogo

Cada seguido necesita en `config/targets.json` un link `{"store": "mercadolibre", "url": "https://www.mercadolibre.com.ar/p/MLA..."}`.
Las fichas `/p/MLA` traen JSON-LD; los listados de búsqueda no sirven.

## Paso 2: adaptador `scrapers/stores/mercadolibre.py`

Hoy devuelve `error="Mercado Libre: sólo links y carga manual"` sin hacer pedidos. Reemplazarlo por:
- `JINA = "https://r.jina.ai/"`, `WALL = re.compile(r"account-verification|ingresa a\s+tu cuenta|Para continuar", re.I)`.
- `parse(html, url) -> ScrapeResult`: si `WALL` matchea → `error="ML pidió verificación (no se reintenta)"`.
  Si no, recorrer los `<script ... ld+json>`, buscar `@type == "Product"` y tomar `offers.price` o `offers.lowPrice`
  (`offers` puede ser lista), `in_stock` según `availability` contenga `InStock`, `title=name`.
- `MercadoLibreScraper.scrape`: rechazar URLs sin `/p/MLA`; `httpx.AsyncClient(timeout=60)`, GET `JINA + url` con
  header `X-Return-Format: html` (+ `Authorization: Bearer $JINA_API_KEY` si existe); `asyncio.sleep(4)` antes;
  status ≠ 200 → error. `uses_browser = False`.
- Tests: `parse` con un HTML de ejemplo con JSON-LD, y otro con la página de verificación (debe dar error).

## Paso 3: dejar de saltear ML

- `services/tracker.py`: en el armado de jobs, `and u.store not in ("mercadolibre", "tiendabna")` → `and u.store != "tiendabna"`.
- `app/main.py` `build_dashboard`: hoy anula snapshots de tiendas manuales que no son carga manual fresca.
  Agregar excepción: snapshot de `mercadolibre` sin error y con `_age_hours(scanned_at) <= STALE_HOURS` cuenta como una tienda más.
- `.github/workflows/price_watch.yml`: `JINA_API_KEY: ${{ secrets.JINA_API_KEY }}` en `env:` si se usa clave.

## Paso 4: probar

```powershell
.venv\Scripts\python.exe scan.py --url "https://www.mercadolibre.com.ar/p/MLA74960236"
.venv\Scripts\python.exe scan.py --once --target dell-s2725dc
.venv\Scripts\python.exe -m pytest -q
```

Van a fallar a propósito `tests/test_ml_manual.py::test_ml_scraper_never_reads_the_web` y el chequeo equivalente
del ensayo de Black Friday: adaptarlos a "sólo lee fichas /p/MLA vía Jina y corta ante verificación".

## Paso 5: documentar

README sección 7 (fecha, decisión del dueño, reglas de arriba), fila de Mercado Libre en la tabla de tiendas,
y `services/stores_info.py` (sacar ML de "manuales" y de "Jina descartado").
