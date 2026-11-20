# Monitor de precios de monitores (Argentina)

App local en **Python + FastAPI + Playwright + SQLite** que sigue precio y stock de monitores en
tiendas argentinas, guarda historial y avisa por **Telegram** cuando:

- el precio transferencia (`price_cash`) **baja** respecto al último registro válido,
- el precio llega o queda **por debajo del objetivo** (`target_price`), o
- un producto **sin stock vuelve a estar disponible**.

Hay dos modos de ejecución:

| Modo | Comando | Uso |
|---|---|---|
| Web | `python -m app.main` | Dashboard en http://127.0.0.1:8000 con botón "Escanear ahora" y scheduler opcional |
| CLI | `python scan.py --once` | Un escaneo y termina. Sirve para GitHub Actions, el Programador de tareas de Windows o cron |

---

## 1. Instalación

Requiere Python 3.11 o superior.

```powershell
cd monitor
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium       # en Linux/CI: playwright install --with-deps chromium
copy .env.example .env            # Linux/macOS: cp .env.example .env
```

Probalo:

```powershell
python -m pytest -q                       # tests unitarios (sin red)
python scan.py --once --no-alerts         # escaneo real, sin mandar Telegram
python -m app.main                        # dashboard en http://127.0.0.1:8000
```

## 2. Configurar el bot de Telegram (opcional)

Si no lo configurás, todo funciona igual: las alertas quedan en la consola y en la tabla `alerts`.

1. En Telegram hablale a **@BotFather**, mandá `/newbot` y seguí los pasos. Te devuelve un token
   del estilo `123456789:AAH...`. Ese valor va en `TELEGRAM_BOT_TOKEN`.
2. Abrí el chat con tu bot nuevo y mandale cualquier mensaje (por ejemplo `/start`).
3. Para conseguir tu chat id, abrí en el navegador
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y buscá `"chat":{"id": ...}`.
   Ese número va en `TELEGRAM_CHAT_ID`. Para un grupo, agregá el bot al grupo, escribí algo y
   repetí el paso; el id de un grupo empieza con `-`.
4. Completá `.env`:

   ```env
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   TELEGRAM_CHAT_ID=987654321
   ```

## 3. Productos y links (`config/targets.json`)

```json
{
  "id": "lg-27gs75q-b",
  "name": "LG UltraGear 27GS75Q-B",
  "target_price": 410000,
  "price_high": 560000,
  "notes": "Rango relevado en nov-2026: $529-582k",
  "keywords": ["27GS75Q"],
  "urls": [
    {"store": "compragamer", "url": "https://compragamer.com/productos?criterio=27GS75Q"},
    {"store": "hardgamers",  "url": "https://www.hardgamers.com.ar/search?text=27GS75Q"},
    {"store": "maximus",     "url": "https://www.maximus.com.ar/Producto/ITEM=12345/maximus.aspx"}
  ]
}
```

- `target_price` y `price_high` definen el **rango de precio** (ver abajo).
- `keywords`: todas tienen que aparecer en el título para que un resultado cuente. Se usan en
  páginas de **búsqueda** (HardGamers, Compra Gamer, listados de ML). La comparación ignora
  espacios y guiones, así que `27GS75Q` matchea "27GS75Q-B". Con `|` se aceptan alternativas:
  `["MAG", "275QF|274QF"]` sigue los dos modelos de MSI en un mismo producto.
- `exclude` (opcional): palabras que descartan un resultado. Si no lo ponés, se usa
  `usado, reacondicionado, refurbished, open box`.
- `store`: elige el adaptador. Con un nombre sin adaptador propio (`maximus`, `mexx`, `fullh4rd`,
  `fravega`…) se usa el **genérico** y el nombre queda como etiqueta en el dashboard.
- `active: false` pausa un link o un producto sin borrarlo.

También podés agregar productos y links, pausarlos y cambiar el precio objetivo desde el dashboard.
Eso llama a `POST /api/targets` y reescribe el JSON.

### Rangos de precio: Bajo / Normal / Alto

Cada producto clasifica su mejor precio transferencia actual en tres rangos:

| Rango | Condición | Qué significa |
|---|---|---|
| **Bajo · comprá** | precio ≤ `target_price` | Precio de compra recomendado. Dispara la alerta "precio objetivo alcanzado". |
| **Normal** | `target_price` < precio ≤ `price_high` | Precio habitual de mercado. |
| **Alto** | precio > `price_high` | Caro: conviene esperar. |

Si no definís `price_high`, se usa el objetivo + 15 %. Los dos límites se editan desde la tabla del
dashboard. Los valores iniciales salen del relevamiento de precios de noviembre de 2026 (ver `notes`
de cada producto). El rango también aparece en las alertas de baja de precio.

### Historial de precios

Cada escaneo guarda un snapshot por link en `data/prices.db`, con o sin error. En el dashboard:

