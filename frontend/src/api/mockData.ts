import type { CatalogStream, PublicStats, AdminSummary, EventDTO, CommentDTO } from '@/types/api'

// Données de démonstration — utilisées uniquement si l'API backend
// (Livewatch.py) n'est pas joignable, pour que l'interface reste explorable.

export const MOCK_STREAMS: CatalogStream[] = [
  { id: '1', title: 'RTNC Direct', logo: '', category: 'news', country: 'CD', stream_type: 'hls', quality: 'HD', url: '/watch/external/1', viewers: 4210 },
  { id: '2', title: 'Canal Foot Live', logo: '', category: 'sports', country: 'FR', stream_type: 'hls', quality: 'FHD', url: '/watch/external/2', viewers: 12830 },
  { id: '3', title: 'Radio Okapi', logo: '', category: 'radio', country: 'CD', stream_type: 'hls', quality: 'AUDIO', url: '/watch/external/3', viewers: 980 },
  { id: '4', title: 'Trace Africa', logo: '', category: 'entertainment', country: 'CI', stream_type: 'hls', quality: 'HD', url: '/watch/external/4', viewers: 3120 },
  { id: '5', title: 'Kids Cartoon TV', logo: '', category: 'iptv_kids', country: 'US', stream_type: 'hls', quality: 'HD', url: '/watch/external/5', viewers: 640 },
  { id: '6', title: 'Nat Geo Wild', logo: '', category: 'iptv_science', country: 'US', stream_type: 'hls', quality: 'FHD', url: '/watch/external/6', viewers: 2210 },
  { id: '7', title: 'Gospel Live Praise', logo: '', category: 'religion', country: 'CD', stream_type: 'hls', quality: 'HD', url: '/watch/external/7', viewers: 1540 },
  { id: '8', title: 'ESport Arena', logo: '', category: 'gaming', country: 'FR', stream_type: 'youtube', quality: 'FHD', url: '/watch/external/8', viewers: 5870 },
]

export const MOCK_PUBLIC_STATS: PublicStats = {
  live_now: 38,
  total_viewers: 48210,
  total_channels: 1260,
  total_streams_today: 214,
}

export const MOCK_ADMIN_SUMMARY: AdminSummary = {
  live_now: 38,
  total_viewers: 48210,
  total_channels: 1260,
  new_reports: 3,
  category_breakdown: [
    { category: 'Sports', count: 32 },
    { category: 'News', count: 24 },
    { category: 'Divertissement', count: 18 },
    { category: 'Chaînes TV', count: 15 },
    { category: 'Radio', count: 11 },
  ],
  viewers_trend: [
    { label: 'Lun', viewers: 21000 },
    { label: 'Mar', viewers: 25400 },
    { label: 'Mer', viewers: 23100 },
    { label: 'Jeu', viewers: 29800 },
    { label: 'Ven', viewers: 34200 },
    { label: 'Sam', viewers: 41500 },
    { label: 'Dim', viewers: 48210 },
  ],
}

export const MOCK_EVENTS: EventDTO[] = [
  { id: 'e1', title: 'Finale Coupe — Direct', category: 'sports', starts_at: new Date(Date.now() + 3 * 3600e3).toISOString() },
  { id: 'e2', title: 'Culte du dimanche', category: 'religion', starts_at: new Date(Date.now() + 20 * 3600e3).toISOString() },
  { id: 'e3', title: 'Conférence tech Kinshasa', category: 'science', starts_at: new Date(Date.now() + 48 * 3600e3).toISOString() },
]

export const MOCK_COMMENTS: CommentDTO[] = [
  { id: 'c1', content: 'Bonne qualité ce soir 👏', created_at: new Date(Date.now() - 5 * 60e3).toISOString(), visitor_id: 'v1', likes: 4 },
  { id: 'c2', content: 'Le son coupe un peu par moments', created_at: new Date(Date.now() - 2 * 60e3).toISOString(), visitor_id: 'v2', likes: 1 },
]
