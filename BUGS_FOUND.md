# Livewatch — Rapport de correction backend (`Livewatch.py`)

Tout ce qui est listé ci-dessous a été corrigé directement dans le fichier.
Gardé ici comme journal de ce qui a changé et pourquoi — utile si vous
retrouvez un jour un comportement différent de l'ancienne version.

## ✅ 1. CORS cassé pour toute authentification par cookie

Le middleware `CORSMiddleware` était enregistré **deux fois**, chaque fois
avec `allow_origins=["*"]` **et** `allow_credentials=True`. C'est invalide
selon la spécification CORS : un navigateur refuse d'exposer la réponse à une
page qui envoie des identifiants (ici le cookie `visitor_id`, utilisé pour les
favoris et les paramètres) si le serveur répond avec une origine générique
`*`. Un frontend séparé (comme le nouveau frontend React) ne pouvait donc pas
faire fonctionner favoris/paramètres en cross-origin.

**Correctif** : une seule instance du middleware, avec une liste explicite
d'origines autorisées (`ALLOWED_ORIGINS`, configurable par variable
d'environnement — voir le guide de déploiement).

## ✅ 2. Types d'ID incohérents (`int` déclaré, UUID réel en base)

Toutes les tables utilisent `PG_UUID(as_uuid=False)` comme clé primaire (donc
une chaîne comme `"3f2a1e4c-..."`), mais 7 endpoints déclaraient leur
paramètre de chemin comme `int`. FastAPI rejetait alors **toute** requête
avec un vrai identifiant (erreur 422), rendant l'endpoint inutilisable en
pratique :

- `GET /api/streams/{id}/similar`
- `GET` et `POST /api/streams/{id}/comments`
- `DELETE /api/admin/external/{id}/delete`
- `POST /api/admin/ips/unblock/{id}`
- `DELETE /api/favorites/{stream_id}` (utilisé directement par le nouveau frontend)
- `WS /ws/stream/{stream_id}`

**Correctif** : `id: int` → `id: str` sur les 7 endpoints.

## ✅ 3. 36 routes dupliquées (42 définitions mortes) supprimées

