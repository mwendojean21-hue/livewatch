import { Link } from 'react-router-dom'
import { countryFlagImageUrl, countryName } from '@/lib/countries'
import type { CountryDTO } from '@/types/api'

/** Carte pays avec photo de drapeau en fond + dégradé, comme dans l'ancienne
 * version (voir CHANGES.md) — remplace les anciennes puces arrondies qui ne
 * correspondaient pas au design d'origine. */
export function CountryCard({ country, className = '' }: { country: CountryDTO; className?: string }) {
  return (
    <Link
      to={`/country/${country.code}`}
      className={`group relative flex min-h-[90px] shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-surface-2 ${className}`}
    >
      <img
        src={countryFlagImageUrl(country.code)}
        alt=""
        loading="lazy"
        className="absolute inset-0 h-full w-full object-cover opacity-90 transition-transform duration-300 group-hover:scale-105"
        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
      />
      <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent" />
      <div className="relative mt-auto p-2.5">
        <p className="text-xs font-bold leading-tight text-white [text-shadow:0_1px_4px_rgba(0,0,0,0.8)]">
          {countryName(country.code)}
        </p>
        <p className="text-[10px] text-white/80 [text-shadow:0_1px_3px_rgba(0,0,0,0.8)]">
          {country.count} chaîne{country.count > 1 ? 's' : ''}
        </p>
      </div>
    </Link>
  )
}
