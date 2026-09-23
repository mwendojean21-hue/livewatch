import { Calendar, Clock, Megaphone } from 'lucide-react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { getCategory } from '@/lib/categories'
import { DemoBanner, Skeleton } from '@/components/ui'

const ANNOUNCEMENT_STYLES: Record<string, string> = {
  info: 'border-accent-2/30 bg-accent-2-soft text-accent-2',
  warning: 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400',
  update: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  feature: 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400',
}

export function EventsPage() {
  const { data: events, loading } = useAsync(() => api.events(), [])
  // Placement volontaire : le backend renvoie ces annonces spécifiquement
  // pour la section Événements (voir le commentaire sur l'endpoint côté
  // serveur), ce n'est pas un bandeau global.
  const { data: announcements } = useAsync(() => api.activeAnnouncements(), [])

  return (
    <div className="mx-auto max-w-3xl">
      <DemoBanner />
      <h1 className="mb-1 font-display text-2xl font-semibold">Événements à venir</h1>
      <p className="mb-6 text-sm text-ink-muted">Ne manquez aucun direct programmé.</p>

      {announcements && announcements.length > 0 && (
        <div className="mb-6 space-y-2">
          {announcements.map((a) => (
            <div key={a.id} className={`flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm ${ANNOUNCEMENT_STYLES[a.type] ?? ANNOUNCEMENT_STYLES.info}`}>
              <Megaphone size={16} className="mt-0.5 shrink-0" />
              <div>
                <p className="font-semibold">{a.title}</p>
                <p className="mt-0.5 opacity-90">{a.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-3">
        {loading && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)}

        {!loading && events?.map((ev) => {
          const cat = getCategory(ev.category)
          const Icon = cat.icon
          const date = new Date(ev.starts_at)
          return (
            <div key={ev.id} className="card flex items-center gap-4 p-4">
              <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${cat.chip}`}>
                <Icon size={19} className={cat.ink} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{ev.title}</p>
                <p className="text-xs text-ink-muted">{cat.name}</p>
              </div>
              <div className="flex shrink-0 flex-col items-end text-xs text-ink-muted">
                <span className="flex items-center gap-1"><Calendar size={12} /> {date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })}</span>
                <span className="mt-0.5 flex items-center gap-1"><Clock size={12} /> {date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>
              </div>
            </div>
          )
        })}

        {!loading && events?.length === 0 && (
          <div className="card p-10 text-center text-ink-muted">Aucun événement programmé pour le moment.</div>
        )}
      </div>
    </div>
  )
}
