import type {
  CatalogStream, PublicStats, AdminSummary, EventDTO, CommentDTO, SearchResult, FavoriteItem,
  CountryDTO, CountryChannelsDTO, AdminReport, AdminExternalStream, AdminComment, AdminBlockedIp,
  AdminFeedbackItem, AdminAnnouncementItem,
} from '@/types/api'
import {
  MOCK_STREAMS, MOCK_PUBLIC_STATS, MOCK_ADMIN_SUMMARY, MOCK_EVENTS, MOCK_COMMENTS,
} from './mockData'

/** Forme brute renvoyée par GET /api/admin/dashboard/summary (Livewatch.py).
 * Le backend renvoie à la fois cette forme imbriquée "historique" et les
 * champs à plat attendus par AdminSummary (voir mapAdminSummary ci-dessous) —
 * on les type tous les deux ici pour rester robuste si l'un des deux évolue. */
interface RawAdminSummary extends Partial<AdminSummary> {
  streams?: { total: number; live: number; new_24h: number; blocked: number }
  moderation?: { pending_reports: number }
}

function mapAdminSummary(raw: RawAdminSummary): AdminSummary {
  return {
    live_now: raw.live_now ?? raw.streams?.live ?? 0,
    total_viewers: raw.total_viewers ?? 0,
    total_channels: raw.total_channels ?? 0,
    new_reports: raw.new_reports ?? raw.moderation?.pending_reports ?? 0,
    category_breakdown: raw.category_breakdown ?? [],
    viewers_trend: raw.viewers_trend ?? [],
  }
}

/**
 * Client API pour le backend FastAPI (Livewatch.py).
 * En dev, /api est relayé vers http://localhost:8001 via le proxy Vite (voir vite.config.ts).
 * En prod, VITE_API_BASE_URL peut pointer vers un backend séparé.
 *
 * Si le backend n'est pas joignable, chaque fonction retombe sur des données de
 * démonstration pour que l'interface reste explorable hors-ligne — un bandeau
 * "mode démo" s'affiche alors (voir DemoBanner).
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export let isDemoMode = false
const listeners = new Set<(demo: boolean) => void>()
export function onDemoModeChange(cb: (demo: boolean) => void) {
  listeners.add(cb)
  return () => { listeners.delete(cb) }
}
function setDemoMode(v: boolean) {
  if (v !== isDemoMode) {
    isDemoMode = v
    listeners.forEach((cb) => cb(v))
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Le backend FastAPI attend du JSON pour certaines routes (ex: /api/settings/save)
  // et des champs multipart/form-data pour d'autres (Form(...) côté FastAPI, ex:
  // /api/streams/create, /api/streams/{id}/report, /api/favorites/add). On ne force
  // le header JSON que lorsque le corps n'est pas déjà un FormData.
  const isFormData = init?.body instanceof FormData
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: 'include', // nécessaire pour le cookie visitor_id (favoris, paramètres)
    headers: isFormData ? init?.headers : { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      /* réponse non-JSON, on garde statusText */
    }
    throw new Error(detail || `Erreur ${res.status}`)
  }
  return res.json() as Promise<T>
}

async function withFallback<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    const result = await fn()
    setDemoMode(false)
    return result
  } catch {
    setDemoMode(true)
    return fallback
  }
}

/** Construit un FormData pour les routes FastAPI qui attendent des `Form(...)`
 * plutôt qu'un corps JSON (create_stream, report, favorites/add, feedback/submit...).
 * Les valeurs `undefined`/`null` sont omises. */
function toFormData(fields: Record<string, string | number | undefined | null>): FormData {
  const fd = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null) fd.append(key, String(value))
  }
  return fd
}

