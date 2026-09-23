import { useMemo, useState } from 'react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { CountryCard } from '@/components/CountryCard'
import { CONTINENTS, countryContinent, countryName, type Continent } from '@/lib/countries'
import { Skeleton } from '@/components/ui'

type SortMode = 'alpha' | 'count'

/** Grille complète des pays du catalogue — filtrable par continent et
 * triable, comme dans l'ancienne version (qui avait les onglets continents
 * + un tri alphabétique par défaut). Le tri par nombre de chaînes est un
 * ajout, dans le même esprit puisque le compte est déjà affiché sur chaque
 * carte. */
export function CountriesPage() {
  const { data: countries, loading } = useAsync(() => api.countries(), [])
  const [continent, setContinent] = useState<Continent | 'all'>('all')
  const [sort, setSort] = useState<SortMode>('alpha')

  const filtered = useMemo(() => {
    if (!countries) return []
    const list = continent === 'all' ? countries : countries.filter((c) => countryContinent(c.code) === continent)
    return [...list].sort((a, b) =>
      sort === 'count' ? b.count - a.count : countryName(a.code).localeCompare(countryName(b.code), 'fr'),
    )
  }, [countries, continent, sort])

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-5">
        <h1 className="font-display text-2xl font-semibold sm:text-3xl">Chaînes Télévisions par pays</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {countries ? `${countries.length} pays disponibles` : 'Chargement…'}
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" style={{ scrollbarWidth: 'none' }}>
          {CONTINENTS.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setContinent(c.id)}
              className={`shrink-0 rounded-full border px-4 py-1.5 text-xs font-semibold transition-colors ${
                continent === c.id ? 'border-accent bg-accent text-white' : 'border-border text-ink-muted hover:text-ink'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortMode)}
          className="shrink-0 rounded-full border border-border bg-surface px-3.5 py-1.5 text-xs font-medium outline-none"
        >
          <option value="alpha">Trier : alphabétique</option>
          <option value="count">Trier : nombre de chaînes</option>
        </select>
      </div>

      {loading ? (
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6">
          {Array.from({ length: 18 }).map((_, i) => <Skeleton key={i} className="h-[90px] w-full" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-10 text-center text-sm text-ink-muted">Aucun pays dans cette catégorie.</div>
      ) : (
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6">
          {filtered.map((c) => <CountryCard key={c.code} country={c} />)}
        </div>
      )}
    </div>
  )
}
