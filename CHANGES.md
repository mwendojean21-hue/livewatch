# Livewatch — corrections apportées

Diagnostic global : le frontend React (TypeScript) a été construit contre des
formes d'API imaginées (`src/api/mockData.ts`), jamais reconciliées avec les
vraies réponses du backend FastAPI (`backend/Livewatch.py`). Les requêtes
réussissent (200 OK) mais les champs attendus n'existent pas → `undefined`/`NaN`
côté React, sans jamais lever d'erreur visible.

## Session 1

### Backend (`backend/Livewatch.py`)
- **`Visitor.first_seen` n'existe pas** (seule `created_at`/`last_seen`
  existent) → provoquait un 500 sur `/api/admin/dashboard/summary`, ce qui
  faisait échouer `adminSummaryAuthed()` côté frontend et renvoyait toujours
  au formulaire de connexion, même après une connexion réussie. Remplacé
  partout par `created_at`.
- La création d'un nouveau visiteur passait des kwargs inexistants
  (`first_seen`, `page_count`, `last_page`, `favorites`) au constructeur
  SQLAlchemy → `TypeError` silencieusement avalé par le `try/except` du
  middleware. Nettoyé.
- `DELETE /api/favorites/{id}` utilisait un stockage JSON sur
  `visitor.favorites` (colonne inexistante) alors que `POST /api/favorites/add`
  utilise la vraie table `Favorite`. Les deux utilisent maintenant la même
  table.
- `GET /api/stats/public` et `GET /api/admin/dashboard/summary` ne renvoyaient
  pas les champs attendus par le frontend (`live_now`, `total_viewers`,
  `total_channels`, `category_breakdown`…). Ajoutés côté backend (avec un vrai
  calcul de spectateurs et une vraie répartition par catégorie), en gardant
  les anciens champs pour ne rien casser côté templates Jinja restants.
- **Lecture des directs cassée** : `/api/catalog` ne renvoie qu'un lien de
  page (`/watch/external/{id}`), jamais l'URL du média. Ajout d'un nouvel
  endpoint JSON `GET /api/play/{kind}/{id}` (kind = external | iptv | user)
  qui résout la vraie URL de lecture (et l'ID YouTube via `yt_service`).

### Déploiement (`vercel.json`)
- `/proxy/:path*` et `/static/:path*` n'étaient **pas** redirigés vers le
  service backend en production. Ajoutés.
- Le dossier `static/` (contenant `livewatch.apk`) était à la racine du
  dépôt alors que le service backend a `root: "backend/"` sur Vercel → jamais
  déployé. Déplacé dans `backend/static/`.

### Frontend (`frontend/src`)
- `client.ts` : couche de correspondance (`mapAdminSummary`) entre la forme
  brute du backend et celle attendue par les composants, + `resolvePlayback`,
  `countries`, `channelsByCountry`.
- `WatchPage.tsx` : utilise `/api/play/:kind/:id` pour résoudre l'URL de
  lecture réelle au lieu de deviner à partir de l'ID interne.
- `VideoPlayer.tsx` : vrai lecteur `<audio>` pour les flux radio.
- **Navigation par pays restaurée** : `CountryRail.tsx`, `CountryPage.tsx`,
  `lib/countries.ts`, route `/country/:countryCode`.
- **Écran de démarrage restauré** (`SplashScreen.tsx`).
- **Bouton de téléchargement de l'APK restauré** (en-tête + menu mobile).

## Session 2 — parité fonctionnelle avec l'ancienne version

Audit complet : chaque route de l'ancien fichier monolithique a été comparée
à celles du backend actuel. **Le backend a déjà 100 % de parité** (une seule
différence, une route GET dupliquée sans effet). Tout l'écart de
fonctionnalités venait du frontend React, qui n'avait jamais reçu d'interface
pour une bonne partie de ce que le backend expose déjà.

### Bugs backend supplémentaires trouvés en construisant les écrans manquants
- `admin_delete_comment` supprimait dans la table `Comment`, mais
  `/api/admin/comments/recent` liste des `ChatMessage` (table différente) —
  le bouton « supprimer » ne faisait donc jamais rien. Corrigé pour essayer
  les deux tables.
- `PUT /api/admin/external/{stream_id}/edit` déclarait `stream_id: int` alors
  que les ID sont des UUID (string) → 422 systématique. Corrigé.
- Ajout de `POST /api/admin/external/{stream_id}/edit` (alias du PUT) pour
  matcher ce que peut envoyer facilement un formulaire/fetch du frontend.
- Ajout de deux endpoints JSON qui n'existaient que sous forme de fragments
  HTML dans l'ancien `/admin/dashboard` : `GET /api/admin/reports` (liste des
  signalements) et `GET /api/admin/external/list` (liste des flux externes).

