import asyncio
import json
import os
import random
import re
import unicodedata
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote

import httpx
from playwright.async_api import async_playwright

# ============================================================
# PALABRAS CLAVE A BUSCAR
# Arquitectura: 1 SOLO proceso de Chromium, 1 SOLO BrowserContext,
# y una Page (pestaña) por keyword dentro de ese context. Las páginas
# son mucho más baratas en RAM que procesos de navegador completos, así
# que esto reduce el consumo de forma drástica frente a tener ~24
# navegadores independientes.
# ============================================================
SEARCHES = [
    # Consolas
    "nintendo ds lite",
    "nintendo dsi",
    # Lotes
    "lote nintendo ds",
    # Pokémon DS
    "pokemon platino",
    "pokemon heartgold",
    "pokemon soulsilver",
    "pokemon negro ",
    "pokemon blanco ",
    "pokemon diamante DS",
    "pokemon perla DS",
    "pokemon mundo misterioso exploradores del cielo",
    # Otros Juegos DS
    "solatorobo DS",
    "castlevania order of ecclesia DS",
    "metal slug 7 DS",
    "last window DS",
    "kirby super star ultra DS",
    "dragon ball origins 2 DS",
    "golden sun dark dawn DS",
    "ghost trick DS",
    "the world ends with you DS",
    "infinite space DS",
    "blue dragon DS",
    "dragon quest VI DS",
    "legend of zelda spirit tracks",
    "legend of zelda phantom hourglass",
    "aliens infestation DS",
    "final fantasy tactics A2 DS",
    "ace attorney DS",
    "castlevania DS",
    "dragon quest IX DS",
    "dragon quest monsters DS",
]

SEEN_FILE = "seen.json"
DATA_FILE = "wallapop_data.jsonl"


# ============================================================
# FUENTES / MARKETPLACES
# ============================================================
# El mismo conjunto de búsquedas (SEARCHES) se ejecuta en cada fuente
# activa. Hoy hay dos: Wallapop y Vinted. Cada fila del JSONL lleva un
# campo "source" para saber de dónde vino. Los item_id de Vinted se
# prefijan con "v:" para no colisionar con los slugs/hashes de Wallapop
# (importante: el estado existente —seen.json, exclusions.json,
# reviewed.json, learned_filters.json— referencia ids crudos de
# Wallapop, así que esos se dejan tal cual).
#
# Se puede desactivar una fuente por entorno:
#   ENABLE_WALLAPOP=0  ó  ENABLE_VINTED=0
# ------------------------------------------------------------
def _env_flag(name: str, default: bool = True) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "")


ENABLED_SOURCES = []
if _env_flag("ENABLE_WALLAPOP", True):
    ENABLED_SOURCES.append("wallapop")
if _env_flag("ENABLE_VINTED", True):
    ENABLED_SOURCES.append("vinted")

# Etiqueta legible por fuente para los avisos de Telegram.
SOURCE_LABELS = {
    "wallapop": "🛒 Wallapop",
    "vinted": "👕 Vinted",
}

# Vinted: la API acepta hasta 96 items por página (verificado en vivo).
VINTED_BASE = "https://www.vinted.es"
VINTED_PER_PAGE = 96

# ============================================================
# FILTRO DE RUIDO / FALSOS POSITIVOS
# ============================================================
# Wallapop hace matching textual simple: si la keyword aparece en el
# título, el anuncio sale en los resultados, sin importar si es el
# producto que buscas o solo un accesorio/objeto relacionado. Ejemplos
# reales detectados en el dataset:
#   - keyword "dslite" -> "Carcasa Nintendo DSLite Celeste" (accesorio,
#     no la consola)
#   - keyword "dragon quest VI" -> "Dragon Quest VI nº 01/10: Los reinos
#     oníricos" (manga/cómic por tomos, no el videojuego)
#
# Esta lista se usa en DOS sitios con el MISMO criterio, para que el
# comportamiento sea consistente entre lo que se notifica y lo que el
# dashboard puede filtrar:
#   1. Aquí en el watcher: decide si un anuncio nuevo se notifica por
#      Telegram (el ruido NO se notifica, para no molestarte con avisos
#      de cargadores/fundas/cómics).
#   2. En market.html: permite un toggle para mostrar/ocultar el ruido
#      ya guardado, sin tener que volver a escanear nada.
#
# IMPORTANTE: el ruido se SIGUE GUARDANDO en wallapop_data.jsonl (con un
# campo "is_noise": true/false). No se descarta el dato, solo se evita
# la notificación. Esto te permite revisar después si el filtro está
# siendo demasiado agresivo, sin haber perdido información.
#
# Si detectas más falsos positivos con el tiempo, añade aquí la palabra
# o ajusta el patrón de NOISE_TITLE_PATTERNS.
# ------------------------------------------------------------
import re

NOISE_KEYWORDS = [
    # Accesorios sueltos (no la consola/juego en sí)
    "funda", "carcasa", "cargador", "pantalla", "bateria", "batería",
    "lapiz", "lápiz", "pegatina", "sticker", "llavero", "mochila",
    "camiseta", "auriculares", "sleeve",
    # Accesorios en fr/en ("lot de 3 stylets", "casque", "stylus"…)
    "stylet", "stylus", "stylo", "casque",
    # Merchandising / coleccionables no-videojuego
    "funko", "peluche", "figura", "figurine", "figuur", "tazo", "tazos",
    "amiibo", "keychain", "portachiavi", "porte-clé", "porte clé",
    "porte-clef", "porte clef", "álbum", "album", "gomme", "binder",
    "moneda", "moneta", "moeda", "médaillon", "jeton", "mini tin",
    "pokeball", "pokéball", "pixel art", "juguete", "jugete",
    "etui", "étui",
    # Ropa/textil (Vinted trae mucha ropa de Pokémon en varios idiomas).
    # "shirt" solo ya cubre t-shirt/tshirt/tee-shirt/sweatshirt.
    "shirt", "sudadera", "hoodie", "sweat", "gorra", "chaqueta",
    "pyjama", "pijama", "pajama", "veste", "camisola", "crop top",
    "pantalon", "coussin", "cojín", "cojin",
    "calcetines", "chaussettes", "schoenen", "zapatilla", "chaussure",
    # Peluches/muñecos en otros idiomas (Vinted es internacional)
    "knuffel", "plush", "pluche", "poupée", "muñec",
    # Manualidades (bordados, punto de cruz "hecho a mano" de Pikachu…)
    "handmade", "fatto a mano", "hecho a mano", "punto croce", "punto de cruz",
    # Material impreso (cómics/mangas confundidos con el videojuego)
    "comic", "cómic", "manga", "novela", "libro", "bande dessin",
    # Juegos de mesa ("jeu de société monopoly…")
    "de société",
]

