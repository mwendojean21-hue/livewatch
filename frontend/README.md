# Livewatch — Frontend (React + TypeScript)

Nouveau frontend de Livewatch, entièrement réécrit en TypeScript (React 19 + Vite +
Tailwind CSS v4), pensé pour être responsive du mobile au desktop et pour offrir
un vrai mode clair et un vrai mode sombre (pas un simple filtre).

Il consomme le backend FastAPI existant (`Livewatch.py`) via ses routes `/api/...`
en JSON — le HTML généré côté serveur (Jinja2) n'est plus utilisé par cette
interface.

## Démarrer en développement

```bash
npm install
npm run dev
```

Le serveur de dev tourne sur http://localhost:5173 et relaie automatiquement
`/api`, `/ws` et `/proxy` vers le backend FastAPI sur `http://localhost:8001`
(voir `vite.config.ts`). Lancez donc `Livewatch.py` en parallèle sur le port 8001.

Si le backend n'est pas joignable, l'interface reste utilisable : elle bascule
automatiquement en **mode démo** (données d'exemple, bandeau d'avertissement en
haut de chaque page) — pratique pour travailler sur le design sans base de
données PostgreSQL connectée.

## Build de production

```bash
npm run build   # → dist/
npm run preview # sert dist/ localement pour vérification
```

Pour un déploiement où le frontend et le backend ne sont pas sur le même
domaine, définissez `VITE_API_BASE_URL` (voir `.env.example`) et activez CORS
côté FastAPI pour ce domaine (déjà fait dans `Livewatch.py`, voir la section
CORS ajoutée en tête du fichier).

## Structure

```
src/
  api/          client HTTP typé + données de démonstration
  components/   AppShell (sidebar/bottom-nav), StreamCard, VideoPlayer, Charts...
  context/      ThemeContext (clair/sombre/système, persistant)
  hooks/        useAsync (chargement de données), useDemoMode
  lib/          métadonnées des catégories (icônes, couleurs)
  pages/        une page par route
  types/        types alignés sur les modèles SQLAlchemy du backend
```

## Design

- **Sombre par défaut** (produit de diffusion, usage en soirée), clair
  entièrement supporté — bascule dans les réglages ou la barre du haut.
- Rouge signal (`--accent`) réservé aux indicateurs "en direct" ; bleu
  (`--accent-2`) pour les liens, l'état actif et les graphiques.
- Barre latérale sur desktop, barre d'onglets en bas sur mobile (bouton
  "Diffuser" mis en avant), au format des applications mobiles modernes.
