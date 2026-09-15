import { useCallback, useEffect, useState } from 'react'
import { Radio, Users, Tv2, Flag, LogOut } from 'lucide-react'
import { api } from '@/api/client'
import { SectionHeading, StatCard, Skeleton } from '@/components/ui'
import { CategoryDonut, ViewersTrendChart } from '@/components/Charts'
import { AdminLoginForm } from '@/components/AdminLoginForm'
import {
  ReportsPanel, ExternalStreamsPanel, CommentsPanel, IpsPanel, FeedbackPanel, AnnouncementsPanel, IptvSyncPanel,
} from '@/components/admin/ModerationPanels'
import type { AdminSummary } from '@/types/api'

const TABS = [
  { id: 'overview', label: "Vue d'ensemble" },
  { id: 'streams', label: 'Flux externes' },
  { id: 'iptv', label: 'Synchro IPTV' },
  { id: 'reports', label: 'Signalements' },
  { id: 'comments', label: 'Commentaires' },
  { id: 'ips', label: 'IPs bloquées' },
  { id: 'feedback', label: 'Avis' },
  { id: 'announcements', label: 'Annonces' },
] as const

type TabId = typeof TABS[number]['id']

export function AdminPage() {
  const [status, setStatus] = useState<'checking' | 'authed' | 'anonymous'>('checking')
  const [data, setData] = useState<AdminSummary | null>(null)
  const [tab, setTab] = useState<TabId>('overview')

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
          <h1 className="font-display text-2xl font-semibold">Administration</h1>
          <p className="text-sm text-ink-muted">Vue d'ensemble et modération de la plateforme.</p>
        </div>
        <button
          type="button"
          onClick={() => api.adminLogout().finally(load)}
          className="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-ink-muted hover:text-ink"
        >
          <LogOut size={15} /> Déconnexion
        </button>
      </div>

      <div className="-mx-1 mb-6 flex gap-2 overflow-x-auto px-1 pb-1" style={{ scrollbarWidth: 'none' }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`shrink-0 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.id ? 'border-accent-2 bg-accent-2-soft text-accent-2' : 'border-border text-ink-muted hover:text-ink'
            }`}
          >
            {t.label}
            {t.id === 'reports' && data && data.new_reports > 0 && (
              <span className="ml-1.5 rounded-full bg-accent px-1.5 py-0.5 text-[10px] text-white">{data.new_reports}</span>
            )}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <>
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
        </>
      )}

      {tab === 'streams' && <div className="card p-5"><ExternalStreamsPanel /></div>}
      {tab === 'iptv' && <div className="card p-5"><IptvSyncPanel /></div>}
      {tab === 'reports' && <div className="card p-5"><ReportsPanel /></div>}
      {tab === 'comments' && <div className="card p-5"><CommentsPanel /></div>}
      {tab === 'ips' && <div className="card p-5"><IpsPanel /></div>}
      {tab === 'feedback' && <div className="card p-5"><FeedbackPanel /></div>}
      {tab === 'announcements' && <div className="card p-5"><AnnouncementsPanel /></div>}
    </div>
  )
}