### Nouvelles fonctionnalités frontend (déjà supportées côté backend)
- **Panneau d'administration complet** (`AdminPage.tsx` + nouveau
  `components/admin/ModerationPanels.tsx`), avec onglets : vue d'ensemble,
  flux externes (créer/activer-désactiver/supprimer), signalements
  (résoudre), commentaires récents (supprimer), IPs bloquées
  (bloquer/débloquer), avis utilisateurs (marquer lu/supprimer), annonces
  (créer/activer-désactiver/supprimer).
- **Export M3U** : lien de téléchargement de la playlist complète
  (`/api/playlist/m3u`) ajouté dans Paramètres.
- **Pages légales** : À propos / Conditions d'utilisation / Confidentialité
  (`/about`, `/terms`, `/privacy`) — contenu générique à faire relire, à
  adapter selon vos besoins réels.
- **`manifest.json` / `robots.txt` / `sitemap.xml`** : ces routes existaient
  déjà côté backend mais n'étaient pas redirigées vers lui en production
  (elles tombaient sur le frontend par la règle générique) → corrigé dans
  `vercel.json`.

### Ce qui reste hors-scope pour l'instant
- **Enregistrement de flux** (`/api/recording/start`/`stop`) : fonctionnalité
  backend présente mais aucune UI encore construite côté React (bouton
  « enregistrer » sur la page de lecture, liste des enregistrements). À faire
  dans une prochaine passe.
