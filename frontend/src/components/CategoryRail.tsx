import { Link, useParams } from 'react-router-dom'
import { CATEGORIES } from '@/lib/categories'

export function CategoryRail() {
  const { categoryId } = useParams()

  return (
    <div className="-mx-1 flex gap-2.5 overflow-x-auto px-1 pb-1" style={{ scrollbarWidth: 'none' }}>
      <Link
        to="/"
        className={`flex shrink-0 items-center rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
          !categoryId
            ? 'border-accent-2 bg-accent-2-soft text-accent-2'
            : 'border-border text-ink-muted hover:text-ink'
        }`}
      >
        Tout
      </Link>
      {CATEGORIES.map((c) => {
        const Icon = c.icon
        const active = categoryId === c.id
        return (
          <Link
            key={c.id}
            to={`/category/${c.id}`}
            className={`flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
              active ? 'border-accent-2 bg-accent-2-soft text-accent-2' : 'border-border text-ink-muted hover:text-ink'
            }`}
          >
            <Icon size={15} className={active ? 'text-accent-2' : c.ink} />
            {c.name}
          </Link>
        )
      })}
    </div>
  )
}