- la columna **Historial** muestra un minigráfico del mejor precio de cada escaneo, sobre las zonas de rango;
- al desplegar un producto aparece el gráfico grande con mínimo, mediana y máximo, y un botón
  **descargar CSV** con todos los snapshots (`/api/history/<id>.csv`).

### Adaptadores

| Tienda | Qué hace |
|---|---|
| `compragamer` | Compra Gamer es una SPA en Angular. Playwright carga el sitio e **intercepta el catálogo JSON** que descarga la propia SPA, de donde salen `precioEspecial` (transferencia) y `precioLista`. Acepta fichas (`/producto/..._<id>`) o búsquedas (`/productos?criterio=...`). Si el producto no figura en el catálogo, se registra **sin stock**. |
| `hardgamers` | Con una búsqueda trae las ofertas de decenas de tiendas y se queda con la **más barata** que matchee las keywords. En `seller` guarda la tienda (Maximus, Mexx, Full H4rd, etc.). |
| `fravega` | Búsquedas (`/l/?keyword=EW270Q`): el más barato que matchee las keywords, con el vendedor del marketplace en `seller`. Las fichas (`/p/...`) usan el genérico. Frávega no indexa en HardGamers y suele tener LG, Samsung y BenQ. |
| `mercadolibre` | Fichas (`articulo.mercadolibre.com.ar/...`, `/p/MLA...`) y listados (`listado.mercadolibre.com.ar/...`). Mirá la limitación más abajo. |
| `generic` | Cualquier ficha de producto. Busca el precio en JSON-LD, después en meta OpenGraph/itemprop y después en selectores comunes (WooCommerce, Tiendanube, VTEX, Magento, PrestaShop). Del bloque principal toma el **mínimo como precio transferencia** y el **máximo como precio de lista/cuotas**. Ignora valores de cuota, precios sin impuestos y productos relacionados. Se probó con Maximus, Mexx, TryHardware y Slot One. |

Para probar una URL sin tocar la base:

```powershell
python scan.py --url "https://www.mexx.com.ar/productos-rubro/monitores/....html"
python scan.py --url "https://www.hardgamers.com.ar/search?text=EW270Q" --keywords EW270Q
```

### Detalles del mercado argentino

- **Doble precio**: `price_cash` es el precio especial (transferencia o efectivo) y es el que se
  compara contra el objetivo. `price_list` es el precio de lista, tarjeta o cuotas.
- **Formato de montos**: `"$ 340.869,00"`, `"$339.785"` y `"ARS 418.299"` se convierten a
  `float` sin confundir el separador de miles con el decimal (ver `services/price_parser.py`).
- **Stock**: se usa el `availability` de schema.org. Si no está, se buscan carteles como
  "Sin stock", "Agotado", "Pausado" o "Sin disponibilidad" contra botones de compra.
  "Sin stock en el local" no se cuenta como agotado.

## 4. Descubrir modelos que cumplan los requisitos

El botón **🔎 Descubrir** del dashboard (o `python scan.py --discover`) no sigue productos puntuales:
recorre el **catálogo completo de Compra Gamer** y búsquedas amplias de **HardGamers** y **Frávega**
("monitor 27 qhd", "2k", "1440", "wqhd"...), agrupa las ofertas por modelo y evalúa cada uno contra
los requisitos obligatorios de `config/discovery.json`:

| Requisito | De dónde sale |
|---|---|
| 27" plano, QHD 2560×1440, ≥ 120 Hz, IPS (no VA), no curvo, no usado | Título de la publicación |
| Mate antirreflejo, VESA 75/100, peso sin base < 8 kg, al menos un HDMI | `config/specs.json` (fichas verificadas) |
| Brillo ≥ 300 nits, flicker-free, Hz por HDMI, fuente 100-240 V, ficha USA | Advertencias (no descartan) |
| USB-C con PD ≥ 65 W | Insignia (opcional valorado) |

Cada modelo queda en uno de estos estados:

- **Cumple todo**: pasa el título y tiene las specs verificadas en el catálogo.
- **A confirmar**: pasa lo que dice el título, pero falta en `specs.json` algún dato (mate, VESA, peso).
  La columna "Notas" dice qué revisar. Cuando lo confirmes, agregá el modelo a `specs.json` y pasa a "Cumple".
- **OLED en oferta**: los OLED se descartan, salvo que bajen de `oled_max_price` ($650.000 por defecto).
- **Descartado**: falla algún requisito; se muestra el motivo (filtro "Descartado").

Con **+ Seguir** un modelo pasa a la tabla principal con links de búsqueda de Compra Gamer y
HardGamers (y Frávega si lo vende), y un rango inicial (bajo = mejor precio −5 %, alto = +10 %).

La primera corrida es la "línea base". De ahí en más, cuando aparece un modelo **nuevo** que cumple o
podría cumplir, llega una alerta por Telegram. El precio de cada modelo descubierto también queda en
el historial (`discovery_prices`). En GitHub Actions corre una vez por día (12 UTC) o a mano.

## 5. Escaneo automático

