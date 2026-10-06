# Contexto del proyecto: Monitor de mercado Wallapop (DS / Pokémon retro)

Este documento resume el estado y las decisiones de diseño tomadas hasta
ahora, para que puedas seguir trabajando en este proyecto sin tener que
redescubrirlas leyendo el código desde cero.

## Qué es esto

Un sistema para detectar y analizar anuncios de hardware/juegos
retro de Nintendo DS (consolas, Pokémon, RPGs de culto como Castlevania,
Dragon Quest, Zelda DS) en Wallapop. Tiene tres piezas independientes:

1. **`wallapop_watcher.py`** — scraper que corre indefinidamente,
   escanea ~30 keywords en DOS fuentes (Wallapop y Vinted), notifica
   anuncios nuevos por Telegram, y guarda histórico en
   `wallapop_data.jsonl` (nombre heredado; ahora contiene ambas fuentes).
2. **`market_server.py`** — servidor HTTP en Python puro (sin
   frameworks) que sirve esos datos y persiste exclusiones manuales del
   usuario en `exclusions.json`.
3. **`market_dashboard/`** — proyecto React + Vite, la interfaz visual
   de análisis de mercado.

## Estructura de carpetas esperada

```
proyecto/
├── wallapop_watcher.py
├── market_server.py
├── wallapop_data.jsonl       (generado por el watcher)
├── exclusions.json           (generado por market_server.py)
└── market_dashboard/
    ├── package.json
    ├── src/
    └── dist/                 (generado con "npm run build")
```

`market_server.py` espera que `market_dashboard/` sea su carpeta
hermana directa. Es configurable con la variable de entorno
`DASHBOARD_DIST` si se necesita otra ubicación.

## Decisiones de diseño importantes (y por qué)

### 1. Arquitectura del watcher: 1 browser + 1 context + N páginas

El watcher usa `async_playwright` (no `sync_playwright`, no threads)
con **un solo proceso de Chromium**, **un solo `BrowserContext`**, y
una `Page` por keyword dentro de ese mismo context. Se llegó a esta
arquitectura después de probar alternativas más pesadas:
- Empezamos con 1 navegador completo por keyword (threads) → consumía
  demasiada RAM (~24-38 procesos de Chromium).
- Migramos a 1 browser + 1 context + N páginas → mucho más ligero,
  las páginas son baratas comparado con browsers/contexts.

`headless=True` está activado. Para evitar que Wallapop detecte
headless y bloquee las peticiones (esto pasó realmente y se diagnosticó
en esta conversación), se aplican estos contramedidas:
- `--disable-blink-features=AutomationControlled` al lanzar Chromium.
- Override de `navigator.webdriver` a `undefined` vía
  `context.add_init_script`.
- User-Agent real de Chrome de escritorio (no el UA por defecto de
  Playwright headless).
- `locale`, `timezone_id`, `viewport` configurados explícitamente.
- `wait_until="networkidle"` en `goto()` y `reload()`.

Si en el futuro Wallapop vuelve a bloquear en headless, estas son las
primeras cosas a revisar/reforzar.

### 1b. Dos fuentes: Wallapop + Vinted (una sola arquitectura)

El watcher escanea el MISMO conjunto de búsquedas (`SEARCHES`) en dos
marketplaces: Wallapop y Vinted. Ambas fuentes reutilizan el mismo
navegador/context de Playwright (misma medida anti-headless, mismas
páginas baratas). En `main()` se lanza una tarea `watch_search(context,
search_term, source)` por cada combinación (fuente × búsqueda).

Piezas clave:
- **Normalización a formato común**: `normalize_wallapop_item()` y
  `normalize_vinted_item()` convierten los items crudos de cada API a un
  dict con SIEMPRE las mismas claves (`item_id, title, price, currency,
  created (datetime|None), url, source`). A partir de ahí `process_items`
  es agnóstico de la fuente. Si añades una tercera fuente, el patrón es:
  un `fetch_all_items_<x>` + un `normalize_<x>_item` + añadirla a
  `ENABLED_SOURCES`/`SOURCE_LABELS`, sin tocar `process_items`.
