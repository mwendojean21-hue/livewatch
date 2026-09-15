import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { CountryCard } from '@/components/CountryCard'

/** Bandeau de pays (drapeaux) sur la page d'accueil — aperçu des pays les
 * plus fournis, avec un lien vers la grille complète (/countries) où l'on
 * peut filtrer par continent et trier, comme dans l'ancienne version. */
export function CountryRail() {
  const { data: countries, loading } = useAsync(() => api.countries(), [])

  if (loading) {
    return (
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-1">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-[90px] w-32 shrink-0 animate-pulse rounded-xl bg-surface-2" />
        ))}
      </div>
    )
  }

  if (!countries || countries.length === 0) return null

  const top = [...countries].sort((a, b) => b.count - a.count).slice(0, 10)

  return (
    <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-1" style={{ scrollbarWidth: 'none' }}>
      {top.map((c) => (
        <CountryCard key={c.code} country={c} className="w-32" />
      ))}
      <Link
        to="/countries"
        className="flex min-h-[90px] w-32 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border text-xs font-medium text-ink-muted hover:text-ink"
      >
        Voir tous les pays
        <span className="text-[10px] text-ink-muted/70">({countries.length})</span>
      </Link>
    </div>
  )
}
