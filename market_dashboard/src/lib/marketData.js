import { isNoise } from "./noiseDetection.js";
import { median, detectPriceOutliers } from "./priceOutliers.js";

// ---- Filtros aprendidos ----
const _LF_STOPWORDS = new Set([
  "the", "and", "for", "que", "con", "del", "los", "las", "una",
  "par", "per", "von", "para", "nintendo", "juego", "juegos",
]);

function extractFilterWords(title) {
  const normalized = title
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
  const words = normalized.match(/\b[a-z0-9]{3,}\b/g) || [];
  return words.filter((w) => !_LF_STOPWORDS.has(w));
}

// Un título coincide con una regla solo si contiene TODAS sus palabras
// clave (el título es un superconjunto del patrón). Se exige coincidencia
// total —y no un umbral parcial— para no arrasar juegos legítimos cuyo
// nombre comparte casi todas las palabras con el ruido: p.ej. excluir
// "Folleto Mundo Misterioso Exploradores del Cielo" no debe borrar el juego
// "Pokémon Mundo Misterioso Exploradores del Cielo"; la palabra
// discriminante "folleto", ausente en el juego, lo protege.
export function matchesLearnedFilter(title, searchTerm, rules) {
  if (!rules || rules.length === 0) return false;
  const candidate = new Set(extractFilterWords(title));
  for (const rule of rules) {
    if (rule.search_term !== searchTerm) continue;
    const ruleWords = rule.words || [];
    if (ruleWords.length === 0) continue;
    if (ruleWords.every((w) => candidate.has(w))) return true;
  }
  return false;
}

/**
 * Reduce el histórico de avistamientos (muchas líneas por item_id a lo
 * largo del tiempo) a un registro por anuncio, conservando el estado
 * más reciente (precio/título actuales) y el conteo de cuántas veces
 * se ha visto.
 */
export function deduplicateByItem(rawRows) {
  const byItem = new Map();
  const keywordSet = new Set();

  for (const r of rawRows) {
    if (!r.item_id) continue;
    const kw = r.search_term || "(sin categoría)";
    keywordSet.add(kw);

    const existing = byItem.get(r.item_id);
    if (!existing) {
      byItem.set(r.item_id, {
        ...r,
        search_term: kw,
        // Filas antiguas (pre-Vinted) no traen `source`: se asumen Wallapop.
        source: r.source || "wallapop",
        firstSeen: r.scanned_at,
        lastSeen: r.scanned_at,
        sightingCount: 1,
      });
    } else {
      if (r.scanned_at > existing.lastSeen) {
        existing.lastSeen = r.scanned_at;
        existing.price = r.price;
        existing.title = r.title;
        existing.url = r.url;
      }
      if (r.scanned_at < existing.firstSeen) existing.firstSeen = r.scanned_at;
      existing.sightingCount += 1;
    }
  }

  return {
    items: Array.from(byItem.values()),
    allKeywords: Array.from(keywordSet).sort(),
  };
}

/**
 * Aplica todas las clasificaciones (ruido automático, exclusión manual
 * permanente, exclusión manual solo-de-cálculo, outlier de precio
 * automático, filtros aprendidos) a cada item, y calcula las estadísticas
 * por categoría SOLO con los anuncios que deben contar para el cálculo.
 *
 * `exclusions`: { excluded: [...], excludedFromCalc: [...] }
 * `learnedFilters`: { rules: [...] } — opcional
 */
export function buildMarketView(rawRows, exclusions, learnedFilters) {
  const excludedSet = new Set(exclusions?.excluded || []);
  const excludedFromCalcSet = new Set(exclusions?.excludedFromCalc || []);
  const learnedRules = learnedFilters?.rules || [];

  const { items: dedupedItems, allKeywords } = deduplicateByItem(rawRows);

  // Clasificación por item: ruido automático y exclusión manual total.
  // Los excluidos manualmente de forma TOTAL se quitan de absolutamente
  // todo (tabla y cálculo) — son "esto no es un anuncio real / es spam
  // / está mal clasificado y no quiero verlo más".
  const classified = dedupedItems
    .map((item) => ({
      ...item,
      isNoiseAuto: isNoise(item.title),
      isExcludedManually: excludedSet.has(item.item_id),
      isExcludedFromCalcManually: excludedFromCalcSet.has(item.item_id),
      isLearnedExcluded: matchesLearnedFilter(item.title, item.search_term, learnedRules),
    }))
    .filter((item) => !item.isExcludedManually && !item.isLearnedExcluded);

  // Agrupar por categoría para calcular outliers de precio (el cálculo
  // de outliers necesita compararse contra el resto de su MISMA
  // categoría, no contra el global).
  const byKeyword = new Map();
  for (const item of classified) {
    if (!byKeyword.has(item.search_term)) byKeyword.set(item.search_term, []);
    byKeyword.get(item.search_term).push(item);
  }

  // Para detectar outliers de precio de forma significativa, primero
  // hay que quitar el ruido (si no, una categoría contaminada de
  // accesorios baratos distorsiona la mediana sobre la que se mide la
  // distancia de cada outlier).
  const statsByKeyword = new Map();
  for (const [kw, items] of byKeyword.entries()) {
    const nonNoiseItems = items.filter((i) => !i.isNoiseAuto);
    const outlierIds = detectPriceOutliers(nonNoiseItems);

    for (const item of items) {
      item.isPriceOutlierAuto = outlierIds.has(item.item_id);
    }

    // Lo que SÍ cuenta para el cálculo de mediana/min/max: no es ruido,
    // no es outlier automático, no está excluido manualmente del
    // cálculo, y tiene precio > 0 (los gratis/intercambio se manejan
    // con el toggle "excludeZero" aparte, en la capa de filtrado de la
    // UI, no aquí).
    const pricesForCalc = items
      .filter(
        (i) =>
          !i.isNoiseAuto &&
          !i.isPriceOutlierAuto &&
          !i.isExcludedFromCalcManually &&
          typeof i.price === "number" &&
          i.price > 0
      )
      .map((i) => i.price);

    statsByKeyword.set(kw, {
      count: items.length,
      countForCalc: pricesForCalc.length,
      median: median(pricesForCalc),
      min: pricesForCalc.length ? Math.min(...pricesForCalc) : null,
      max: pricesForCalc.length ? Math.max(...pricesForCalc) : null,
    });
  }

  return { items: classified, allKeywords, statsByKeyword };
}