- **Fetch de Vinted (VERIFICADO EN VIVO, reescrito)**: Vinted renderiza
  los resultados EN EL SERVIDOR — al cargar `/catalog` NO se dispara
  ningún XHR a `/api/v2/catalog/items` (solo banners/promoted_closets).
  La versión original esperaba ese XHR con `expect_response`, hacía
  timeout de 30s en cada ciclo y Vinted devolvía 0 items siempre (ese
  era el bug de "Vinted no funciona"). Ahora `fetch_all_items_vinted()`
  carga `/catalog` SOLO para sembrar cookies (`anon_id`,
  `access_token_web`, `__cf_bm`) y luego llama a la API directamente con
  `context.request`: `/api/v2/catalog/items?search_text=…&page=N&
  per_page=96&order=newest_first` (constantes `VINTED_BASE`,
  `VINTED_PER_PAGE`). No hace falta x-csrf-token; con las cookies
  sembradas la API devuelve 200. Pagina con `pagination.total_pages`.
  Campos confirmados en vivo: `id`, `title`, `price.amount` (string),
  `price.currency_code`, `url`. No hay `created_at`, pero
  `photo.high_resolution.timestamp` funciona como proxy de la fecha de
  publicación (`_vinted_created()`), así que las filas de Vinted SÍ
  llevan fecha ahora.
- **Namespacing de IDs**: los item_id de Vinted se prefijan con **`v:`**
  (`v:123456`). Los de Wallapop se dejan CRUDOS para no romper el estado
  existente (`seen.json`, `exclusions.json`, `reviewed.json`,
  `learned_filters.json`) que referencia ids de Wallapop sin prefijo.
- **Calentamiento POR FUENTE (rediseñado)**: ya no hay un booleano
  global `warming_up`. Cada fuente decide al arrancar si calienta según
  tenga o no histórico PROPIO en `seen.json` (`warming_sources`; umbral
  `MIN_HISTORY_FOR_NO_WARMUP = 20` ids). La fuente se deduce del id
  (`v:` = Vinted). Motivo: con el booleano global, al arreglar Vinted
  con un `seen.json` lleno solo de ids de Wallapop, Vinted se habría
  saltado el calentamiento y notificado ~miles de anuncios de golpe.
  `warmed_up_searches` sigue guardando claves `f"{source}::{search}"`;
  una fuente sale de `warming_sources` cuando todas sus búsquedas han
  hecho su primera pasada.
- **Toggles por entorno**: `ENABLE_WALLAPOP=0` / `ENABLE_VINTED=0`
  desactivan una fuente (por defecto ambas activas). Con ninguna activa,
  el watcher avisa y sale.
- **Precios de Vinted**: llegan como string (`"12.0"`) → se convierten a
  float. La búsqueda de Vinted NO expone fecha de publicación fiable, así
  que `created_at` se guarda como `null` para esos anuncios (el dashboard
  lo tolera: columna "Publicado" vacía, orden por fecha los agrupa).

**Verificado en vivo (2026-07-09)**: las tres incógnitas anteriores se
confirmaron ejecutando contra Vinted real desde la máquina del usuario
(este entorno SÍ tiene red, a diferencia del sandbox original): la ruta
y params son correctos, `context.request` + cookies sembradas pasa
Cloudflare sin `x-csrf-token`, y los campos coinciden con los
normalizadores.

**Filtro de ruido ampliado para Vinted (2026-07-09)**: Vinted trae
mayoría de cartas TCG y merchandising multiidioma. Se amplió el filtro
(en Python Y en el .js, verificada paridad total sobre los ~24k títulos
únicos reales con un script que ejecuta ambas implementaciones):
- `NOISE_KEYWORDS` (incondicional): ropa multiidioma ("shirt" cubre
  t-shirt/tee-shirt/sweatshirt, pyjama/pijama, veste, maat/taille…),
  peluches (knuffel/plush/pluche), llaveros (keychain/portachiavi/
  porte-clé[f]), figurine, album, binder, moneda/moneta/moeda, pokeball,
  stylet/stylus/casque, manualidades (fatto a mano, punto croce)…
- `NOISE_TITLE_PATTERNS`: tallas de ropa (`maat|taille|talla|size` +
  número/S/M/L). Y FIX de bug real: el patrón `n[ºo°]\s*\d+` no tenía
  `\b` inicial y marcaba como ruido "Plati**no 3**0", "An**no 17**01" —
  ahora `\bn[ºo°]\.?\s*\d+` (además cubre "No.148" de cartas japonesas).
