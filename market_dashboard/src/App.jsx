import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { fetchMarketData, fetchExclusions, updateExclusion, fetchPending, submitReview, fetchLearnedFilters, deleteLearnedFilter } from "./lib/api";
import { buildMarketView } from "./lib/marketData";
import { isNoise } from "./lib/noiseDetection";
import StatCard, { formatPrice } from "./components/StatCard";
import Controls from "./components/Controls";
import MarketRow from "./components/MarketRow";
import KeywordRanking from "./components/KeywordRanking";
import ReviewQueue from "./components/ReviewQueue";

const POLL_INTERVAL_MS = 60000;

// Cuántas filas se montan en el DOM de golpe. Sin este tope, un filtro
// permisivo (ej. desactivar "ocultar ruido") monta 15.000+ <tr> y el
// primer render tarda ~15s en móvil. El botón "Mostrar más" amplía el
// tope de RENDER_CHUNK en RENDER_CHUNK; los cálculos (medianas, stats)
// siguen usando la lista completa, esto solo limita lo que se pinta.
const RENDER_CHUNK = 500;

function SortArrow({ column, sort }) {
  if (sort.column !== column) return <span className="sort-arrow inactive">▲</span>;
  return <span className="sort-arrow active">{sort.direction === "asc" ? "▲" : "▼"}</span>;
}

