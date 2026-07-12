// Cliente del backend Python (market_server.py). Centraliza las rutas
// y el manejo de errores de red, para que los componentes no tengan
// que repetir try/catch de fetch.

const API_BASE = ""; // mismo origen: market_server.py sirve también el frontend

export async function fetchMarketData() {
  const res = await fetch(`${API_BASE}/api/data`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Error del servidor (${res.status})`);
  }
  return res.json(); // { rows: [...], error: string|null }
}

export async function fetchExclusions() {
  const res = await fetch(`${API_BASE}/api/exclusions`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Error del servidor (${res.status})`);
  }
  return res.json(); // { excluded: [...], excludedFromCalc: [...] }
}

/**
 * action: "exclude" | "unexclude" | "excludeFromCalc" | "unexcludeFromCalc"
 * meta: { title, searchTerm } — cuando action="exclude", el servidor crea
 *       automáticamente un filtro aprendido si se proporcionan estos campos.
 */
export async function updateExclusion(itemId, action, meta = {}) {
  const body = { item_id: itemId, action };
  if (action === "exclude" && meta.title && meta.searchTerm) {
    body.title = meta.title;
    body.search_term = meta.searchTerm;
  }
  const res = await fetch(`${API_BASE}/api/exclusions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Error del servidor (${res.status})`);
  }
  return res.json();
}

export async function fetchPending() {
  const res = await fetch(`${API_BASE}/api/pending`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Error del servidor (${res.status})`);
  return res.json(); // { pending: [...] }
}

/**
 * action: "approve" | "discard"
 * meta: { title, searchTerm } — al descartar, el servidor crea un filtro
 *       aprendido para no volver a preguntar por anuncios similares.
 */
export async function submitReview(itemId, action, meta = {}) {
  const body = { item_id: itemId, action };
  if (action === "discard" && meta.title && meta.searchTerm) {
    body.title = meta.title;
    body.search_term = meta.searchTerm;
  }
  const res = await fetch(`${API_BASE}/api/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Error del servidor (${res.status})`);
  return res.json();
}

export async function fetchLearnedFilters() {
  const res = await fetch(`${API_BASE}/api/learned_filters`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Error del servidor (${res.status})`);
  return res.json(); // { rules: [...] }
}

export async function deleteLearnedFilter(ruleId) {
  const res = await fetch(`${API_BASE}/api/learned_filters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "delete", rule_id: ruleId }),
  });
  if (!res.ok) throw new Error(`Error del servidor (${res.status})`);
  return res.json(); // { rules: [...] }
}