# Patrones de texto que indican ruido sin importar el idioma:
#  - "nº 01/10", "no.148", "tomo 3", "vol. 2" → tomos de manga o números
#    de carta japoneses. OJO: \b delante de la n es imprescindible — sin
#    él, "PlatiNO 30" matcheaba "no 30" y marcaba como ruido anuncios
#    legítimos de Pokémon Platino con un número detrás (bug real).
#  - tallas de ropa en varios idiomas ("maat 33", "taille 40", "talla M")
#    → prenda de vestir, no un juego.
NOISE_TITLE_PATTERNS = [
    re.compile(r"\bn[ºo°]\.?\s*\d+", re.IGNORECASE),
    re.compile(r"\btomo\s*\d+", re.IGNORECASE),
    re.compile(r"\bvol\.?\s*\d+", re.IGNORECASE),
    re.compile(r"\b(maat|taille|talla|größe|grösse|size)\s*(\d{2,3}|xxs|xs|s|m|l|xl|xxl)\b", re.IGNORECASE),
]

# ------------------------------------------------------------
# FILTRO DE PLATAFORMA INCORRECTA Y CARTAS/COLECCIONABLES
# ------------------------------------------------------------
# Wallapop hace matching textual: "mario & luigi DS" trae juegos de
# Switch/PS, "pokemon negro" trae cartas TCG, etc. Filtramos esos casos,
# PERO con una salvaguarda: si el título también menciona DS (la familia
# DS real: DS / DS Lite / DSi), se CONSERVA. Esto evita perder anuncios
# legítimos de DS que solo mencionan otra plataforma de pasada (ej:
# "Zelda Spirit Tracks para DS, DSi, 3DS y 2DS" — menciona 3DS pero es DS)
# o juegos de DS cuyo TÍTULO contiene una barra/número parecido a un
# código de carta (ej: "Kingdom Hearts 358/2 Days").
#
# OJO: a diferencia de la decisión original (que dejaba pasar 3DS/2DS),
# AHORA sí se filtran 3DS/2DS — pero solo cuando el título NO menciona la
# familia DS, así que el caso legítimo de arriba se sigue conservando.
DS_FAMILY_PATTERN = re.compile(r"\b(ds|dsi|dsl|nds|ndsi|ndsl)\b", re.IGNORECASE)

OTHER_PLATFORM_PATTERNS = [
    re.compile(r"\b3\s*ds\b", re.IGNORECASE),
    re.compile(r"\b2\s*ds\b", re.IGNORECASE),
    re.compile(r"\bps[1-5]\b|\bplaystation\b|\bpsx\b|\bpsone\b", re.IGNORECASE),
    re.compile(r"\bpsp\b|\bvita\b", re.IGNORECASE),
    re.compile(r"\bswitch\b", re.IGNORECASE),
    re.compile(r"\bwii\s*u?\b", re.IGNORECASE),
    re.compile(r"\bxbox\b|\bx360\b", re.IGNORECASE),
    re.compile(r"\bgame\s*cube\b|\bgamecube\b|\bngc\b|\bn64\b|\bnintendo\s*64\b", re.IGNORECASE),
    re.compile(r"\bgba\b|\bgame\s*boy\b|\bgameboy\b", re.IGNORECASE),
    re.compile(
        r"\bsnes\b|\bsuper\s*nintendo\b|\bnes\b|\bmega\s*drive\b|\bmegadrive\b|"
        r"\bgenesis\b|\bmaster\s*system\b|\bgame\s*gear\b|\bsaturn\b|\bdreamcast\b|"
        r"\bneo\s*geo\b|\bneogeo\b|\bamiga\b|\bcommodore\b|\bspectrum\b|\bmsx\b|\batari\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bandroid\b|\bm[oó]vil\b", re.IGNORECASE),
    re.compile(r"\bsteam\b|\bpc\b", re.IGNORECASE),
]

# Cartas/coleccionables TCG. Vinted trae muchísima carta en varios
# idiomas, así que además del español se cubren fr/it/en/de y la jerga
# TCG (holo, booster, graded, vmax…). Todo esto está PROTEGIDO por la
# salvaguarda DS: un título que menciona la familia DS nunca se filtra
# por estos patrones (con "carta" es clave: los boundaries de regex
# evitan además que matchee "cartouche"/"cartuccia" = cartucho legítimo).
# Códigos de carta: "FA 162/086", "162/086" (2-3 dígitos tras la barra
# para no chocar con "358/2 Days"), "#119", y códigos de set entre
# paréntesis tipo "(N4)" o "(PAF 211)".
CARD_PATTERNS = [
    re.compile(
        r"\b(cartas?|cartes?|cards?|karten?|cromos?|coleccionables?|"
        r"p?tcg|jcc|gcc|wotc|trading\s*card)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bholo\b|\bhologr[aá]f|\bbooster\b|\bdisplay\b|\belite\s*trainer\b|"
        r"\betb\b|\bsobres\b|\bpromo\b|\bgraded\b|\bgradad[ao]\b|\bpsa\s*\d{1,2}\b|"
        r"\bvmax\b|\bvstar\b|\bgx\b|\bfull\s*art\b|\benergy\b|\benerg[ií]a\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[a-z]{1,4}\s*\d{1,3}/\d{2,3}\b|\b\d{1,3}/\d{2,3}\b|"
        r"#\s*\d{1,3}\b|\(\s*[a-z]{1,4}\s*\d{1,3}\s*\)",
        re.IGNORECASE,
    ),
]


