import { useEffect, useState } from 'react'
import { Trash2, Check, Ban, Power, Star, Megaphone, Plus } from 'lucide-react'
import { api } from '@/api/client'
import type {
  AdminReport, AdminExternalStream, AdminComment, AdminBlockedIp,
  AdminFeedbackItem, AdminAnnouncementItem,
} from '@/types/api'

function EmptyRow({ label }: { label: string }) {
  return <p className="py-6 text-center text-sm text-ink-muted">{label}</p>
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-3 border-b border-border py-3 last:border-0">{children}</div>
}

function IconButton({ onClick, title, children, tone = 'default' }: {
  onClick: () => void; title: string; children: React.ReactNode; tone?: 'default' | 'danger'
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`flex h-8 w-8 items-center justify-center rounded-lg border border-border hover:bg-surface-2 ${
        tone === 'danger' ? 'text-accent' : 'text-ink-muted hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

// ── Signalements ────────────────────────────────────────────────────────
export function ReportsPanel() {
  const [items, setItems] = useState<AdminReport[] | null>(null)

  const load = () => { api.adminReports().then(setItems).catch(() => setItems([])) }
  useEffect(load, [])

  if (items === null) return <EmptyRow label="Chargement…" />
  if (items.length === 0) return <EmptyRow label="Aucun signalement en attente." />

  return (
    <div>
      {items.map((r) => (
        <Row key={r.id}>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{r.reason}</p>
            <p className="text-xs text-ink-muted">
              {r.stream_type ?? 'commentaire'} · {r.created_at ? new Date(r.created_at).toLocaleString('fr-FR') : ''}
            </p>
          </div>
          <IconButton title="Marquer comme résolu" onClick={() => api.resolveReport(r.id).then(load)}>
            <Check size={15} />
          </IconButton>
        </Row>
      ))}
    </div>
  )
}

// ── Flux externes (CRUD) ──────────────────────────────────────────────
export function ExternalStreamsPanel() {
  const [items, setItems] = useState<AdminExternalStream[] | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ title: '', stream_url: '', category: 'general', country: '', stream_type: 'hls', logo: '', quality: 'HD' })

  const load = () => { api.adminExternalStreams().then(setItems).catch(() => setItems([])) }
  useEffect(load, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!form.title.trim() || !form.stream_url.trim()) return
    await api.createExternalStream(form).catch(() => {})
    setForm({ title: '', stream_url: '', category: 'general', country: '', stream_type: 'hls', logo: '', quality: 'HD' })
    setShowForm(false)
    load()
  }

  return (
    <div>
      <div className="mb-3 flex justify-end">
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 rounded-full bg-accent-2 px-4 py-2 text-sm font-medium text-white"
        >
          <Plus size={15} /> Ajouter un flux
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-4 grid gap-2 rounded-xl border border-border p-4 sm:grid-cols-2">
          <input required placeholder="Titre" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          <input required placeholder="URL du flux (m3u8, youtube…)" value={form.stream_url} onChange={(e) => setForm({ ...form, stream_url: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          <input placeholder="Catégorie" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          <input placeholder="Pays (ex: FR)" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          <select value={form.stream_type} onChange={(e) => setForm({ ...form, stream_type: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none">
            <option value="hls">hls</option>
            <option value="youtube">youtube</option>
            <option value="audio">audio</option>
            <option value="iframe">iframe</option>
          </select>
          <input placeholder="URL du logo" value={form.logo} onChange={(e) => setForm({ ...form, logo: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          <button type="submit" className="rounded-lg bg-accent-2 px-4 py-2 text-sm font-medium text-white sm:col-span-2">Créer</button>
        </form>
      )}

      {items === null ? (
        <EmptyRow label="Chargement…" />
      ) : items.length === 0 ? (
        <EmptyRow label="Aucun flux externe." />
      ) : (
        items.map((s) => (
          <Row key={s.id}>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{s.title} {!s.is_active && <span className="text-xs text-accent">(désactivé)</span>}</p>
              <p className="truncate text-xs text-ink-muted">{s.category} · {s.country ?? '—'} · {s.stream_type}</p>
            </div>
            <IconButton title={s.is_active ? 'Désactiver' : 'Activer'} onClick={() => api.toggleExternalStream(s.id).then(load)}>
              <Power size={15} />
            </IconButton>
            <IconButton title="Supprimer" tone="danger" onClick={() => { if (confirm('Supprimer ce flux ?')) api.deleteExternalStream(s.id).then(load) }}>
              <Trash2 size={15} />
            </IconButton>
          </Row>
        ))
      )}
    </div>
  )
}

// ── Commentaires récents ──────────────────────────────────────────────
export function CommentsPanel() {
  const [items, setItems] = useState<AdminComment[] | null>(null)
  const load = () => { api.adminComments().then(setItems).catch(() => setItems([])) }
  useEffect(load, [])

  if (items === null) return <EmptyRow label="Chargement…" />
  const visible = items.filter((c) => !c.is_deleted)
  if (visible.length === 0) return <EmptyRow label="Aucun commentaire récent." />

  return (
    <div>
      {visible.map((c) => (
        <Row key={c.id}>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm">{c.content}</p>
            <p className="text-xs text-ink-muted">
              {new Date(c.created_at).toLocaleString('fr-FR')}
              {c.report_count > 0 && <span className="ml-2 text-accent">{c.report_count} signalement(s)</span>}
            </p>
          </div>
          <IconButton title="Supprimer" tone="danger" onClick={() => api.deleteComment(c.id).then(load)}>
            <Trash2 size={15} />
          </IconButton>
        </Row>
      ))}
    </div>
  )
}

// ── IPs bloquées ────────────────────────────────────────────────────
export function IpsPanel() {
  const [items, setItems] = useState<AdminBlockedIp[] | null>(null)
  const [ip, setIp] = useState('')
  const [reason, setReason] = useState('')
  const load = () => { api.adminIps().then(setItems).catch(() => setItems([])) }
  useEffect(load, [])

  async function handleBlock(e: React.FormEvent) {
    e.preventDefault()
    if (!ip.trim()) return
    await api.blockIp(ip.trim(), reason.trim() || 'Non spécifiée').catch(() => {})
    setIp(''); setReason(''); load()
  }

  return (
    <div>
      <form onSubmit={handleBlock} className="mb-4 flex flex-wrap gap-2">
        <input placeholder="Adresse IP" value={ip} onChange={(e) => setIp(e.target.value)} className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
        <input placeholder="Raison" value={reason} onChange={(e) => setReason(e.target.value)} className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
        <button type="submit" className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white">
          <Ban size={15} /> Bloquer
        </button>
      </form>

      {items === null ? (
        <EmptyRow label="Chargement…" />
      ) : items.length === 0 ? (
        <EmptyRow label="Aucune IP bloquée." />
      ) : (
        items.map((i) => (
          <Row key={i.id}>
            <div className="min-w-0 flex-1">
              <p className="font-mono text-sm">{i.ip_address}</p>
              <p className="truncate text-xs text-ink-muted">{i.reason} · {i.is_permanent ? 'permanent' : `jusqu'au ${i.expires_at ? new Date(i.expires_at).toLocaleDateString('fr-FR') : '?'}`}</p>
            </div>
            <IconButton title="Débloquer" onClick={() => api.unblockIp(i.id).then(load)}>
              <Check size={15} />
            </IconButton>
          </Row>
        ))
      )}
    </div>
  )
}