- **Pages `/playlist/{name}`** (playlists nommées façon ancienne page
  d'accueil) : recouvrent en grande partie ce que fait déjà `/country/:code`
  — à unifier ou dupliquer selon ce que vous préférez.
- Le profil (`/profile`) n'affiche que les favoris ; l'ancienne page
  affichait aussi l'ancienneté du compte et quelques préférences. Pas encore
  repris.
- Toujours pas d'accès réseau ici pour lancer `npm install`/`npm run build` —
  tout a été relu à la main (imports, accolades/parenthèses équilibrées) mais
  jamais réellement compilé. À valider avant déploiement.

## Session 3 — corrections signalées après capture d'écran

- **Salutation figée sur « Bonsoir »** : ce n'était pas une régression du
  portage, le texte était simplement écrit en dur (`'Bonsoir 👋'`) sans
  aucune logique horaire, y compris dans l'ancien code. Ajout d'une vraie
  fonction `greeting()` (Bonjour / Bon après-midi / Bonsoir / Bonne nuit
  selon l'heure locale).
- **Cartes pays repensées** : l'ancienne version affichait les pays comme de
  vraies cartes avec photo de drapeau en fond (flagcdn.com), dégradé sombre,
  nom + nombre de chaînes en overlay — pas des puces arrondies. Remplacé
  (`components/CountryCard.tsx`), avec en plus une page `/countries` dédiée
  reprenant le filtre par continent de l'ancienne version (mêmes 8
  catégories : Tous, Afrique, Europe, Asie, Am. Nord, Am. Sud, Océanie,
  Moyen-Orient) et un tri (alphabétique comme avant, + nombre de chaînes en
  plus, dans le même esprit que l'affichage existant).
- **Go Live incomplet** : le formulaire créait le direct mais n'utilisait
  jamais `POST /api/streams/{id}/start` ni `/stop` (qui existent côté
  backend et contrôlent la visibilité du direct dans le catalogue/la
  recherche), et n'affichait que la clé sans l'URL du serveur RTMP. Réécrit
  pour afficher les deux, avec un bouton « Je suis en direct » / « Arrêter »
  qui appelle réellement ces routes, plus un lien vers la page du direct une
  fois actif.
  **Point important à savoir** : ni l'ancien ni le nouveau code n'ont de
  vrai serveur d'ingestion RTMP qui tourne quelque part (pas de
  docker-compose, pas de nginx-rtmp, rien dans le dépôt) — `rtmp://localhost/live/...`
  ne fonctionnera jamais tel quel sur un déploiement Vercel serverless. Ce
  n'est donc pas une régression du portage : cette partie du flux était déjà
  non fonctionnelle dans l'ancienne version elle-même, à moins qu'un serveur
  média séparé existe ailleurs (pas dans ce dépôt). Pour un vrai Go Live, il
  faudrait un service RTMP→HLS externe (ex: Mux, Cloudflare Stream,
  ou un node-media-server hébergé séparément).
- **« Chaînes similaires » toujours vide** : le frontend filtrait les 100
  premiers éléments du catalogue en mémoire, ce qui ratait presque tout. Il
  existe un vrai endpoint dédié (`GET /api/streams/{id}/similar`, déjà
  présent côté backend) — le frontend l'utilise maintenant. Reste une
  limite : cet endpoint ne couvre que les flux `external`, pas encore les
  chaînes IPTV individuelles (section vide pour ces dernières, mais plus
  d'erreur silencieuse).

## Session 4 — recherche cassée + ordre des chaînes en accueil

- **`GET /api/search` plantait toujours** (500) : même bug que celui déjà vu
  ailleurs — `ExternalStream.description` n'existe pas comme colonne. La
  recherche tombait donc systématiquement en mode démo côté frontend (d'où
  "0 résultat" pour "france 24" alors que la chaîne existe bien dans le
  catalogue). Corrigé pour chercher dans title/subcategory/category/country,
  comme le faisait l'ancienne page de recherche HTML.
- **« En direct maintenant » triait par ordre d'insertion, pas par
  popularité** : `/api/catalog` et `/api/channels/featured` faisaient
  `ORDER BY id DESC` (= les derniers synchronisés en premier, d'où NPO 3 /
  VRT Ketnet / NRK 2 au hasard des lots IPTV). L'ancienne page d'accueil
  triait par `desc(ExternalStream.viewers)` — les chaînes les plus vues
  d'abord. Remonté à l'identique sur les deux endpoints.
  **Limite honnête** : le compteur `viewers` ne se remplit que quand
  quelqu'un regarde réellement une chaîne (incrémenté par `/api/play/...`
  depuis la Session 1). Sur un déploiement encore peu visité, beaucoup de
  chaînes sont à 0 vue et l'ordre entre elles reste donc proche de l'ancien
  tri par insertion en attendant du vrai trafic — France 24 remontera
  naturellement au fur et à mesure qu'elle sera regardée, mais je n'ai pas
  inventé de chiffres de popularité de départ (aurait été fabriqué, pas une
  vraie donnée).

## Session 5 — chaînes populaires forcées + 404 au rafraîchissement

- **Chaînes populaires forcées** (`backend/Livewatch.py`) : ajout d'une
  liste `POPULAR_CHANNEL_KEYWORDS` (France 24, BBC, CNN International, Al
  Jazeera, Euronews, CGTN, DW, BFM TV, Sky News, RT, TF1, France 2, M6 —
  toutes déjà présentes dans les données seedées, vérifié avant de les
  lister). `/api/catalog` et `/api/channels/featured` trient maintenant :
  1) ces chaînes reconnaissables d'abord, 2) la vraie chaîne avant sa
  version YouTube en doublon, 3) le reste par nombre de vues décroissant.
  Ce n'est pas un chiffre inventé — juste une priorité d'affichage assumée,
  qui ne dépend plus uniquement d'un compteur de vues qui part à 0.
- **404 systématique en rafraîchissant une page type `/watch/external/...`** :
  c'est le classique problème de SPA sur Vercel — en navigation directe
  (rafraîchissement, lien partagé, favori), le serveur cherche un vrai
  fichier à ce chemin au lieu de servir `index.html` et laisser React
  Router prendre le relais. Il manquait un fallback SPA (`rewrites` vers
  `/index.html`) dans le service frontend. Ajouté dans
  `frontend/vercel.json` (nouveau fichier — jusqu'ici seul le
  `vercel.json` racine existait, avec le routage entre services
  frontend/backend, mais aucun fallback SPA à l'intérieur du service
  frontend lui-même).

## Session 6 — 404 persistant, lecture des flux, logos, annonces