- `CARD_PATTERNS` (protegido por la salvaguarda DS): carta multiidioma
  con word boundaries (carte/cards/karten NO matchean cartouche/cartuccia
  = cartucho legítimo), holo, booster, ETB, sobres, promo, graded/psa,
  vmax/gx, energy, códigos "#119" y "(N4)"/"(PAF 211)".
Impacto medido sobre datos reales: Vinted pasaba 75% → pasa 61%; en
Wallapop los ~500 recién filtrados son merch/cartas genuinas (muestreo
manual sin falsos positivos) y se rescataron 5 anuncios legítimos del
bug del `\b`. Queda ruido residual imposible de filtrar por palabras
(cartas tituladas solo con el nombre del Pokémon, ej. "Umbreon"), pero
casi todo a 1€ y ya excluido de medianas por la regla de ≤2€.

**Telegram con cola y rate limit**: los mensajes ya no se envían
directamente desde `process_items`; se encolan (`enqueue_telegram`) y un
único `telegram_sender_worker()` los envía espaciados
`TELEGRAM_MIN_INTERVAL` seg (3,5s por defecto, configurable por entorno)
respetando el `retry_after` de los 429 (reintenta, no pierde mensajes).
Antes, una ráfaga de anuncios disparaba decenas de sendMessage
simultáneos y Telegram descartaba los que pasaban del límite.

### 2. Deduplicación de anuncios y "seen" global

Un mismo anuncio puede coincidir con varias keywords (ej. "pokemon ds"
y "nintendo ds"). Se decidió usar un **set global único de IDs vistos**
compartido entre todas las keywords (protegido con `asyncio.Lock`), no
un set por keyword — así no se notifica el mismo anuncio dos veces solo
porque coincide con dos búsquedas distintas.

### 3. Formato de datos: JSONL, no JSON con lista

Se eligió **JSONL** (un objeto JSON por línea) en vez de un único
`.json` con una lista, porque:
- Permite *append* sin leer/reescribir el fichero completo (importante
  con miles de líneas acumulándose con el tiempo).
- Un *append* interrumpido a mitad solo arriesga la última línea, no
  todo el fichero.

Es **histórico completo**: cada vez que un anuncio se ve en un escaneo,
se añade una línea nueva (aunque sea el mismo `item_id` repetido). Esto
permite reconstruir evolución de precio en el tiempo, no solo el estado
actual. Campos por línea: `scanned_at`, `search_term`, `source`
(`"wallapop"`/`"vinted"`), `item_id`, `title`, `price`, `currency`,
`created_at`, `url`, `is_noise`. Las filas antiguas (pre-Vinted) no
tienen `source`; el dashboard las trata como `"wallapop"` por defecto.

### 4. "Calentamiento" (warming_up) al primer arranque

Si `seen.json` no existe (primer arranque), la primera respuesta de
cada keyword trae TODO el catálogo actual de golpe. Sin tratamiento
especial, esto generaría un aluvión de notificaciones de Telegram de
anuncios "viejos". Por eso: la primera pasada de cada keyword se
guarda pero no se notifica. Si `seen.json` ya existe (reinicio), se
asume que el histórico es válido y se notifica desde el primer ciclo.

### 5. Detección de ruido / falsos positivos

Wallapop hace matching textual simple: si la keyword aparece en el
título, sale en resultados, sin importar si es el producto real. Casos
reales encontrados y diagnosticados en esta conversación:
- keyword `"dslite"` → traía "Carcasa Nintendo DSLite Celeste"
  (accesorio, no la consola).
- keyword `"dragon quest VI"` → traía "Dragon Quest VI nº 01/10: Los
  reinos oníricos" (manga/cómic por tomos, no el videojuego).
- Categorías con remasters/secuelas en otra plataforma (Switch, PS4...)
  traían esos juegos en vez del original de DS.
- Caso especial: la keyword `"shin chan contra los plastas"` colisionaba
  con anuncios de **plantas** (Tradescantia) por matching de texto
  parcial de Wallapop. Se corrigió cambiando la keyword en el watcher a
  `"shin chan contra los plastas ds"` — arreglo en el origen, no en el
  filtro. **Aún no verificado en producción** (no hay acceso de red
  desde el sandbox de Claude para confirmar contra Wallapop real).