export const api = {
  catalog: (category?: string, limit = 40) =>
    withFallback(
      () => request<{ streams: CatalogStream[] }>(
        `/api/catalog?${category ? `category=${encodeURIComponent(category)}&` : ''}limit=${limit}`,
      ).then((r) => r.streams),
      category ? MOCK_STREAMS.filter((s) => s.category === category) : MOCK_STREAMS,
    ),

  publicStats: () =>
    withFallback(() => request<PublicStats>('/api/stats/public'), MOCK_PUBLIC_STATS),

  adminSummary: () =>
    withFallback(() => request<RawAdminSummary>('/api/admin/dashboard/summary').then(mapAdminSummary), MOCK_ADMIN_SUMMARY),

  /** Comme adminSummary(), mais sans repli démo : sert à détecter un vrai
   * 401 (non connecté) pour afficher le formulaire de connexion plutôt que
   * des données d'exemple. */
  adminSummaryAuthed: () => request<RawAdminSummary>('/api/admin/dashboard/summary').then(mapAdminSummary),

  /** Résout l'URL de lecture réelle d'un flux (le catalogue ne renvoie qu'un
   * lien de page /watch/..., jamais l'URL du média — voir /api/play côté
   * backend). `kind` vient du paramètre de route (:kind dans /watch/:kind/:id). */
  resolvePlayback: (kind: string, id: string) =>
    request<{ stream_type: string; url: string; title?: string }>(`/api/play/${kind}/${id}`),

  /** POST /admin/login attend un formulaire (pas du JSON) et répond par une
   * redirection 303 vers /admin/dashboard en cas de succès, ou renvoie la
   * page de connexion (HTML, 200) avec un message d'erreur sinon. On suit la
   * redirection et on regarde l'URL finale pour savoir si ça a marché. */
  adminLogin: async (username: string, password: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/admin/login`, {
      method: 'POST',
      credentials: 'include',
      body: toFormData({ username, password }),
    })
    return res.url.includes('/admin/dashboard')
  },

  adminLogout: () => fetch(`${BASE}/admin/logout`, { credentials: 'include' }),

  search: (q: string) =>
    withFallback(
      () => request<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`),
      {
        results: MOCK_STREAMS.filter((s) => s.title.toLowerCase().includes(q.toLowerCase())),
        total: MOCK_STREAMS.filter((s) => s.title.toLowerCase().includes(q.toLowerCase())).length,
      },
    ),

  events: () =>
    withFallback(() => request<{ events: EventDTO[] }>('/api/events/upcoming').then((r) => r.events), MOCK_EVENTS),

  /** Liste des pays disponibles dans le catalogue IPTV, avec un compte de
   * chaînes par pays — sert au bandeau de drapeaux de la page d'accueil. */
  countries: () =>
    withFallback(
      () => request<{ countries: CountryDTO[] }>('/api/iptv/countries').then((r) => r.countries),
      [] as CountryDTO[],
    ),

  /** Chaînes (externes + IPTV) d'un pays donné. Les deux tableaux renvoient
   * déjà des `url` au format /watch/{kind}/{id}, directement utilisables par
   * <Link>/StreamCard. */
  channelsByCountry: (code: string) =>
    withFallback(
      () => request<CountryChannelsDTO>(`/api/channels/by-country/${encodeURIComponent(code)}`),
      { country: code, external: [], iptv: [], total: 0 } as CountryChannelsDTO,
    ),

  comments: (streamId: string) =>
    withFallback(
      () => request<{ comments: CommentDTO[] }>(`/api/streams/${streamId}/comments`).then((r) => r.comments),
      MOCK_COMMENTS,
    ),

  // Ces trois routes attendent des champs `Form(...)` côté FastAPI, pas du JSON.
  postComment: (streamId: string, content: string, username = 'Anonyme') =>
    request<{ success: boolean; id: string; username: string; content: string; created_at: string }>(
      `/api/streams/${streamId}/comments`,
      { method: 'POST', body: toFormData({ content, username }) },
    ),

  likeStream: (streamId: string) =>
    request<{ success: boolean; likes: number }>(`/api/streams/${streamId}/like`, { method: 'POST' })
      .then((r) => ({ like_count: r.likes })),

  reportStream: (streamId: string, reason: string) =>
    request(`/api/streams/${streamId}/report`, { method: 'POST', body: toFormData({ reason }) }),

  createStream: (payload: { title: string; category: string; description?: string; tags?: string }) =>
    request<{ success: boolean; stream_id: string; stream_key: string; watch_url: string }>(
      '/api/streams/create',
      { method: 'POST', body: toFormData(payload) },
    ).then((r) => ({ id: r.stream_id, stream_key: r.stream_key })),

  favorites: () =>
    withFallback(
      () => request<{ favorites: FavoriteItem[] }>('/api/favorites').then((r) => r.favorites),
      [] as FavoriteItem[],
    ),

  addFavorite: (streamId: string, streamType: string) =>
    request('/api/favorites/add', { method: 'POST', body: toFormData({ stream_id: streamId, stream_type: streamType }) }),

  removeFavorite: (streamId: string) =>
    request(`/api/favorites/${streamId}`, { method: 'DELETE' }),

  saveSettings: (settings: Record<string, unknown>) =>
    request('/api/settings/save', { method: 'POST', body: JSON.stringify(settings) }),

  loadSettings: () =>
    withFallback(() => request<Record<string, unknown>>('/api/settings/load'), {}),

  submitFeedback: (payload: { message: string; email?: string; rating?: number }) =>
    request('/api/feedback/submit', { method: 'POST', body: toFormData(payload) }),

  // ── Modération admin ──────────────────────────────────────────────────
  // Toutes ces routes exigent la session admin (cookie posé par adminLogin).

  adminReports: () =>
    request<{ reports: AdminReport[] }>('/api/admin/reports').then((r) => r.reports),
  resolveReport: (id: string) =>
    request(`/api/admin/reports/${id}/resolve`, { method: 'POST' }),

  adminExternalStreams: () =>
    request<{ streams: AdminExternalStream[] }>('/api/admin/external/list').then((r) => r.streams),
  createExternalStream: (payload: Record<string, string>) =>
    request('/api/admin/external/create', { method: 'POST', body: toFormData(payload) }),
  editExternalStream: (id: string, payload: Record<string, string>) =>
    request(`/api/admin/external/${id}/edit`, { method: 'POST', body: toFormData(payload) }),
  toggleExternalStream: (id: string) =>
    request(`/api/admin/external/${id}/toggle`, { method: 'POST' }),
  deleteExternalStream: (id: string) =>
    request(`/api/admin/external/${id}/delete`, { method: 'DELETE' }),

  adminComments: (limit = 50) =>
    request<{ comments: AdminComment[] }>(`/api/admin/comments/recent?limit=${limit}`).then((r) => r.comments),
  deleteComment: (id: string) =>
    request(`/api/admin/comments/${id}/delete`, { method: 'POST' }),

  adminIps: () =>
    request<{ ips: AdminBlockedIp[] }>('/api/admin/ips/list').then((r) => r.ips),
  blockIp: (ipAddress: string, reason: string, permanent = false) =>
    request('/api/admin/ips/block', { method: 'POST', body: toFormData({ ip_address: ipAddress, reason, permanent: permanent ? 'true' : 'false' }) }),
  unblockIp: (id: string) =>
    request(`/api/admin/ips/${id}/unblock`, { method: 'POST' }),

  adminFeedback: () =>
    request<AdminFeedbackItem[]>('/api/admin/feedback'),
  markFeedbackRead: (id: string) =>
    request(`/api/admin/feedback/${id}/read`, { method: 'POST' }),
  deleteFeedback: (id: string) =>
    request(`/api/admin/feedback/${id}`, { method: 'DELETE' }),

  adminAnnouncements: () =>
    request<AdminAnnouncementItem[]>('/api/admin/announcements'),
  createAnnouncement: (payload: { title: string; message: string; type: string; expires_hours?: string }) =>
    request('/api/admin/announcements/create', { method: 'POST', body: toFormData(payload) }),
  toggleAnnouncement: (id: string) =>
    request(`/api/admin/announcements/${id}/toggle`, { method: 'POST' }),
  deleteAnnouncement: (id: string) =>
    request(`/api/admin/announcements/${id}`, { method: 'DELETE' }),
}