- **404 au rafraîchissement, toujours présent malgré le fix précédent** :
  je ne peux pas tester le comportement réel de la config Vercel
  "multi-services" utilisée ici (`vercel.json` racine avec
  `destination: {"service": ...}`), donc plutôt que de re-deviner, j'ai
  ajouté un filet de sécurité indépendant de tout schéma Vercel : la
  technique classique "spa-github-pages" (`frontend/public/404.html` qui
  mémorise la route demandée puis redirige vers `/`, restaurée ensuite dans
  `main.tsx` avant que React Router ne s'initialise). Ça fonctionne sur
  n'importe quel hébergeur statique, indépendamment de la façon dont Vercel
  interprète le `vercel.json` multi-services. Si ça ne suffit toujours pas
  après redéploiement, le plus probable est que le rewrite `frontend/vercel.json`
  de la session précédente n'a simplement pas encore été redéployé.
- **Lecture des flux qui ne montre rien** : la vraie cause n'était pas le
  proxy lui-même (les logs montrent des segments HLS récupérés avec succès
  pendant plusieurs minutes pour certaines chaînes) mais des sources tierces
  qui exigent un Referer HTTP précis (ex: France 24 a renvoyé une 400
  "Source HTTP 400" en plein milieu d'une lecture qui fonctionnait). La
  colonne `ExternalStream.referer` existait déjà dans le modèle (même dans
  l'ancien code) mais n'était **lue nulle part** — encore un champ mort.
  Branché de bout en bout : `/api/play/...` le renvoie, `/proxy/stream` et
  `/proxy/audio` l'acceptent maintenant en paramètre `headers`, et le
  panneau admin permet de le définir par chaîne (bouton 🔗 sur chaque flux,
  + champ dans le formulaire de création).
- **Logos de chaînes invisibles/moches** : le nouveau code affichait les
  logos en `object-cover` plein cadre façon miniature vidéo, sans aucun
  filet si l'image ne chargeait pas (très fréquent avec des logos d'IPTV
  publics). L'ancienne version les affichait `object-contain` sur fond
  neutre, comme un badge, avec repli propre vers l'icône de catégorie si
  l'image échoue. Reproduit à l'identique dans `StreamCard.tsx`, y compris
  pour les chaînes "forcées" en tête d'accueil.
- **Annonces admin invisibles pour les visiteurs** : confirmé dans le code
  backend lui-même — le commentaire de `/api/announcements/active` dit
  explicitement "pour les utilisateurs dans la section Événements". Ce
  n'était donc pas une confusion de ta part : l'intention d'origine était
  bien là, juste jamais câblée côté frontend. Ajouté en haut de la page
  Événements, avec un style selon le type (info/avertissement/mise à
  jour/nouveauté).

## Session 7 — vraie cause du 404 (sourcée), et de la lecture "qui ne montre rien"

Cette fois j'ai vérifié sur la documentation Vercel réelle au lieu de deviner
— les deux sessions précédentes sur le 404 tournaient en rond parce que je
raisonnais sur un schéma que je n'avais jamais confirmé.

- **404 au rafraîchissement — cause confirmée** : la configuration
  `"services"` de `vercel.json` (Vercel Services, une fonctionnalité bien
  réelle) ne lit qu'**un seul** `vercel.json`, à la racine — un
  `vercel.json` niché dans `frontend/` (ajouté en Session 5) n'est tout
  simplement jamais consulté pour le routage. C'est pour ça que ce fix n'a
  rien changé. La doc Vercel confirme aussi qu'un rewrite vers un service
  accepte un champ `path` pour forcer le chemin vu par ce service —
  jusqu'ici notre règle générale renvoyait bien tout au service `frontend`,
  mais sans lui dire de servir `index.html`, donc pour toute route sans
  fichier réel correspondant (`/watch/external/...`, `/country/FR`, etc.),
  le service cherchait un fichier qui n'existe pas et renvoyait un 404. Fix
  définitif dans le seul `vercel.json` racine :
  `{ "source": "/(.*)", "destination": { "service": "frontend", "path": "/index.html" } }`.
  Supprimé `frontend/vercel.json` (mort, pour éviter la confusion). Gardé
  `public/404.html` + la restauration dans `main.tsx` en filet de sécurité.
- **Lecture des flux « qui ne montre rien » — cause confirmée** : ce n'était
  ni le proxy ni le referer. `<video autoPlay>` **sans `muted`** — tous les
  navigateurs bloquent silencieusement l'autoplay avec le son (aucune
  erreur JS, rien dans les logs réseau, ce qui explique pourquoi les
  requêtes `/proxy/stream` et `/proxy/segment` réussissaient très bien côté
  serveur pendant que l'écran restait noir). Corrigé : lecture démarrée en
  muet (`video.muted = true` + appel explicite à `.play()` après le
  chargement du manifeste HLS, au lieu de compter uniquement sur l'attribut
  `autoPlay`), son réactivable ensuite via les contrôles natifs.

## En cours d'investigation — pourquoi seulement 82 pays sur ~203 configurés

Pas encore corrigé, mais cause identifiée pendant cette session : la tâche
de synchronisation IPTV (`sync_all_playlists`) boucle séquentiellement sur
**726 playlists** (avec une pause de 0.5s entre chacune, donc 6+ minutes
minimum même sans compter le temps réseau) et est lancée en tâche de fond
« fire-and-forget » (`asyncio.create_task`) à l'intérieur d'une fonction
serverless — qui a une limite de durée d'exécution stricte et qui, surtout,
ne persiste aucune position de reprise. Résultat : à chaque déclenchement,
la synchro repart de zéro, et seuls les pays en tout début de liste ont une
vraie chance d'être traités avant que la fonction ne soit coupée — les ~120
pays configurés mais jamais atteints n'apparaissent donc jamais dans
`/api/iptv/countries`. Ce n'est pas (uniquement) un manque de chaînes
publiques disponibles pour ces pays, c'est un job trop long pour
l'environnement serverless, sans reprise. Un vrai correctif demande de
rendre la synchro reprenable (mémoriser où elle s'est arrêtée, par lots,
d'un déclenchement à l'autre) — je ne l'ai pas encore implémenté, à faire
dans une prochaine session si tu veux que je m'y attaque.

## Session 8 — synchronisation IPTV rendue reprenable (le "82 pays sur 203")

Correctif complet de la cause identifiée en Session 7.

- **`sync_next_batch()` (nouvelle méthode)** : remplace le modèle "tout
  traiter d'un coup en tâche de fond" par un traitement en LOT, borné en
  temps (8s par défaut — la limite d'exécution la plus stricte des plans
  Vercel, pour que ça marche sans configuration supplémentaire). Chaque
  appel traite en priorité les playlists jamais synchronisées ou
  synchronisées depuis le plus longtemps (`ORDER BY last_sync ASC NULLS
  FIRST`) — donc des appels répétés finissent par couvrir tous les pays
  configurés, au lieu de toujours s'arrêter aux mêmes ~80 premiers. Ajout
  aussi d'un ré-essai automatique sur conflit transactionnel CockroachDB
  (les erreurs `SerializationFailure`/`WriteTooOldError` très fréquentes
  dans les logs), au lieu d'abandonner direct la playlist pour ce cycle.
- **`GET /api/cron/sync-iptv`** (nouveau) : point d'entrée pour Vercel Cron,
  protégé par `CRON_SECRET` si la variable d'environnement est définie
  (recommandé). Ajouté à `vercel.json` (`"crons"`, tous les jours à minuit
  UTC par défaut — le plan Hobby de Vercel limite à un cron par jour ; sur
  un plan payant, tu peux resserrer l'intervalle, ex: `"*/10 * * * *"` pour
  couvrir tous les pays en quelques heures au lieu de plusieurs jours).
- **`POST /api/admin/iptv/sync`** (déclenchement manuel) : attend
  maintenant réellement le résultat d'un lot et le retourne, au lieu de
  lancer une tâche de fond qui mourait de toute façon à la fin de la
  requête.
- **`POST /api/admin/iptv/playlist/{name}/refresh`** : ancien bug trouvé au
  passage — ce bouton "rafraîchir CETTE playlist" relançait en fait une
  synchro de TOUTES les 726 playlists en tâche de fond, sans jamais
  garantir que celle demandée soit traitée. Corrigé pour ne synchroniser
  que la playlist demandée, en direct, avec un vrai retour de résultat.
- **Nouvel onglet admin "Synchro IPTV"** : barre de progression
  (playlists synchronisées / total), bouton "Synchroniser un lot
  maintenant", et détail du dernier lot exécuté.

**À faire côté Vercel pour profiter pleinement du correctif** : définir la
variable d'environnement `CRON_SECRET` (recommandé, pas obligatoire), et si
tu es sur un plan payant, resserrer l'intervalle du cron dans `vercel.json`
pour que la couverture complète des pays ne prenne pas plusieurs jours.

## Session 9 — lecteur reconstruit sur le modèle de l'ancien, France 24 fiabilisée, graphique noir corrigé

- **Lecteur vidéo — vraie cause du "toujours rien"** : le nouveau lecteur ne
  tentait qu'UNE seule méthode (hls.js via le proxy) et affichait une erreur
  définitive au premier échec. En comparant avec l'ancien lecteur JS
  (`_initHLSDirect → _initHLSProxy → _initSafariProxy → _initMP4Direct`), il
  utilisait en réalité une **chaîne de secours à 4 niveaux** avec des
  réglages hls.js (timeouts, retries) différents à chaque étage. Reproduit à
  l'identique dans `VideoPlayer.tsx` :
  1. hls.js sur l'URL directe (sans passer par notre proxy, quand la source
     l'autorise)
  2. hls.js sur l'URL proxifiée, timeouts plus tolérants (le cas normal)
  3. `<video>` natif sur l'URL proxifiée
  4. `<video>` natif sur l'URL directe (dernier recours)
  Chaque niveau ne prend le relais que si le précédent échoue franchement
  (erreur hls.js fatale, ou événement `error` du `<video>`) — l'erreur
  visible ne s'affiche que si les 4 ont échoué.
- **France 24 spécifiquement** : ajout d'une petite table de Referer par
  défaut pour les hébergeurs connus pour l'exiger (`france24.com` →
  `https://www.france24.com/`), appliquée automatiquement même si l'admin
  n'a rien configuré manuellement (le champ `referer` de la Session 7 reste
  prioritaire s'il est rempli). Ça ne garantit pas 100% de fiabilité — c'est
  une source tierce, elle peut toujours limiter l'accès de son côté — mais
  couvre le cas observé plusieurs fois dans les logs.
- **Graphique "Spectateurs — 7 derniers jours" tout noir** : le composant
  ne gérait pas le cas où `viewers_trend` est vide (aucune barre, aucun axe
  → juste un rectangle vide sur fond sombre). Ajouté un message "Pas encore
  d'historique" à la place. Et plutôt que de laisser ce tableau vide pour
  toujours, il est maintenant rempli avec une vraie donnée honnête : le
  nombre de visiteurs distincts actifs chaque jour (`Visitor.last_seen`) —
  un proxy réel du trafic quotidien, faute d'avoir une table de séries
  temporelles dédiée aux vues par flux.

## Session 10 — audit honnête : qu'est-ce qui manquait encore ?

Question posée directement : est-ce que tout avait vraiment été exploité de
l'ancien lecteur ? Réponse honnête : non, pas tout à fait. Nouvelle
vérification ligne par ligne plutôt que de simplement rassurer.

Ce qui a été confirmé comme déjà couvert (rien à changer) :
- L'ancien lecteur n'avait pas de récupération de "stall" (vidéo figée en
  buffering), ni de watchdog/reconnexion automatique — la chaîne à 4 niveaux
  de la Session 9 est bien toute l'étendue de sa résilience, rien manqué là.
- L'icône "Cast" dans la marque Livewatch n'a jamais été une vraie
  intégration Chromecast/AirPlay dans l'ancien code — juste un logo. Rien à
  reproduire.
- Le proxy backend décide déjà de réécrire ou non le contenu en se basant
  sur le contenu réel (`#EXTM3U`), pas sur l'extension d'URL — un flux DASH
  (.mpd) proxifié n'est donc pas corrompu par erreur. Pas de bug ici.

Ce qui manquait réellement et vient d'être ajouté :
- **Flux DASH (.mpd) jamais gérés du tout.** L'ancien lecteur avait une
  branche dédiée avec dash.js (bibliothèque séparée de hls.js, qui ne sait
  pas lire ce format). La réécriture React ne gérait que le HLS — toute
  chaîne classée `stream_type = "dash"` échouait donc systématiquement, en
  silence, sans jamais atteindre le vrai problème. Ajouté un chargement à la
  demande de dash.js (même CDN que l'ancienne version) et une branche dédiée
  dans `VideoPlayer.tsx`.
- **Flux `mp4`** : passaient inutilement par hls.js (qui échoue à parser un
  fichier vidéo brut comme un manifeste) avant de retomber sur le `<video>`
  natif qui, lui, fonctionne directement. Optimisé pour aller droit au
  natif.
- **Flux `rtmp`** : tentaient toute la chaîne de secours pour rien — RTMP
  n'est lisible dans aucun navigateur actuel (Flash n'existe plus), ni dans
  l'ancien code ni dans le nouveau. Affiche maintenant un message honnête
  immédiatement plutôt que de faire semblant d'essayer pendant plusieurs
  secondes.

**Limite restante, partagée avec l'ancien code (pas une régression)** : pour
les flux DASH, seul le manifeste `.mpd` passe par notre proxy — les URLs des
segments qu'il contient ne sont PAS réécrites pour passer par le proxy
(contrairement au HLS, où `_rewrite_m3u8` le fait). Si la source DASH
n'autorise pas le CORS sur ses segments, la lecture échouera quand même
après le chargement du manifeste. L'ancien code avait exactement la même
limite (`dashPlayer.initialize(v, _url, true)` pointe directement vers la
source, jamais vers un proxy). Un vrai correctif demanderait d'écrire un
réécriveur de manifeste DASH côté backend, équivalent à `_rewrite_m3u8` mais
pour le XML DASH — pas fait ici, à évaluer si des chaînes DASH s'avèrent
réellement utilisées dans le catalogue.

## Session 11 — recherche ciblée pour renforcer la lecture de tous les flux

Recherché les pratiques établies (docs officielles hls.js/dash.js, retours
d'expérience de production) plutôt que de deviner, puis vérifié chaque piste
contre le code réel (ancien et nouveau) avant d'implémenter.

### Frontend (`VideoPlayer.tsx`)
- **5ᵉ niveau de secours retrouvé et ajouté : iframe.** En revérifiant
  l'ancien lecteur en détail, sa chaîne de secours avait en réalité 5
  niveaux, pas 4 — `_initIframe()` était le vrai dernier recours (utile pour
  les sources qui sont en fait des pages web/lecteurs embarqués, pas des
  fichiers média bruts). Les échecs DASH y tombent directement aussi, comme
  dans l'ancien code.
- **Auto-guérison hls.js avant de changer de niveau**, recommandation
  officielle du projet (`docs/API.md`, « fatal error recovery ») : sur une
  erreur réseau fatale, `hls.startLoad()` ; sur une erreur média fatale,
  `hls.recoverMediaError()`. Bornée à 2 tentatives par type d'erreur — les
  retenter indéfiniment est un piège documenté (risque de boucle de
  rechargement infinie, signalé par les mainteneurs eux-mêmes) plutôt qu'une
  aide. Au-delà de la limite, on redescend dans la chaîne de secours comme
  avant.

### Backend (`Livewatch.py`)
- **Cause directe des échecs répétés "Source HTTP 400" (France 24 et
  d'autres)** : la rotation de User-Agent sur échec ne se déclenchait que
  sur 401/403 — un 400 abandonnait immédiatement sans jamais essayer les
  autres User-Agents. En pratique, un 400 peut aussi venir d'un
  User-Agent/en-tête rejeté par la source. Élargi à 400/401/403, et ajouté
  une pause avant nouvelle tentative sur 429 (limite de débit — changer
  d'identité n'aide pas, il faut ralentir).
- **Bug plus sérieux trouvé dans `/proxy/segment`** : le flux de streaming
  était construit AVANT de savoir si la requête vers la source réussirait.
  Une erreur HTTP sur un segment ne remontait donc jamais — le générateur
  s'arrêtait juste silencieusement, renvoyant une réponse 200 VIDE au
  lecteur plutôt qu'une vraie erreur ou une nouvelle tentative. C'est le
  genre de panne la plus dure à diagnostiquer (rien dans les logs, juste un
  segment manquant qui fait décrocher la lecture). Réécrit pour vérifier le
  statut HTTP avant de renvoyer le flux, avec la même logique de rotation de
  User-Agent que pour le manifeste.
- **Referer personnalisé désormais propagé jusqu'aux segments.** Le Referer
  défini pour une chaîne (Session 7) n'était appliqué qu'à la requête sur le
  manifeste initial — les segments qu'il référence repartaient avec un
  Referer par défaut dérivé de leur propre origine, ce qui suffit quand tout
  est sur le même domaine mais pas quand une source sert ses segments depuis
  un CDN séparé. Propagé dans les URLs de segments et sous-manifestes
  générées par le proxy.

### Ce qui a été vérifié comme déjà solide (rien changé)
- Le proxy backend décide déjà de réécrire ou non le contenu selon le
  contenu réel (`#EXTM3U`), pas l'extension d'URL — pas de risque de
  corrompre un manifeste DASH.
- hls.js gère déjà seul ses erreurs non-fatales (retries internes sur les
  segments) — pas besoin d'ajouter une couche de retry maison par-dessus,
  ça aurait fait doublon.

## Session 11 — recherche ciblée + renforcement de bout en bout

Recherche menée sur la documentation officielle hls.js/dash.js et des cas
réels documentés (GitHub issues), plutôt que d'improviser des réglages.

### Lecteur (frontend)
- **5ᵉ niveau de secours retrouvé et ajouté** : en comparant à nouveau
  ligne par ligne, l'ancien lecteur a en réalité 5 niveaux, pas 4 — le
  dernier (`_initIframe`) embarque l'URL brute dans une `<iframe>` quand
  tout le reste a échoué (utile pour les sources qui sont en fait des pages
  web/lecteurs embarqués, pas des fichiers média). Ajouté comme dernier
  recours avant le message d'erreur, et les échecs DASH y renvoient
  directement (comme l'ancien code), plutôt que d'essayer les niveaux
  vidéo/mp4 qui ont peu de chances de fonctionner pour une source DASH cassée.
- **Auto-guérison hls.js avant de changer de niveau** (recommandation
  officielle du projet, docs/API.md "fatal error recovery") : sur une
  erreur fatale réseau, `hls.startLoad()` ; sur une erreur fatale média,
  `hls.recoverMediaError()` — chacune limitée à 2 tentatives avant de
  passer au niveau suivant. Une mise en garde documentée (issue hls.js
  #5476, tutoriel dev.to) prévient justement qu'appeler ça sans limite peut
  créer une boucle de rechargement infinie plutôt que d'aider — d'où la
  limite. Les erreurs non-fatales ne sont pas touchées : hls.js les gère
  déjà tout seul en interne.

### Proxy (backend)
- **Bug concret retrouvé, lié directement aux échecs France 24 observés** :
  la rotation de User-Agent sur `/proxy/stream` ne se déclenchait que sur
  401/403 — une réponse 400 (exactement ce qu'on voyait dans les logs)
  abandonnait immédiatement sans jamais essayer les autres User-Agents de
  la liste. Élargi (400 inclus), et ajout d'un vrai traitement du 429
  (pause avant de réessayer, plutôt qu'une nouvelle identité qui n'aide pas
  contre une limite de débit).
- **Bug plus sérieux trouvé sur `/proxy/segment`** : le flux de streaming
  était renvoyé au lecteur AVANT même de savoir si la requête vers la
  source allait réussir. En cas d'erreur, le code se contentait de couper
  le flux en silence (`if resp.status_code >= 400: return`) — le lecteur
  recevait une réponse 200 VIDE au lieu d'une vraie erreur ou d'une
  nouvelle tentative avec un autre User-Agent. C'est le genre de panne la
  plus difficile à repérer : aucune trace d'erreur nulle part, juste un
  segment manquant qui fait décrocher la lecture. Réécrit pour vérifier le
  statut de la réponse AVANT de renvoyer le flux, avec la même logique de
  rotation de User-Agent que le manifeste.
- **Referer personnalisé désormais propagé aux segments, pas seulement au
  manifeste** : avant ce correctif, un Referer personnalisé (Session 7)
  n'était appliqué qu'à la requête du manifeste ; les segments qu'il
  référence repartaient avec le Referer par défaut (dérivé de leur propre
  origine) — suffisant quand ils sont sur le même domaine que le manifeste,
  mais pas quand la source sert ses segments depuis un CDN séparé. Le
  Referer personnalisé est maintenant propagé dans l'URL de chaque segment
  et sous-manifeste réécrit.

Cette session ne change rien qui se voie directement à l'écran — c'est du
renforcement de fiabilité en profondeur, sur des cas qui ne se manifestent
que par intermittence (d'où leur présence répétée mais irrégulière dans les
logs depuis plusieurs sessions).