def is_noise(title: str) -> bool:
    """
    Devuelve True si el título parece ruido (accesorio suelto, cómic/
    manga, merchandising, OTRA plataforma distinta de DS, o cartas/
    coleccionables) en vez del producto buscado. Es una heurística basada
    en palabras clave y patrones de texto, no perfecta: puede tener tanto
    falsos positivos como falsos negativos.

    IMPORTANTE: esta función debe mantenerse sincronizada con
    market_dashboard/src/lib/noiseDetection.js (misma lógica en JS).
    """
    if not title:
        return False
    t = title.lower()
    if any(word in t for word in NOISE_KEYWORDS):
        return True
    if any(pattern.search(t) for pattern in NOISE_TITLE_PATTERNS):
        return True
    # Plataforma incorrecta o cartas: solo si el título NO menciona la
    # familia DS real (salvaguarda contra falsos positivos legítimos).
    if not DS_FAMILY_PATTERN.search(title):
        if any(pattern.search(title) for pattern in OTHER_PLATFORM_PATTERNS):
            return True
        if any(pattern.search(title) for pattern in CARD_PATTERNS):
            return True
    return False


# ============================================================
# FILTROS APRENDIDOS
# ============================================================
# Cuando el usuario descarta un anuncio desde el dashboard (o la cola
# de revisión), el servidor guarda automáticamente una regla en
# learned_filters.json: para esa búsqueda concreta, títulos con palabras
# similares se filtran sin notificar por Telegram.
# El watcher recarga el fichero al detectar que cambió en disco (comparando
# mtime), así que una regla nueva surte efecto en el siguiente ciclo de
# escaneo sin necesidad de reiniciar el watcher.
# ------------------------------------------------------------
LEARNED_FILTERS_FILE = "learned_filters.json"
_lf_cache: list = []
_lf_mtime: float = 0.0

_LF_STOPWORDS = {
    "the", "and", "for", "que", "con", "del", "los", "las", "una",
    "par", "per", "von", "para", "nintendo", "juego", "juegos",
}


def _extract_filter_words(title: str) -> list:
    normalized = unicodedata.normalize("NFD", title.lower())
    ascii_text = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    words = re.findall(r"\b[a-z0-9]{3,}\b", ascii_text)
    return [w for w in words if w not in _LF_STOPWORDS]


