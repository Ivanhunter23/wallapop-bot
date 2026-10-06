"""
Servidor local para el dashboard de análisis de mercado.

Hace dos cosas, sin tocar el watcher para nada:
  1. Lee wallapop_data.jsonl y lo expone por HTTP (/api/data) para que
     el frontend pueda consultarlo y refrescarse automáticamente.
  2. Persiste en disco (exclusions.json) las exclusiones manuales que
     marques en el dashboard (anuncios falsos, o precios que no deben
     contar en el cálculo de mediana), vía /api/exclusions.

También sirve los ficheros estáticos del build de Vite (carpeta dist/),
así que solo necesitas este único proceso Python corriendo para usar
todo el dashboard.

Uso:
    # 1. Generar el build del frontend (una vez, o cada vez que cambies
    #    el código del dashboard):
    cd market_dashboard && npm run build

    # 2. Arrancar el servidor (sirve market_dashboard/dist):
    python3 market_server.py
    (luego abre http://localhost:8765 en el navegador)

Puedes dejarlo corriendo indefinidamente junto al watcher; cada vez que
el navegador hace polling, este servidor relee el fichero del disco, así
que siempre verás los datos más recientes que el watcher haya guardado.
"""

import json
import os
import re
import threading
import unicodedata
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ============================================================
# CONFIGURACIÓN
# ============================================================
DATA_FILE = os.environ.get("WALLAPOP_DATA_FILE", "wallapop_data.jsonl")
EXCLUSIONS_FILE = os.environ.get("EXCLUSIONS_FILE", "exclusions.json")
LEARNED_FILTERS_FILE = os.environ.get("LEARNED_FILTERS_FILE", "learned_filters.json")
REVIEWED_FILE = os.environ.get("REVIEWED_FILE", "reviewed.json")
HOST = "127.0.0.1"
PORT = 8765

# Carpeta del build de Vite. Por defecto se espera que market_server.py
# y la carpeta del proyecto Vite (market_dashboard/) sean hermanos en el
# mismo directorio. Si organizas las carpetas de otra forma, puedes
# sobreescribir la ruta completa con la variable de entorno
# DASHBOARD_DIST.
DIST_DIR = Path(os.environ.get("DASHBOARD_DIST", str(Path(__file__).parent / "market_dashboard" / "dist")))

# Tipos MIME básicos para servir los estáticos del build (JS, CSS, etc).
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

exclusions_lock = threading.Lock()
learned_filters_lock = threading.Lock()
reviewed_lock = threading.Lock()

# ============================================================
# FILTROS APRENDIDOS
# ============================================================
# Palabras muy comunes que no aportan señal discriminadora si aparecen
# en el título excluido. Se filtran al extraer las palabras clave de un
# título para que el umbral de matching sea sobre palabras significativas.
_FILTER_STOPWORDS = {
    "the", "and", "for", "que", "con", "del", "los", "las", "una",
    "par", "per", "von", "para", "nintendo", "juego", "juegos",
}


def extract_filter_words(title: str) -> list[str]:
    """
    Extrae palabras significativas de un título para usarlas como patrón
    de un filtro aprendido. Normaliza a ASCII minúsculas, descarta palabras
    de ≤2 caracteres y palabras vacías comunes.
    """
    normalized = unicodedata.normalize("NFD", title.lower())
    ascii_text = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    words = re.findall(r"\b[a-z0-9]{3,}\b", ascii_text)
    return [w for w in words if w not in _FILTER_STOPWORDS]


