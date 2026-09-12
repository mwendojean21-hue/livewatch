import { Link } from 'react-router-dom'
import { Heart, Home } from 'lucide-react'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useApi'
import { DemoBanner, SectionHeading, Skeleton } from '@/components/ui'
import { getCategory } from '@/lib/categories'

export function ProfilePage() {
  const { data: favorites, loading } = useAsync(() => api.favorites(), [])

  return (
    <div className="mx-auto max-w-4xl">
      <DemoBanner />
      <div className="mb-8 flex items-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-2-soft font-display text-xl font-semibold text-accent-2">
          V
        </div>
        <div>
          <h1 className="font-display text-xl font-semibold">Visiteur</h1>
          <p className="text-sm text-ink-muted">Session anonyme · aucune donnée personnelle requise</p>
        </div>
      </div>

      <SectionHeading title="Mes favoris" action={<Heart size={16} className="text-accent" />} />

      {loading && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="aspect-video w-full" />)}
        </div>
      )}

      {!loading && favorites && favorites.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          {favorites.map((f) => {
            const cat = getCategory(f.category)
            const Icon = cat.icon
            return (
              <Link key={f.id} to={f.url} className="card group flex flex-col overflow-hidden">
                <div className="relative aspect-video w-full overflow-hidden bg-surface-2">
                  {f.logo ? (
                    <img src={f.logo} alt="" loading="lazy" className="h-full w-full object-cover" />
                  ) : (
                    <div className={`flex h-full w-full items-center justify-center ${cat.chip}`}>
                      <Icon size={28} className={cat.ink} strokeWidth={1.75} />
                    </div>
                  )}
                </div>
                <div className="flex items-start gap-2.5 p-3.5">
                  <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${cat.chip}`}>
                    <Icon size={14} className={cat.ink} />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold leading-snug">{f.title}</p>
                    <p className="truncate text-xs text-ink-muted">{cat.name}</p>
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      )}

      {!loading && (!favorites || favorites.length === 0) && (
        <div className="card p-10 text-center text-ink-muted">
          Aucun favori pour l'instant — ajoutez-en depuis une chaîne en direct.
        </div>
      )}
    </div>
  )
}

export function AboutPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-4 font-display text-2xl font-semibold">À propos de Livewatch</h1>
      <div className="card space-y-3 p-6 text-sm leading-relaxed text-ink-muted">
        <p>
          Livewatch est une plateforme qui rassemble en un seul endroit des chaînes de
          télévision en direct, des radios, des webcams publiques et des directs créés
          par la communauté, classés par catégorie et par pays.
        </p>
        <p>
          Le catalogue est alimenté automatiquement à partir de sources publiques de
          flux IPTV, complété par des flux ajoutés manuellement par l'équipe
          Livewatch et par les créateurs qui utilisent la fonction « Diffuser ».
        </p>
        <p>
          Livewatch ne stocke ni n'héberge lui-même les flux tiers qu'il référence :
          il agit comme un annuaire et un lecteur unifié. Voir les
          <Link to="/terms" className="text-accent-2 underline underline-offset-2"> conditions d'utilisation</Link>
          {' '}et la <Link to="/privacy" className="text-accent-2 underline underline-offset-2">politique de confidentialité</Link> pour le détail.
        </p>
      </div>
    </div>
  )
}

export function TermsPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-4 font-display text-2xl font-semibold">Conditions d'utilisation</h1>
      <div className="card space-y-4 p-6 text-sm leading-relaxed text-ink-muted">
        <section>
          <h2 className="mb-1 font-medium text-ink">1. Utilisation du service</h2>
          <p>L'accès à Livewatch est gratuit. Vous vous engagez à ne pas utiliser le service à des fins illégales, à ne pas perturber son fonctionnement et à respecter les autres utilisateurs (commentaires, directs communautaires).</p>
        </section>
        <section>
          <h2 className="mb-1 font-medium text-ink">2. Contenu tiers</h2>
          <p>Les chaînes et flux référencés proviennent de sources publiques ou fournies par des tiers. Livewatch n'édite pas ce contenu et n'est pas responsable de sa disponibilité, de sa légalité dans votre juridiction ou de son exactitude.</p>
        </section>
        <section>
          <h2 className="mb-1 font-medium text-ink">3. Contenu communautaire</h2>
          <p>En publiant un commentaire ou en diffusant via « Diffuser », vous restez responsable du contenu publié. Livewatch se réserve le droit de modérer, masquer ou supprimer tout contenu signalé qui enfreint ces conditions.</p>
        </section>
        <section>
          <h2 className="mb-1 font-medium text-ink">4. Signalement</h2>
          <p>Tout contenu inapproprié peut être signalé depuis la page de lecture. Les signalements sont examinés par l'équipe de modération.</p>
        </section>
        <p className="text-xs italic">Ce texte est un modèle générique — à faire relire par un juriste avant publication officielle.</p>
      </div>
    </div>
  )
}

export function PrivacyPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-4 font-display text-2xl font-semibold">Confidentialité</h1>
      <div className="card space-y-4 p-6 text-sm leading-relaxed text-ink-muted">
        <section>
          <h2 className="mb-1 font-medium text-ink">Données collectées</h2>
          <p>Livewatch utilise un identifiant de visiteur anonyme (cookie) pour retenir vos favoris, vos préférences (thème, langue) et calculer des statistiques d'audience agrégées. Aucune inscription ni information personnelle n'est requise pour regarder du contenu.</p>
        </section>
        <section>
          <h2 className="mb-1 font-medium text-ink">Adresse IP</h2>
          <p>Votre adresse IP peut être conservée temporairement à des fins de sécurité (limitation d'abus, blocage en cas de comportement malveillant).</p>
        </section>
        <section>
          <h2 className="mb-1 font-medium text-ink">Partage</h2>
          <p>Ces données ne sont ni vendues ni partagées avec des tiers à des fins publicitaires.</p>
        </section>
        <p className="text-xs italic">Ce texte est un modèle générique — à faire relire par un juriste avant publication officielle.</p>
      </div>
    </div>
  )
}

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-20 text-center">
      <p className="font-display text-6xl font-semibold text-ink-muted">404</p>
      <h1 className="font-display text-xl font-semibold">Page introuvable</h1>
      <p className="text-sm text-ink-muted">Cette page n'existe pas ou a été déplacée.</p>
      <Link to="/" className="mt-2 flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white">
        <Home size={15} /> Retour à l'accueil
      </Link>
    </div>
  )
}
