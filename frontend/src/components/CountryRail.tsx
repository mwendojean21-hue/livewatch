import { Link, useParams } from 'react-router-dom'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { countryFlag, countryName } from '@/lib/countries'

/** Bandeau de pays (drapeaux) — clique sur un drapeau pour voir toutes les
 * chaînes de ce pays. Existait dans l'ancienne version (page d'accueil avec
 * la liste des pays et leurs drapeaux) mais n'avait pas été repris lors du
 * passage au frontend React ; le backend expose déjà tout ce qu'il faut
 * (GET /api/iptv/countries, GET /api/channels/by-country/{code}). */
export function CountryRail() {
  const { countryCode } = useParams()
  const { data: countries, loading } = useAsync(() => api.countries(), [])

  if (loading) {
    return <div className="-mx-1 flex gap-2.5 overflow-x-auto px-1 pb-1">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="h-9 w-24 shrink-0 animate-pulse rounded-full bg-surface-2" />
      ))}
    </div>
  }

  if (!countries || countries.length === 0) return null

  return (
    <div className="-mx-1 flex gap-2.5 overflow-x-auto px-1 pb-1" style={{ scrollbarWidth: 'none' }}>
      {countries.map((c) => {
        const active = countryCode === c.code
        return (
          <Link
            key={c.code}
            to={`/country/${c.code}`}
            className={`flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
              active ? 'border-accent-2 bg-accent-2-soft text-accent-2' : 'border-border text-ink-muted hover:text-ink'
            }`}
          >
            <span className="text-base leading-none">{countryFlag(c.code)}</span>
            {countryName(c.code)}
            <span className="text-xs text-ink-muted">{c.count}</span>
          </Link>
        )
      })}
    </div>
  )
}