def matches_learned_filter(title: str, search_term: str, rules: list) -> bool:
    """
    Devuelve True si el título coincide con alguna regla aprendida para
    esta búsqueda. Misma lógica que `is_learned_excluded` en
    wallapop_watcher.py: un título coincide si contiene TODAS las palabras
    del patrón (el título es un superconjunto del patrón).

    Se exige coincidencia total para no arrasar juegos legítimos cuyo
    nombre comparte casi todas las palabras con el ruido (p.ej. excluir
    "Folleto Mundo Misterioso Exploradores del Cielo" no debe borrar el
    juego "Pokémon Mundo Misterioso Exploradores del Cielo"; la palabra
    discriminante "folleto", ausente en el juego, lo protege).

    Se usa para que el dashboard NO meta en la cola de confirmación
    anuncios que ya están cubiertos por una regla: el filtro aprendido
    actúa automáticamente, igual que en el watcher con Telegram. La
    comprobación es en tiempo de lectura (no se persiste): si más adelante
    borras la regla, esos anuncios vuelven a aparecer como pendientes.
    """
    if not rules:
        return False
    candidate = set(extract_filter_words(title))
    for rule in rules:
        if rule.get("search_term") != search_term:
            continue
        rule_words = rule.get("words", [])
        if not rule_words:
            continue
        if all(w in candidate for w in rule_words):
            return True
    return False


def read_learned_filters() -> dict:
    if not os.path.exists(LEARNED_FILTERS_FILE):
        return {"rules": [], "next_id": 1}
    try:
        with open(LEARNED_FILTERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "rules": data.get("rules", []),
                "next_id": data.get("next_id", 1),
            }
    except Exception:
        return {"rules": [], "next_id": 1}


