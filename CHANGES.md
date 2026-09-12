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
