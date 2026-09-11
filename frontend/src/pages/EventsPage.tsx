import { Calendar, Clock } from 'lucide-react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { getCategory } from '@/lib/categories'
import { DemoBanner, Skeleton } from '@/components/ui'

export function EventsPage() {
  const { data: events, loading } = useAsync(() => api.events(), [])

  return (
    <div className="mx-auto max-w-3xl">
      <DemoBanner />
      <h1 className="mb-1 font-display text-2xl font-semibold">Événements à venir</h1>
      <p className="mb-6 text-sm text-ink-muted">Ne manquez aucun direct programmé.</p>

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
