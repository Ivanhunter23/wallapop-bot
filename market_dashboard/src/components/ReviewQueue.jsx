import { useState } from "react";
import { formatPrice, formatDate } from "./StatCard";

// Tope de items montados en el DOM. La cola puede traer miles de
// pendientes acumulados y montarlos todos congela el primer render;
// en el panel solo caben ~6 a la vista de todos modos. Al aprobar o
// descartar, la lista se rellena sola con los siguientes.
const RENDER_LIMIT_STEP = 50;

export default function ReviewQueue({ items, onApprove, onDiscard, onDismiss }) {
  const [expanded, setExpanded] = useState(true);
  const [renderLimit, setRenderLimit] = useState(RENDER_LIMIT_STEP);

  if (!items || items.length === 0) return null;

  return (
    <div className="review-panel">
      <div className="review-header" onClick={() => setExpanded((e) => !e)}>
        <span className="review-badge">{items.length}</span>
        <span className="review-title">
          anuncio{items.length !== 1 ? "s" : ""} nuevo{items.length !== 1 ? "s" : ""} — confirma si te interesan
        </span>
        <div className="review-header-actions">
          <button className="review-toggle-btn">{expanded ? "▲ Ocultar" : "▼ Ver"}</button>
          <button
            className="review-dismiss-btn"
            title="Revisar más tarde"
            onClick={(e) => { e.stopPropagation(); onDismiss(); }}
          >
            ✕
          </button>
        </div>
      </div>

      {expanded && (
        <div className="review-list">
          {items.slice(0, renderLimit).map((item) => (
            <div key={item.item_id} className="review-item">
              <div className="review-item-info">
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="review-item-title"
                  title={item.title}
                >
                  {item.title || "(sin título)"}
                </a>
                <div className="review-item-meta">
                  <span className="review-item-kw">{item.search_term}</span>
                  <span className="review-item-price mono">{formatPrice(item.price)}</span>
                  <span className="review-item-date">{formatDate(item.created_at)}</span>
                </div>
              </div>
              <div className="review-item-btns">
                <button className="review-btn approve" onClick={() => onApprove(item.item_id)}>
                  ✓ Me interesa
                </button>
                <button className="review-btn discard" onClick={() => onDiscard(item.item_id, item.title, item.search_term)}>
                  ✗ Descartar
                </button>
              </div>
            </div>
          ))}
          {items.length > renderLimit && (
            <button
              className="show-more-btn"
              onClick={() => setRenderLimit((n) => n + RENDER_LIMIT_STEP)}
            >
              Mostrar {Math.min(RENDER_LIMIT_STEP, items.length - renderLimit)} más
              ({(items.length - renderLimit).toLocaleString("es-ES")} pendientes)
            </button>
          )}
        </div>
      )}
    </div>
  );
}