// ── Avis utilisateurs ──────────────────────────────────────────────
export function FeedbackPanel() {
  const [items, setItems] = useState<AdminFeedbackItem[] | null>(null)
  const load = () => { api.adminFeedback().then(setItems).catch(() => setItems([])) }
  useEffect(load, [])

  if (items === null) return <EmptyRow label="Chargement…" />
  if (items.length === 0) return <EmptyRow label="Aucun avis pour l'instant." />

  return (
    <div>
      {items.map((f) => (
        <Row key={f.id}>
          <div className="min-w-0 flex-1">
            <p className="text-sm">{f.message} {!f.is_read && <span className="ml-1 rounded-full bg-accent-2-soft px-1.5 py-0.5 text-[10px] text-accent-2">nouveau</span>}</p>
            <p className="text-xs text-ink-muted">
              {f.email ?? 'anonyme'} {f.rating != null && <span className="inline-flex items-center gap-0.5"><Star size={11} className="fill-current" /> {f.rating}/5</span>} · {new Date(f.created_at).toLocaleString('fr-FR')}
            </p>
          </div>
          {!f.is_read && (
            <IconButton title="Marquer comme lu" onClick={() => api.markFeedbackRead(f.id).then(load)}>
              <Check size={15} />
            </IconButton>
          )}
          <IconButton title="Supprimer" tone="danger" onClick={() => api.deleteFeedback(f.id).then(load)}>
            <Trash2 size={15} />
          </IconButton>
        </Row>
      ))}
    </div>
  )
}

// ── Annonces ────────────────────────────────────────────────────────
export function AnnouncementsPanel() {
  const [items, setItems] = useState<AdminAnnouncementItem[] | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ title: '', message: '', type: 'info', expires_hours: '24' })
  const load = () => { api.adminAnnouncements().then(setItems).catch(() => setItems([])) }
  useEffect(load, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (form.title.trim().length < 3 || form.message.trim().length < 5) return
    await api.createAnnouncement(form).catch(() => {})
    setForm({ title: '', message: '', type: 'info', expires_hours: '24' })
    setShowForm(false)
    load()
  }

  return (
    <div>
      <div className="mb-3 flex justify-end">
        <button type="button" onClick={() => setShowForm((v) => !v)} className="flex items-center gap-1.5 rounded-full bg-accent-2 px-4 py-2 text-sm font-medium text-white">
          <Megaphone size={15} /> Nouvelle annonce
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-4 grid gap-2 rounded-xl border border-border p-4">
          <input required minLength={3} placeholder="Titre" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          <textarea required minLength={5} placeholder="Message" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          <div className="flex gap-2">
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none">
              <option value="info">info</option>
              <option value="warning">avertissement</option>
              <option value="update">mise à jour</option>
              <option value="feature">nouveauté</option>
            </select>
            <input type="number" min={0} placeholder="Expire dans (heures, 0 = jamais)" value={form.expires_hours} onChange={(e) => setForm({ ...form, expires_hours: e.target.value })} className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none" />
          </div>
          <button type="submit" className="rounded-lg bg-accent-2 px-4 py-2 text-sm font-medium text-white">Publier</button>
        </form>
      )}

      {items === null ? (
        <EmptyRow label="Chargement…" />
      ) : items.length === 0 ? (
        <EmptyRow label="Aucune annonce." />
      ) : (
        items.map((a) => (
          <Row key={a.id}>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{a.title} {!a.is_active && <span className="text-xs text-ink-muted">(masquée)</span>}</p>
              <p className="truncate text-xs text-ink-muted">{a.message}</p>
            </div>
            <IconButton title={a.is_active ? 'Masquer' : 'Afficher'} onClick={() => api.toggleAnnouncement(a.id).then(load)}>
              <Power size={15} />
            </IconButton>
            <IconButton title="Supprimer" tone="danger" onClick={() => api.deleteAnnouncement(a.id).then(load)}>
              <Trash2 size={15} />
            </IconButton>
          </Row>
        ))
      )}
    </div>
  )
}
