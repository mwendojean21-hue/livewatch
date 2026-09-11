import type {
  CatalogStream, PublicStats, AdminSummary, EventDTO, CommentDTO, SearchResult, FavoriteItem,
} from '@/types/api'
import {
  MOCK_STREAMS, MOCK_PUBLIC_STATS, MOCK_ADMIN_SUMMARY, MOCK_EVENTS, MOCK_COMMENTS,
} from './mockData'

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
    withFallback(() => request<AdminSummary>('/api/admin/dashboard/summary'), MOCK_ADMIN_SUMMARY),

  /** Comme adminSummary(), mais sans repli démo : sert à détecter un vrai
   * 401 (non connecté) pour afficher le formulaire de connexion plutôt que
   * des données d'exemple. */
  adminSummaryAuthed: () => request<AdminSummary>('/api/admin/dashboard/summary'),

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
}
