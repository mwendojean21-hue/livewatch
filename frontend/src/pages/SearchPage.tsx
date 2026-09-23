import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search as SearchIcon } from 'lucide-react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { DemoBanner, SectionHeading } from '@/components/ui'
import { StreamCard, StreamCardSkeleton } from '@/components/StreamCard'

export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const [value, setValue] = useState(q)

  const { data, loading } = useAsync(() => (q ? api.search(q) : Promise.resolve({ results: [], total: 0 })), [q])

  return (
    <div className="mx-auto max-w-6xl">
      <DemoBanner />
      <h1 className="mb-5 font-display text-2xl font-semibold">Rechercher</h1>

      <form
        onSubmit={(e) => { e.preventDefault(); setParams(value ? { q: value } : {}) }}
        className="relative mb-7 max-w-lg"
      >
        <SearchIcon size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-muted" />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Chaîne, sport, pays…"
          className="w-full rounded-full border border-border bg-surface py-3 pl-11 pr-4 text-sm outline-none focus-visible:border-accent-2"
          autoFocus
        />
      </form>

      {q && (
        <SectionHeading title={loading ? 'Recherche en cours…' : `${data?.total ?? 0} résultat(s) pour « ${q} »`} />
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
        {loading && q && Array.from({ length: 4 }).map((_, i) => <StreamCardSkeleton key={i} />)}
        {!loading && data?.results.map((s) => <StreamCard key={s.id} stream={s} />)}
      </div>

      {!loading && q && data?.results.length === 0 && (
        <div className="card mt-4 flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
          <p className="font-medium text-ink">Aucun résultat pour « {q} »</p>
          <p className="text-sm">Essayez un autre mot-clé, ou parcourez les catégories depuis l'accueil.</p>
        </div>
      )}
    </div>
  )
}
