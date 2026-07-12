export function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function Controls({
  searchFilter,
  onSearchFilterChange,
  selectedKeyword,
  onSelectedKeywordChange,
  allKeywords,
  sourceFilter,
  onSourceFilterChange,
  excludeZero,
  onExcludeZeroChange,
  hideNoise,
  onHideNoiseChange,
  dayFilter,
  onDayFilterChange,
}) {
  const today = todayStr();
  return (
    <div className="controls">
      <input
        type="text"
        placeholder="Buscar por título o categoría..."
        value={searchFilter}
        onChange={(e) => onSearchFilterChange(e.target.value)}
      />
      <select value={selectedKeyword} onChange={(e) => onSelectedKeywordChange(e.target.value)}>
        <option value="all">Todas las categorías</option>
        {allKeywords.map((kw) => (
          <option key={kw} value={kw}>{kw}</option>
        ))}
      </select>
      <select value={sourceFilter} onChange={(e) => onSourceFilterChange(e.target.value)}>
        <option value="all">Todas las fuentes</option>
        <option value="wallapop">Wallapop</option>
        <option value="vinted">Vinted</option>
      </select>
      <div className="day-filter">
        <span className="day-label">Publicado el día:</span>
        <button
          type="button"
          className={`day-btn ${dayFilter === today ? "active" : ""}`}
          onClick={() => onDayFilterChange(dayFilter === today ? "" : today)}
        >
          Hoy
        </button>
        <input
          type="date"
          max={today}
          value={dayFilter}
          onChange={(e) => onDayFilterChange(e.target.value)}
        />
        {dayFilter && (
          <button type="button" className="day-btn" onClick={() => onDayFilterChange("")}>
            Todos
          </button>
        )}
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={excludeZero}
          onChange={(e) => onExcludeZeroChange(e.target.checked)}
        />
        Excluir precio 0€ (intercambios)
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={hideNoise}
          onChange={(e) => onHideNoiseChange(e.target.checked)}
        />
        Ocultar ruido (accesorios, otras consolas, cómics)
      </label>
    </div>
  );
}
