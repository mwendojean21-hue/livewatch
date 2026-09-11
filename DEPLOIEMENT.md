# Livewatch — Guide de mise à jour sur Vercel (via GitHub)

Architecture retenue : **un seul projet Vercel** (`livewatch-pink`), qui héberge
à la fois le nouveau frontend React et le backend FastAPI (`Livewatch.py`),
grâce à la fonctionnalité **Vercel Services** — un seul domaine, pas de CORS
à gérer entre les deux. La base de données PostgreSQL reste où elle est déjà
hébergée (elle n'a pas besoin de bouger).

**Limite à connaître** : le chat en direct (`/ws/...`) fonctionne sur Vercel
depuis juin 2026, mais chaque connexion WebSocket est épinglée à une seule
instance, sans diffusion automatique entre instances. Résultat concret : un
visiteur seul dans un chat, ça marche. Plusieurs visiteurs du même direct qui
doivent se voir écrire entre eux, ça ne marche pas de façon fiable sans un
store externe (Redis / Vercel KV) — non fait dans cette passe, à traiter
séparément si tu veux ce chat multi-spectateurs.

---

## 0. Avant tout : rotation des identifiants compromis

L'ancien `Livewatch.py` contenait ton vrai mot de passe PostgreSQL, une clé
JWT fixe et un mot de passe admin fixe, écrits en dur à 8 endroits du fichier
(détail dans `BUGS_FOUND.md`). Ce fichier est passé par cette conversation :
considère ces trois secrets comme grillés.

- **Mot de passe PostgreSQL** : va dans le dashboard de l'hébergeur de ta
  base (Render si c'est là qu'elle vit) → la base → **Rotate credentials** /
  **Reset Password**. Si la base est chez Render et que le mot de passe est
  régénéré depuis Render, il change uniquement là-bas : il faudra recopier la
  nouvelle `DATABASE_URL` dans les variables d'environnement Vercel (étape 4).
- **Nouvelle `SECRET_KEY`** :
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
- **Nouveau `ADMIN_PASSWORD`** : un mot de passe fort, différent de l'ancien.

---

## 1. Préparer les fichiers en local

Structure du dépôt (déjà organisée dans le zip fourni) :
```
livewatch/
├── vercel.json          ← config Vercel Services (fournie)
├── BUGS_FOUND.md
├── backend/
│   ├── Livewatch.py      ← corrigé
│   ├── requirements.txt
│   ├── .env.example
│   └── .gitignore
└── frontend/
    └── (le frontend React/TypeScript)
```

`vercel.json` à la racine (déjà inclus dans le zip) :
```json
{
  "services": {
    "frontend": { "root": "frontend/", "framework": "vite" },
    "backend": { "root": "backend/", "entrypoint": "Livewatch:app" }
  },
  "rewrites": [
    { "source": "/api/:path*", "destination": { "service": "backend" } },
    { "source": "/ws/:path*", "destination": { "service": "backend" } },
    { "source": "/health", "destination": { "service": "backend" } },
    { "source": "/admin/login", "destination": { "service": "backend" } },
    { "source": "/admin/logout", "destination": { "service": "backend" } },
    { "source": "/(.*)", "destination": { "service": "frontend" } }
  ]
}
```
Ce fichier dit à Vercel : « tout ce qui commence par `/api`, `/ws`, `/health`,
ou les deux routes de connexion admin va au service Python ; **tout le
reste** (l'accueil, `/watch/...`, `/search`, `/admin`, `/settings`...) va au
frontend React, qui gère sa propre navigation. »

`backend/requirements.txt` — déjà fourni, testé (installation propre, import
réussi) :
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
python-dotenv==1.0.1
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
jinja2==3.1.4
aiofiles==24.1.0
aiohttp==3.10.5
httpx==0.27.2
Pillow==10.4.0
m3u8==5.1.0
python-dateutil==2.9.0.post0
yt-dlp==2024.8.6
```

---

## 2. Pousser sur GitHub

Si `livewatch-pink` est **déjà** relié à un dépôt GitHub existant : passe
directement à l'étape « mettre à jour » ci-dessous. Sinon (nouveau dépôt) :

```bash
cd livewatch
git init
git add .
git commit -m "Réécriture frontend TypeScript + corrections backend + Vercel Services"
git branch -M main
git remote add origin https://github.com/VOTRE-COMPTE/livewatch.git
git push -u origin main
```

**Mettre à jour un dépôt existant** (cas le plus probable ici, puisque
`livewatch-pink` tourne déjà) :
```bash
cd /chemin/vers/ton/dépôt/existant

# Remplace le contenu par les nouveaux fichiers fournis :
#  - copie Livewatch.py corrigé dans backend/
#  - copie le contenu du frontend dans frontend/
#  - copie vercel.json à la racine
#  - copie BUGS_FOUND.md à la racine

git add .
git commit -m "Réécriture frontend TypeScript + corrections backend + Vercel Services"
git push
```
Un `git push` sur la branche connectée à Vercel déclenche automatiquement un
nouveau déploiement (comportement déjà actif si le site marche déjà sur
Vercel aujourd'hui).

---

## 3. Configurer/vérifier le projet Vercel

Si le projet Vercel existe déjà (`livewatch-pink`), Vercel va détecter le
nouveau `vercel.json` au prochain déploiement et basculer automatiquement sur
la configuration Services (deux services au lieu d'un seul gros backend
monolithique). Rien à recréer manuellement.

Si tu pars de zéro :
1. [vercel.com](https://vercel.com) → **Add New** → **Project**.
2. Importe le dépôt GitHub `livewatch`.
3. Vercel lit `vercel.json` à la racine et détecte les deux services
   (`frontend`, `backend`) automatiquement — pas besoin de choisir un
   framework à la main.
4. Clique **Deploy**. Le premier déploiement peut échouer si les variables
   d'environnement obligatoires du backend ne sont pas encore définies —
   normal, on les ajoute à l'étape suivante.

---

## 4. Variables d'environnement

Dashboard Vercel → le projet → **Settings** → **Environment Variables**.
Ajoute (si l'interface propose de cibler un service en particulier, choisis
le service **backend** pour celles-ci — sinon elles s'appliquent au projet
entier, ce qui est sans risque puisque le frontend n'en a pas besoin) :

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | `postgresql://user:motdepasse@host:5432/dbname` (le nouveau mot de passe de l'étape 0) |
| `SECRET_KEY` | la valeur générée à l'étape 0 |
| `ADMIN_USERNAME` | ton choix |
| `ADMIN_PASSWORD` | le nouveau mot de passe de l'étape 0 |
| `ADMIN_EMAIL` | ton email |

`ALLOWED_ORIGINS` et `VITE_API_BASE_URL` **ne sont pas nécessaires** en
production dans cette architecture : frontend et backend partagent le même
domaine (`livewatch-pink.vercel.app`), donc pas de CORS à configurer, et les
appels `/api/...` du frontend fonctionnent tels quels sans URL à préciser.

Clique **Save**, puis **Deployments** → **⋯** sur le dernier déploiement →
**Redeploy** pour que les nouvelles variables soient prises en compte.

---

## 5. Vérifier que tout fonctionne

1. `https://livewatch-pink.vercel.app/health` → doit répondre `{"status":"ok", ...}`.
   Si erreur : **Deployments** → le déploiement → onglet **Logs**, l'erreur
   exacte y apparaît (souvent une variable manquante — l'app est conçue pour
   refuser de démarrer avec un message clair dans ce cas).
2. `https://livewatch-pink.vercel.app/` → doit afficher le **nouveau**
   frontend React (cartes, catégories colorées, mode sombre par défaut) —
   plus l'ancien HTML.
3. `https://livewatch-pink.vercel.app/admin` → doit afficher un formulaire de
   connexion (nouveau, remplace l'ancienne page Jinja) ; connecte-toi avec
   `ADMIN_USERNAME`/`ADMIN_PASSWORD` définis à l'étape 4 → le tableau de bord
   avec les graphiques doit s'afficher.
4. Ajoute un favori ou sauvegarde un paramètre depuis le frontend : si ça
   fonctionne sans erreur dans la console du navigateur (F12), le cookie de
   session passe bien (normal ici, tout est same-origin).

---

## 6. Et après ?

- **Déploiements automatiques** : chaque `git push` sur la branche connectée
  redéploie automatiquement les deux services.
- **Domaine personnalisé** : Project Settings → **Domains** — s'applique au
  projet entier (donc aux deux services via le routage `vercel.json`).
- **Chat multi-spectateurs** : si tu veux vraiment que plusieurs visiteurs
  d'un même direct se voient écrire en temps réel, dis-le-moi — ça demande
  d'ajouter un store externe (Vercel KV ou Redis) pour la diffusion entre
  instances, ce n'est pas fait dans cette passe.
- **Base de données** : si elle est hébergée gratuitement sur Render, elle
  expire 30 jours après sa création (grâce de 14 jours, puis suppression).
  Vérifie son échéance dans le dashboard Render si Livewatch doit rester en
  ligne durablement.

---

## Checklist finale

- [ ] Mot de passe PostgreSQL changé
- [ ] Nouvelle `SECRET_KEY` générée
- [ ] Nouveau `ADMIN_PASSWORD` choisi
- [ ] Code poussé sur GitHub (`backend/`, `frontend/`, `vercel.json` à la racine)
- [ ] Variables d'environnement backend renseignées sur Vercel, puis redeploy
- [ ] `/health` répond `ok`
- [ ] `/` affiche le nouveau frontend React (plus l'ancien HTML)
- [ ] `/admin` affiche le formulaire de connexion, et la connexion fonctionne
- [ ] Favoris/paramètres fonctionnent sans erreur console
