# Monitor de precios de monitores (Argentina)

Sigue precio y stock de monitores **27" QHD IPS mate** en ~75 tiendas argentinas, detecta
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
| Avisos | Telegram: ofertas reales, tu precio de aviso, modelos nuevos que cumplen y resumen diario a las 9. Los avisos de cada escaneo llegan **en un solo mensaje** (ofertas primero); sólo una oferta excepcional (≥ 30 %) sale al instante |

**Qué compraría hoy.** Arriba de Seguidos (y al principio del resumen de Telegram): el monitor más
barato que cumple todo entre seguidos y descubrimiento (marcas conocidas), la opción USB-C más barata
y cuánto más sale, y un veredicto: **comprá** si alguno tiene descuento real ≥ 15 %, si no **esperá**
(con los días que faltan para el próximo evento). Código: `services/advice.py`.

**Pestañas del dashboard**

- **Seguidos**: los monitores que elegiste, escaneados cada ~3 h en cada tienda y agrupados por
  segmento (`segment` en `config/targets.json`, editable desde el dashboard), cada uno con su "por qué":
  **Opciones baratas** · **Un escalón arriba** · **Con USB-C 65 W** · **Gama alta: solo si caen fuerte** ·
  **Accesorios** (el brazo Ironstek FL04A: sólo precio, sin evaluar requisitos).
  Arriba de todo, las ofertas reales del momento.
  Cada seguido suma además las ofertas que el descubrimiento encontró para ese modelo en las
  otras tiendas ("visto en Descubrimiento"): si alguna es más barata, pasa a ser su mejor precio.
- **Descubrimiento**: todos los 27" QHD de todas las tiendas, evaluados contra los requisitos,
  una vez por día (cada ~3 h durante eventos). Arriba aparecen los **💡 sugeridos para seguir**.
  De "falta confirmar" se ven los 6 más baratos (**Ver los N** muestra el resto); los modelos sin
  marca reconocida cuentan como marcas no conocidas. Con **+ Seguir** un modelo pasa
  a Seguidos. Los no seguidos igual se vigilan: si aparece una oferta real, avisa.
- **Alertas** e **Info** (requisitos obligatorios/deseables, en qué tiendas se busca y el **estado
  de las tiendas**: ofertas que trajo cada una en el último descubrimiento, última vez con datos y
  último problema). El resumen diario avisa las tiendas que volvieron vacías o con error.

