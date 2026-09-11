import { useCallback, useEffect, useState } from 'react'
import { Radio, Users, Tv2, Flag, LogOut } from 'lucide-react'
import { api } from '@/api/client'
import { SectionHeading, StatCard, Skeleton } from '@/components/ui'
import { CategoryDonut, ViewersTrendChart } from '@/components/Charts'
import { AdminLoginForm } from '@/components/AdminLoginForm'
import type { AdminSummary } from '@/types/api'

export function AdminPage() {
  const [status, setStatus] = useState<'checking' | 'authed' | 'anonymous'>('checking')
  const [data, setData] = useState<AdminSummary | null>(null)

  const load = useCallback(() => {
    setStatus('checking')
    api.adminSummaryAuthed()
      .then((res) => { setData(res); setStatus('authed') })
      .catch(() => setStatus('anonymous'))
  }, [])

  useEffect(() => { load() }, [load])

  if (status === 'checking') {
    return <div className="mx-auto max-w-6xl"><Skeleton className="h-32 w-full" /></div>
  }

  if (status === 'anonymous') {
    return <AdminLoginForm onSuccess={load} />
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold">Statistiques</h1>
          <p className="text-sm text-ink-muted">Vue d'ensemble de la plateforme, en temps réel.</p>
        </div>
        <button
          type="button"
          onClick={() => api.adminLogout().finally(load)}
          className="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink"
        >
          <LogOut size={15} /> Déconnexion
        </button>
      </div>

      {!data ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="En direct" value={String(data.live_now)} icon={Radio} />
          <StatCard label="Spectateurs" value={data.total_viewers.toLocaleString('fr-FR')} icon={Users} />
          <StatCard label="Chaînes" value={data.total_channels.toLocaleString('fr-FR')} icon={Tv2} />
          <StatCard label="Signalements" value={String(data.new_reports)} icon={Flag} hint="à traiter" />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <SectionHeading title="Répartition par catégorie" />
          {!data ? <Skeleton className="h-40 w-full" /> : <CategoryDonut data={data.category_breakdown} />}
        </div>
        <div className="card p-5">
          <SectionHeading title="Spectateurs — 7 derniers jours" />
          {!data ? <Skeleton className="h-56 w-full" /> : <ViewersTrendChart data={data.viewers_trend} />}
        </div>
      </div>
    </div>
  )
}