def _load_learned_filters() -> list:
    """Recarga learned_filters.json si ha cambiado en disco desde la última lectura."""
    global _lf_cache, _lf_mtime
    try:
        mtime = os.path.getmtime(LEARNED_FILTERS_FILE)
        if mtime != _lf_mtime:
            with open(LEARNED_FILTERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _lf_cache = data.get("rules", [])
            _lf_mtime = mtime
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return _lf_cache


def is_learned_excluded(title: str, search_term: str) -> bool:
    """
    Devuelve True si el título coincide con alguna regla aprendida para
    esta búsqueda. Un título coincide si contiene TODAS las palabras clave
    del patrón guardado (el título es un superconjunto del patrón).

    Se exige coincidencia total —y no un umbral parcial— para no arrasar
    juegos legítimos cuyo nombre comparte casi todas las palabras con el
    ruido. Caso real: excluir "Folleto Mundo Misterioso Exploradores del
    Cielo" generaba el patrón [folleto, mundo, misterioso, exploradores,
    cielo]; con umbral parcial, "Pokémon Mundo Misterioso Exploradores del
    Cielo" (el juego real) compartía 4 palabras y desaparecía. Exigiendo
    todas, la palabra discriminante "folleto" —que el juego no tiene—
    protege al anuncio legítimo.
    """
    rules = _load_learned_filters()
    if not rules:
        return False
    candidate = set(_extract_filter_words(title))
    for rule in rules:
        if rule.get("search_term") != search_term:
            continue
        rule_words = rule.get("words", [])
        if not rule_words:
            continue
        if all(w in candidate for w in rule_words):
            return True
    return False

# Telegram: configura estas dos variables de entorno antes de ejecutar
#   export TELEGRAM_BOT_TOKEN="123456789:ABC..."
#   export TELEGRAM_CHAT_ID="987654321"
# (ver instrucciones al final del archivo para crear el bot y obtener el chat_id)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ------------------------------------------------------------
# Estado global compartido entre todas las páginas/keywords.
# Un mismo anuncio puede aparecer en varias búsquedas (ej: "pokemon ds"
# y "nintendo ds"); usamos un único set "seen" para que solo se
# notifique una vez, sin importar por qué keyword se detectó primero.
# Con asyncio (todo corre en un solo hilo/loop de eventos) no hace falta
# un Lock de threading: solo puede ejecutarse una corrutina a la vez en
# cada punto sin "await" en medio, así que no hay condiciones de carrera
# reales mientras no metamos un await dentro de la sección crítica.
# Aun así usamos un asyncio.Lock por claridad y por seguridad ante
# futuros cambios en el código.
# ------------------------------------------------------------
seen_lock = asyncio.Lock()

if Path(SEEN_FILE).exists():
    with open(SEEN_FILE, "r") as f:
        seen = set(json.load(f))
else:
    seen = set()


# ------------------------------------------------------------
# CALENTAMIENTO POR FUENTE (no global)
# ------------------------------------------------------------
# El calentamiento evita que la primera pasada de una búsqueda te
# bombardee con todo el catálogo existente: se guarda como visto, pero no
# se notifica.
#
# Antes esto era un único booleano global: "¿existe seen.json? entonces no
# calentamos". Eso es incorrecto cuando se AÑADE una fuente nueva (o una
# fuente rota empieza a funcionar): seen.json existe y está lleno de ids
# de Wallapop, así que la fuente nueva se salta el calentamiento y
# notifica su catálogo entero de golpe. Es exactamente lo que pasaría con
# Vinted al arreglar su fetch: seen.json tiene ~11k ids de Wallapop y
# ninguno de Vinted.
#
# Ahora se decide POR FUENTE: una fuente calienta si no tiene histórico
# propio en seen.json. Los ids de Vinted llevan prefijo "v:", los de
# Wallapop no, así que podemos contarlos por separado.
# ------------------------------------------------------------
# Un puñado suelto de ids no es un catálogo real (p. ej. 2 ids de Vinted
# que se colaron cuando el fetch fallaba casi siempre). Por debajo de este
# umbral consideramos que la fuente no tiene histórico y hay que calentar.
MIN_HISTORY_FOR_NO_WARMUP = 20


def _source_of_id(item_id) -> str:
    """Deduce la fuente a partir del id (Vinted va prefijado con 'v:')."""
    return "vinted" if str(item_id).startswith("v:") else "wallapop"


_seen_counts: dict = {}
for _iid in seen:
    _s = _source_of_id(_iid)
    _seen_counts[_s] = _seen_counts.get(_s, 0) + 1

# Fuentes que aún deben calentar (guardar sin notificar en su 1ª pasada).
warming_sources = {
    s for s in ENABLED_SOURCES
    if _seen_counts.get(s, 0) < MIN_HISTORY_FOR_NO_WARMUP
}
for _s in ENABLED_SOURCES:
    _n = _seen_counts.get(_s, 0)
    if _s in warming_sources:
        print(
            f"🌡️  [{_s}] Sin histórico propio ({_n} ids en seen.json): "
            f"la primera pasada se guardará SIN notificar."
        )
    else:
        print(f"✅ [{_s}] Histórico presente ({_n} ids): se notifica desde el primer ciclo.")

# Qué pares (fuente, búsqueda) ya han hecho su primera pasada.
warmed_up_searches = set()

# Cliente HTTP async reutilizable para Telegram (más eficiente que crear
# uno nuevo en cada llamada).
http_client: httpx.AsyncClient | None = None

# ------------------------------------------------------------
# RATE LIMITING DE TELEGRAM
# ------------------------------------------------------------
# Todas las tareas watch_search (búsqueda × fuente) corren en paralelo y
# pueden querer notificar a la vez. Sin control, cuando termina el
# calentamiento o aparece un aluvión de anuncios nuevos se disparan
# decenas de sendMessage casi simultáneos y Telegram devuelve 429 ("Too
# Many Requests"): el límite práctico es ~1 mensaje/segundo por chat (y
# ~20/minuto en grupos). Los mensajes por encima del límite se PIERDEN.
#
# Solución: en vez de que cada tarea llame a sendMessage directamente,
# encolan el texto en una cola global y UN ÚNICO worker los va enviando
# espaciados TELEGRAM_MIN_INTERVAL segundos entre sí, y además respeta el
# `retry_after` que devuelve Telegram en un 429 (reintenta el mismo
# mensaje sin perderlo). Así el ritmo de salida es constante y seguro sin
# importar cuántos anuncios lleguen de golpe.
# ------------------------------------------------------------
# Segundos mínimos entre mensajes. 3.5s ≈ 17/min, por debajo del límite
# de grupos (20/min). Ajustable por entorno si tu chat aguanta más ritmo.
try:
    TELEGRAM_MIN_INTERVAL = float(os.environ.get("TELEGRAM_MIN_INTERVAL", "3.5"))
except ValueError:
    TELEGRAM_MIN_INTERVAL = 3.5

# Se crea dentro del event loop (en main), no a nivel de módulo.
telegram_queue: "asyncio.Queue[str] | None" = None


def save_seen():
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# ------------------------------------------------------------
# Último precio conocido por item_id. Solo añadimos una línea nueva al
# JSONL cuando un anuncio aparece por PRIMERA vez o cuando su precio
# CAMBIA respecto al último guardado — ya NO en cada escaneo. Antes se
# añadía una línea por item en cada pasada, lo que hizo crecer el
# fichero a ~1,9 millones de líneas / 623 MB en pocos días y dejó
# inservible al market_server (releía el fichero entero en cada
# petición). El histórico que conservamos ahora es la evolución de
# PRECIOS, que es lo único que el dashboard realmente usa.
# ------------------------------------------------------------
_PRICE_UNSET = object()
last_price_by_item: dict = {}


def load_last_prices():
    """Reconstruye el último precio conocido por item_id leyendo el
    JSONL existente. Barato porque el fichero ya no acumula una línea
    por escaneo. Tolerante a una última línea a medio escribir."""
    if not Path(DATA_FILE).exists():
        return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            item_id = rec.get("item_id")
            if item_id is not None:
                last_price_by_item[item_id] = rec.get("price")


load_last_prices()


def append_sighting(record: dict):
    """
    Añade una línea al fichero de datos histórico (JSONL: un objeto JSON
    por línea). Usamos modo append ("a") para no tener que leer ni
    reescribir el fichero completo cada vez — esto es lo que hace viable
    acumular miles de registros sin que la escritura se vuelva lenta o
    arriesgada (una reescritura completa interrumpida a mitad podría
    corromper todo el fichero; un append solo arriesga la última línea).
    """
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _send_telegram_once(text) -> float:
    """
    Intenta enviar UN mensaje a Telegram. Devuelve cuántos segundos hay
    que esperar antes de reintentar el MISMO mensaje:
      - 0  -> enviado (o error no recuperable): pasar al siguiente.
      - >0 -> Telegram respondió 429; hay que esperar ese `retry_after`
              (más un pequeño margen) y reintentar sin perder el mensaje.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    try:
        r = await http_client.post(url, data=payload, timeout=15)
    except httpx.HTTPError as e:
        print(f"⚠️  Excepción enviando a Telegram: {e}")
        return 0

    if r.status_code == 429:
        # Too Many Requests: Telegram nos dice cuánto esperar en
        # parameters.retry_after. Reintentamos el mismo mensaje.
        try:
            retry_after = r.json().get("parameters", {}).get("retry_after", 1)
        except Exception:
            retry_after = 1
        return float(retry_after) + 0.5

    if r.status_code != 200:
        print(f"⚠️  Error Telegram ({r.status_code}): {r.text}")
    return 0


async def enqueue_telegram(text):
    """
    Encola un mensaje para que el worker global lo envíe respetando el
    rate limit. Si Telegram no está configurado, solo avisa por consola
    (el watcher sigue funcionando y guardando datos igual).
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID no configurados, no se envía aviso.")
        return
    await telegram_queue.put(text)


async def telegram_sender_worker():
    """
    Único consumidor de la cola de Telegram. Envía los mensajes de uno en
    uno, con al menos TELEGRAM_MIN_INTERVAL segundos entre envíos, y
    respetando el retry_after de los 429. Esto convierte cualquier ráfaga
    de notificaciones en un goteo constante que Telegram no rechaza.
    """
    while True:
        text = await telegram_queue.get()
        try:
            while True:
                retry_after = await _send_telegram_once(text)
                if retry_after <= 0:
                    break
                print(f"⏳ Telegram 429: esperando {retry_after:.1f}s y reintentando…")
                await asyncio.sleep(retry_after)
        finally:
            telegram_queue.task_done()
        # Espaciado base entre mensajes para no acercarnos al límite.
        await asyncio.sleep(TELEGRAM_MIN_INTERVAL)


def extract_items(data: dict) -> list:
    """
    Saca la lista de anuncios de una respuesta del endpoint
    /api/v3/search/section. Tolerante a respuestas sin section/items
    (p. ej. la última página de la paginación): devuelve [] en vez de
    petar.
    """
    try:
        items = data["data"]["section"]["items"]
    except (KeyError, TypeError):
        return []
    return items or []


def extract_next_page(data: dict):
    """
    Token de continuación de la paginación (meta.next_page). Devuelve
    None cuando no hay más páginas (no existe o es null).
    """
    meta = data.get("meta") or {}
    return meta.get("next_page")


# ============================================================
# NORMALIZACIÓN A UN FORMATO COMÚN
# ============================================================
# Wallapop y Vinted devuelven estructuras de item distintas. Las
# convertimos a un dict común con SIEMPRE estas claves antes de
# procesarlas, para que process_items sea agnóstico de la fuente:
#   item_id, title, price, currency, created (datetime|None), url, source
# ------------------------------------------------------------
def normalize_wallapop_item(item: dict):
    """Convierte un item crudo del endpoint de Wallapop al formato común.
    Devuelve None si le faltan campos imprescindibles (id/web_slug)."""
    try:
        created_ms = item.get("created_at")
        created = datetime.fromtimestamp(created_ms / 1000) if created_ms else None
        price_obj = item.get("price") or {}
        return {
            "item_id": item["id"],
            "title": item.get("title", ""),
            "price": price_obj.get("amount", "?"),
            "currency": price_obj.get("currency", "EUR"),
            "created": created,
            "url": f"https://es.wallapop.com/item/{item['web_slug']}",
            "source": "wallapop",
        }
    except (KeyError, TypeError):
        return None


def _vinted_created(item: dict):
    """
    Vinted NO expone un `created_at` en los items del catálogo (verificado
    en vivo: la clave no existe). Lo más cercano es el timestamp de subida
    de la foto principal (`photo.high_resolution.timestamp`), que en la
    práctica coincide con el momento de publicar el anuncio. Es un PROXY,
    no la fecha oficial: si falta o es inválido, devolvemos None (el
    dashboard ya tolera "Publicado" vacío).
    """
    photo = item.get("photo") or {}
    hi = photo.get("high_resolution") or {}
    ts = hi.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def normalize_vinted_item(item: dict):
    """Convierte un item crudo del endpoint de Vinted al formato común.
    Vinted da el precio como string (ej. "12.0") dentro de un objeto
    `price`, y sus ids son enteros que prefijamos con "v:".
    Devuelve None si le falta el id."""
    try:
        price_obj = item.get("price") or {}
        amount = price_obj.get("amount")
        try:
            price = float(amount) if amount is not None else "?"
        except (TypeError, ValueError):
            price = "?"
        return {
            "item_id": f"v:{item['id']}",
            "title": item.get("title", ""),
            "price": price,
            "currency": price_obj.get("currency_code", "EUR"),
            "created": _vinted_created(item),
            "url": item.get("url", ""),
            "source": "vinted",
        }
    except (KeyError, TypeError):
        return None


async def process_items(items: list, search_term: str, source: str):
    """
    Procesa la lista YA COMPLETA de anuncios (todas las páginas) de una
    keyword: guarda cada avistamiento en el JSONL (histórico), deduplica
    contra el set global `seen` para no notificar dos veces, aplica el
    filtro de ruido y los filtros aprendidos, y envía por Telegram solo
    lo nuevo y relevante.

    Antes esta lógica vivía dentro del handler de page.on("response"),
    que la disparaba reactivamente por cada respuesta de red. Se ha
    extraído para poder alimentarla con la lista completa obtenida por
    paginación directa contra la API (fetch_all_items).
    """
    new_count = 0
    mensajes_a_enviar = []
    scanned_at = datetime.now().isoformat(timespec="seconds")

    # El calentamiento se lleva por (fuente, búsqueda): cada combinación
    # hace su propia primera pasada sin notificar. Si se llevara solo por
    # búsqueda, la segunda fuente notificaría todo su catálogo de golpe en
    # cuanto la primera marcara la búsqueda como "ya calentada".
    warm_key = f"{source}::{search_term}"

    async with seen_lock:
        is_first_pass_for_this_search = warm_key not in warmed_up_searches

        for item in items:
            item_id = item["item_id"]

            title = item.get("title", "")
            price = item.get("price", "?")
            created = item.get("created")  # datetime | None
            link = item.get("url", "")
            noise = is_noise(title)

            # Histórico de PRECIOS: guardamos una línea solo cuando el
            # anuncio aparece por primera vez o cuando su precio cambia
            # respecto al último guardado (no en cada escaneo). Así el
            # fichero no crece sin límite pero seguimos pudiendo estudiar
            # la evolución de precio en el tiempo (filtrando por item_id
            # y ordenando por scanned_at). Guardamos TODO, incluido el
            # ruido (is_noise=True), para no perder datos: el filtrado de
            # ruido se aplica al decidir si notificar (abajo) y
            # opcionalmente en el dashboard, no al guardar.
            if last_price_by_item.get(item_id, _PRICE_UNSET) != price:
                append_sighting({
                    "scanned_at": scanned_at,
                    "search_term": search_term,
                    "source": source,
                    "item_id": item_id,
                    "title": title,
                    "price": price,
                    "currency": item.get("currency", "EUR"),
                    "created_at": created.isoformat(timespec="seconds") if created else None,
                    "url": link,
                    "is_noise": noise,
                })
                last_price_by_item[item_id] = price

            if item_id in seen:
                continue

            seen.add(item_id)
            new_count += 1

            if noise:
                # Es ruido probable (accesorio/cómic/merchandising):
                # no se notifica por Telegram, pero ya quedó guardado
                # arriba en el JSONL para que puedas revisarlo en el
                # dashboard si quieres ajustar el filtro.
                print(f"\n[{search_term}] (ruido, no notificado) {title}\n")
                continue

            if is_learned_excluded(title, search_term):
                # Filtrado por regla aprendida: el usuario descartó
                # anuncios similares antes, así que no se notifica.
                print(f"\n[{search_term}] (filtro aprendido, no notificado) {title}\n")
                continue

            fecha_str = created.strftime('%d/%m/%Y %H:%M') if created else "fecha desconocida"
            mensaje = (
                f"🔥 {title}\n\n"
                f"💰 {price}€\n"
                f"📅 {fecha_str}\n"
                f"🏪 {SOURCE_LABELS.get(source, source)}\n"
                f"🔎 Búsqueda: {search_term}\n"
                f"🔗 {link}"
            )

            print(f"\n[{search_term}] {mensaje}\n")

            if is_first_pass_for_this_search and source in warming_sources:
                # Calentamiento de ESTA fuente: guardamos como visto, no
                # notificamos. Otras fuentes con histórico siguen avisando.
                continue

            mensajes_a_enviar.append(mensaje)

        if new_count > 0:
            save_seen()
            print(f"\n💾 [{search_term}] Guardados {new_count} anuncios nuevos")

        if is_first_pass_for_this_search:
            warmed_up_searches.add(warm_key)
            print(
                f"ℹ️  [{source}/{search_term}] Primera pasada completa "
                f"({new_count} anuncios guardados como vistos)."
            )
            # Una fuente deja de calentar cuando TODAS sus búsquedas han
            # hecho ya su primera pasada. A partir de ahí notifica.
            if source in warming_sources and all(
                f"{source}::{st}" in warmed_up_searches for st in SEARCHES
            ):
                warming_sources.discard(source)
                print(
                    f"\n✅ [{source}] Calentamiento completo en todas las búsquedas. "
                    f"A partir de ahora se notifica por Telegram.\n"
                )

    # Encolamos los mensajes FUERA del lock, para no tener al resto de
    # keywords bloqueadas esperando. Encolar es instantáneo: el envío real
    # (espaciado, con reintentos ante 429) lo hace telegram_sender_worker.
    for mensaje in mensajes_a_enviar:
        await enqueue_telegram(mensaje)


def _with_query_param(url: str, key: str, value) -> str:
    """
    Devuelve la misma URL pero con el parámetro `key=value` añadido o
    reemplazado, conservando el resto de parámetros originales (keywords,
    filtros, per_page, lat/long…). Se usa tanto para el token de
    continuación de Wallapop (next_page) como para el número de página de
    Vinted (page), que se interpretan en el contexto de esa misma consulta.
    """
    parts = urlparse(url)
    qs = parse_qs(parts.query, keep_blank_values=True)
    qs[key] = [str(value)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parts._replace(query=new_query))


def _with_next_page(url: str, token: str) -> str:
    """Atajo para la paginación de Wallapop (next_page=TOKEN)."""
    return _with_query_param(url, "next_page", token)


async def fetch_all_items(context, page, search_term: str, max_pages: int = 40) -> list:
    """
    Obtiene TODOS los anuncios de una keyword recorriendo la paginación
    completa del endpoint /api/v3/search/section mediante meta.next_page.

    Estrategia (rápida y ligera en RAM):
      1. La PRIMERA página se carga en el navegador (page.goto). Esto
         establece la sesión/cookies y, sobre todo, nos deja capturar la
         petición real a la API con TODAS sus cabeceras (auth, device-id,
         firma…), que necesitamos para replicar las siguientes páginas.
      2. Las páginas siguientes se piden DIRECTAMENTE contra la API con
         `context.request` (APIRequestContext de Playwright). Comparte las
         cookies/sesión del navegador, pero no renderiza nada: es como un
         fetch, mucho más barato que cargar la página y pulsar "Cargar
         más" N veces.
      3. Se sigue meta.next_page hasta que no exista o sea null.

    Acumula los items deduplicados por id (un mismo anuncio podría
    repetirse entre páginas por solapamiento) y los devuelve.
    """
    search_url = (
        "https://es.wallapop.com/app/search?keywords="
        + search_term.replace(" ", "%20")
    )

    # Cargamos la primera página en el navegador y capturamos AL VUELO la
    # respuesta real del endpoint de búsqueda (de ahí sacamos la URL con
    # todos sus parámetros y las cabeceras firmadas a reutilizar).
    async with page.expect_response(
        lambda r: "/api/v3/search/section" in r.url, timeout=30000
    ) as resp_info:
        await page.goto(search_url, wait_until="domcontentloaded")
    response = await resp_info.value

    request = response.request
    headers = await request.all_headers()
    # Cabeceras que NO debemos reenviar: las gestiona el propio cliente
    # HTTP (host/longitud/codificación/conexión) o ya las aporta el
    # context compartido (cookie).
    for h in ("host", "content-length", "accept-encoding", "connection", "cookie"):
        headers.pop(h, None)
    first_url = request.url

    try:
        data = await response.json()
    except Exception as e:
        print(f"[{search_term}] ERROR parseando la primera respuesta: {e}")
        return []

    all_items: list = []
    seen_in_scan: set = set()

    def accumulate(items: list, page_num: int) -> int:
        added = 0
        for it in items:
            iid = it.get("id")
            if iid is None or iid in seen_in_scan:
                continue
            seen_in_scan.add(iid)
            all_items.append(it)
            added += 1
        print(
            f"[{search_term}] Página {page_num}: {added} anuncios nuevos "
            f"(total acumulado: {len(all_items)})"
        )
        return added

    page_num = 1
    accumulate(extract_items(data), page_num)
    next_page = extract_next_page(data)

    while next_page and page_num < max_pages:
        page_num += 1
        url = _with_next_page(first_url, next_page)
        print(f"[{search_term}] Solicitando página {page_num} a la API…")
        try:
            api_resp = await context.request.get(url, headers=headers, timeout=15000)
        except Exception as e:
            print(
                f"[{search_term}] Error de red al paginar (página {page_num}): {e}. "
                f"Se detiene la paginación."
            )
            break

        if not api_resp.ok:
            print(
                f"[{search_term}] La API respondió {api_resp.status} en la página "
                f"{page_num}. Se detiene la paginación (te quedas con lo acumulado)."
            )
            break

        try:
            data = await api_resp.json()
        except Exception as e:
            print(f"[{search_term}] ERROR parseando la página {page_num}: {e}. Se detiene.")
            break

        accumulate(extract_items(data), page_num)
        next_page = extract_next_page(data)

    if next_page and page_num >= max_pages:
        print(
            f"[{search_term}] ⚠️  Alcanzado el tope de {max_pages} páginas; "
            f"podría haber más resultados. Total: {len(all_items)} anuncios."
        )
    else:
        print(
            f"[{search_term}] ✅ Paginación finalizada: {page_num} páginas, "
            f"{len(all_items)} anuncios únicos en total."
        )

    return all_items


async def fetch_all_items_vinted(context, page, search_term: str, max_pages: int = 20) -> list:
    """
    Equivalente a fetch_all_items() pero para Vinted. Misma estrategia:
      1. Se carga la 1ª página del catálogo en el navegador (page.goto)
         para establecer sesión/cookies y capturar al vuelo la petición
         real al endpoint /api/v2/catalog/items (con sus cabeceras).
      2. Las páginas siguientes se piden directamente contra la API con
         context.request (comparte cookies del navegador, no renderiza).
      3. Vinted pagina con un parámetro `page` numérico y expone el total
         en pagination.total_pages (no un token como Wallapop).

    Devuelve los items CRUDOS de Vinted deduplicados por id; la
    normalización al formato común la hace el llamador (watch_search).
    """
    catalog_url = (
        f"{VINTED_BASE}/catalog?search_text="
        + quote(search_term)
        + "&order=newest_first"
    )

    # Visitamos el catálogo SOLO para sembrar cookies de sesión válidas
    # (anon_id, access_token_web, __cf_bm) en el context compartido, que
    # es lo que después deja pasar las llamadas directas a la API.
    #
    # OJO — esto NO espera ningún XHR, a propósito. Vinted RENDERIZA LOS
    # RESULTADOS EN EL SERVIDOR: al cargar /catalog no se dispara ninguna
    # petición a /api/v2/catalog/items (verificado en vivo: solo salen
    # /api/v2/banners, /info_banners, /promoted_closets). La versión
    # anterior hacía page.expect_response("/api/v2/catalog/items") y por
    # tanto se colgaba 30s, lanzaba TimeoutError y dejaba Vinted SIN
    # resultados en todos los ciclos. Construimos la URL de la API a mano.
    try:
        await page.goto(catalog_url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print(f"[vinted/{search_term}] No se pudo cargar el catálogo (sembrado de cookies): {e}")
        return []

    headers = {
        "accept": "application/json, text/plain, */*",
        "x-requested-with": "XMLHttpRequest",
        "referer": catalog_url,
    }

    all_items: list = []
    seen_in_scan: set = set()

    def extract_vinted_items(d: dict) -> list:
        return (d.get("items") if isinstance(d, dict) else None) or []

    def extract_total_pages(d: dict) -> int:
        pag = (d.get("pagination") if isinstance(d, dict) else None) or {}
        try:
            return int(pag.get("total_pages") or 1)
        except (TypeError, ValueError):
            return 1

    def accumulate(items: list, page_num: int) -> int:
        added = 0
        for it in items:
            iid = it.get("id")
            if iid is None or iid in seen_in_scan:
                continue
            seen_in_scan.add(iid)
            all_items.append(it)
            added += 1
        print(
            f"[vinted/{search_term}] Página {page_num}: {added} anuncios nuevos "
            f"(total acumulado: {len(all_items)})"
        )
        return added

    def api_url(page_num: int) -> str:
        return (
            f"{VINTED_BASE}/api/v2/catalog/items?search_text={quote(search_term)}"
            f"&page={page_num}&per_page={VINTED_PER_PAGE}&order=newest_first"
        )

    page_num = 1
    total_pages = 1

    while page_num <= min(total_pages, max_pages):
        try:
            api_resp = await context.request.get(
                api_url(page_num), headers=headers, timeout=20000
            )
        except Exception as e:
            print(
                f"[vinted/{search_term}] Error de red al pedir la página {page_num}: {e}. "
                f"Se detiene la paginación."
            )
            break

        if not api_resp.ok:
            print(
                f"[vinted/{search_term}] La API respondió {api_resp.status} en la página "
                f"{page_num}. Se detiene la paginación (te quedas con lo acumulado)."
            )
            break

        try:
            data = await api_resp.json()
        except Exception as e:
            print(f"[vinted/{search_term}] ERROR parseando la página {page_num}: {e}. Se detiene.")
            break

        accumulate(extract_vinted_items(data), page_num)
        if page_num == 1:
            total_pages = extract_total_pages(data)

        page_num += 1

    page_num -= 1  # última página realmente descargada

    if page_num < total_pages and page_num >= max_pages:
        print(
            f"[vinted/{search_term}] ⚠️  Alcanzado el tope de {max_pages} páginas; "
            f"podría haber más resultados. Total: {len(all_items)} anuncios."
        )
    else:
        print(
            f"[vinted/{search_term}] ✅ Paginación finalizada: {page_num} páginas, "
            f"{len(all_items)} anuncios únicos en total."
        )

    return all_items


async def watch_search(context, search_term: str, source: str):
    """
    Abre una pestaña (Page) dedicada a una (búsqueda, fuente) dentro del
    context compartido y, en bucle indefinido (cada 4-6 min con jitter),
    obtiene TODOS los anuncios paginando contra la API de esa fuente, los
    normaliza al formato común y los procesa.

    Según `source` se despacha al fetch adecuado (Wallapop o Vinted) y al
    normalizador correspondiente; process_items ya es agnóstico de fuente.
    """
    page = await context.new_page()

    if source == "vinted":
        fetcher, normalizer = fetch_all_items_vinted, normalize_vinted_item
    else:
        fetcher, normalizer = fetch_all_items, normalize_wallapop_item

    while True:
        try:
            raw_items = await fetcher(context, page, search_term)
            items = [n for n in (normalizer(it) for it in raw_items) if n is not None]
            await process_items(items, search_term, source)
        except Exception as e:
            print(f"[{source}/{search_term}] ERROR en el ciclo de escaneo: {e}")

        wait_time = random.uniform(240, 360)  # 4-6 minutos, en segundos
        print(f"⏳ [{source}/{search_term}] Esperando {wait_time:.0f}s...")
        await asyncio.sleep(wait_time)
        print(f"🔄 [{source}/{search_term}] Actualizando búsqueda...")


async def main():
    global http_client, telegram_queue

    if not ENABLED_SOURCES:
        print("⚠️  No hay ninguna fuente activa (ENABLE_WALLAPOP / ENABLE_VINTED están ambos desactivados). Nada que hacer.")
        return

    # La cola debe crearse dentro del event loop que la va a usar.
    telegram_queue = asyncio.Queue()

    async with httpx.AsyncClient() as client:
        http_client = client

        async with async_playwright() as p:
            # UN SOLO navegador y UN SOLO contexto para todas las
            # keywords. Cada keyword obtiene su propia Page (pestaña)
            # dentro de este mismo contexto: esto es lo que mantiene el
            # consumo de RAM bajo, comparado con lanzar un browser o
            # context por keyword.
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    # Quita una de las señales más comunes que usan los
                    # sitios para detectar automatización/headless.
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                # User-Agent de un Chrome real de escritorio. El UA por
                # defecto en algunas versiones de Playwright headless
                # incluye literalmente "HeadlessChrome", lo cual muchos
                # sitios usan para bloquear directamente la petición.
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="es-ES",
                timezone_id="Europe/Madrid",
            )

            # navigator.webdriver = true es la señal de detección de
            # automatización más común y más fácil de comprobar desde
            # JS. La sobreescribimos a False ANTES de que cargue
            # cualquier página (add_init_script se ejecuta en cada
            # documento nuevo del context, no solo en la página actual).
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            # Un único worker drena la cola de Telegram a ritmo constante.
            # Va aparte de las tareas de escaneo: si lo metiéramos en el
            # gather, un fallo suyo tumbaría todo el watcher.
            sender_task = asyncio.create_task(telegram_sender_worker())
            print(
                f"📨 Worker de Telegram activo (1 mensaje cada "
                f"{TELEGRAM_MIN_INTERVAL:.1f}s como mínimo)."
            )

            tasks = []
            for source in ENABLED_SOURCES:
                for search_term in SEARCHES:
                    tasks.append(
                        asyncio.create_task(watch_search(context, search_term, source))
                    )
                    # Pequeño desfase al abrir cada pestaña para no lanzar
                    # decenas de navegaciones simultáneas de golpe (más
                    # suave para tu máquina y menos "huella" de bot).
                    await asyncio.sleep(random.uniform(1.5, 4.0))

            print(
                f"👀 Vigilando {len(SEARCHES)} búsquedas × {len(ENABLED_SOURCES)} "
                f"fuente(s) ({', '.join(ENABLED_SOURCES) or 'ninguna'}) = "
                f"{len(tasks)} tareas."
            )

            # Mantener el proceso vivo mientras las tareas trabajan.
            try:
                await asyncio.gather(*tasks)
            finally:
                sender_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())


