import { Link } from 'react-router-dom'
import { Heart, Home } from 'lucide-react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { DemoBanner, SectionHeading, Skeleton } from '@/components/ui'
import { getCategory } from '@/lib/categories'

export function ProfilePage() {
  const { data: favorites, loading } = useAsync(() => api.favorites(), [])

  return (
    <div className="mx-auto max-w-4xl">
      <DemoBanner />
      <div className="mb-8 flex items-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-2-soft font-display text-xl font-semibold text-accent-2">
          V
        </div>
        <div>
          <h1 className="font-display text-xl font-semibold">Visiteur</h1>
          <p className="text-sm text-ink-muted">Session anonyme · aucune donnée personnelle requise</p>
        </div>
      </div>

      <SectionHeading title="Mes favoris" action={<Heart size={16} className="text-accent" />} />

      {loading && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="aspect-video w-full" />)}
        </div>
      )}

      {!loading && favorites && favorites.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          {favorites.map((f) => {
            const cat = getCategory(f.category)
            const Icon = cat.icon
            return (
              <Link key={f.id} to={f.url} className="card group flex flex-col overflow-hidden">
                <div className="relative aspect-video w-full overflow-hidden bg-surface-2">
                  {f.logo ? (
                    <img src={f.logo} alt="" loading="lazy" className="h-full w-full object-cover" />
                  ) : (
                    <div className={`flex h-full w-full items-center justify-center ${cat.chip}`}>
                      <Icon size={28} className={cat.ink} strokeWidth={1.75} />
                    </div>
                  )}
                </div>
                <div className="flex items-start gap-2.5 p-3.5">
                  <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${cat.chip}`}>
                    <Icon size={14} className={cat.ink} />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold leading-snug">{f.title}</p>
                    <p className="truncate text-xs text-ink-muted">{cat.name}</p>
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      )}

      {!loading && (!favorites || favorites.length === 0) && (
        <div className="card p-10 text-center text-ink-muted">
          Aucun favori pour l'instant — ajoutez-en depuis une chaîne en direct.
        </div>
      )}
    </div>
  )
}

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
      <p className="font-display text-6xl font-semibold text-ink-muted">404</p>
      <h1 className="font-display text-xl font-semibold">Page introuvable</h1>
      <p className="text-sm text-ink-muted">Cette page n'existe pas ou a été déplacée.</p>
      <Link to="/" className="mt-2 flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white">
        <Home size={15} /> Retour à l'accueil
      </Link>
    </div>
  )
}
