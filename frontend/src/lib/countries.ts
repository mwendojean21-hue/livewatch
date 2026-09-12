/** Convertit un code pays ISO 3166-1 alpha-2 (ex: "FR") en emoji drapeau (🇫🇷). */
export function countryFlag(code: string): string {
  const cc = code.trim().toUpperCase()
  if (cc.length !== 2) return '🏳️'
  const A = 0x1f1e6
  const codePoints = [...cc].map((c) => A + (c.charCodeAt(0) - 65))
  if (codePoints.some((cp) => cp < A || cp > A + 25)) return '🏳️'
  return String.fromCodePoint(...codePoints)
}

/** Noms d'affichage en français pour les pays les plus fréquents du catalogue.
 * Repli sur le code brut si absent — la liste n'a pas besoin d'être exhaustive. */
const NAMES: Record<string, string> = {
  FR: 'France', CA: 'Canada', BE: 'Belgique', CH: 'Suisse', LU: 'Luxembourg',
  MC: 'Monaco', MA: 'Maroc', DZ: 'Algérie', TN: 'Tunisie', SN: 'Sénégal',
  CI: "Côte d'Ivoire", CM: 'Cameroun', ML: 'Mali', CD: 'Congo RDC',
  CG: 'Congo-Brazzaville', BF: 'Burkina Faso', NE: 'Niger', TD: 'Tchad',
  GA: 'Gabon', US: 'États-Unis', GB: 'Royaume-Uni', DE: 'Allemagne',
  ES: 'Espagne', IT: 'Italie', PT: 'Portugal', NL: 'Pays-Bas', NO: 'Norvège',
}

export function countryName(code: string): string {
  return NAMES[code.trim().toUpperCase()] ?? code
}