FastAPI ne garde que la **première** route déclarée pour un couple
(méthode, chemin) ; Starlette, à l'inverse, garde la **dernière** pour un
gestionnaire d'erreur (`exception_handler`). Le fichier contenait 36 chemins
déclarés plusieurs fois (jusqu'à 3 fois pour certains), soit 42 définitions
qui n'étaient jamais exécutées — du code mort silencieux.

Pour chaque doublon, j'ai comparé les implémentations avant de trancher :
- **Routes API** : gardé la première déclaration (celle réellement active
  jusqu'ici), supprimé les suivantes.
- **`exception_handler(404)`** (seul cas de ce type dupliqué) : gardé la
  **dernière** déclaration, car c'est elle qui l'emportait réellement.

Le fichier est passé de 14 631 à environ 13 890 lignes. Vérifié après coup :
zéro route dupliquée restante, et l'application s'importe et enregistre ses
125 routes sans erreur.

**Point d'attention** : plusieurs paires de doublons avaient des corps
sensiblement différents (`/api/admin/dashboard/summary`,
`/ws/admin/live`, `/api/favorites` GET et POST, `/api/iptv/channels`,
`/api/iptv/playlists`, `/api/recording/start`...) — signe que ces routes ont
été réécrites à un moment sans que l'ancienne version soit supprimée. J'ai
gardé dans chaque cas la version qui était **déjà active en production**
(donc aucun changement de comportement pour vos utilisateurs), mais si vous
vous souvenez avoir voulu remplacer l'une de ces routes par une réécriture
plus récente qui n'a jamais pris effet à cause de ce bug, dites-le-moi — je
peux comparer les deux versions précisément et basculer sur la bonne.

## ✅ 4. Action destructive exposée en `GET` (CSRF)

`GET /api/admin/ips/{ip_id}/unblock` débloquait une IP en réponse à une
simple requête `GET` — déclenchable par un lien, une balise `<img>`, ou un
scanner automatique, sans aucune confirmation. **Supprimé** ; la version
`POST` équivalente couvre déjà ce besoin.

## ✅ 5. Secrets codés en dur — dans 8 endroits différents, pas juste un

`Settings.SECRET_KEY`, `ADMIN_PASSWORD`, `ADMIN_USERNAME`, `ADMIN_EMAIL`, et
l'URL PostgreSQL complète **avec le mot de passe réel de votre base de
données de production** apparaissaient en clair non pas à un seul endroit,
mais dans **8 endroits** du fichier : la classe `Settings`, deux fonctions
distinctes de création du compte admin (`init_admin_account` et un second
bloc dans `lifespan`, jamais nettoyé après une réécriture), la page de
connexion admin, le log de démarrage (deux fois — `print` et `logger.info`),
la route `/api/admin/config/export`, le docstring d'en-tête du fichier, et un
bloc de commentaires de documentation. Trois de ces endroits recréaient même
le compte admin avec les identifiants codés en dur **indépendamment** de la
variable d'environnement `ADMIN_PASSWORD` — donc même en la changeant, le
mot de passe réel restait `WALKER92259` tant que ce bloc n'était pas modifié.

Ce fichier est passé par plusieurs échanges depuis — **ces identifiants
doivent être considérés comme compromis, qu'ils fuient publiquement ou non.**

**Correctif** : les 8 endroits pointent maintenant vers une seule source de
vérité (`Settings`, alimentée uniquement par les variables d'environnement,
sans aucun défaut fonctionnel) ; le mot de passe n'est plus jamais écrit dans
les logs ni dans le docstring.

**Action de votre côté (à faire avant tout redéploiement)** — voir la
section « Rotation des identifiants » du guide de déploiement ci-dessous :
1. Changer le mot de passe de la base PostgreSQL sur Render.
2. Générer une nouvelle `SECRET_KEY`.
3. Choisir un nouveau `ADMIN_PASSWORD` (différent de `WALKER92259`).

## ✅ 6. Frontend : page de connexion admin manquante

En remplaçant les pages HTML générées par Jinja2 par le nouveau frontend
React, la page `/admin` n'avait plus de formulaire de connexion (l'ancien
`admin_login.html` disparaissait sans équivalent) — le tableau de bord admin
du nouveau frontend supposait une session déjà active. Un composant
`AdminLoginForm` a été ajouté, qui appelle `POST /admin/login` (le même
endpoint que l'ancien système, format de formulaire inchangé) et affiche le
tableau de bord dès la connexion réussie, sans recharger la page.

**Point d'attention lié à Vercel Services** : `/admin/login` et
`/admin/logout` ne sont pas sous `/api/...` — sans règle explicite dans
`vercel.json`, ils auraient été interceptés par la route « tout le reste » du
frontend au lieu d'atteindre le backend. Ajouté explicitement dans les
`rewrites` (voir `DEPLOIEMENT.md`).

## ⚠️ Non corrigé — incohérence de modélisation des commentaires

`GET`/`POST /api/streams/{id}/comments` interrogent la table `LiveStream`,
alors que les endpoints de like/report (`/like`, `/report`) interrogent
`UserStream` — deux tables différentes pour ce qui devrait être « le même
stream ». Le nouveau frontend affiche les chaînes du catalogue
(`ExternalStream`, via `/api/catalog`), qui n'est ni l'une ni l'autre : les
commentaires ne remonteront donc rien pour ces chaînes tant que ce point
n'est pas clarifié. C'est une décision de modélisation (faut-il un seul type
de « stream » unifié, ou vraiment trois entités séparées ?) que je n'ai pas
tranchée à votre place — dites-moi ce que vous préférez et je l'implémente.
