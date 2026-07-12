// Detección de ruido / falsos positivos por título.
//
// Replica EXACTAMENTE la misma lógica que usa wallapop_watcher.py
// (función is_noise en Python), para que el comportamiento sea
// consistente entre lo que se notificó por Telegram y lo que este
// dashboard oculta. Si cambias algo aquí, cámbialo también en
// wallapop_watcher.py para mantener ambos lados alineados.

export const NOISE_KEYWORDS = [
  // Accesorios sueltos (no la consola/juego en sí)
  "funda", "carcasa", "cargador", "pantalla", "bateria", "batería",
  "lapiz", "lápiz", "pegatina", "sticker", "llavero", "mochila",
  "camiseta", "auriculares", "sleeve",
  // Accesorios en fr/en ("lot de 3 stylets", "casque", "stylus"…)
  "stylet", "stylus", "stylo", "casque",
  // Merchandising / coleccionables no-videojuego
  "funko", "peluche", "figura", "figurine", "figuur", "tazo", "tazos",
  "amiibo", "keychain", "portachiavi", "porte-clé", "porte clé",
  "porte-clef", "porte clef", "álbum", "album", "gomme", "binder",
  "moneda", "moneta", "moeda", "médaillon", "jeton", "mini tin",
  "pokeball", "pokéball", "pixel art", "juguete", "jugete",
  "etui", "étui",
  // Ropa/textil (Vinted trae mucha ropa de Pokémon en varios idiomas).
  // "shirt" solo ya cubre t-shirt/tshirt/tee-shirt/sweatshirt.
  "shirt", "sudadera", "hoodie", "sweat", "gorra", "chaqueta",
  "pyjama", "pijama", "pajama", "veste", "camisola", "crop top",
  "pantalon", "coussin", "cojín", "cojin",
  "calcetines", "chaussettes", "schoenen", "zapatilla", "chaussure",
  // Peluches/muñecos en otros idiomas (Vinted es internacional)
  "knuffel", "plush", "pluche", "poupée", "muñec",
  // Manualidades (bordados, punto de cruz "hecho a mano" de Pikachu…)
  "handmade", "fatto a mano", "hecho a mano", "punto croce", "punto de cruz",
  // Material impreso (cómics/mangas confundidos con el videojuego)
  "comic", "cómic", "manga", "novela", "libro", "bande dessin",
  // Juegos de mesa ("jeu de société monopoly…")
  "de société",
];

// Patrones de texto que indican ruido sin importar el idioma:
//  - "nº 01/10", "no.148", "tomo 3", "vol. 2" → tomos de manga o números
//    de carta japoneses. OJO: \b delante de la n es imprescindible — sin
//    él, "PlatiNO 30" matcheaba "no 30" y marcaba como ruido anuncios
//    legítimos de Pokémon Platino con un número detrás (bug real).
//  - tallas de ropa en varios idiomas ("maat 33", "taille 40", "talla M")
//    → prenda de vestir, no un juego.
const NOISE_TITLE_PATTERNS = [
  /\bn[ºo°]\.?\s*\d+/i,
  /\btomo\s*\d+/i,
  /\bvol\.?\s*\d+/i,
  /\b(maat|taille|talla|größe|grösse|size)\s*(\d{2,3}|xxs|xs|s|m|l|xl|xxl)\b/i,
];

// ------------------------------------------------------------
// FILTRO DE PLATAFORMA INCORRECTA Y CARTAS/COLECCIONABLES
// ------------------------------------------------------------
// Misma idea que en el watcher: filtramos juegos de otra plataforma
// (Switch, PS, 3DS/2DS, retro…) y cartas/coleccionables TCG, PERO con
// una salvaguarda: si el título también menciona la familia DS real
// (DS / DS Lite / DSi), se CONSERVA. Así no perdemos anuncios legítimos
// de DS que mencionan 3DS de pasada, ni juegos DS con barras/números en
// el título tipo "Kingdom Hearts 358/2 Days".
const DS_FAMILY_PATTERN = /\b(ds|dsi|dsl|nds|ndsi|ndsl)\b/i;

