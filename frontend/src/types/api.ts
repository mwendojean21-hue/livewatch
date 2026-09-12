/**
 * Types alignés sur les modèles SQLAlchemy et réponses JSON de Livewatch.py
 * (ExternalStream, IPTVChannel, UserStream, Comment, Visitor, ...)
 */

export type CategoryId =
  | 'sports' | 'news' | 'entertainment' | 'religion' | 'radio' | 'webcam'
  | 'science' | 'iptv' | 'iptv_sports' | 'iptv_news' | 'iptv_documentary'
  | 'iptv_music' | 'iptv_kids' | 'iptv_movies' | 'iptv_science'
  | 'iptv_travel' | 'iptv_business' | 'gaming';

export interface Category {
  id: CategoryId | string;
  name: string;
  color: string;
}

export interface CatalogStream {
  id: string;
  title: string;
  logo: string;
  category: string;
  country: string;
  stream_type: 'hls' | 'youtube' | 'iframe' | string;
  quality: string;
  url: string;
  viewers?: number;
}

export interface IPTVChannelDTO {
  id: string;
  name: string;
  logo: string;
  category: string;
  country: string;
  stream_type: string;
  is_working: boolean;
}

export interface UserStreamDTO {
  id: string;
  title: string;
  description?: string;
  category: string;
  thumbnail?: string;
  viewer_count: number;
  like_count: number;
  is_live: boolean;
  language: string;
  started_at?: string;
  tags?: string;
}

export interface CommentDTO {
  id: string;
  content: string;
  created_at: string;
  visitor_id: string;
  likes: number;
}

export interface EventDTO {
  id: string;
  title: string;
  category: string;
  starts_at: string;
  stream_id?: string;
}

export interface PublicStats {
  live_now: number;
  total_viewers: number;
  total_channels: number;
  total_streams_today?: number;
}

export interface AdminSummary {
  live_now: number;
  total_viewers: number;
  total_channels: number;
  new_reports: number;
  category_breakdown: { category: string; count: number }[];
  viewers_trend: { label: string; viewers: number }[];
}

export interface CountryDTO {
  code: string;
  count: number;
}

export interface CountryChannelItem {
  id: string;
  title?: string;
  name?: string;
  logo: string;
  category?: string;
  stream_type?: string;
  url: string;
}

export interface CountryChannelsDTO {
  country: string;
  external: CountryChannelItem[];
  iptv: CountryChannelItem[];
  total: number;
}

export interface AdminReport {
  id: string;
  reason: string;
  comment_id?: string | null;
  stream_id?: string | null;
  stream_type?: string | null;
  created_at: string | null;
}

export interface AdminExternalStream {
  id: string;
  title: string;
  category: string;
  country: string | null;
  url: string;
  logo: string | null;
  quality: string | null;
  stream_type: string;
  is_active: boolean;
  viewers: number;
}

export interface AdminComment {
  id: string;
  content: string;
  created_at: string;
  report_count: number;
  is_deleted: boolean;
  is_auto_hidden: boolean;
}

export interface AdminBlockedIp {
  id: string;
  ip_address: string;
  reason: string;
  blocked_at: string;
  is_permanent: boolean;
  expires_at: string | null;
}

export interface AdminFeedbackItem {
  id: string;
  message: string;
  email: string | null;
  rating: number | null;
  is_read: boolean;
  created_at: string;
  ip_address: string | null;
}

export interface AdminAnnouncementItem {
  id: string;
  title: string;
  message: string;
  type: string;
  is_active: boolean;
  created_at: string;
  expires_at: string | null;
}

export interface SearchResult {
  results: CatalogStream[];
  total: number;
}

export interface Favorite {
  stream_id: string;
  stream_type: string;
}

export interface FavoriteItem {
  id: string;
  title: string;
  category: string;
  logo: string;
  type: 'external' | 'iptv' | 'user';
  url: string;
}

export interface ApiError {
  detail: string;
}
