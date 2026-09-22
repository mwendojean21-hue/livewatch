# Livewatch — déploiement en un seul service

Ce dossier remplace l'architecture à deux services Vercel (frontend + backend
séparés) par **un seul service Python**, exactement comme la toute première
version qui tournait sur Vercel. `Livewatch.py` sert maintenant lui-même le
frontend React déjà compilé (`frontend/dist/`), en plus de toutes les routes
`/api`, `/proxy`, `/ws`, `/admin/login`.

## Ce qui a changé par rapport à `backend/Livewatch.py`

- Les anciennes pages Jinja2 (`/`, `/watch/...`, `/search`, `/admin`,
  `/admin/dashboard`, `/settings`, `/profile`, `/about`, `/terms`,
  `/privacy`, `/go-live`, `/events`, `/playlist/...`) ont été retirées : le
  frontend React gère déjà exactement ces mêmes routes côté navigateur.
- Tout en bas du fichier, une route `catch-all` sert `frontend/dist/index.html`
  pour toute URL qui n'est pas une route backend explicite — c'est ce qui
  permet au React Router de prendre le relais.
- Rien d'autre n'a été modifié : toutes les routes `/api/...`, `/proxy/...`,
  `/ws/...`, la logique de lecture des flux, l'admin, etc. sont identiques à
  `backend/Livewatch.py`.

## Déploiement sur Vercel

1. **Supprime** de ton dépôt GitHub : l'ancien `vercel.json` à la racine (le
   multi-services), et surtout l'ancien `Livewatch.py` / `requirements.txt` /
   `pyproject.toml` qui traînaient à la racine (l'ancienne version non
   corrigée — mot de passe admin en dur, à ne surtout pas laisser dans le
   dépôt).
2. **Remplace** le contenu du dépôt par les fichiers de ce dossier
   (`Livewatch.py`, `requirements.txt`, `pyproject.toml`, `static/`,
   `frontend/`).
3. Dans Vercel → Project Settings → Build and Deployment → **Framework
   Preset** : laisse-le sur la valeur par défaut (ou "Other") — surtout pas
   "Services", il n'y a plus de `vercel.json` multi-services.
4. Vérifie dans Settings → Environment Variables que ces trois variables
   sont bien définies (le backend refuse de démarrer sans elles) :
   - `SECRET_KEY`
   - `DATABASE_URL`
   - `ADMIN_PASSWORD`
5. Push et laisse Vercel redéployer. Il détecte `pyproject.toml` →
   `[tool.vercel] entrypoint = "Livewatch:app"`, exactement comme avant.

## Si tu modifies le frontend (React) plus tard

Le dossier `frontend/dist/` est ce qui est réellement servi — ce n'est PAS
reconstruit automatiquement par Vercel. Après une modif dans `frontend/src` :

```
cd frontend
npm install
npm run build
```

Puis commite le nouveau contenu de `frontend/dist/` avec le reste.

## Deux points annexes trouvés en chemin (pas corrigés ici, pour ne pas élargir le changement)

- `resolve_playback` (`/api/play/user/{id}`) n'applique pas les vérifications
  IP bloquée / stream bloqué que l'ancienne page `/watch/user/...` faisait.
  Le frontend React appelle déjà exclusivement cette route, donc ce n'est pas
  une régression introduite ici — mais si la modération de tes streams
  utilisateurs t'importe, ça vaut le coup de l'ajouter dans
  `resolve_playback`.
- À l'arrêt du serveur (`lifespan` shutdown), `await proxy.close()` échoue
  car `HLSProxy` ne définit pas de méthode `close()`. Sans impact pendant que
  le service tourne et répond aux requêtes — juste une erreur inoffensive
  loggée à l'extinction.
