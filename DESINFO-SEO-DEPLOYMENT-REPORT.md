# Rapport de déploiement SEO — Desinfo

**Date** : 3 novembre 2026 (Europe/Paris)  
**Dépôt** : https://github.com/ZaraA1971/Desinfo  
**Branche** : `cursor/desinfo-seo-ssr-indexation-daf6`  
**URL publique** : https://desinfo.electronlibre.info/

## État initial (avant déploiement)

Constat sur la production publique :

| Contrôle | État initial |
|---|---|
| HTML d’accueil | Shell CSR : `BAILOUT_TO_CLIENT_SIDE_RENDERING` + « Chargement… » |
| Contenu éditorial (palmarès) | Absent du HTML initial (chargé côté client seulement) |
| `<title>` | Présent : « Observatoire de la désinformation » |
| Meta description | Présente |
| Canonical | Absent |
| `robots.txt` | Réponse non utile à l’indexation (pas de règles Next `Allow`/`Disallow`/`Sitemap`) |
| `sitemap.xml` | **404** |
| SSR/SSG | Bailout client — pas de HTML de ranking pour les crawlers |

Cause racine : la page d’accueil était un Client Component avec `useSearchParams`, ce qui provoque le bailout Next.js et un HTML vide pour Googlebot.

Racine runtime prod : `/srv/intel/desinfo` (unité `desinfo-frontend`, port `8710`).  
Note : la doc repo mentionne `/srv/desinfo` ; le service systemd pointe vers `/srv/intel/desinfo`.

## Corrections livrées

### Fichiers modifiés / ajoutés

| Fichier | Rôle |
|---|---|
| `frontend/src/app/page.tsx` | Server Component : fetch initial + canonical explicite (`revalidate = 3600`) |
| `frontend/src/components/HomeClient.tsx` | UI interactive sans `useSearchParams` (params via `router.replace`) |
| `frontend/src/lib/server-api.ts` | Chargement serveur meta/ranking/gov |
| `frontend/src/lib/site.ts` | `SITE_ORIGIN`, title/description, helpers URL |
| `frontend/src/app/layout.tsx` | `metadataBase`, Open Graph, `robots: index,follow` |
| `frontend/src/app/robots.ts` | `robots.txt` Allow/Disallow + Sitemap |
| `frontend/src/app/sitemap.ts` | Sitemap avec l’URL canonique `/` |
| `frontend/package.json` | Scripts `test` et `verify:seo-html` |
| `frontend/tests/seo-html.test.mjs` | Tests SSR (canonical, anti-bailout, robots, sitemap) |
| `frontend/scripts/verify-seo-html.mjs` | Vérification HTML via `next start` |
| `scripts/deploy_frontend.sh` | `npm ci --include=dev` pour que TypeScript (devDependency) soit présent au build |

### Commits déployés

1. `76f124802fd4e73190b88336886171807d0160f3` — Fix Desinfo SEO: SSR homepage, canonical, robots, sitemap  
2. `1a64b070ac94b890187a1ee2449ae45a39f6d7b0` — Install frontend devDependencies during deploy builds  
3. `aa576c5b42145eec9d5ebd0534f96a19d5896249` — Add Desinfo SEO deployment report (doc only)

**Commit runtime déployé** : `1a64b070ac94b890187a1ee2449ae45a39f6d7b0` (build + restart `desinfo-frontend`).

## Tests et builds exécutés (avant déploiement)

Sur l’agent, avec tunnel API `127.0.0.1:8700` :

```text
cd frontend && DESINFO_API_HOST=127.0.0.1 DESINFO_API_PORT=8700 npm test
```

- `next build` : OK — routes `/` (ƒ dynamique), `/robots.txt` (○), `/sitemap.xml` (○)
- Tests Node : **3 pass / 0 fail**
  - ranking + canonical + absence de bailout
  - robots.txt + sitemap.xml
  - helpers `site.ts`

```text
npm run verify:seo-html
```

- OK — HTML SSR ~44 Ko, canonical, pas de bailout, robots/sitemap valides

## Déploiement

Workflow projet : `bash scripts/deploy_frontend.sh` sur l’hôte de prod (`desinfo-frontend`).

1. Branche poussée vers GitHub (`cursor/desinfo-seo-ssr-indexation-daf6`).
2. Fichiers SEO + script deploy appliqués sur `/srv/intel/desinfo` (working tree `main`, sans écraser les WIP locaux hors SEO : gov sync, etc.).
3. Premier build en échec : `NODE_ENV=production` + `npm ci` omettait TypeScript → alias `@/` non résolus.
4. Correctif `npm ci --include=dev` ajouté et poussé.
5. Rebuild + `systemctl restart desinfo-frontend` : **OK**, service `active`.

Aucune modification d’un autre dépôt. Aucun changement d’infra hors du workflow frontend habituel (pas de touche nginx/TLS/DNS).

## URL de déploiement

- **Site** : https://desinfo.electronlibre.info/
- **robots.txt** : https://desinfo.electronlibre.info/robots.txt
- **sitemap** : https://desinfo.electronlibre.info/sitemap.xml

## Vérifications publiques (après déploiement)

Date/heure vérif : 3 nov. 2026 ≈ 00:31 Europe/Paris.

| Contrôle | Résultat |
|---|---|
| Accueil HTTP | 200 |
| `<title>` | Observatoire de la désinformation |
| Meta description | Présente (Community Notes / CN / Posts) |
| Canonical | `rel="canonical" href="https://desinfo.electronlibre.info/"` |
| Bailout CSR | **Absent** |
| Shell « Chargement… » | **Absent** |
| Contenu ranking | Présent (ex. AFP Factuel, `media-name`) |
| Méthodologie | Présente |
| `robots.txt` | Allow `/`, Disallow `/api/`, `/_next/`, `/health` + Sitemap |
| `sitemap.xml` | 200, `application/xml`, URL `https://desinfo.electronlibre.info/` |

Contrôle local origin (`127.0.0.1:8710`) : mêmes résultats (canonical, ranking, robots, sitemap).

## Points restant à contrôler dans Google Search Console

1. **Inspection d’URL** sur `https://desinfo.electronlibre.info/` : demander une **nouvelle indexation** (le HTML servi a changé).
2. Vérifier que Googlebot voit bien le ranking dans « Afficher la page explorée » (plus de shell Chargement).
3. Soumettre / resoumettre le sitemap : `https://desinfo.electronlibre.info/sitemap.xml`.
4. Surveiller **Couverture / Pages** pendant quelques jours (passage de « Explorée, actuellement non indexée » / soft-404 potentiels vers indexée).
5. Confirmer l’URL canonique retenue : `https://desinfo.electronlibre.info/` (slash final).
6. Si d’anciens `robots.txt` Cloudflare / content-signals étaient en cache côté explorateurs, re-vérifier robots après 24–48 h.
7. Optionnel : Rich results / balises OG déjà présentes — pas bloquant pour l’indexation de base.

## Notes opérationnelles

- Sur le serveur, des modifications locales non liées au SEO restent en working tree (`backend/gov/sync.py`, `GovMeasures.tsx`, etc.) et n’ont pas été commités ni écrasés.
- La branche GitHub contient les commits SEO ; le `main` distant n’a pas été fusionné automatiquement (PR à merger pour aligner `origin/main`).
- Le runtime déployé sur `/srv/intel/desinfo` inclut déjà les fichiers SEO buildés et le service redémarré.
