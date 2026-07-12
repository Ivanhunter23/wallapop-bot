// Detección automática de precios irregulares (outliers) para excluirlos
// del cálculo de mediana/min/max de una categoría, sin ocultar el
// anuncio de la tabla.
//
// Por qué MAD (Median Absolute Deviation) en vez de desviación
// estándar: con pocas muestras y outliers extremos (p. ej. un lote de
// 2199€ entre anuncios de 20-50€), la desviación estándar se infla
// muchísimo por el propio outlier, haciendo que el umbral de detección
// se vuelva inútil (el outlier "ensancha" el rango hasta incluirse a sí
// mismo como normal). La mediana y el MAD son estadísticos robustos:
// no se ven arrastrados por los valores extremos que precisamente
// queremos detectar.

export function median(nums) {
  if (nums.length === 0) return null;
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Calcula el MAD (Median Absolute Deviation) de un array de números:
 * la mediana de las distancias absolutas de cada valor a la mediana
 * del conjunto.
 */
function mad(nums) {
  const med = median(nums);
  if (med === null) return null;
  const deviations = nums.map((n) => Math.abs(n - med));
  return median(deviations);
}

// Umbral en "MAD modificados". 3.5 es el valor estándar recomendado en
// la literatura estadística (Iglewicz & Hoyle) para detección robusta
// de outliers — suficientemente estricto para no descartar variación
// normal de precios de mercado, pero capaz de pillar casos como "1€ de
// negociable" en una categoría donde el resto está en 20-40€.
const MODIFIED_Z_THRESHOLD = 3.5;

// Regla complementaria, independiente de MAD: precios muy bajos (1-2€)
// casi siempre son "precio de salida para negociar", no el valor real
// del producto. MAD no los detecta como outliers porque en categorías
// con mucho rango de precio (ej. estado/región variable) un 1€ no es
// estadísticamente extremo frente al resto — pero sigue sin ser un
// precio de mercado real, así que lo tratamos como caso aparte.
const LOW_PRICE_NEGOTIABLE_THRESHOLD = 2;

/**
 * Devuelve un Set con los item_id que se consideran outliers de precio
 * dentro de un array de items de la MISMA categoría (search_term).
 *
 * Se necesitan al menos 5 muestras con precio > 0 para que el cálculo
 * tenga sentido estadístico; con menos, no se descarta nada (no hay
 * suficiente información para distinguir "outlier real" de "la
 * categoría tiene pocos anuncios y por eso varían mucho").
 */
export function detectPriceOutliers(items) {
  const outlierIds = new Set();
  const prices = items
    .filter((i) => typeof i.price === "number" && i.price > 0)
    .map((i) => ({ id: i.item_id, price: i.price }));

  // Regla de precio bajo "negociable": se aplica siempre, sin importar
  // cuántas muestras haya en la categoría (no depende de MAD).
  for (const { id, price } of prices) {
    if (price <= LOW_PRICE_NEGOTIABLE_THRESHOLD) {
      outlierIds.add(id);
    }
  }

  if (prices.length < 5) return outlierIds;

  const values = prices.map((p) => p.price);
  const med = median(values);
  const madValue = mad(values);

  // Si el MAD es 0 (todos los precios son iguales o casi iguales), no
  // hay variación que analizar; no se marca nada más como outlier para
  // evitar división por cero.
  if (!madValue || madValue === 0) return outlierIds;

  // Constante 0.6745 normaliza el MAD para que sea comparable a una
  // desviación estándar bajo una distribución normal (es el factor
  // estándar usado en la fórmula del "modified Z-score").
  for (const { id, price } of prices) {
    const modifiedZ = (0.6745 * (price - med)) / madValue;
    if (Math.abs(modifiedZ) > MODIFIED_Z_THRESHOLD) {
      outlierIds.add(id);
    }
  }

  return outlierIds;
}
