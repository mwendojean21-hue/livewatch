# Livewatch

## Structure du projet

```
livewatch/
└── livewatch-backend/
    ├── Livewatch.py          Serveur FastAPI (backend + rendu des pages)
    ├── requirements.txt
    ├── .env.example
    ├── templates/             généré automatiquement au premier lancement
    └── static/
        ├── uploads/
        ├── thumbnails/
        ├── recordings/
        └── downloads/
            └── livewatch.apk  ← déposez ici l'APK Android
```

Livewatch est une application monolithique (backend + pages rendues côté
serveur en Jinja2), il n'y a donc pas de dossier frontend séparé comme
dans un projet SPA classique : les pages HTML sont générées par
`Livewatch.py` lui-même dans `templates/` au démarrage.

## Installation

```bash
cd livewatch-backend
pip install -r requirements.txt
cp .env.example .env
# éditez .env avec vos vraies valeurs (DATABASE_URL, SECRET_KEY, ADMIN_PASSWORD)
```

## Lancer le serveur

```bash
python Livewatch.py
```

Le serveur écoute sur `http://0.0.0.0:8001` (ou la variable `PORT`).

## Téléchargement de l'APK par les utilisateurs

Déposez le fichier `livewatch.apk` dans :
```
livewatch-backend/static/downloads/livewatch.apk
```

Le bouton **Télécharger l'APK** apparaît dans le tableau de bord utilisateur,
page **Paramètres** (`/settings`), et appelle la route `/download/apk`.

## Accès administrateur

Le lien **Administration** n'apparaît plus dans le menu que pour les
utilisateurs authentifiés en tant qu'admin (cookie `admin_token` valide).
Pour un visiteur normal, ce lien est totalement absent du HTML rendu
(pas seulement caché en CSS).

Connexion admin : `/admin` (identifiants dans `.env`).
