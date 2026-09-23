import {
  Trophy, Newspaper, Clapperboard, Church, Radio, Video, FlaskConical,
  Tv, ShieldHalf, Landmark, Film, Music2, Baby, Globe2, Briefcase, Gamepad2,
  type LucideIcon,
} from 'lucide-react'

export interface CategoryMeta {
  id: string
  name: string
  icon: LucideIcon
  chip: string  // classes tailwind pour le fond de la pastille icône
  ink: string   // classes tailwind pour la couleur de l'icône/texte
}

// Reflète CATEGORIES dans Livewatch.py (id, name, color) avec une icône dédiée.
export const CATEGORIES: CategoryMeta[] = [
  { id: 'sports', name: 'Sports', icon: Trophy, chip: 'bg-blue-100 dark:bg-blue-500/15', ink: 'text-blue-600 dark:text-blue-400' },
  { id: 'news', name: 'News', icon: Newspaper, chip: 'bg-red-100 dark:bg-red-500/15', ink: 'text-red-600 dark:text-red-400' },
  { id: 'entertainment', name: 'Divertissement', icon: Clapperboard, chip: 'bg-purple-100 dark:bg-purple-500/15', ink: 'text-purple-600 dark:text-purple-400' },
  { id: 'religion', name: 'Religion', icon: Church, chip: 'bg-emerald-100 dark:bg-emerald-500/15', ink: 'text-emerald-600 dark:text-emerald-400' },
  { id: 'radio', name: 'Radio', icon: Radio, chip: 'bg-orange-100 dark:bg-orange-500/15', ink: 'text-orange-600 dark:text-orange-400' },
  { id: 'webcam', name: 'Webcams', icon: Video, chip: 'bg-cyan-100 dark:bg-cyan-500/15', ink: 'text-cyan-600 dark:text-cyan-400' },
  { id: 'science', name: 'Science', icon: FlaskConical, chip: 'bg-teal-100 dark:bg-teal-500/15', ink: 'text-teal-600 dark:text-teal-400' },
  { id: 'iptv', name: 'Chaînes TV', icon: Tv, chip: 'bg-indigo-100 dark:bg-indigo-500/15', ink: 'text-indigo-600 dark:text-indigo-400' },
  { id: 'iptv_sports', name: 'Sports TV', icon: ShieldHalf, chip: 'bg-blue-100 dark:bg-blue-500/15', ink: 'text-blue-600 dark:text-blue-400' },
  { id: 'iptv_news', name: 'Info TV', icon: Landmark, chip: 'bg-red-100 dark:bg-red-500/15', ink: 'text-red-600 dark:text-red-400' },
  { id: 'iptv_documentary', name: 'Documentaires', icon: Film, chip: 'bg-amber-100 dark:bg-amber-500/15', ink: 'text-amber-600 dark:text-amber-400' },
  { id: 'iptv_music', name: 'Musique TV', icon: Music2, chip: 'bg-pink-100 dark:bg-pink-500/15', ink: 'text-pink-600 dark:text-pink-400' },
  { id: 'iptv_kids', name: 'Jeunesse TV', icon: Baby, chip: 'bg-yellow-100 dark:bg-yellow-500/15', ink: 'text-yellow-600 dark:text-yellow-500' },
  { id: 'iptv_movies', name: 'Films TV', icon: Film, chip: 'bg-purple-100 dark:bg-purple-500/15', ink: 'text-purple-600 dark:text-purple-400' },
  { id: 'iptv_science', name: 'Science TV', icon: FlaskConical, chip: 'bg-teal-100 dark:bg-teal-500/15', ink: 'text-teal-600 dark:text-teal-400' },
  { id: 'iptv_travel', name: 'Voyage TV', icon: Globe2, chip: 'bg-emerald-100 dark:bg-emerald-500/15', ink: 'text-emerald-600 dark:text-emerald-400' },
  { id: 'iptv_business', name: 'Business TV', icon: Briefcase, chip: 'bg-slate-200 dark:bg-slate-500/15', ink: 'text-slate-600 dark:text-slate-300' },
  { id: 'gaming', name: 'Gaming', icon: Gamepad2, chip: 'bg-fuchsia-100 dark:bg-fuchsia-500/15', ink: 'text-fuchsia-600 dark:text-fuchsia-400' },
]

export function getCategory(id: string): CategoryMeta {
  return CATEGORIES.find((c) => c.id === id) ?? CATEGORIES[0]
}