La solución es una función `isNoise(title)` que vive **duplicada
intencionalmente en dos sitios** con la MISMA lista, para que lo que se
notifica por Telegram coincida con lo que el dashboard oculta:
- `wallapop_watcher.py` → variable `NOISE_KEYWORDS` + `NOISE_TITLE_PATTERNS`
- `market_dashboard/src/lib/noiseDetection.js` → mismas constantes

**Si se añade una palabra nueva de ruido, hay que añadirla en AMBOS
sitios**, y tras editar el `.js` hace falta `npm run build` para que el
servidor sirva la versión actualizada.

**Filtro de plataforma incorrecta y cartas (añadido al activar la
paginación completa)**: además de accesorios/cómics, `is_noise` /
`isNoise` filtran ahora juegos de **otra plataforma** (3DS, 2DS, PS1-5,
PSP/Vita, Switch, Wii/WiiU, Xbox, GameCube/N64, GBA/GameBoy, retro
NES/SNES/MegaDrive/etc., PC/Steam, móvil) y **cartas/coleccionables TCG**
(palabras `carta(s)`/`coleccionable`/`tcg` y códigos tipo `FA 162/086`).
Esto vive en `OTHER_PLATFORM_PATTERNS` + `CARD_PATTERNS` (Python) y sus
gemelos en el `.js`.

**Salvaguarda clave (revisión del caso límite anterior)**: estos dos
filtros SOLO se aplican si el título NO menciona la familia DS real
(`DS_FAMILY_PATTERN` = `ds`/`dsi`/`dsl`/`nds`…). Así se REVIERTE de forma
segura la decisión antigua de no filtrar 3DS/2DS: ahora sí se filtran,
pero el caso legítimo "Zelda Spirit Tracks para DS, DS Lite, DSi, 3DS y
2DS" se conserva porque menciona DS. La misma salvaguarda evita borrar
juegos DS con barra/número en el título tipo "Kingdom Hearts 358/2 Days"
(por eso los códigos de carta exigen 2-3 dígitos tras la barra).

Nota histórica: el `.js` del frontend y el watcher llegaron a estar
**desincronizados** (el frontend filtraba plataformas por substring y el
watcher no filtraba ninguna). Se unificaron con la lógica de arriba; si
vuelven a divergir, ese es el primer sitio a revisar.

El ruido se **guarda siempre en el JSONL** (con flag `is_noise` en
Python), nunca se descarta el dato — solo se evita notificar por
Telegram, y el dashboard puede mostrarlo/ocultarlo con un toggle.

### 6. Detección de outliers de precio (MAD, no desviación estándar)

Para excluir precios anómalos del cálculo de mediana sin ocultar el
anuncio de la tabla, se usa el **método MAD (Median Absolute
Deviation)** con un modified Z-score y umbral 3.5 (estándar de la
literatura, Iglewicz & Hoyle). Se eligió MAD en vez de desviación
estándar porque con pocas muestras y outliers extremos (ej. un lote de
2199€ entre anuncios de 20-50€), la desviación estándar se infla tanto
por el propio outlier que deja de ser útil para detectarlo.

**Hallazgo importante de esta conversación**: en los datos reales del
usuario, MAD detecta los outliers CAROS (lotes, ediciones precintadas)
pero NO los baratos de "1€ para negociar", porque estos últimos no son
estadísticamente extremos en la distribución real (hay continuidad
gradual desde 1€ hasta 30€+ en categorías como Dragon Quest VI). Por
eso se añadió una **regla complementaria independiente de MAD**:
precios ≤2€ (`LOW_PRICE_NEGOTIABLE_THRESHOLD`) se excluyen siempre del
cálculo, sin importar cuántas muestras haya.

El orden de aplicación importa: el ruido por palabras clave se quita
ANTES de calcular outliers de precio, porque si no, una categoría
contaminada de accesorios baratos distorsiona la mediana sobre la que
se mide la distancia de cada outlier.

