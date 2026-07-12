# Sistema de monitorización de mercado Wallapop (DS / Pokémon retro)

Tres piezas que trabajan juntas:

1. **`wallapop_watcher.py`** — escanea Wallapop cada 4-6 min por keyword,
   notifica anuncios nuevos por Telegram, y guarda histórico en
   `wallapop_data.jsonl`.
2. **`market_server.py`** — sirve esos datos por HTTP y persiste tus
   exclusiones manuales en `exclusions.json`.
3. **`market_dashboard/`** — proyecto React + Vite: la interfaz visual
   para analizar el mercado.

## Estructura de carpetas esperada

```
tu_carpeta/
├── wallapop_watcher.py
├── market_server.py
├── wallapop_data.jsonl       (lo genera el watcher al correr)
├── exclusions.json           (lo genera market_server.py al usar el dashboard)
└── market_dashboard/
    ├── package.json
    ├── src/
    └── dist/                 (se genera con "npm run build")
```

`market_server.py` espera que `market_dashboard/` sea su hermano
directo. Si prefieres otra organización, puedes apuntar a otra ruta
con la variable de entorno `DASHBOARD_DIST`.

## Primera instalación

```bash
# 1. Dependencias del watcher
pip install playwright httpx --break-system-packages
playwright install chromium

# 2. Dependencias y build del dashboard
cd market_dashboard
npm install
npm run build
cd ..
```

## Uso diario

Necesitas **dos procesos corriendo a la vez**, en dos terminales:

**Terminal 1 — el watcher** (escanea Wallapop y notifica por Telegram):
```bash
export TELEGRAM_BOT_TOKEN="tu_token"
export TELEGRAM_CHAT_ID="tu_chat_id"
python3 wallapop_watcher.py
```

**Terminal 2 — el servidor del dashboard**:
```bash
python3 market_server.py
```

Luego abre **http://localhost:8765** en tu navegador. Se actualiza solo
cada 60 segundos mientras el watcher siga añadiendo datos.

## Si cambias el código del dashboard

Cada vez que edites algo dentro de `market_dashboard/src/`, hay que
reconstruir el build para que `market_server.py` lo sirva actualizado:

```bash
cd market_dashboard
npm run build
```

(`market_server.py` no necesita reiniciarse para esto, solo recargar la
página del navegador después del build.)

## Qué hace el dashboard

- **Filtra ruido automáticamente**: accesorios sueltos (fundas,
  cargadores, baterías...), cómics/manga por tomos, y juegos de otras
  consolas (Switch, PS4, Xbox...) que coinciden por texto con tu
  búsqueda pero no son el producto buscado. Toggle "Ocultar ruido" para
  ver/ocultar.
- **Detecta precios atípicos automáticamente**: outliers estadísticos
  (método MAD, robusto a valores extremos) y precios ≤2€ (casi siempre
  "negociable", no el valor real). Se excluyen del cálculo de mediana
  pero no se ocultan de la tabla cuando el toggle de ruido está
  desactivado.
- **Exclusión manual permanente**: botón "Excluir" en cada fila, para
  marcar anuncios que ningún filtro automático captura (falsos
  positivos, spam). Persiste en `exclusions.json`, sobrevive a
  reinicios y recargas.
- **Exclusión manual solo del cálculo**: botón "Excluir del cálculo" /
  "Incluir en cálculo", para anuncios que quieres seguir viendo pero
  que no deben contar en la mediana de su categoría (igual, persiste en
  disco).
- **Ranking lateral** por precio mediano de cada categoría, y tabla
  ordenable por precio, fecha, o "mejor oferta relativa".

## Mantener sincronizadas las reglas de ruido

Las palabras de exclusión (`NOISE_KEYWORDS`) existen en **dos sitios**
con la misma lista, para que lo que se notifica por Telegram coincida
con lo que el dashboard oculta:

- `wallapop_watcher.py` → variable `NOISE_KEYWORDS`
- `market_dashboard/src/lib/noiseDetection.js` → constante `NOISE_KEYWORDS`

Si detectas un nuevo patrón de ruido, añádelo en **ambos** archivos.
Tras editar el `.js`, recuerda volver a correr `npm run build`.