### Opción A: GitHub Actions (gratis)

`.github/workflows/price_watch.yml` corre `python scan.py --once` cada 3 horas y commitea
`data/prices.db` con el historial actualizado.

1. Subí **esta carpeta como raíz de un repositorio**. GitHub solo lee workflows desde
   `.github/` en la raíz del repo.
2. En el repo, entrá a *Settings → Secrets and variables → Actions* y creá
   `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
3. En *Settings → Actions → General → Workflow permissions*, elegí "Read and write".
4. Para correrlo a mano: pestaña *Actions → price-watch → Run workflow*.

> El cron de GitHub usa UTC y puede atrasarse varios minutos en horas pico.
> Mercado Libre suele bloquear las IPs de datacenter con más fuerza que una conexión hogareña.

### Opción B: Programador de tareas de Windows

```powershell
schtasks /Create /SC HOURLY /MO 3 /TN "MonitorPrecios" /TR "\"C:\ruta\monitor\.venv\Scripts\python.exe\" \"C:\ruta\monitor\scan.py\" --once"
```

Las rutas son absolutas. `settings.py` resuelve `.env`, `config/` y `data/` relativo al proyecto,
así que no importa desde qué carpeta se lance.

### Opción C: scheduler interno

Con `SCHEDULER_ENABLED=true` en `.env`, `python -m app.main` escanea cada
`SCAN_INTERVAL_MINUTES` (180 por defecto) mientras el servidor esté levantado.

## 6. API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Dashboard |
| POST | `/api/scan` | Lanza un escaneo en segundo plano (202). Si ya hay uno corriendo devuelve 409. Body opcional: `{"target_ids": [...]}` |
| GET | `/api/status` | Estado del escaneo (`running`, `done/total`, `current`) y última corrida |
| GET | `/api/dashboard` | Los datos de la tabla en JSON |
| GET/POST | `/api/targets` | Lista, o crea/edita. Body: `{target_id?, name?, target_price?, price_high?, keywords?, store?, url?, active?}` |
| POST | `/api/targets/{id}/urls` | `{url, active}` pausa o activa un link, `{url, delete: true}` lo quita |
| GET | `/api/history/{id}` | Historial de snapshots de un producto |
| POST | `/api/discover` | Lanza un descubrimiento en segundo plano (202, o 409 si hay un escaneo en curso) |
| GET | `/api/discover` | Resultado del último descubrimiento |
| POST | `/api/discover/track` | `{key}`: pasa un modelo descubierto a seguimiento |
| GET | `/api/history/{id}/best` | Mejor precio de cada escaneo (la curva del gráfico) |
| GET | `/api/history/{id}.csv` | Todos los snapshots en CSV |

## 7. Variables de entorno

Ver `.env.example`. Las principales:

- `HEADLESS`: `false` muestra el navegador, útil para depurar selectores.
- `BLOCK_STYLESHEETS`: bloquea el CSS además de imágenes, fuentes y media. Si una tienda deja de
  funcionar, probá con `false`.
- `SCAN_DELAY_MIN` / `SCAN_DELAY_MAX`: pausa aleatoria entre URLs (2 a 5 s).
- `SCRAPE_RETRIES`: reintentos con backoff exponencial (2 s, 4 s, ... más jitter).

## 8. Estructura

```
app/main.py              FastAPI: dashboard, API y scheduler
app/templates/index.html UI (Tailwind CDN + JS vanilla)
config/targets.json      Productos, precios objetivo y links
config/discovery.json    Requisitos obligatorios y fuentes del descubrimiento
config/specs.json        Specs verificadas por modelo (mate, VESA, peso, brillo, Hz HDMI...)
scrapers/base.py         Playwright: bloqueo de recursos, rotación de UA, reintentos, JSON-LD, stock
scrapers/stores/         compragamer, hardgamers, fravega, mercadolibre, generic
services/price_parser.py Normalizador de montos ARS
services/db.py           SQLite: snapshots, scan_runs, alerts
services/tracker.py      Orquestador secuencial y reglas de alertas
services/discovery.py    Descubrimiento: recolección, agrupado por modelo y evaluación de requisitos
services/notifier.py     Telegram Bot API
scan.py                  CLI
tests/                   pytest (parser, DB, heurísticas, alertas)
```

## Limitaciones conocidas

- **Mercado Libre** suele redirigir a los navegadores automatizados a una verificación anti-bot
  (`/gz/account-verification`). El scraper **no intenta evadirla**: registra el link como
  `bloqueado` y sigue con el resto. Por eso los links de ML vienen con `active: false`. Si desde
  tu conexión funcionan, activalos.
- Los selectores dependen del HTML de cada tienda y pueden romperse cuando lo cambian. El
  adaptador genérico y el fallback por JSON-LD reducen el riesgo, pero conviene revisar los
  errores del dashboard cada tanto.
- Usalo con frecuencias razonables (cada 3 horas está bien) y respetá los términos de cada sitio.
