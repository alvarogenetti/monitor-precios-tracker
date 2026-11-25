# Monitor de precios de monitores (Argentina)

Sigue precio y stock de monitores **27" QHD IPS mate** en ~90 tiendas argentinas, detecta
**ofertas reales** (descuento contra el precio de mercado, no contra el "precio de lista"), recomienda
qué comprar y avisa por **Telegram**. Corre solo en GitHub Actions y publica un dashboard.

- **Dashboard público (sólo lectura):** https://alvarogenetti.github.io/monitor-precios-tracker/
- **Dashboard completo en la PC:** `C:\Proyectos\monitor-precios-tracker\iniciar.ps1`
- **Qué se busca y por qué:** [PERFIL.md](PERFIL.md)

## Índice

1. [Uso diario](#1-uso-diario)
2. [Cómo decide](#2-cómo-decide)
3. [Tiendas](#3-tiendas)
4. [Arquitectura](#4-arquitectura)
5. [Instalación](#5-instalación)
6. [Referencia](#6-referencia)
7. [Mercado Libre: cobertura parcial](#7-mercado-libre-cobertura-parcial)
8. [Decisiones y límites](#8-decisiones-y-límites)

---

## 1. Uso diario

### Telegram

| Mensaje | Cuándo |
|---|---|
| **Resumen diario** | 9 AR. Empieza con **Qué compraría hoy**, después el precio de cada seguido (🟢 oferta · 🔵 normal · 🔴 caro), sugeridos para seguir y tiendas con problemas |
| **Avisos de un escaneo** | Ofertas reales (≥ 15 %), precio de aviso alcanzado, vuelta de stock en oferta y subas antes de eventos, **en un solo mensaje** por escaneo (ofertas primero) |
| **Oferta excepcional** | ≥ 30 % debajo del mercado: sale al instante, sin esperar al final del escaneo |
| **Modelos nuevos** | Un mensaje agrupado cuando el descubrimiento encuentra modelos nuevos que cumplen |
| **Eventos** | 2 días antes: precios de referencia + links de Mercado Libre. Al terminar: **Cómo fue el evento** |

### Dashboard

- **Qué compraría hoy** (arriba de Seguidos): el monitor más barato que cumple todo (seguidos y
  descubrimiento, marcas conocidas), la opción USB-C más barata y cuánto más sale (también en cuotas,
  en pesos de hoy) y un veredicto: **comprá** si alguno tiene descuento real ≥ 15 %, si no **esperá**
  (con los días que faltan para el próximo evento).
- **Seguidos**: los monitores elegidos, por segmento (**Opciones baratas** · **Un escalón arriba** ·
  **Con USB-C 65 W** · **Gama alta: solo si caen fuerte** · **Accesorios**), cada uno con su "por qué".
  Arriba, las ofertas reales del momento. Cada fila suma las ofertas que el descubrimiento vio para
  ese modelo en las otras tiendas ("visto en Descubrimiento"): si alguna es más barata, es su mejor precio.
- **Descubrimiento**: todos los 27" QHD de todas las tiendas, evaluados contra los requisitos.
  Arriba, los **sugeridos para seguir**. De "falta confirmar" se ven los 6 más baratos (**Ver los N**).
  Los que ya seguís no se repiten acá.
- **Historial** (al abrir cualquier seguido o modelo): un punto por día (día de Argentina, valor al
  **cierre**: el último escaneo del día) con el **más barato** (línea
  llena), el **promedio** (rayada) y el **más caro** (punteada) de las ofertas nuevas con stock, más el
  precio de mercado. Períodos **1 semana · 1 mes · 3 meses · 6 meses · 1 año · Todo** (sólo aparecen los
  que ya tienen datos; recuerda el último elegido), mínimo y máximo del período y variación del más
  barato. Los seguidos suman lo que el descubrimiento vio del mismo modelo en las otras tiendas. El
  historial se baja recién al abrir el gráfico (`/api/series/...` en la PC, `series/*.json` en la web).
  Del descubrimiento, más caro y promedio existen desde el 24/11/2026. El minigráfico de la fila usa la
  misma serie (últimos 30 días), así que su último punto es el precio de la fila; lo del descubrimiento
  vale 30 h, como en la fila.
- **Alertas** e **Info** (requisitos, tiendas y **estado de las tiendas**: ofertas que trajo cada una
  en el último descubrimiento, última vez con datos y último problema).

### Acciones (sólo en el dashboard de la PC)

- **Seguir** un modelo del descubrimiento (rechaza los que ya seguís).
- **Confirmar o descartar** un dato: "¿Pantalla mate? Sí / No". Se guarda en `config/overrides.json`,
  se sube solo a GitHub y pisa cualquier otro dato.
- **Lo vi a $** (Mercado Libre) y **En Tienda BNA a $**: carga a mano un precio que viste. Entra al
  análisis como cualquier tienda durante **3 días** y se publica solo. Si el vendedor de ML no tiene su
  página cubierta, avisa para sumarla.
- Cambiar segmento, precio de aviso / "caro desde", agregar, pausar o quitar links.

---

## 2. Cómo decide

### Requisitos (`config/discovery.json`)

27" plano · QHD 2560×1440 · ≥ 120 Hz · IPS (VA no; OLED sólo bajo $650.000) · pantalla mate ·
VESA 75/100 · HDMI. Deseable: USB-C con carga ≥ 65 W. El peso es informativo.

- Lo que dice el **título** (tamaño, resolución, Hz, panel, curvo, usado) se verifica siempre.
  Si el título no dice QHD/2K/1440 o no dice el tamaño, se descarta.
- **Sólo nuevos** (`requirements.accept_used: false`): si el título dice outlet, usado, reacondicionado,
  exhibición, caja abierta o píxeles quemados, la oferta se muestra marcada "outlet/usado · no cuenta",
  pero no es el mejor precio, no entra en la mediana ni en "cumple". Un modelo con sólo ofertas así queda
  ⛔ "sólo outlet/usado". Los seguidos nunca toman esas ofertas. Lo que sólo aparece en la descripción
  (y no en el título) no se detecta: el aviso del modelo lo menciona si hay outlet en otras tiendas.
- Lo que el título no dice (mate, VESA, peso, brillo, Hz por HDMI, USB-C) sale de, en orden:
  1. **tus confirmaciones** (`config/overrides.json`),
  2. el **catálogo curado** de fichas técnicas (`config/specs.json`, con fuentes),
  3. los **atributos del catálogo de Mercado Libre** guardados hasta el 23/11/2026 (ya no se consultan)
     y el **texto de la ficha de la tienda** ("antirreflejo", "VESA 100x100"...; cacheado 30 días).
     Si uno de estos datos descalifica, queda "a verificar" en vez de descartar.
- Estados: ✅ cumple todo · ❔ a confirmar · 🟣 OLED en oferta · ⛔ no cumple.
- Marcas sin reseñas (`generic_brands`) y títulos sin marca reconocida: sólo avisan ofertas ≥ 30 %.

### Un monitor, un nombre, un ID

- **Nombre = Marca + Modelo** (`MSI MAG 274QPF X32`, `ViewSonic VX2718`), sin Hz ni marketing. Si dos
  modelos distintos quedan iguales, se agregan los Hz. Sin código en el título: marca + Hz.
- **ID** = código normalizado (`274QPFX32`), visible en el detalle.
- **Sin duplicados**: un título sin sufijo de variante ("274QPF … 320HZ") se une a la variante con esos
  Hz ("274QPF X32"); los sufijos con guion ("VX2718-2KPC-MHD", "-W") son la misma variante; una
  resolución ("2560x1440px") nunca es un código; un título sin código se une al único modelo de esa
  marca con esos Hz. Un modelo es "nuevo" sólo si ninguna de sus publicaciones estaba en el
  descubrimiento anterior. Cada descubrimiento loguea los posibles duplicados que quedan.

### Ofertas reales

- **Precio de mercado** = mediana del mejor precio entre todas las tiendas de los últimos 30 días
  (sin las últimas 24 h). Al principio se usa `market_price` de cada seguido.
- **Descuento real** = cuánto está por debajo de ese mercado: **≥ 15 % buena oferta, ≥ 30 % excepcional**.
- Si la tienda anuncia "-50 %" pero contra el mercado es menos de la mitad → **inflado**.
- La misma oferta no se repite durante 7 días salvo que mejore. Si la tienda la mira el escaneo de seguidos,
  avisa él y el descubrimiento no la repite.
- **Datos viejos no cuentan**: un precio de hace más de 26 h (p. ej. Frávega con la PC apagada) se
  muestra ("dato de hace N días") pero no compite; un descubrimiento de más de 30 h no se usa para
  recomendar; una carga manual vale 3 días y no mueve el precio de mercado. En el descubrimiento, el
  mercado de cada modelo usa un punto por día (el mínimo), así los eventos no lo distorsionan.

### Cuotas en pesos de hoy

Con inflación, N cuotas fijas sin interés valen menos que el mismo precio de contado. Cada oferta con
cuotas (tiendas VTEX y las del descubrimiento que lo publican) muestra su **valor presente** con la
inflación mensual de `config/discovery.json` → `finance.inflation_monthly` (2 %; 0 = no descontar).
Si en cuotas sale menos que el mejor contado, el seguido lo muestra ("En 12 cuotas en Frávega ≈ $598.800
de hoy") y también "Qué compraría hoy".

### Eventos (`config/events.json`)

- **14 días antes**: si una tienda **sube** un precio ≥ 10 % sobre su precio habitual, avisa
  ("Subió antes de Black Friday"): es la trampa del "50 % OFF".
- **2 días antes**: el resumen manda los **precios de referencia** de cada seguido y los congela;
  durante el evento las ofertas se miden contra ese precio. También trae los links de Mercado Libre.
- **Durante**: seguidos cada hora y descubrimiento cada ~3 h, además del diario con resumen.
- **Después**: el primer resumen trae **Cómo fue el evento** (ofertas reales que hubo, descuentos
  inflados por tienda, subas previas). Una sola vez por evento.
- Ensayo general con las fechas reales del Black Friday 2026: `tests/test_black_friday_dryrun.py`.

---

## 3. Tiendas

| Cómo se leen | Tiendas | Cada cuánto |
|---|---|---|
| Catálogo JSON de la propia SPA (Playwright) | Compra Gamer | Seguidos + descubrimiento |
| Comparador (Playwright) | ~41 tiendas vía HardGamers (Maximus, Mexx, Full H4rd, Gezatek, TryHardware, Slot One, Logg...) | Seguidos + descubrimiento |
| Buscador VTEX (JSON) | Frávega (desde la PC), On City, Cetrogar, Carrefour, Pardo, Coppel, Naldo, Jumbo, Samsung Shop, Diamond Computación, Provincia Compras | Seguidos + descubrimiento |
| WooCommerce (API pública) | Comeros, ISInet, Aura Gamer, Espaciotek, Zonetech, Hardcore Computación, DeCaba, HardLoots, Astro Hard | Descubrimiento |
| Marketplace (API de búsqueda) | Libre Opción (Gears Store, STORE GS, BsAsPC, BitBayres, Hunnox) | Descubrimiento |
| Comparador (JSON público) | Seguimiento Gamer (23 tiendas, casi todas ya cubiertas: sirve de respaldo y su ficha tiene historial) | Descubrimiento |
| Tiendanube (búsqueda, precio por transferencia) | Nickhard, Shopgamer, Dualkey, NG Technologies, West Solution | Descubrimiento |
| Qloud (búsqueda) | Electrotics, Gerbio, PC Registrada, Red Sur, Ultra Computación, City Gadgets, Nova Online, Clanco, 710 Technology, PC Store, Support Oficial, Best Informática, Hunter Gaming | Descubrimiento |
| PrestaShop / TiendaNegocio | Armytech / Otecno | Descubrimiento |
| Categoría en HTML | Dell AR, Megatone, Mallweb | Descubrimiento |
| Ficha directa (genérico) | Venex (desde la PC), Maximus, Electro y Hogar | Seguidos |
| Comparador (fichas de producto en HTML) | **ComparaYa**: **Mercado Libre** (es afiliado de ML) y tiendas que no leemos directo (Portal Store, Gaming City, SCP Hardstore, Net Gaming…) | Descubrimiento |
| **A mano** (link + "Lo vi a $") | **Mercado Libre** (además de ComparaYa), **Tienda BNA** (Cloudflare) | Cuando cargás un precio |

Los comparadores (HardGamers, Seguimiento Gamer, BuscaHard, Precios GG, Historial de Precios, Precialo,
ComparaYa, Libre Opción) se revisaron uno por uno (noviembre 2026): se leen los que lo permiten y sus tiendas útiles
se leen directo. **ComparaYa** es el que trae Mercado Libre: es afiliado de ML (sus links a ML son de
afiliado) y publica en cada ficha el precio de ML junto al de las otras tiendas. Su robots.txt permite
las fichas (`/p/...`) y prohíbe `/api/` (buscador y listados), así que se leen sólo fichas, armando la
dirección `monitor-<marca>-<código>-27` (~60 % aparece así; el resto se fija a mano en
`config/discovery.json → comparaya_slugs`). Se miran los modelos que cumplen o falta confirmar (hasta 80,
una ficha cada 1,5 s) y se toman las ofertas **nuevas** de Mercado Libre y de tiendas cuyo dominio no
leemos directo, sólo si el título tiene el código exacto (la ficha junta "versiones"). Aparecen como
"Tienda (vía ComparaYa)"; las de ML marcadas "Internacional" llevan el aviso de importado.
MejoresCompras sigue como link **Historial** al lado de cada **Ver en ML**.

**Frávega por VTEX** (corregido el 24/11/2026): la API todavía es la de VTEX, pero en vendedores del
marketplace `Price` viene **sin IVA** y el impuesto aparte en `Tax` (p. ej. Acer KG271U de Microglobal:
$394.884 + $82.926 = $477.810, el precio de la web). Se toma siempre `Price + Tax` (en las demás tiendas
VTEX `Tax` es 0), y el % sobre lista se calcula contra ese total. Los monitores seguidos (vendedores Glic
y Ebox) traen `Tax` 0, así que su historial no cambia. Además Frávega dejó VTEX para su web propia: el
link de la API (`/<linkText>/p`) abre una página vacía, y la ficha real es
`https://www.fravega.com/p/<nombre-del-producto>-<itemId>/`, que es lo que se guarda ahora.

Los seguidos se escanean cada ~3 h (cada hora en eventos) y además suman lo que el descubrimiento
(1 vez por día, cada ~3 h en eventos) vio en las demás tiendas.

**Sumar una tienda** de una plataforma conocida es una línea en `config/discovery.json` → `sources`:
`{"store": "nombre", "platform": "woocommerce|tiendanube|qloud|prestashop|tiendanegocio|shopify", "url": "<búsqueda>"}`
(VTEX: agregarla a `VTEX_STORES` en `scrapers/stores/vtex.py`). La pestaña **Info** lista también las
tiendas evaluadas y descartadas (con el motivo) y el estado de cada una.

---

## 4. Arquitectura

```
Despertador externo (cron-job.org, cada 15 min) ─┐   el cron de GitHub solo corre cada 6-12 h
GitHub Actions · price_watch.yml  ◄──────────────┘   (cron cada 30 min + workflow_dispatch auto=true; decide si toca)
 ├─ escaneo de seguidos        si pasaron 2 h 45 desde el último (45 min en eventos)
 ├─ descubrimiento + resumen   primera corrida desde las 9 AR
 ├─ descubrimiento extra       cada ~3 h durante eventos (sin resumen)
 ├─ publica la base en la rama `data` (un único commit que se reemplaza)
 └─ publica el dashboard en GitHub Pages
GitHub Actions · tests.yml     pytest en cada push

Tu PC
 ├─ iniciar.ps1                dashboard completo (baja la base y fusiona lo local sin publicar)
 └─ tarea "MonitorPrecios-local" (cada 3 h): escaneo-local.ps1 → Frávega y Venex (bloquean a GitHub)
```

- La base `data/prices.db` **no** está en `main`: vive en la rama `data`. `python -m services.datastore
  pull|push` la sincroniza; si dos procesos publican a la vez, se fusionan **todas** las tablas
  (escaneos, descubrimientos, referencias de eventos, avisos ya enviados, caché de specs), y un `pull`
  no pisa lo que tenías local sin publicar.
- Cada paso largo del workflow tiene su propio límite de 20 min, así la base siempre se publica.
- **Por qué un despertador externo.** El `schedule` de GitHub es "lo mejor que se pueda": con
  `7,37 * * * *` corrió cada 6 a 12 h (21-25/11/2026: 13 corridas automáticas en 4 días). Un servicio
  de cron gratuito (cron-job.org) llama cada 15 min a la API de GitHub con
  `workflow_dispatch` + `auto=true`; el workflow decide igual que con el cron (2 h 45 / 45 min en
  eventos). Con **Run workflow** a mano (sin `auto`) se fuerza todo: escaneo, descubrimiento y resumen.
  Si el despertador falla, sigue el cron de GitHub como respaldo. Configuración en la sección 5.
- Secrets del repo: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### Código

```
app/main.py          FastAPI: arma el contexto del dashboard (build_context) y la API local
app/site.py          genera el dashboard estático para GitHub Pages
app/templates/       index.html (todo el dashboard)
scrapers/base.py     Playwright, reintentos, keywords
scrapers/stores/     compragamer, hardgamers, vtex, catalogs (Dell, Megatone, Mallweb y plataformas),
                     generic, mercadolibre (apagado: sólo devuelve "manual")
services/tracker.py  escaneo de seguidos, alertas y mensaje agrupado
services/discovery.py descubrimiento: recolección, nombres/IDs, duplicados, evaluación de requisitos
services/market.py   precio de mercado, descuento real, inflados, cuotas en pesos de hoy
services/advice.py   "Qué compraría hoy"
services/summary.py  resumen diario · event_report.py: informe al terminar un evento
services/events.py   eventos y "¿toca escanear?" · daily.py: "¿toca descubrir/resumen?"
services/datastore.py rama `data` · db.py: SQLite · overrides.py: confirmaciones
services/page_specs.py / spec_enrich.py  datos de fichas de tiendas / caché de atributos de ML
services/segments.py · stores_info.py · notifier.py (Telegram) · targets.py · price_parser.py
config/              targets, discovery, specs, overrides, events
tests/               pytest, sin red
```

---

## 5. Instalación

```powershell
git clone https://github.com/alvarogenetti/monitor-precios-tracker
cd monitor-precios-tracker
copy .env.example .env      # completar Telegram
.\iniciar.ps1               # crea el entorno, instala Chromium, baja la base y abre el dashboard
```

**Telegram:** hablale a @BotFather → `/newbot` → token en `TELEGRAM_BOT_TOKEN`; mandale un mensaje
al bot y tomá tu `chat.id` de `https://api.telegram.org/bot<TOKEN>/getUpdates`. En GitHub, los dos
van como secrets del repo.

**Escaneo local programado** (Frávega y Venex):

```powershell
schtasks /Create /SC HOURLY /MO 3 /ST 00:30 /TN "MonitorPrecios-local" /TR "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\Proyectos\monitor-precios-tracker\escaneo-local.ps1"
```

---

## 6. Referencia

### Despertador externo (para que corra cada 45 min en eventos)

1. **Token** (GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token):
   nombre `despertador-monitor`, vencimiento 1 año, *Repository access: Only select repositories* →
   `monitor-precios-tracker`, *Permissions → Repository → Actions: Read and write*. Nada más.
2. **cron-job.org** (cuenta gratis) → *Create cronjob*:
   - URL: `https://api.github.com/repos/alvarogenetti/monitor-precios-tracker/actions/workflows/price_watch.yml/dispatches`
   - Horario: cada 15 minutos.
   - *Advanced* → método `POST`; headers `Accept: application/vnd.github+json`,
     `Authorization: Bearer <token>`, `X-GitHub-Api-Version: 2022-11-28`; body
     `{"ref":"main","inputs":{"auto":"true"}}`.
   - Respuesta esperada: `204`. En Actions aparece una corrida "workflow_dispatch" cada 15 min; la
     mayoría termina en segundos ("no toca") y cada 2 h 45 (45 min en eventos) escanea.
3. El token sólo puede disparar workflows de este repo. Si vence, el cron de GitHub sigue de respaldo.

### Configuración

| Archivo | Qué tiene |
|---|---|
| `config/targets.json` | Seguidos: links por tienda, keywords (`"274QF\|275QF"` = alternativas), precio de aviso, `price_high`, `market_price`, `segment` y `why`, `"ci": false` para links que sólo se escanean desde la PC, `"kind": "accesorio"` para algo que no es un monitor |
| `config/discovery.json` | Requisitos, fuentes del descubrimiento (`sources`), marcas sin reseñas, OLED máximo, `finance.inflation_monthly` |
| `config/specs.json` | Fichas técnicas verificadas por modelo (nombre canónico, `series`, fuentes y confianza) |
| `config/overrides.json` | Tus confirmaciones / descartes desde el dashboard |
| `config/events.json` | Fechas de eventos de descuentos |
| `.env` | Telegram y ajustes (ver `.env.example`) |

### CLI

```powershell
python scan.py --once                 # escanea los seguidos
python scan.py --once --only-local    # sólo los links "ci": false (Frávega, Venex)
python scan.py --discover             # descubrimiento
python scan.py --summary              # resumen diario por Telegram
python scan.py --url <URL> --keywords X   # probar una URL sin guardar nada
python -m app.site site               # generar el dashboard estático
python -m services.datastore pull     # bajar la base de la rama data
python -m services.daily due|discover-due   # ¿toca resumen? / ¿toca descubrimiento extra?
python -m pytest -q                   # tests
```

### API local

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/scan` · `/api/discover` | Escaneo / descubrimiento en segundo plano (409 si ya hay uno) |
| GET | `/api/status` · `/api/dashboard` · `/api/discover` | Estado y datos |
| GET/POST | `/api/targets` | Listar / crear / editar seguidos |
| POST | `/api/targets/{id}/urls` | Pausar, activar o quitar un link |
| POST | `/api/discover/track` | Pasar un modelo descubierto a seguidos (409 si ya lo seguís) |
| POST | `/api/confirm` | Confirmar un dato (`si`/`no`), descartar o deshacer |
| POST | `/api/manual-price` | Carga manual (`store`: `mercadolibre` o `tiendabna`) |
| GET | `/api/series/t/{id}?m={clave}` · `/api/series/m/{clave}` | Historial por día del gráfico (más barato, más caro, promedio) |
| GET | `/api/history/{id}` · `/best` · `.csv` | Historial |

---

## 7. Mercado Libre: cobertura parcial

**En una línea.** ML se contempla, pero no completo: su precio entra solo cuando ComparaYa (afiliado de
ML) lo publica para ese modelo, una vez por día; para el resto quedan los links **Ver en ML** /
**Historial** y la carga manual **Lo vi a $**. En la primera prueba (24/11/2026) ComparaYa tenía ficha
de 26 de los 67 modelos que cumplen o falta confirmar, y precio de ML en **2** (Asus VG27AQL3A
$640.000, LG 27GS75Q-B $867.894; en los dos ML era más caro que la mejor tienda).

| Vía | Qué cubre | Automático |
|---|---|---|
| ComparaYa (sección 3) | Modelos cuya ficha de ComparaYa tiene oferta nueva de ML con el código exacto | Sí, en cada descubrimiento |
| **Lo vi a $** | Lo que veas vos en ML (vale 3 días) | No |
| **Ver en ML** / **Historial** | Búsqueda en ML e historial en MejoresCompras | Sólo links |
| API oficial de ML | Nada: bloqueada desde el 23/11/2026 | — |
| Jina Reader | Nada: ML lo manda a verificación de cuenta (probado 24/11/2026). Plan por si cambia: skill `.claude/skills/ml-via-jina` | — |

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
cl. 7.6), no se crea otra cuenta o app para esquivar el bloqueo y no se usan proxies. El adaptador
(`scrapers/stores/mercadolibre.py`) no hace pedidos y el escaneo de seguidos saltea los links de ML.

**Precios de ML vía ComparaYa (desde el 24/11/2026).** El descubrimiento lee las fichas públicas de
ComparaYa (ver sección 3), que muestra el precio de ML porque es afiliado. Nosotros no tocamos ML: leemos
una página de ComparaYa que su robots.txt permite. Los precios de ML se actualizan una vez por día
(lo que ComparaYa tenga) y aparecen en Seguidos como "Mercado Libre (vía ComparaYa)".

**Qué se hace además.** Links **Ver en ML** y **Historial** (MejoresCompras, que dice usar la API
oficial de ML) en cada seguido y modelo del descubrimiento; los mismos links en el resumen de Telegram
durante eventos; carga manual **Lo vi a $** (3 días); aviso si el vendedor no tiene su página cubierta.

**Intermediarios evaluados (noviembre 2026) y descartados.** Los términos generales de ML (sección 12,
"Uso Automatizado del Sitio") prohíben bots, scrapers y agentes para extraer o almacenar información
"sin importar" la vía, e incluyen expresamente "eludir medidas técnicas de protección". Por eso no se
usan: scrapers con IPs residenciales (Apify, Octoparse), leer ML desde la PC con pausas, ni sitios que
prohíben que los lean (RadarLibre prohíbe el scraping masivo; Precialo, el buscador). Jina Reader se
probó y ML lo bloquea. ComparaYa es distinto: no leemos ML sino páginas de ComparaYa que su robots.txt
permite, y ellos tienen el precio de ML porque son afiliados. ML no ofrece otro canal de datos para
nosotros: su servidor MCP sólo busca en la documentación.

**Cuánto se pierde.** Con los datos de la API del 20 al 23/11/2026 (4 monitores, 71 corridas), ML
**nunca** fue la opción más barata: en la mediana estaba **31 % arriba** de la mejor otra tienda
(MSI 274QF X24 +15 %, Gigabyte GS27QA +21 %, KTC M27T6S +31 %). Lo que puede escaparse son ofertas
puntuales de ML (relámpago, tiendas oficiales, eventos) en modelos que ComparaYa no tiene: para eso
están los links y la carga manual.

---

## 8. Decisiones y límites

**Decisiones**

- **No se evade ningún control anti-bot.** Las tiendas que bloquean (ASUS con captcha, Tienda BNA con
  Cloudflare, Frávega/Venex desde GitHub) se descartan, se escanean desde la PC o quedan a mano.
- **El sitio público es sólo lectura**; las acciones (seguir, confirmar, cargar precios) se hacen
  desde la PC.
- **Ninguna credencial en el repo**: `.env` es local; en GitHub van como secrets.
- Descuentos siempre **contra el mercado**, nunca contra el precio de lista de la tienda.

**Límites conocidos**

- HardGamers trae ~54 resultados por búsqueda; Megatone sólo los primeros 20 por categoría; Dell sólo
  la primera página desde GitHub.
- Los cupones que se cargan en el checkout no se ven.
- Frávega y Venex dependen de que la PC esté prendida.
- Mercado Libre: automático sólo donde ComparaYa lo publica (2 de 67 modelos en la primera prueba);
  el resto, y Tienda BNA, dependen de que cargues a mano lo que ves.
- ComparaYa: sólo se encuentran las fichas cuya dirección sigue el patrón `monitor-marca-codigo-27`
  (26 de 67); las demás se fijan a mano en `comparaya_slugs`.
