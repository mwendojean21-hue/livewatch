import { useParams } from 'react-router-dom'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { SectionHeading } from '@/components/ui'
import { StreamCard, StreamCardSkeleton } from '@/components/StreamCard'
import { CountryRail } from '@/components/CountryRail'
import { countryFlag, countryName } from '@/lib/countries'
import type { CatalogStream, CountryChannelItem } from '@/types/api'

/** Adapte un item /api/channels/by-country (external OU iptv, formes
 * légèrement différentes) vers la forme attendue par <StreamCard>. */
function toCatalogStream(item: CountryChannelItem): CatalogStream {
  return {
    id: item.id,
    title: item.title ?? item.name ?? 'Chaîne',
    logo: item.logo,
    category: item.category ?? 'iptv',
    country: '',
    stream_type: item.stream_type ?? 'hls',
    quality: '',
    url: item.url,
  }
}

export function CountryPage() {
  const { countryCode } = useParams<{ countryCode: string }>()
  const code = countryCode ?? ''
  const { data, loading } = useAsync(() => api.channelsByCountry(code), [code])

  const streams = data
    ? [
        ...data.external.map((c) => toCatalogStream(c)),
        ...data.iptv.map((c) => toCatalogStream(c)),
      ]
    : []

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6">
        <h1 className="font-display text-2xl font-semibold sm:text-3xl">
          {countryFlag(code)} {countryName(code)}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          {data ? `${data.total} chaîne${data.total > 1 ? 's' : ''} en direct` : 'Chargement des chaînes…'}
        </p>
      </div>

      <div className="mb-7">
        <CountryRail />
      </div>

      <SectionHeading title={`Chaînes — ${countryName(code)}`} />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
        {loading
          ? Array.from({ length: 8 }).map((_, i) => <StreamCardSkeleton key={i} />)
          : streams.map((s) => <StreamCard key={s.url} stream={s} />)}
      </div>

      {!loading && streams.length === 0 && (
        <div className="card mt-4 flex flex-col items-center gap-2 p-10 text-center text-ink-muted">
          <p className="font-medium text-ink">Aucune chaîne trouvée pour ce pays</p>
          <p className="text-sm">Le catalogue est peut-être encore en cours de synchronisation.</p>
        </div>
      )}
    </div>
  )
}
