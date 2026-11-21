# Monitor de precios de monitores (Argentina)

Sigue precio y stock de monitores **27" QHD IPS mate** en ~60 tiendas argentinas, detecta
**ofertas reales** (descuento contra el precio de mercado, no contra el "precio de lista") y avisa
por **Telegram**. Corre solo en GitHub Actions y publica un dashboard.

- **Dashboard público:** https://alvarogenetti.github.io/monitor-precios-tracker/
- **Qué se busca y por qué:** [PERFIL.md](PERFIL.md)

---

## 1. Uso diario

| Qué | Cómo |
|---|---|
| Ver el dashboard desde cualquier lado | El link de GitHub Pages (sólo lectura, se actualiza en cada escaneo) |
| Dashboard completo en tu PC (escanear, confirmar datos, seguir modelos) | `C:\Proyectos\monitor-precios-tracker\iniciar.ps1` |
| Avisos | Telegram: ofertas reales, tu precio de aviso, modelos nuevos que cumplen y resumen diario a las 9 |

**Pestañas del dashboard**

- **📌 Seguidos**: los monitores que elegiste. Se escanean cada ~3 h en cada tienda. Secciones:
  ofertas reales · cumple todo + USB-C · cumple todo · a confirmar · no cumple.
- **🔎 Descubrimiento**: todos los 27" QHD de todas las tiendas, evaluados contra los requisitos,
  una vez por día. Arriba aparecen los **💡 sugeridos para seguir**. Con **+ Seguir** un modelo pasa
  a Seguidos. Los no seguidos igual se vigilan: si aparece una oferta real, avisa.
- **🔔 Alertas** y **ℹ️ Info** (requisitos obligatorios/deseables y en qué tiendas se busca).

**Confirmar o descartar.** Si un modelo dice "A confirmar: acabado mate", podés responder
**¿Pantalla mate? Sí / No** (lo viste en la ficha, en una reseña...). Se guarda en
`config/overrides.json`, se sube solo a GitHub y pisa cualquier otro dato. **Descartar** saca un
modelo de la lista (se puede deshacer).

---

## 2. Cómo decide

### Requisitos (`config/discovery.json`)

27" plano · QHD 2560×1440 · ≥ 120 Hz · IPS (VA no; OLED sólo bajo $650.000) · pantalla mate ·
VESA 75/100 · HDMI. Deseable: USB-C con carga ≥ 65 W. El peso es informativo.

- Lo que dice el **título** (tamaño, resolución, Hz, panel, curvo, usado) se verifica siempre.
  Si el título no dice QHD/2K/1440 o no dice el tamaño, se descarta.
- Lo que el título no dice (mate, VESA, peso, brillo, Hz por HDMI, USB-C) sale de:
  1. **tus confirmaciones** (`config/overrides.json`),
  2. el **catálogo curado** de fichas técnicas (`config/specs.json`, con fuentes),
  3. los **atributos del catálogo de Mercado Libre** (cacheados 30 días). Si un dato de ML
     descalifica, queda "a verificar" en vez de descartar (ML a veces tiene datos mal cargados).
- Estados: ✅ cumple todo · ❔ a confirmar · 🟣 OLED en oferta · ⛔ no cumple.
- Marcas sin reseñas (`generic_brands`): sólo avisan ofertas ≥ 30 %.

### Ofertas reales

- **Precio de mercado** = mediana del mejor precio entre todas las tiendas de los últimos 30 días
  (sin las últimas 24 h). Al principio se usa `market_price` de cada monitor seguido.
- **Descuento real** = cuánto está por debajo de ese mercado: **≥ 15 % buena oferta 💰,
  ≥ 30 % excepcional 🔥**.
- Si la tienda anuncia "-50 %" pero contra el mercado es menos de la mitad → **inflado**.
- La misma oferta no se repite durante 7 días salvo que mejore.

### Eventos (`config/events.json`)

Hot Sale, Cyber Monday, Black Friday...: durante un evento se escanea **cada hora** y las alertas
lo marcan con 🔥.

---

## 3. Arquitectura

```
GitHub Actions (cada 30 min decide si toca)
 ├─ escaneo de seguidos   (si pasaron 2h45 desde el último; 45 min en eventos)
 ├─ descubrimiento + resumen diario (primera corrida desde las 9 AR)
 ├─ publica la base en la rama `data`  (un único commit que se reemplaza)
 └─ publica el dashboard en GitHub Pages

Tu PC (tarea programada "MonitorPrecios-local", cada 3 h a y media)
 └─ escaneo-local.ps1: Frávega y Venex (bloquean a GitHub) → fusiona y publica en la rama `data`
```

- La base `data/prices.db` **no** está en `main`: vive en la rama `data` (así git no acumula una
  copia por escaneo). `python -m services.datastore pull|push` la sincroniza; si dos procesos
  publican a la vez, se fusionan las filas.
