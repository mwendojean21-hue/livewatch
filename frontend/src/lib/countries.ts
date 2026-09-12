/** Convertit un code pays ISO 3166-1 alpha-2 (ex: "FR") en emoji drapeau (🇫🇷).
 * Gardé pour les endroits où une icône suffit (petits libellés, listes texte). */
export function countryFlag(code: string): string {
  const cc = code.trim().toUpperCase()
  if (cc.length !== 2) return '🏳️'
  const A = 0x1f1e6
  const codePoints = [...cc].map((c) => A + (c.charCodeAt(0) - 65))
  if (codePoints.some((cp) => cp < A || cp > A + 25)) return '🏳️'
  return String.fromCodePoint(...codePoints)
}

/** URL d'une vraie photo de drapeau (flagcdn.com), comme dans l'ancienne
 * version — plus lisible qu'un emoji en fond de carte. */
export function countryFlagImageUrl(code: string): string {
  return `https://flagcdn.com/w320/${code.trim().toLowerCase()}.png`
}

export type Continent = 'EU' | 'AF' | 'AS' | 'ME' | 'NA' | 'SA' | 'OC' | 'OTHER'

export const CONTINENTS: { id: Continent | 'all'; label: string }[] = [
  { id: 'all', label: 'Tous' },
  { id: 'AF', label: 'Afrique' },
  { id: 'EU', label: 'Europe' },
  { id: 'AS', label: 'Asie' },
  { id: 'NA', label: 'Am. Nord' },
  { id: 'SA', label: 'Am. Sud' },
  { id: 'OC', label: 'Océanie' },
  { id: 'ME', label: 'Moyen-Orient' },
]

// Même table de correspondance pays → continent que l'ancienne version.
const CONTINENT_MAP: Record<string, Continent> = {
  FR:'EU',BE:'EU',CH:'EU',LU:'EU',DE:'EU',ES:'EU',IT:'EU',PT:'EU',NL:'EU',RU:'EU',
  PL:'EU',UA:'EU',RO:'EU',BG:'EU',RS:'EU',HR:'EU',SI:'EU',SK:'EU',CZ:'EU',HU:'EU',
  AT:'EU',GR:'EU',CY:'EU',MT:'EU',IS:'EU',NO:'EU',SE:'EU',FI:'EU',DK:'EU',IE:'EU',
  LT:'EU',LV:'EU',EE:'EU',MD:'EU',BY:'EU',GB:'EU',AL:'EU',AD:'EU',MC:'EU',
  MA:'AF',DZ:'AF',TN:'AF',SN:'AF',CI:'AF',CM:'AF',ML:'AF',CD:'AF',CG:'AF',BF:'AF',
  NE:'AF',TD:'AF',GA:'AF',GN:'AF',BJ:'AF',TG:'AF',MR:'AF',LY:'AF',EG:'AF',ZA:'AF',
  NG:'AF',KE:'AF',TZ:'AF',UG:'AF',RW:'AF',MZ:'AF',GH:'AF',ET:'AF',AO:'AF',ZM:'AF',ZW:'AF',SD:'AF',
  CN:'AS',JP:'AS',KR:'AS',IN:'AS',PK:'AS',BD:'AS',ID:'AS',MY:'AS',SG:'AS',PH:'AS',
  VN:'AS',TH:'AS',MM:'AS',KH:'AS',LA:'AS',NP:'AS',LK:'AS',KZ:'AS',UZ:'AS',TJ:'AS',
  KG:'AS',TM:'AS',GE:'AS',AM:'AS',AZ:'AS',BN:'AS',MN:'AS',TW:'AS',HK:'AS',
  SA:'ME',AE:'ME',QA:'ME',KW:'ME',BH:'ME',OM:'ME',JO:'ME',IQ:'ME',IR:'ME',SY:'ME',LB:'ME',IL:'ME',TR:'ME',YE:'ME',PS:'ME',
  US:'NA',CA:'NA',MX:'NA',GT:'NA',HN:'NA',SV:'NA',NI:'NA',CR:'NA',PA:'NA',CU:'NA',DO:'NA',HT:'NA',JM:'NA',PR:'NA',
  BR:'SA',AR:'SA',CO:'SA',CL:'SA',PE:'SA',VE:'SA',EC:'SA',BO:'SA',PY:'SA',UY:'SA',
  AU:'OC',NZ:'OC',FJ:'OC',PG:'OC',
}

export function countryContinent(code: string): Continent {
  return CONTINENT_MAP[code.trim().toUpperCase()] ?? 'OTHER'
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