Vive en `market_dashboard/src/lib/priceOutliers.js`. No existe
equivalente en Python/watcher — solo se aplica en el dashboard, porque
es un cálculo de análisis, no algo que afecte qué se notifica por
Telegram.

### 7. Sistema de exclusión manual (dos tipos distintos)

Hay DOS botones por fila, con semántica distinta:
- **"Excluir"** (`exclude`/`unexclude`): oculta el anuncio POR COMPLETO
  de todo (tabla y cálculo). Para "esto es spam / no es un anuncio real
  / está mal clasificado y no quiero verlo más".
- **"Excluir del cálculo"** (`excludeFromCalc`/`unexcludeFromCalc`):
  mantiene el anuncio VISIBLE en la tabla, pero su precio no cuenta en
  la mediana/min/max de su categoría. Para "quiero seguir viendo este
  anuncio pero su precio no es representativo del mercado real".

Ambos se persisten en `exclusions.json` en disco vía
`market_server.py` (endpoints `GET/POST /api/exclusions`), NO en
localStorage del navegador — se decidió así explícitamente para que
sobreviva a cambios de navegador/dispositivo. El POST espera
`{item_id, action}` donde `action` es uno de los 4 strings de arriba.

La UI hace **actualización optimista** (refleja el cambio al instante)
y revierte si la petición al servidor falla.

### 8. Backend: Python puro, sin frameworks

`market_server.py` usa `http.server.ThreadingHTTPServer` de la
librería estándar — decisión deliberada para no requerir Flask/FastAPI
ni gestión de entornos virtuales adicionales. Sirve:
- `GET /api/data` — relee `wallapop_data.jsonl` del disco EN CADA
  petición (no cachea en memoria), tolerante a líneas a medio escribir
  por el watcher (las descarta silenciosamente, se recogen completas en
  la siguiente lectura).
- `GET/POST /api/exclusions` — lee/escribe `exclusions.json`.
- Estáticos del build de Vite (`market_dashboard/dist/`).
- Maneja `OPTIONS` (preflight CORS) porque el POST con JSON dispara
  preflight en navegadores.

**Conocido y aceptado**: relee el `.jsonl` completo en cada petición.
Con ~22k líneas / 6.4MB esto es trivial; si el fichero crece a decenas
de MB, habrá que cambiar a leer solo líneas nuevas desde la última
lectura.

### 9. Frontend: React + Vite, sin servidor de desarrollo separado

Se migró desde un HTML+JS plano (sin build) a React+Vite por
mantenibilidad, pero **`market_server.py` sigue siendo el único
servidor** — sirve el `dist/` generado por Vite, no hay un dev-server
de Vite corriendo aparte. Esto significa: **cada cambio en
`market_dashboard/src/` requiere `npm run build` antes de que el
usuario lo vea** (no hay hot-reload en este setup). Si se quiere
hot-reload durante desarrollo activo, se podría correr `npm run dev`
en paralelo apuntando a la misma API, pero no está configurado así
ahora — decisión consciente de simplicidad para el día a día (un solo
proceso del lado del dashboard).

Estructura de módulos en `src/`:
- `lib/noiseDetection.js` — `isNoise(title)`, lista de palabras de
  ruido (debe mantenerse sincronizada con el Python del watcher).
- `lib/priceOutliers.js` — `median()`, `detectPriceOutliers()` (MAD +
  regla de precio bajo).
- `lib/marketData.js` — `deduplicateByItem()`, `buildMarketView()`:
  pipeline central que combina deduplicación + clasificación de
  ruido/outliers + exclusiones manuales + stats por categoría.
- `lib/api.js` — cliente fetch hacia `market_server.py`.
- `components/` — `StatCard`, `Controls`, `MarketRow`,
  `KeywordRanking`, `SortableHeader`. `MarketRow` muestra un distintivo
  de fuente (Wallapop/Vinted, colores en `SOURCE_BADGES`) junto al
  título; `Controls` incluye un `<select>` de fuente
  (`all`/`wallapop`/`vinted`) que filtra la tabla en `App.jsx`
  (estado `sourceFilter`).
- `App.jsx` — orquestación: polling de datos (60s) y de exclusiones,
  estado de filtros/orden, handlers de exclusión con actualización
  optimista.

### 10. Ordenación: por click en cabeceras, no por dropdown