- Secrets del repo: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ML_CLIENT_ID`, `ML_CLIENT_SECRET`.

### Tiendas y adaptadores (`scrapers/stores/`)

| Adaptador | Tiendas | Cómo |
|---|---|---|
| `compragamer` | Compra Gamer | Intercepta el catálogo JSON que descarga la propia SPA (Playwright) |
| `hardgamers` | ~41 tiendas vía HardGamers | Listado de búsqueda (Playwright) |
| `mercadolibre` | Mercado Libre | **API oficial** con app propia: catálogo + publicación nueva más barata de vendedores con reputación |
| `vtex` (`fravega`, `oncity`, `cetrogar`, `carrefour`, `pardo`, `coppel`, `naldo`, `jumbo`, `samsung`) y `electro` (todas juntas) | Electro y Samsung Shop | Buscador JSON público del storefront VTEX (sin navegador) |
| `catalogs` (`dell`, `megatone`) | Dell AR, Megatone | Categoría de monitores leída del HTML (descubrimiento) |
| `generic` | Cualquier ficha (Maximus, Venex...) | JSON-LD, meta tags y heurística de precios |

No se evade ningún control anti-bot: las tiendas que bloquean (ASUS con captcha, Frávega/Venex
desde GitHub) se descartan o se escanean desde la PC. Detalle en la pestaña **Info**.

---

## 4. Instalación desde cero

```powershell
git clone https://github.com/alvarogenetti/monitor-precios-tracker
cd monitor-precios-tracker
copy .env.example .env      # completar Telegram y Mercado Libre
.\iniciar.ps1               # crea el entorno, instala Chromium, baja la base y abre el dashboard
```

**Telegram:** hablale a @BotFather → `/newbot` → token en `TELEGRAM_BOT_TOKEN`; mandale un mensaje
al bot y tomá tu `chat.id` de `https://api.telegram.org/bot<TOKEN>/getUpdates`.

**Mercado Libre:** creá una app en https://developers.mercadolibre.com.ar/devcenter (Redirect URI:
`https://github.com/alvarogenetti/monitor-precios-tracker`) y activá los **permisos funcionales**
de lectura de publicaciones/catálogo (sin eso la API responde 403). App ID y Secret Key van en
`ML_CLIENT_ID` / `ML_CLIENT_SECRET`. Probá con `python scan.py --meli-check`.

**Escaneo local programado** (Frávega y Venex):

```powershell
schtasks /Create /SC HOURLY /MO 3 /ST 00:30 /TN "MonitorPrecios-local" /TR "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\Proyectos\monitor-precios-tracker\escaneo-local.ps1"
```

---

## 5. Referencia

### Configuración

| Archivo | Qué tiene |
|---|---|
| `config/targets.json` | Monitores seguidos: links por tienda, keywords (`"274QF\|275QF"` = alternativas), precio de aviso, `market_price`, `"ci": false` para links que sólo se escanean desde la PC |
| `config/discovery.json` | Requisitos, fuentes del descubrimiento, marcas sin reseñas, OLED máximo |
| `config/specs.json` | Fichas técnicas verificadas por modelo (con fuentes y confianza) |
| `config/overrides.json` | Tus confirmaciones / descartes desde el dashboard |
| `config/events.json` | Fechas de eventos de descuentos |
| `.env` | Credenciales y ajustes (ver `.env.example`) |

### CLI (`scan.py`)

```powershell
python scan.py --once                 # escanea los seguidos
python scan.py --once --only-local    # sólo los links "ci": false (Frávega, Venex)
python scan.py --discover             # descubrimiento
python scan.py --summary              # resumen diario por Telegram
python scan.py --url <URL> --keywords X   # probar una URL sin guardar nada
python scan.py --meli-check           # probar la API de Mercado Libre
python -m app.site site               # generar el dashboard estático
python -m services.datastore pull     # bajar la base de la rama data
```

### API local

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/scan` · `/api/discover` | Escaneo / descubrimiento en segundo plano (409 si ya hay uno) |
| GET | `/api/status` · `/api/dashboard` · `/api/discover` | Estado y datos |
| GET/POST | `/api/targets` | Listar / crear / editar seguidos |
| POST | `/api/targets/{id}/urls` | Pausar, activar o quitar un link |
| POST | `/api/discover/track` | Pasar un modelo descubierto a seguidos |
| POST | `/api/confirm` | Confirmar un dato (`si`/`no`), descartar o deshacer |
| GET | `/api/history/{id}` · `/best` · `.csv` | Historial |

### Estructura

```
app/            FastAPI, dashboard (templates/index.html) y generador estático (site.py)
scrapers/       base Playwright + adaptadores por tienda
services/       tracker (escaneo y alertas), discovery, market (ofertas reales), spec_enrich (ML),
                overrides, datastore (rama data), events, daily, summary, meli_api, notifier, db
config/         targets, discovery, specs, overrides, events
tests/          pytest (sin red)
iniciar.ps1     dashboard local · escaneo-local.ps1: tarea programada
```

### Limitaciones

- HardGamers trae ~54 resultados por búsqueda; Megatone sólo los primeros 20 por categoría y Dell
  sólo la primera página desde GitHub.
- El buscador del catálogo de ML es impreciso; algunos modelos no aparecen.
- Los cupones que se cargan en el checkout no se ven.
- Frávega y Venex dependen de que la PC esté prendida.
