import { Link } from 'react-router-dom'
import { Eye } from 'lucide-react'
import type { CatalogStream } from '@/types/api'
import { getCategory } from '@/lib/categories'
import { LiveBadge } from './ui'

function formatViewers(n?: number) {
  if (!n) return null
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)} k`
  return `${n}`
}

export function StreamCard({ stream }: { stream: CatalogStream }) {
  const cat = getCategory(stream.category)
  const Icon = cat.icon

  return (
    <Link
      to={stream.url}
      className="card group flex flex-col overflow-hidden transition-transform hover:-translate-y-0.5"
    >
      <div className="relative aspect-video w-full overflow-hidden bg-surface-2">
        {stream.logo ? (
          <img
            src={stream.logo}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className={`flex h-full w-full items-center justify-center ${cat.chip}`}>
            <Icon size={30} className={cat.ink} strokeWidth={1.75} />
          </div>
        )}
        <div className="absolute left-2.5 top-2.5"><LiveBadge /></div>
        {stream.quality && (
          <span className="absolute right-2.5 top-2.5 rounded-md bg-black/55 px-1.5 py-0.5 text-[10px] font-semibold text-white backdrop-blur-sm">
            {stream.quality}
          </span>
        )}
        {stream.viewers != null && (
          <div className="absolute bottom-2.5 left-2.5 flex items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white backdrop-blur-sm">
            <Eye size={12} /> {formatViewers(stream.viewers)}
          </div>
        )}
      </div>
      <div className="flex items-start gap-2.5 p-3.5">
        <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${cat.chip}`}>
          <Icon size={14} className={cat.ink} />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-snug">{stream.title}</p>
          <p className="truncate text-xs text-ink-muted">{cat.name}{stream.country ? ` · ${stream.country}` : ''}</p>
        </div>
      </div>
    </Link>
  )
}

export function StreamCardSkeleton() {
  return (
    <div className="card overflow-hidden">
      <div className="aspect-video w-full animate-pulse bg-surface-2" />
      <div className="space-y-2 p-3.5">
        <div className="h-3.5 w-3/4 animate-pulse rounded bg-surface-2" />
        <div className="h-3 w-1/2 animate-pulse rounded bg-surface-2" />
      </div>
    </div>
  )
}