Se quitó un `<select>` de "ordenar por" que existía antes, porque era
redundante. Ahora se ordena clicando las cabeceras de columna
(Categoría, Precio, Posición en mercado, Publicado, Avistado): primer
click ordena ascendente (flecha ▲), segundo click en la misma columna
invierte a descendente (▼), click en otra columna reinicia a
ascendente. Estado: `const [sort, setSort] = useState({ column:
"price", direction: "asc" })` — un solo objeto, no dos `useState`
separados (se simplificó así para evitar anidar updaters funcionales).

### 11. Layout: ancho ampliado, alturas relativas al viewport

`.wrap` (contenedor principal) es `max-width: 1600px` (antes 1200px).
La tabla y el panel de ranking usan alturas relativas al viewport
(`calc(100vh - 300px)`) en vez de píxeles fijos.

### 12. Rediseño visual ("modern UI") y tope de renderizado

`index.css` se reescribió entero sobre **tokens CSS** (`:root` con
variables de superficie/borde/texto/acento): si se quiere retocar el
tema, se tocan solo los tokens, no los componentes. Elementos clave:
cabecera sticky con `backdrop-filter` (glass), stat-cards con hover,
checkboxes/selects custom, badges unificados con la clase `.badge` +
variable `--badge-color` inyectada desde el JSX (sustituyó a los estilos
inline repetidos de MarketRow), scrollbars finos, `tabular-nums` en
precios, y media queries a 1100px/720px + `prefers-reduced-motion`.

**Tope de renderizado (importante para el rendimiento)**: sin tope, con
los datos reales se montaban ~15.600 `<tr>` de golpe y el primer render
tardaba ~15s en un viewport móvil (medido con Playwright). Ahora
`App.jsx` solo monta `renderLimit` filas (`RENDER_CHUNK = 500`) con un
botón "Mostrar más"; el límite se resetea al cambiar filtros/orden pero
NO en el refresco de datos de cada 60s. Lo mismo en `ReviewQueue.jsx`
(tope 50). Los cálculos de medianas/stats siguen usando la lista
completa — el tope solo limita el DOM. Tras el cambio: ~1s de primer
render. Si la tabla vuelve a ir lenta, revisar que estos topes sigan
ahí.

## Cosas pendientes / no verificadas (honestidad sobre limitaciones)

- **Ningún cambio se ha podido probar contra Wallapop real.** El
  entorno donde se desarrolló esto (sandbox de Claude) no tiene acceso
  de red a `wallapop.com`, solo a un par de dominios whitelisted (pypi,
  npm, github). Todo lo relativo al scraper en sí (selectores, formato
  de respuesta de la API interna, si el fix de headless detection
  sigue funcionando, si el cambio de keyword de "shin chan" evita el
  choque con plantas) se verificó por estructura de código y pruebas
  con datos ya capturados, NUNCA en vivo contra Wallapop.
- El dashboard SÍ se probó de extremo a extremo con Playwright +
  Chromium headless contra los datos reales subidos por el usuario
  (`wallapop_data.jsonl`, ~21.7k líneas / 1525 anuncios únicos / 38
  keywords) — incluyendo build de Vite desde cero, render sin errores
  de consola, toggle de ruido, ambos tipos de exclusión manual con
  persistencia tras recargar la página, y ordenación por click.
- Quedan falsos positivos residuales conocidos sin resolver
  específicamente (ej. "Coches de colección Citroën" en la categoría
  "coleccion ds", "Salero Pimentero Robots Cuerda" en "solatorobo") —
  son colisiones de texto parecidas al caso de "shin chan"/plantas que
  probablemente requieran el mismo enfoque (ajustar la keyword de
  búsqueda en el origen) en vez de intentar cubrirlos con
  `NOISE_KEYWORDS` genérico.
- El usuario tuvo un error de `vite: command not found` que se debía a
  no haber corrido `npm install` antes de `npm run build` — no es un
  bug del código, pero es la primera cosa a revisar si vuelve a pasar
  algo similar tras clonar/copiar el proyecto.

## Estado de Telegram

El watcher requiere `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` como
variables de entorno. Si no están configuradas, el watcher sigue
funcionando (guarda datos igual) pero solo imprime por consola en vez
de notificar, con un warning explícito.
