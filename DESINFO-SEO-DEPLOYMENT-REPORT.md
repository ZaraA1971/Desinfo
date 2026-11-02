# Rapport de déploiement SEO — Desinfo

**Date** : 3 novembre 2026 (Europe/Paris)  
**Dépôt** : https://github.com/ZaraA1971/Desinfo  
**Branche** : `cursor/desinfo-seo-ssr-indexation-daf6`  
**PR** : https://github.com/ZaraA1971/Desinfo/pull/3  
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
| `frontend/tests/seo-html.test.mjs` | Tests SSR (HTTP 200, canonical, anti-bailout, robots, sitemap) |
| `frontend/scripts/verify-seo-html.mjs` | Vérif post-build via `next start` + **assert HTTP 200** sur `/`, `/robots.txt`, `/sitemap.xml` |
| `scripts/deploy_frontend.sh` | `npm ci --include=dev` pour que TypeScript (devDependency) soit présent au build |

### Commits

1. `76f124802fd4e73190b88336886171807d0160f3` — Fix Desinfo SEO: SSR homepage, canonical, robots, sitemap  
2. `1a64b070ac94b890187a1ee2449ae45a39f6d7b0` — Install frontend devDependencies during deploy builds  
3. `aa576c5b42145eec9d5ebd0534f96a19d5896249` — Add Desinfo SEO deployment report  
4. `4efa589f9cd9b85e4eda4e82aba0c066322a6888` — Clarify deployed commit SHAs in SEO report  
5. `90519a23744d1e1ba547def2fc0e2c9423ae3667` — Assert HTTP 200 for `/`, robots.txt, and sitemap in SEO verify  

**Commit runtime déployé (actuel)** : `90519a23744d1e1ba547def2fc0e2c9423ae3667`

## Tests et builds exécutés

### Cycle validation + redéploiement (3 nov. 2026 ≈ 00:35 Europe/Paris)

Sur l’agent, avec tunnel API `127.0.0.1:8700` :

```text
cd frontend
DESINFO_API_HOST=127.0.0.1 DESINFO_API_PORT=8700 npm run build
DESINFO_API_HOST=127.0.0.1 DESINFO_API_PORT=8700 npm run verify:seo-html
```

Résultats :

- `next build` : OK — `/` (ƒ), `/robots.txt` (○), `/sitemap.xml` (○)
- `verify:seo-html` : **OK** — `status /robots/sitemap=200/200/200`, HTML SSR ~44073 octets, canonical, pas de bailout

Assertions HTTP 200 ajoutées dans `frontend/scripts/verify-seo-html.mjs` pour `/`, `/robots.txt` et `/sitemap.xml` (déjà présentes dans `frontend/tests/seo-html.test.mjs`).

### Cycle antérieur

```text
cd frontend && DESINFO_API_HOST=127.0.0.1 DESINFO_API_PORT=8700 npm test
```

- Tests Node : **3 pass / 0 fail**

## Déploiement

Workflow projet : `bash scripts/deploy_frontend.sh` sur l’hôte de prod (`desinfo-frontend`).

1. Branche poussée vers GitHub (`cursor/desinfo-seo-ssr-indexation-daf6`).
2. Fichiers SEO + script deploy appliqués sur `/srv/intel/desinfo` (working tree `main`, sans écraser les WIP locaux hors SEO).
3. Correctif historique : `npm ci --include=dev` (TypeScript requis pour les alias `@/`).
4. Après succès de `verify:seo-html` (200/200/200) : rebuild prod + `systemctl restart desinfo-frontend` → **active**.
5. Contrôle origin local post-restart : `/=200`, `robots.txt=200`, `sitemap.xml=200`.

Aucune modification d’un autre dépôt. Aucun changement d’infra hors du workflow frontend habituel.

## URL de déploiement

- **Site** : https://desinfo.electronlibre.info/
- **robots.txt** : https://desinfo.electronlibre.info/robots.txt
- **sitemap** : https://desinfo.electronlibre.info/sitemap.xml

## Vérifications publiques (après redéploiement)

Date/heure vérif : **3 nov. 2026, 00:36 Europe/Paris (CET)**.

| URL | Statut HTTP | Contrôle contenu |
|---|---|---|
| `/` | **200** | title, meta description, canonical `/`, ranking (AFP Factuel), pas de bailout / Chargement |
| `/robots.txt` | **200** | Allow `/`, Disallow `/api/`, `/_next/`, `/health` + Sitemap |
| `/sitemap.xml` | **200** | URL `https://desinfo.electronlibre.info/` |

Contrôle origin (`127.0.0.1:8710`) : mêmes statuts 200/200/200.

## Points restant à contrôler dans Google Search Console

1. **Inspection d’URL** sur `https://desinfo.electronlibre.info/` : demander une **nouvelle indexation**.
2. Vérifier que Googlebot voit le ranking dans « Afficher la page explorée ».
3. Soumettre / resoumettre le sitemap : `https://desinfo.electronlibre.info/sitemap.xml`.
4. Surveiller **Couverture / Pages** pendant quelques jours.
5. Confirmer l’URL canonique retenue : `https://desinfo.electronlibre.info/` (slash final).
6. Re-vérifier `robots.txt` côté GSC après 24–48 h si un ancien corps Cloudflare était en cache.
7. Optionnel : balises OG déjà présentes — non bloquant pour l’indexation de base.

## Notes opérationnelles

- Sur le serveur, des modifications locales non liées au SEO restent en working tree (`backend/gov/sync.py`, `GovMeasures.tsx`, etc.) et n’ont pas été commités ni écrasés.
- La branche GitHub contient les commits SEO ; merger la PR #3 pour aligner `origin/main`.
- Le runtime déployé sur `/srv/intel/desinfo` inclut le build validé par `verify:seo-html` (commit `90519a2`).
