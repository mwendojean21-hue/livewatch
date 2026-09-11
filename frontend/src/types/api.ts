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