const OTHER_PLATFORM_PATTERNS = [
  /\b3\s*ds\b/i,
  /\b2\s*ds\b/i,
  /\bps[1-5]\b|\bplaystation\b|\bpsx\b|\bpsone\b/i,
  /\bpsp\b|\bvita\b/i,
  /\bswitch\b/i,
  /\bwii\s*u?\b/i,
  /\bxbox\b|\bx360\b/i,
  /\bgame\s*cube\b|\bgamecube\b|\bngc\b|\bn64\b|\bnintendo\s*64\b/i,
  /\bgba\b|\bgame\s*boy\b|\bgameboy\b/i,
  /\bsnes\b|\bsuper\s*nintendo\b|\bnes\b|\bmega\s*drive\b|\bmegadrive\b|\bgenesis\b|\bmaster\s*system\b|\bgame\s*gear\b|\bsaturn\b|\bdreamcast\b|\bneo\s*geo\b|\bneogeo\b|\bamiga\b|\bcommodore\b|\bspectrum\b|\bmsx\b|\batari\b/i,
  /\bandroid\b|\bm[oó]vil\b/i,
  /\bsteam\b|\bpc\b/i,
];

// Cartas/coleccionables TCG. Vinted trae muchísima carta en varios
// idiomas, así que además del español se cubren fr/it/en/de y la jerga
// TCG (holo, booster, graded, vmax…). Todo esto está PROTEGIDO por la
// salvaguarda DS: un título que menciona la familia DS nunca se filtra
// por estos patrones (con "carta" es clave: los boundaries de regex
// evitan además que matchee "cartouche"/"cartuccia" = cartucho legítimo).
// Códigos de carta: "FA 162/086", "162/086" (2-3 dígitos tras la barra
// para no chocar con "358/2 Days"), "#119", y códigos de set entre
// paréntesis tipo "(N4)" o "(PAF 211)".
const CARD_PATTERNS = [
  /\b(cartas?|cartes?|cards?|karten?|cromos?|coleccionables?|p?tcg|jcc|gcc|wotc|trading\s*card)\b/i,
  /\bholo\b|\bhologr[aá]f|\bbooster\b|\bdisplay\b|\belite\s*trainer\b|\betb\b|\bsobres\b|\bpromo\b|\bgraded\b|\bgradad[ao]\b|\bpsa\s*\d{1,2}\b|\bvmax\b|\bvstar\b|\bgx\b|\bfull\s*art\b|\benergy\b|\benerg[ií]a\b/i,
  /\b[a-z]{1,4}\s*\d{1,3}\/\d{2,3}\b|\b\d{1,3}\/\d{2,3}\b|#\s*\d{1,3}\b|\(\s*[a-z]{1,4}\s*\d{1,3}\s*\)/i,
];

/**
 * Devuelve true si el título parece ruido (accesorio suelto, cómic/
 * manga, merchandising, otra plataforma distinta de DS, o cartas/
 * coleccionables) en vez del producto buscado. Es una heurística basada
 * en palabras clave y patrones de texto: no es perfecta, puede tener
 * falsos positivos y negativos.
 */
export function isNoise(title) {
  if (!title) return false;
  const t = title.toLowerCase();
  if (NOISE_KEYWORDS.some((w) => t.includes(w))) return true;
  if (NOISE_TITLE_PATTERNS.some((p) => p.test(t))) return true;
  // Plataforma incorrecta o cartas: solo si el título NO menciona la
  // familia DS real (salvaguarda contra falsos positivos legítimos).
  if (!DS_FAMILY_PATTERN.test(title)) {
    if (OTHER_PLATFORM_PATTERNS.some((p) => p.test(title))) return true;
    if (CARD_PATTERNS.some((p) => p.test(title))) return true;
  }
  return false;
}