export default function App() {
  const [rawRows, setRawRows] = useState([]);
  const [exclusions, setExclusions] = useState({ excluded: [], excludedFromCalc: [] });
  const [learnedFilters, setLearnedFilters] = useState({ rules: [] });
  const [pendingItems, setPendingItems] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  const [searchFilter, setSearchFilter] = useState("");
  const [selectedKeyword, setSelectedKeyword] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sort, setSort] = useState({ column: "price", direction: "asc" });
  const [excludeZero, setExcludeZero] = useState(true);
  const [hideNoise, setHideNoise] = useState(true);
  const [dayFilter, setDayFilter] = useState("");
  const [renderLimit, setRenderLimit] = useState(RENDER_CHUNK);

  // Al cambiar cualquier filtro u orden se vuelve al tope inicial (la
  // lista es otra). No depende de visibleItems para que el refresco de
  // datos de cada 60s no deshaga los "Mostrar más" del usuario.
  useEffect(() => {
    setRenderLimit(RENDER_CHUNK);
  }, [hideNoise, selectedKeyword, sourceFilter, excludeZero, dayFilter, searchFilter, sort]);

  const handleSort = useCallback((column) => {
    setSort((prev) => ({
      column,
      direction: prev.column === column && prev.direction === "asc" ? "desc" : "asc",
    }));
  }, []);

  const isMountedRef = useRef(true);
  useEffect(() => () => { isMountedRef.current = false; }, []);

  const loadData = useCallback(async () => {
    try {
      const data = await fetchMarketData();
      if (!isMountedRef.current) return;
      if (data.error && (!data.rows || data.rows.length === 0)) {
        setErrorMsg(data.error);
      } else {
        setErrorMsg(null);
        setRawRows(data.rows);
        setLastUpdated(new Date());
      }
    } catch (e) {
      if (!isMountedRef.current) return;
      setErrorMsg("No se pudo conectar con el servidor local (¿sigue corriendo market_server.py?)");
    }
  }, []);

  const loadExclusions = useCallback(async () => {
    try {
      const data = await fetchExclusions();
      if (!isMountedRef.current) return;
      setExclusions(data);
    } catch (e) {
      console.error("No se pudieron cargar las exclusiones:", e);
    }
  }, []);

  const loadLearnedFilters = useCallback(async () => {
    try {
      const data = await fetchLearnedFilters();
      if (!isMountedRef.current) return;
      setLearnedFilters(data);
    } catch (e) {
      // Fallo silencioso: si el servidor aún no tiene el endpoint nuevo,
      // simplemente no se aplican filtros aprendidos.
    }
  }, []);

  const loadPending = useCallback(async () => {
    try {
      const data = await fetchPending();
      if (!isMountedRef.current) return;
      setPendingItems(data.pending || []);
    } catch (e) {
      // Fallo silencioso: la cola de revisión es opcional
    }
  }, []);

  useEffect(() => {
    loadData();
    loadExclusions();
    loadLearnedFilters();
    loadPending();
    const interval = setInterval(loadData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadData, loadExclusions, loadLearnedFilters, loadPending]);

  const handleApprove = useCallback(async (itemId) => {
    setPendingItems((prev) => prev.filter((i) => i.item_id !== itemId));
    try {
      await submitReview(itemId, "approve");
    } catch (e) {
      console.error("No se pudo confirmar la revisión:", e);
    }
  }, []);

  const handleDiscard = useCallback(async (itemId, title, searchTerm) => {
    setPendingItems((prev) => prev.filter((i) => i.item_id !== itemId));
    setExclusions((prev) => ({ ...prev, excluded: [...prev.excluded, itemId] }));
    try {
      await submitReview(itemId, "discard", { title, searchTerm });
      if (title && searchTerm) loadLearnedFilters();
    } catch (e) {
      setExclusions((prev) => ({ ...prev, excluded: prev.excluded.filter((id) => id !== itemId) }));
      setPendingItems((prev) => [...prev]);
    }
  }, [loadLearnedFilters]);

  const handleDismissReview = useCallback(() => {
    setPendingItems([]);
  }, []);

  const handleExclude = useCallback(async (itemId, title, searchTerm) => {
    setExclusions((prev) => ({ ...prev, excluded: [...prev.excluded, itemId] }));
    try {
      const updated = await updateExclusion(itemId, "exclude", { title, searchTerm });
      setExclusions(updated);
      if (title && searchTerm) loadLearnedFilters();
    } catch (e) {
      setExclusions((prev) => ({ ...prev, excluded: prev.excluded.filter((id) => id !== itemId) }));
      alert("No se pudo guardar la exclusión. ¿Sigue corriendo market_server.py?");
    }
  }, [loadLearnedFilters]);

  const handleExcludeFromCalc = useCallback(async (itemId, shouldExclude) => {
    const action = shouldExclude ? "excludeFromCalc" : "unexcludeFromCalc";
    setExclusions((prev) => ({
      ...prev,
      excludedFromCalc: shouldExclude
        ? [...prev.excludedFromCalc, itemId]
        : prev.excludedFromCalc.filter((id) => id !== itemId),
    }));
    try {
      const updated = await updateExclusion(itemId, action);
      setExclusions(updated);
    } catch (e) {
      setExclusions((prev) => ({
        ...prev,
        excludedFromCalc: shouldExclude
          ? prev.excludedFromCalc.filter((id) => id !== itemId)
          : [...prev.excludedFromCalc, itemId],
      }));
      alert("No se pudo guardar el cambio. ¿Sigue corriendo market_server.py?");
    }
  }, []);

  const { items, allKeywords, statsByKeyword } = useMemo(
    () => buildMarketView(rawRows, exclusions, learnedFilters),
    [rawRows, exclusions, learnedFilters]
  );

  const visibleItems = useMemo(() => {
    let rows = items;

    if (hideNoise) {
      rows = rows.filter((r) => !r.isNoiseAuto && !r.isPriceOutlierAuto);
    }
    if (selectedKeyword !== "all") {
      rows = rows.filter((r) => r.search_term === selectedKeyword);
    }
    if (sourceFilter !== "all") {
      rows = rows.filter((r) => (r.source || "wallapop") === sourceFilter);
    }
    if (excludeZero) {
      rows = rows.filter((r) => r.price > 0);
    }
    if (dayFilter) {
      rows = rows.filter((r) => (r.created_at || "").slice(0, 10) === dayFilter);
    }
    if (searchFilter.trim()) {
      const q = searchFilter.trim().toLowerCase();
      rows = rows.filter(
        (r) => (r.title || "").toLowerCase().includes(q) || (r.search_term || "").toLowerCase().includes(q)
      );
    }

    const sorted = [...rows];
    const dir = sort.direction === "asc" ? 1 : -1;
    switch (sort.column) {
      case "price":
        sorted.sort((a, b) => dir * ((a.price ?? Infinity) - (b.price ?? Infinity)));
        break;
      case "search_term":
        sorted.sort((a, b) => dir * (a.search_term || "").localeCompare(b.search_term || ""));
        break;
      case "created_at":
        sorted.sort((a, b) => dir * (a.created_at || "").localeCompare(b.created_at || ""));
        break;
      case "sightingCount":
        sorted.sort((a, b) => dir * ((a.sightingCount ?? 0) - (b.sightingCount ?? 0)));
        break;
      case "deal":
        sorted.sort((a, b) => {
          const sa = statsByKeyword.get(a.search_term)?.median;
          const sb = statsByKeyword.get(b.search_term)?.median;
          const ra = sa ? a.price / sa : 1;
          const rb = sb ? b.price / sb : 1;
          return dir * (ra - rb);
        });
        break;
    }
    return sorted;
  }, [items, hideNoise, selectedKeyword, sourceFilter, excludeZero, dayFilter, searchFilter, sort, statsByKeyword]);

  const globalStats = useMemo(() => {
    const allPrices = [];
    for (const item of items) {
      if (item.isNoiseAuto || item.isPriceOutlierAuto || item.isExcludedFromCalcManually) continue;
      if (typeof item.price === "number" && (!excludeZero || item.price > 0)) {
        allPrices.push(item.price);
      }
    }
    const sorted = [...allPrices].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const medianPrice = sorted.length === 0
      ? null
      : sorted.length % 2 !== 0
        ? sorted[mid]
        : (sorted[mid - 1] + sorted[mid]) / 2;

    return {
      totalUnique: items.length,
      totalKeywords: allKeywords.length,
      medianPrice,
      minPrice: sorted.length ? sorted[0] : null,
      maxPrice: sorted.length ? sorted[sorted.length - 1] : null,
    };
  }, [items, allKeywords, excludeZero]);

  const handleDeleteLearnedFilter = useCallback(async (ruleId) => {
    try {
      const updated = await deleteLearnedFilter(ruleId);
      setLearnedFilters(updated);
    } catch (e) {
      console.error("No se pudo eliminar el filtro:", e);
    }
  }, []);

  const noiseCount = useMemo(
    () => items.filter((i) => i.isNoiseAuto || i.isPriceOutlierAuto).length,
    [items]
  );

  if (rawRows.length === 0 && !errorMsg) {
    return (
      <div className="wrap">
        <div className="loading-msg">
          <div className="spinner" />
          Cargando datos del mercado...
        </div>
      </div>
    );
  }

  return (
    <div className="wrap">
      <div className="header">
        <div className="header-title-group">
          <div className="header-mark">🎮</div>
          <div>
            <div className="header-label mono">wallapop_data.jsonl</div>
            <h1>Mercado de retro DS y Pokémon</h1>
          </div>
        </div>
        <div className={`status mono ${errorMsg ? "stale" : ""}`}>
          {errorMsg ? errorMsg : lastUpdated ? `Actualizado ${lastUpdated.toLocaleTimeString("es-ES")}` : "—"}
        </div>
      </div>

      {rawRows.length === 0 ? (
        <div className="loading-msg">{errorMsg}</div>
      ) : (
        <>
          <ReviewQueue
            items={pendingItems.filter((i) => !isNoise(i.title))}
            onApprove={handleApprove}
            onDiscard={handleDiscard}
            onDismiss={handleDismissReview}
          />

          <div className="stat-grid">
            <StatCard label="Anuncios únicos" value={globalStats.totalUnique.toLocaleString("es-ES")} />
            <StatCard label="Categorías" value={globalStats.totalKeywords} />
            <StatCard label="Avistamientos totales" value={rawRows.length.toLocaleString("es-ES")} />
            <StatCard label="Precio mediano" value={formatPrice(globalStats.medianPrice)} accent="var(--accent)" />
            <StatCard label="Precio mínimo" value={formatPrice(globalStats.minPrice)} />
            <StatCard label="Precio máximo" value={formatPrice(globalStats.maxPrice)} accent="var(--danger)" />
          </div>

          <Controls
            searchFilter={searchFilter}
            onSearchFilterChange={setSearchFilter}
            selectedKeyword={selectedKeyword}
            onSelectedKeywordChange={setSelectedKeyword}
            allKeywords={allKeywords}
            sourceFilter={sourceFilter}
            onSourceFilterChange={setSourceFilter}
            excludeZero={excludeZero}
            onExcludeZeroChange={setExcludeZero}
            hideNoise={hideNoise}
            onHideNoiseChange={setHideNoise}
            dayFilter={dayFilter}
            onDayFilterChange={setDayFilter}
          />

          {hideNoise && noiseCount > 0 && (
            <div className="noise-note mono">
              🔇 {noiseCount} anuncio(s) detectado(s) como ruido o precio atípico, ocultos del análisis
            </div>
          )}
          {!hideNoise && noiseCount > 0 && (
            <div className="noise-note mono">
              ⚠️ Mostrando {noiseCount} anuncio(s) marcados como ruido/atípico (filtro desactivado)
            </div>
          )}

          {learnedFilters.rules.length > 0 && (
            <details className="learned-filters-panel">
              <summary className="mono">
                🧠 {learnedFilters.rules.length} filtro(s) aprendido(s) activos — anuncios similares a los que descartaste se ocultan automáticamente
              </summary>
              <div className="learned-filters-list">
                {learnedFilters.rules.map((rule) => (
                  <div key={rule.id} className="learned-filter-row mono">
                    <span className="lf-search">[{rule.search_term}]</span>
                    <span className="lf-title">{rule.title}</span>
                    <button
                      className="lf-delete-btn"
                      title="Eliminar este filtro aprendido"
                      onClick={() => handleDeleteLearnedFilter(rule.id)}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </details>
          )}

          <div className="layout">
            <div className="main-col">
              <div className="count-line mono">
                {visibleItems.length > renderLimit
                  ? `${renderLimit} de ${visibleItems.length} anuncios`
                  : `${visibleItems.length} anuncios mostrados`}
                {dayFilter && ` · publicados el ${dayFilter}`}
              </div>
              <div className="table-wrap">
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Anuncio</th>
                        <th className="sortable" onClick={() => handleSort("search_term")}>
                          Categoría <SortArrow column="search_term" sort={sort} />
                        </th>
                        <th className="right sortable" onClick={() => handleSort("price")}>
                          Precio <SortArrow column="price" sort={sort} />
                        </th>
                        <th className="sortable" onClick={() => handleSort("deal")}>
                          Posición en mercado <SortArrow column="deal" sort={sort} />
                        </th>
                        <th className="right sortable" onClick={() => handleSort("created_at")}>
                          Publicado <SortArrow column="created_at" sort={sort} />
                        </th>
                        <th className="right sortable" onClick={() => handleSort("sightingCount")}>
                          Avistado <SortArrow column="sightingCount" sort={sort} />
                        </th>
                        <th className="right">Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleItems.length > 0 ? (
                        <>
                          {visibleItems.slice(0, renderLimit).map((item) => (
                            <MarketRow
                              key={item.item_id}
                              item={item}
                              stats={statsByKeyword.get(item.search_term)}
                              onExclude={handleExclude}
                              onExcludeFromCalc={handleExcludeFromCalc}
                            />
                          ))}
                          {visibleItems.length > renderLimit && (
                            <tr>
                              <td colSpan={7} className="show-more-row">
                                <button
                                  className="show-more-btn"
                                  onClick={() => setRenderLimit((n) => n + RENDER_CHUNK)}
                                >
                                  Mostrar {Math.min(RENDER_CHUNK, visibleItems.length - renderLimit)} más
                                  ({(visibleItems.length - renderLimit).toLocaleString("es-ES")} restantes)
                                </button>
                              </td>
                            </tr>
                          )}
                        </>
                      ) : (
                        <tr>
                          <td colSpan={7} className="empty-row">
                            No hay anuncios que coincidan con los filtros actuales.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <KeywordRanking
              statsByKeyword={statsByKeyword}
              selectedKeyword={selectedKeyword}
              onSelect={setSelectedKeyword}
            />
          </div>
        </>
      )}
    </div>
  );
}
