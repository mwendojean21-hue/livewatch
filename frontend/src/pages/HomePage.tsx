import { useParams, Link } from 'react-router-dom'
import { Radio, Users, Tv2, Flame } from 'lucide-react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { DemoBanner, SectionHeading, StatCard } from '@/components/ui'
import { CategoryRail } from '@/components/CategoryRail'
import { CountryRail } from '@/components/CountryRail'
import { StreamCard, StreamCardSkeleton } from '@/components/StreamCard'
import { getCategory } from '@/lib/categories'

function formatCompact(n: number) {
  return new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(n)
}

/** Salutation selon l'heure locale du visiteur — l'ancien code n'avait pas
 * cette logique du tout (le texte "Bonsoir" était figé en dur), d'où le
 * bug : ce n'est pas une régression du portage, juste jamais implémenté. */
function greeting(): string {
  const h = new Date().getHours()
  if (h < 5) return 'Bonne nuit'
  if (h < 12) return 'Bonjour'
  if (h < 18) return 'Bon après-midi'
  return 'Bonsoir'
}

export function HomePage() {
  const { categoryId } = useParams()
  const { data: stats } = useAsync(() => api.publicStats(), [])
  const { data: streams, loading } = useAsync(() => api.catalog(categoryId), [categoryId])

  const cat = categoryId ? getCategory(categoryId) : null

  return (
    <div className="mx-auto max-w-6xl">
      <DemoBanner />

      <div className="mb-6">
        <h1 className="font-display text-2xl font-semibold sm:text-3xl">
          {cat ? cat.name : `${greeting()} 👋`}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          {cat ? `Toutes les chaînes ${cat.name.toLowerCase()} en direct` : 'Voici ce qui se passe en direct maintenant.'}
        </p>
      </div>

      {!categoryId && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="En direct" value={stats ? String(stats.live_now) : '—'} icon={Radio} />
          <StatCard label="Spectateurs" value={stats ? formatCompact(stats.total_viewers) : '—'} icon={Users} />
          <StatCard label="Chaînes" value={stats ? formatCompact(stats.total_channels) : '—'} icon={Tv2} />
          <StatCard label="Lives aujourd'hui" value={stats?.total_streams_today != null ? String(stats.total_streams_today) : '—'} icon={Flame} />
        </div>
      )}

      <div className="mb-7">
        <CategoryRail />
      </div>

      {!categoryId && (
        <div className="mb-7">
          <div className="mb-2.5 flex items-center justify-between">
            <p className="text-sm font-medium text-ink-muted">Parcourir par pays</p>
            <Link to="/countries" className="text-xs font-medium text-accent-2 hover:underline">Voir tout →</Link>
          </div>
          <CountryRail />
        </div>
      )}

      <SectionHeading title={cat ? `${cat.name} en direct` : 'En direct maintenant'} />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
        {loading
          ? Array.from({ length: 8 }).map((_, i) => <StreamCardSkeleton key={i} />)
          : streams?.map((s) => <StreamCard key={s.id} stream={s} />)}
      </div>

      {!loading && streams?.length === 0 && (
        <div className="card mt-4 flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
          <p className="font-medium text-ink">Aucune chaîne dans cette catégorie pour l'instant</p>
          <p className="text-sm">Revenez plus tard ou explorez une autre catégorie.</p>
        </div>
      )}
    </div>
  )
}