def write_learned_filters(data: dict):
    with open(LEARNED_FILTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_learned_filter_rule(search_term: str, title: str, item_id: str):
    """
    Crea una regla nueva que auto-excluirá anuncios con título similar a
    `title` cuando aparezcan en la búsqueda `search_term`. Si ya existe
    una regla idéntica (mismo search_term + mismas palabras clave), no
    crea duplicado.
    """
    words = extract_filter_words(title)
    if not words:
        return
    with learned_filters_lock:
        data = read_learned_filters()
        for rule in data["rules"]:
            if rule.get("search_term") == search_term and rule.get("words") == words:
                return  # ya existe
        rule = {
            "id": data["next_id"],
            "search_term": search_term,
            "title": title,
            "words": words,
            "excluded_item_id": item_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["rules"].append(rule)
        data["next_id"] += 1
        write_learned_filters(data)


def read_jsonl_safely(path: str):
    """
    Lee el fichero JSONL línea a línea, ignorando líneas que no se
    puedan parsear. Esto es importante porque el watcher puede estar
    escribiendo una línea nueva justo en el instante en que el servidor
    lee el fichero: la última línea podría estar a medio escribir. En
    ese caso, simplemente se descarta esa línea concreta (se recogerá
    completa en la siguiente lectura, un minuto después) en vez de
    fallar toda la petición.
    """
    if not os.path.exists(path):
        return [], f"No se encontró el fichero de datos: {path}"

    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        return [], f"Error leyendo el fichero: {e}"

    return rows, None


def read_exclusions():
    if not os.path.exists(EXCLUSIONS_FILE):
        return {"excluded": [], "excludedFromCalc": []}
    try:
        with open(EXCLUSIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "excluded": data.get("excluded", []),
                "excludedFromCalc": data.get("excludedFromCalc", []),
            }
    except Exception:
        # Si el fichero está corrupto por alguna razón, no rompemos el
        # servidor: simplemente se actúa como si no hubiera exclusiones
        # guardadas (el usuario puede volver a marcar lo que necesite).
        return {"excluded": [], "excludedFromCalc": []}


def write_exclusions(data):
    with open(EXCLUSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_reviewed():
    """Devuelve el set de item_ids ya revisados, o None si el fichero no existe todavía."""
    if not os.path.exists(REVIEWED_FILE):
        return None
    try:
        with open(REVIEWED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("reviewed", []))
    except Exception:
        return set()


def write_reviewed(reviewed_set):
    with open(REVIEWED_FILE, "w", encoding="utf-8") as f:
        json.dump({"reviewed": sorted(reviewed_set)}, f, ensure_ascii=False, indent=2)


def apply_exclusion_action(item_id: str, action: str):
    """
    Modifica el estado de exclusión de un item_id según la acción
    pedida, y persiste el resultado en disco. Devuelve el estado
    completo actualizado de exclusiones.
    """
    with exclusions_lock:
        data = read_exclusions()
        excluded = set(data["excluded"])
        excluded_from_calc = set(data["excludedFromCalc"])

        if action == "exclude":
            excluded.add(item_id)
        elif action == "unexclude":
            excluded.discard(item_id)
        elif action == "excludeFromCalc":
            excluded_from_calc.add(item_id)
        elif action == "unexcludeFromCalc":
            excluded_from_calc.discard(item_id)
        else:
            raise ValueError(f"Acción desconocida: {action}")

        new_data = {
            "excluded": sorted(excluded),
            "excludedFromCalc": sorted(excluded_from_calc),
        }
        write_exclusions(new_data)
        return new_data


class Handler(BaseHTTPRequestHandler):
    # Silenciamos el log por defecto de BaseHTTPRequestHandler (escribe
    # una línea por petición a stderr); imprimimos algo más legible
    # solo para los métodos que nos interesan.
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # CORS abierto: como esto corre en localhost para uso personal,
        # no hay necesidad de restringir orígenes.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message, status=400):
        self._send_json({"error": message}, status=status)

    def _send_static_file(self, path: Path):
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        mime = MIME_TYPES.get(path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        # Preflight CORS: los navegadores lo mandan automáticamente
        # antes de un POST con Content-Type: application/json. Sin
        # responder esto, el POST real nunca llega a salir del navegador.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/data"):
            rows, error = read_jsonl_safely(DATA_FILE)
            if error and not rows:
                self._send_json({"rows": [], "error": error}, status=200)
                return
            self._send_json({"rows": rows, "error": None})
            return

        if self.path.startswith("/api/exclusions"):
            self._send_json(read_exclusions())
            return

        if self.path.startswith("/api/learned_filters"):
            with learned_filters_lock:
                data = read_learned_filters()
            self._send_json({"rules": data["rules"]})
            return

        if self.path.startswith("/api/pending"):
            rows, _ = read_jsonl_safely(DATA_FILE)
            # Deduplicar por item_id (el último avistamiento gana)
            by_id = {}
            for row in rows:
                iid = row.get("item_id")
                if iid:
                    by_id[iid] = row

            with reviewed_lock:
                reviewed = read_reviewed()
                if reviewed is None:
                    # Primera vez: auto-inicializar con todos los ids existentes
                    # para no inundar de golpe con anuncios ya conocidos.
                    write_reviewed(set(by_id.keys()))
                    self._send_json({"pending": []})
                    return
                exclusions = read_exclusions()
                excluded_set = set(exclusions["excluded"])
                # Los filtros aprendidos actúan automáticamente: si un
                # anuncio ya coincide con una regla, NO se mete en la cola
                # de confirmación (solo quedan los casos dudosos que ningún
                # filtro decide). No se persiste como "reviewed": es un
                # filtrado dinámico, así que borrar la regla los revive.
                lf_rules = read_learned_filters()["rules"]
                pending = [
                    item for iid, item in by_id.items()
                    if iid not in reviewed
                    and iid not in excluded_set
                    and not matches_learned_filter(
                        item.get("title", ""), item.get("search_term", ""), lf_rules
                    )
                ]

            pending.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            self._send_json({"pending": pending})
            return

        # Servir estáticos del build de Vite.
        self._serve_static_path()

    def do_POST(self):
        if self.path.startswith("/api/exclusions"):
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                self._send_error_json("Cuerpo de la petición no es JSON válido.")
                return

            item_id = body.get("item_id")
            action = body.get("action")
            if not item_id or action not in (
                "exclude", "unexclude", "excludeFromCalc", "unexcludeFromCalc"
            ):
                self._send_error_json(
                    "Se requiere 'item_id' y una 'action' válida "
                    "(exclude/unexclude/excludeFromCalc/unexcludeFromCalc)."
                )
                return

            try:
                updated = apply_exclusion_action(item_id, action)
            except Exception as e:
                self._send_error_json(f"Error aplicando la exclusión: {e}", status=500)
                return

            # Si se excluye un anuncio y el cliente proporciona título y
            # búsqueda, crear automáticamente un filtro aprendido para que
            # anuncios similares no vuelvan a aparecer en esa búsqueda.
            title = body.get("title", "").strip()
            search_term = body.get("search_term", "").strip()
            if action == "exclude" and title and search_term:
                add_learned_filter_rule(search_term, title, item_id)

            self._send_json(updated)
            return

        if self.path.startswith("/api/learned_filters"):
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                self._send_error_json("Cuerpo de la petición no es JSON válido.")
                return

            action = body.get("action")
            if action == "delete":
                rule_id = body.get("rule_id")
                if rule_id is None:
                    self._send_error_json("Se requiere 'rule_id' para borrar una regla.")
                    return
                with learned_filters_lock:
                    data = read_learned_filters()
                    data["rules"] = [r for r in data["rules"] if r.get("id") != rule_id]
                    write_learned_filters(data)
                self._send_json({"rules": data["rules"]})
            else:
                self._send_error_json("Acción no reconocida. Usa 'delete'.")
            return

        if self.path.startswith("/api/review"):
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                self._send_error_json("Cuerpo de la petición no es JSON válido.")
                return

            item_id = body.get("item_id")
            action = body.get("action")
            if not item_id or action not in ("approve", "discard"):
                self._send_error_json("Se requiere 'item_id' y 'action' (approve/discard).")
                return

            with reviewed_lock:
                reviewed = read_reviewed() or set()
                reviewed.add(item_id)
                write_reviewed(reviewed)

            if action == "discard":
                apply_exclusion_action(item_id, "exclude")
                title = body.get("title", "").strip()
                search_term = body.get("search_term", "").strip()
                if title and search_term:
                    add_learned_filter_rule(search_term, title, item_id)

            self._send_json({"ok": True})
            return

        self.send_response(404)
        self.end_headers()

    def _serve_static_path(self):
        if not DIST_DIR.exists():
            self._send_json(
                {
                    "error": (
                        "No se encontró market_dashboard/dist. "
                        "Ejecuta 'npm run build' dentro de market_dashboard/ "
                        "antes de arrancar este servidor."
                    )
                },
                status=200,
            )
            return

        # Quitar query string si la hay, y normalizar "/" -> index.html
        clean_path = self.path.split("?")[0]
        if clean_path == "/":
            clean_path = "/index.html"

        file_path = DIST_DIR / clean_path.lstrip("/")

        # Si la ruta no corresponde a un fichero real (típico en SPAs
        # con rutas del lado del cliente), servimos index.html como
        # fallback en vez de un 404 — esta app no usa rutas de cliente
        # por ahora, pero deja la puerta abierta sin sorpresas si se
        # añaden en el futuro.
        if not file_path.is_file():
            file_path = DIST_DIR / "index.html"

        self._send_static_file(file_path)


def main():
    print(f"Sirviendo datos desde: {os.path.abspath(DATA_FILE)}")
    print(f"Exclusiones persistidas en: {os.path.abspath(EXCLUSIONS_FILE)}")
    print(f"Filtros aprendidos en: {os.path.abspath(LEARNED_FILTERS_FILE)}")
    print(f"Frontend (build de Vite): {DIST_DIR}")
    if not DIST_DIR.exists():
        print(
            "\n⚠️  No se encontró el build del frontend. Ejecuta:\n"
            "    cd market_dashboard && npm install && npm run build\n"
            "antes de usar el dashboard.\n"
        )
    print(f"Abre http://{HOST}:{PORT} en tu navegador")
    print("(Ctrl+C para detener)")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
        server.shutdown()


if __name__ == "__main__":
    main()
