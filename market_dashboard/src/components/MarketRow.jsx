import { formatPrice, formatDate } from "./StatCard";

const GOOD_DEAL_THRESHOLD = 0.85;
const PRICEY_THRESHOLD = 1.25;

// Distintivo por marketplace de origen. Los colores siguen los tokens
// de index.css (--info / verde azulado) para no desentonar con el tema.
const SOURCE_BADGES = {
  wallapop: { text: "Wallapop", color: "#52a8cd" },
  vinted: { text: "Vinted", color: "#3fb08a" },
};

export default function MarketRow({ item, stats, onExclude, onExcludeFromCalc }) {
  const ratio = stats?.median ? item.price / stats.median : null;
  let barColor = "#9ba2b2";
  let label = "—";
  if (ratio !== null && item.price > 0) {
    if (ratio <= GOOD_DEAL_THRESHOLD) {
      barColor = "#86c06c";
      label = "Buena oferta";
    } else if (ratio >= PRICEY_THRESHOLD) {
      barColor = "#e86a4d";
      label = "Por encima";
    } else {
      barColor = "#9ba2b2";
      label = "En línea";
    }
  }

  let barPct = 50;
  if (stats?.min !== null && stats?.max !== null && stats.max > stats.min && item.price > 0) {
    barPct = Math.min(100, Math.max(0, ((item.price - stats.min) / (stats.max - stats.min)) * 100));
  }

  // Un anuncio puede estar marcado por varias razones distintas a la
  // vez (ej: ruido automático Y excluido manualmente del cálculo). Las
  // mostramos todas como pequeñas etiquetas, no solo la primera que
  // coincida, para que quede claro por qué un precio no cuenta.
  const tags = [];
  if (item.isNoiseAuto) tags.push({ text: "ruido auto", color: "#e86a4d" });
  if (item.isPriceOutlierAuto) tags.push({ text: "precio atípico", color: "#e3a851" });
  if (item.isExcludedFromCalcManually) tags.push({ text: "excluido del cálculo", color: "#9ba2b2" });

  const rowDimmed = item.isNoiseAuto || item.isPriceOutlierAuto || item.isExcludedFromCalcManually;

  const sourceBadge = SOURCE_BADGES[item.source] || SOURCE_BADGES.wallapop;

  return (
    <tr className={rowDimmed ? "dimmed" : undefined}>
      <td className="title-cell">
        {/* El color de cada badge se inyecta como variable CSS, así una
            sola clase .badge sirve para fuentes y para etiquetas de estado. */}
        <span className="badge" title={`Origen: ${sourceBadge.text}`} style={{ "--badge-color": sourceBadge.color }}>
          {sourceBadge.text}
        </span>
        {tags.map((t) => (
          <span key={t.text} className="badge" title={t.text} style={{ "--badge-color": t.color }}>
            {t.text}
          </span>
        ))}
        <a href={item.url} target="_blank" rel="noopener noreferrer" title={item.title}>
          {item.title || "(sin título)"}
        </a>
      </td>
      <td className="kw-cell">{item.search_term}</td>
      <td className="right mono price-cell">{formatPrice(item.price)}</td>
      <td>
        <div className="pos-bar-wrap">
          <div className="pos-track">
            <div className="pos-marker" style={{ left: `${barPct}%`, background: barColor, color: barColor }} />
          </div>
          <span className="pos-label" style={{ color: barColor }}>{label}</span>
        </div>
      </td>
      <td className="right muted-cell">{formatDate(item.created_at)}</td>
      <td className="right muted-cell mono">{item.sightingCount}×</td>
      <td className="right actions-cell">
        <button
          className="action-btn"
          title="Excluir este anuncio y aprender a filtrar títulos similares en esta búsqueda"
          onClick={() => onExclude(item.item_id, item.title, item.search_term)}
        >
          Excluir
        </button>
        <button
          className="action-btn"
          title={
            item.isExcludedFromCalcManually
              ? "Volver a incluir este precio en el cálculo de mediana"
              : "Mantener visible, pero no contar su precio en la mediana"
          }
          onClick={() => onExcludeFromCalc(item.item_id, !item.isExcludedFromCalcManually)}
        >
          {item.isExcludedFromCalcManually ? "Incluir en cálculo" : "Excluir del cálculo"}
        </button>
      </td>
    </tr>
  );
}