**Mercado Libre y Tienda BNA: a mano.** Desde el 23/11/2026 no se lee automáticamente (ver
[sección 6](#6-mercado-libre-por-qué-es-manual)). En cada seguido, la fila de Mercado Libre tiene
**Ver en ML** (abre la búsqueda en tu navegador) y **Lo vi a $** para cargar un precio que viste: entra
al análisis como cualquier tienda durante 3 días. En eventos, el resumen de Telegram trae los links.
Lo mismo con **Tienda BNA** (protegida contra bots con Cloudflare, muy fuerte en cuotas durante los
eventos): "En Tienda BNA a $" en la misma fila.

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
  3. los **atributos del catálogo de Mercado Libre** (los guardados hasta el 23/11/2026; ya no se
     consultan) y, si falta algo, el **texto de la ficha de
     la tienda** ("antirreflejo", "VESA 100x100"...; cacheados 30 días). Si uno de estos datos
     descalifica, queda "a verificar" en vez de descartar.
- Un título sin el sufijo de la variante ("274QPF ... 320HZ") se une a la variante catalogada con
  esos Hz ("274QPF X32"), así el mismo monitor no aparece dos veces.
- **Nombre de cada monitor = Marca + Modelo** (`MSI MAG 274QPF X32`, `ViewSonic VX2718`), sin Hz ni
  frases de marketing; sólo si dos modelos distintos quedan iguales se agregan los Hz. El **ID** es el
  código normalizado (`274QPFX32`) y se ve en el detalle.
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

Hot Sale, Cyber Monday, Black Friday...:

- **2 días antes**, el resumen diario manda los **precios de referencia** de cada seguido y se
  congelan: durante el evento las ofertas se miden contra ese precio, así una suba previa no infla
  la referencia.
- **En los 14 días previos**, si una tienda **sube** un precio 10 % o más sobre su precio habitual,
  avisa ("Subió antes de Black Friday"): es la trampa del "50 % OFF".
- **Durante el evento** los seguidos se escanean cada hora y el descubrimiento (las ~75 tiendas) corre
  cada ~3 h (`python -m services.daily discover-due`), además del diario con resumen.
- Hay un ensayo general con las fechas reales del Black Friday 2026 en
  `tests/test_black_friday_dryrun.py` (referencias congeladas, links de ML, escaneo por hora,
  descubrimiento cada 3 h).

### Promos y cuotas

Cada oferta guarda su promo cuando la tienda la informa: **cuotas sin interés** (máximo de cuotas
sin interés en tiendas VTEX y en las del descubrimiento que lo publican), % sobre el precio de lista.

**Cuotas en pesos de hoy.** Con inflación, N cuotas fijas sin interés valen menos que el mismo
precio de contado. Cada oferta con cuotas muestra cuánto vale hoy (valor presente con la inflación
mensual de `config/discovery.json` → `finance.inflation_monthly`, por defecto 2 %; 0 = no descontar).
Si pagar en cuotas en alguna tienda sale menos que la mejor oferta de contado, el detalle del
seguido lo muestra ("En 12 cuotas en Frávega ≈ $598.800 de hoy"), y también "Qué compraría hoy".

### Informe del evento

El primer día después de que termina un evento, el resumen diario trae **"Cómo fue Black Friday"**:
las ofertas reales que hubo (mejor precio de cada seguido contra su referencia congelada), qué
tiendas anunciaban descuentos inflados y cuántas subas hubo en las 2 semanas previas. Una sola vez
por evento (`services/event_report.py`).

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
- Secrets del repo: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (`ML_CLIENT_ID` / `ML_CLIENT_SECRET`
  quedaron sin uso).

### Tiendas y adaptadores (`scrapers/stores/`)

| Adaptador | Tiendas | Cómo |
|---|---|---|
| `compragamer` | Compra Gamer | Intercepta el catálogo JSON que descarga la propia SPA (Playwright) |
| `hardgamers` | ~41 tiendas vía HardGamers | Listado de búsqueda (Playwright) |
| `mercadolibre` | Mercado Libre | **Apagado** (acceso bloqueado por ML): no se llama a su API ni a su web. Sólo links y carga manual |
| `vtex` (`fravega`, `oncity`, `cetrogar`, `carrefour`, `pardo`, `coppel`, `naldo`, `jumbo`, `samsung`, `diamond`, `provincia`) y `electro` (todas juntas) | Electro, Samsung Shop, Diamond Computación y Provincia Compras | Buscador JSON público del storefront VTEX (sin navegador) |
| `catalogs` (`dell`, `megatone`, `mallweb` + plataformas) | Dell AR, Megatone, Mallweb y las de abajo | Listado de monitores leído del HTML (descubrimiento). Tiendanube: cualquier tienda con `"platform": "tiendanube"` y su URL de búsqueda; toma el precio por transferencia |
| `catalogs` · `"platform"` | WooCommerce (Comeros, ISInet, Aura Gamer, Espaciotek, Zonetech, Hardcore, DeCaba), Tiendanube (Nickhard, Shopgamer, Dualkey), Qloud (Electrotics, Gerbio, PC Registrada), PrestaShop (Armytech), TiendaNegocio (Otecno), Shopify | Lector genérico por plataforma: sumar una tienda es agregar `{"store", "platform", "url"}` en `config/discovery.json` |
| `generic` | Cualquier ficha (Maximus, Venex...) | JSON-LD, meta tags y heurística de precios |

No se evade ningún control anti-bot: las tiendas que bloquean (ASUS con captcha, Frávega/Venex
desde GitHub) se descartan o se escanean desde la PC. Detalle en la pestaña **Info**.

---

## 4. Instalación desde cero

```powershell
git clone https://github.com/alvarogenetti/monitor-precios-tracker
cd monitor-precios-tracker
copy .env.example .env      # completar Telegram
.\iniciar.ps1               # crea el entorno, instala Chromium, baja la base y abre el dashboard
```

**Telegram:** hablale a @BotFather → `/newbot` → token en `TELEGRAM_BOT_TOKEN`; mandale un mensaje
al bot y tomá tu `chat.id` de `https://api.telegram.org/bot<TOKEN>/getUpdates`.

**Mercado Libre (histórico, ya no se usa):** creá una app en https://developers.mercadolibre.com.ar/devcenter (Redirect URI:
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
| `config/targets.json` | Monitores seguidos: links por tienda, keywords (`"274QF\|275QF"` = alternativas), precio de aviso, `market_price`, `"ci": false` para links que sólo se escanean desde la PC, `"kind": "accesorio"` para seguir algo que no es un monitor |
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
python scan.py --meli-check           # (histórico) probar la API de Mercado Libre
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
                page_specs (fichas de tiendas), overrides, segments, datastore (rama data),
                events, daily, summary, stores_info, meli_api, notifier, db
config/         targets, discovery, specs, overrides, events
tests/          pytest (sin red); corren en GitHub Actions en cada push (.github/workflows/tests.yml)
iniciar.ps1     dashboard local · escaneo-local.ps1: tarea programada
```

### Limitaciones

- HardGamers trae ~54 resultados por búsqueda; Megatone sólo los primeros 20 por categoría y Dell
  sólo la primera página desde GitHub.
- El buscador del catálogo de ML es impreciso; algunos modelos no aparecen.
- Los cupones que se cargan en el checkout no se ven.
- Frávega y Venex dependen de que la PC esté prendida.

---

## 6. Mercado Libre: por qué es manual

**Qué pasó.** Hasta el 23/11/2026 los precios de ML salían de su API oficial, con una app de
desarrollador propia. Ese día la API empezó a responder `403` a todo lo que da precios
(`/products/{id}/items`, `/items`, `/sites/MLA/search`). La app desapareció del
[devcenter](https://developers.mercadolibre.com.ar/devcenter) y el botón de crear una nueva dice
*"No tenés permiso para crear aplicaciones. Contactá al equipo de OpenPlatform"*: es un bloqueo de
la cuenta de desarrollador, no un error técnico.

**Por qué (lo más probable).** La página
[Bloqueo de aplicaciones](https://developers.mercadolibre.com.ar/es_ar/bloqueo-de-aplicaciones) lista el
motivo `INTEGRATORS_DATA_INFRACTION`: *"cuando se utilicen únicamente datos de lectura, sin consumo de
APIs que generen valor"*. Es nuestro caso: la app sólo leía precios, no publicaba ni vendía. Los
[términos](https://developers.mercadolibre.com.ar/es-ar-terminos-y-condiciones) dicen además que la
API es para facilitar el uso del sitio a los usuarios de la app (cl. 2), que el contenido no puede
publicarse fuera de la app (7.2) y que sacar estadísticas de precios requiere autorización (5.4).
No se pidió la rehabilitación: para un uso sólo de lectura no la van a dar.

**Qué no se hace.** No se lee la web de ML con un programa (los términos prohíben robots y scraping,
cl. 7.6), no se crea otra cuenta o app para esquivar el bloqueo y no se usan proxies. El código quedó
apagado (`settings.meli_enabled` devuelve `False`, el escaneo saltea los links de ML y el adaptador
no cae a la web).

**Qué se hace en cambio.**

1. **Links**: cada seguido y cada modelo del descubrimiento tiene **Ver en ML** (abre la búsqueda en
   tu navegador). Durante un evento y los 2 días previos, el resumen de Telegram trae esos links.
2. **Carga manual**: en el dashboard local, la fila de Mercado Libre tiene **Lo vi a $ · vendedor ·
   link**. Se guarda como un precio más (`promo = "carga manual"`), cuenta para la mejor oferta, el
   descuento real y el historial durante **3 días**, y se publica solo en la rama `data`.
3. **Vendedores**: si cargás un precio de un vendedor que no leemos por su página propia, el
   dashboard avisa para sumarla (en general es más barata que en ML).

**Cuánto se pierde.** Con los datos de la API del 20 al 23/11/2026 (4 monitores, 71 corridas), ML
**nunca** fue la opción más barata: en la mediana estaba **31 % arriba** de la mejor otra tienda
(MSI 274QF X24 +15 %, Gigabyte GS27QA +21 %, KTC M27T6S +31 %). Lo que puede escaparse son ofertas
puntuales de ML (relámpago, tiendas oficiales, eventos): para eso están los links y la carga manual.