# ============================================================
# NOTAS
# ============================================================
# - Arquitectura de recursos: 1 proceso de Chromium + 1 BrowserContext
#   + N páginas (una por keyword). Esto es mucho más ligero que tener
#   un navegador (o incluso un context) por keyword, porque las páginas
#   comparten el mismo proceso de motor de renderizado y gran parte de
#   la memoria base del navegador.
# - Todo corre en un solo hilo de Python sobre el loop de eventos de
#   asyncio. No hay threads ni Locks "reales" de concurrencia de bajo
#   nivel: las distintas keywords simplemente se ceden el control unas
#   a otras en los puntos "await" (red, timeouts, etc.).
# - Al compartir un mismo BrowserContext, todas las keywords comparten
#   cookies/sesión. Para hacer scraping de búsquedas públicas como esta
#   no debería suponer ningún problema (no hace falta login).
# - El "calentamiento" evita que la primera carga de cada keyword te
#   bombardee con todo el catálogo existente. Se decide POR FUENTE: una
#   fuente calienta solo si no tiene histórico propio en seen.json (menos
#   de MIN_HISTORY_FOR_NO_WARMUP ids suyos). Así, al añadir una fuente
#   nueva a un seen.json ya lleno de otra fuente, la nueva no te notifica
#   su catálogo entero de golpe. Una vez todas las búsquedas de esa fuente
#   han hecho su primera pasada, el aviso por Telegram queda activo.
# - Los mensajes de Telegram NO se envían directamente: se encolan y un
#   único worker los manda espaciados TELEGRAM_MIN_INTERVAL segundos,
#   respetando el retry_after de los 429. Así una ráfaga de anuncios no
#   satura la API de Telegram ni pierde mensajes.
# - Dependencias: pip install playwright httpx && playwright install chromium
#
# ============================================================
# DATOS HISTÓRICOS (wallapop_data.jsonl)
# ============================================================
# Cada vez que se escanea una keyword, se añade UNA LÍNEA por cada
# anuncio que aparece en los resultados (esté ya visto o no). Esto
# genera un histórico completo: si un anuncio sigue publicado durante
# varios escaneos, aparecerá varias veces con distinto "scanned_at" —
# útil para ver evolución de precio en el tiempo, no solo el estado
# actual.
#
# Formato (un objeto JSON por línea, separados por salto de línea):
#   {"scanned_at": "...", "search_term": "...", "item_id": "...",
#    "title": "...", "price": ..., "currency": "EUR",
#    "created_at": "...", "url": "..."}
#
# Por qué JSONL y no un .json con lista: con un .json tradicional, cada
# vez que quieres añadir un registro tendrías que leer el fichero
# entero, parsearlo, añadir la fila, y reescribirlo completo. Con miles
# de registros acumulados esto se vuelve lento y arriesga corromper
# todo el fichero si el proceso se interrumpe a mitad de escritura. Con
# JSONL simplemente añades una línea al final (operación de append),
# sin tocar el resto del fichero.
#
# Cómo convertirlo a CSV (o analizarlo) con pandas, en tu otro programa:
#
#   import pandas as pd
#   df = pd.read_json("wallapop_data.jsonl", lines=True)
#   df.to_csv("wallapop_data.csv", index=False)
#
# Algunos análisis que esta estructura permite directamente:
#   - Precio medio actual por keyword:
#       df.sort_values("scanned_at").groupby("item_id").last() \
#         .groupby("search_term")["price"].mean()
#   - Evolución de precio de un anuncio concreto:
#       df[df.item_id == "ABC123"].sort_values("scanned_at")[["scanned_at", "price"]]
#   - Anuncios únicos vistos por keyword (sin duplicados por repetición
#     en varios escaneos):
#       df.drop_duplicates("item_id").groupby("search_term").size()
#   - Tiempo que lleva un anuncio publicado (created_at) vs. cuándo lo
#     detectaste por primera vez (min(scanned_at) para ese item_id):
#       útil para medir cuánto tardas en detectar anuncios nuevos.

