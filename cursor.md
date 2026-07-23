# Guide de codage — Observatoire de la désinformation

Référence **canonique** pour plans et implémentation. Domaine public : `desinfo.electronlibre.info`. Racine : `/srv/desinfo`.

**Cursor** : la règle `.cursor/rules/desinfo.mdc` (`alwaysApply: true`) reprend l’essentiel de ce fichier.

## Commandements

0. **Plans** — S’appuyer sur l’architecture ci-dessous avant d’en inventer une autre.
1. **Source de vérité** — SQLite `data/desinfo.db` pour les notes ; `config/media_roster.yml` pour le périmètre médias du palmarès ; snapshots `data/snapshots/` pour ce que l’UI affiche. L’UI **observe**, elle ne recalcule pas.
2. **Réutiliser** — Étendre `backend/ingest/`, `backend/scoring/`, `backend/api/`, `backend/x_client/` plutôt que dupliquer.
3. **Pas de fallback silencieux** — Échec d’ingest / scoring → log + exit non-zéro ; pas de posts inventés sans API X.
4. **Bugs** — Corriger la cause (attribution domaine, filtre HELPFUL, fenêtre) ; pas de bricolage dans l’API.
5. **Pipeline souverain** — Ordre fixe : `download → parse → attribute → score → snapshot → API → UI`.
6. **Config centralisée** — `.env` + `config/*.yml` ; pas de magic numbers dispersés.
7. **Notes comptées** — Uniquement statut `CURRENTLY_RATED_HELPFUL` (via `noteStatusHistory`).
8. **Métrique** — Principale : `CN / posts` (`rate_cn_per_post`, plus haut = plus densément noté). Secondaire : `posts / CN`. Sans API X : `metric_mode=cn_only`.
9. **Attribution V1** — Domaines dans le texte des notes → `config/media_domains.yml` → média. Pas de lookup tweet sans API.
10. **Formules métier** — Une seule implémentation dans `backend/scoring/`.
11. **Diagnostics** — Logs journald / `data/` ; flag `DESINFO_DEBUG=1` pour verbosité.

## Architecture

| Module | Rôle |
|--------|------|
| `backend/ingest/` | Download dump CN, parse TSV, attribution domaine |
| `backend/scoring/` | Fenêtres roulantes, ratios, snapshots JSON |
| `backend/api/` | FastAPI public (ranking + export PDF) |
| `backend/export/` | Génération PDF watermarké |
| `backend/x_client/` | Client API X (timelines, counts) |
| `config/media_domains.yml` | Seed domaines FR → média |
| `config/media_roster.yml` | Starter set souverain (issu du bootstrap 365 j) |
| `frontend/` | Next.js App Router — palmarès public |
| `infra/systemd/` | Units API, frontend, ingest timer |
| `deploy/nginx/` | Vhost TLS `desinfo.electronlibre.info` |

## Pipeline nominal

```
download CN dump → parse notes + status → filter HELPFUL
→ attribute URLs → SQLite → score (window) → snapshot JSON
→ FastAPI lit snapshot → Next.js affiche
```

## Anti-patterns (interdits)

- Inventer `post_count` sans données API X.
- Compter des notes non-HELPFUL.
- Hardcoder la liste médias hors `config/*.yml`.
- Recalculer le ranking dans le frontend.
- Exposer uvicorn hors `127.0.0.1` (nginx termine le TLS).
- Servir `.next` depuis le disque via nginx.

## Ports & services

| Service | Bind | Unit |
|---------|------|------|
| FastAPI | `127.0.0.1:8700` | `desinfo-api` |
| Next.js | `127.0.0.1:8710` | `desinfo-frontend` |
| Ingest quotidien | oneshot 05:00 UTC | `desinfo-ingest.timer` |
| X harvest hebdo | oneshot Mon 06:00 UTC | `desinfo-x-sync.timer` |

## Relance services

```bash
sudo systemctl restart desinfo-api desinfo-frontend
# Après build frontend :
cd /srv/desinfo/frontend && npm run build && sudo systemctl restart desinfo-frontend
# Ingest manuel :
sudo systemctl start desinfo-ingest.service
```

| Changement | Action |
|------------|--------|
| `backend/api/` | `systemctl restart desinfo-api` |
| `backend/ingest/` / `scoring/` | prochain timer ou `start desinfo-ingest` |
| `frontend/` | `npm run build` + `restart desinfo-frontend` |
| `.env` | restart services concernés |
| unit systemd | `infra/systemd/install.sh` + `daemon-reload` |

## Variables clés

```
DESINFO_ROOT=/srv/desinfo
DESINFO_DB=/srv/desinfo/data/desinfo.db
DESINFO_API_HOST=127.0.0.1
DESINFO_API_PORT=8700
DESINFO_FRONTEND_PORT=8710
DESINFO_DEFAULT_WINDOW=7d
DESINFO_BOOTSTRAP_DAYS=365
DESINFO_ROSTER_MIN_CN=3
X_API_KEY=          # optionnel V1
X_API_SECRET=
X_BEARER_TOKEN=
DESINFO_X_SYNC_WINDOWS=7d
DESINFO_CASCADE_WINDOWS=30d,90d,365d
DESINFO_CASCADE_COVERAGE=0.7
DESINFO_DEBUG=0
DESINFO_EXPORT_MAX_PER_HOUR=5
DESINFO_PUBLIC_URL=https://desinfo.electronlibre.info
DESINFO_EXPORT_HMAC_SECRET=
DESINFO_API_RATE_LIMIT_GET=120
DESINFO_API_RATE_LIMIT_EXPORT=10
```

## Harvest X (crédits)

- **API X = 7d only** via `counts/recent` (1 req/handle) — jamais de timeline pour 30/365.
- **Cron** : `desinfo-x-sync.timer` — **lundi 06:00 UTC** → `scripts/sync_x_weekly.py`.
- Stocke les buckets jour dans `media_posts_daily` + fenêtre `7d`.
- **Cascade** (0 crédit) : somme des jours → `30d` / `90d` / `365d` dès que couverture ≥ `DESINFO_CASCADE_COVERAGE` (défaut 0.7).
- Ingest quotidien CN : pas de sync X (sauf `--with-x-sync`) ; cascade recalculée gratuitement.

## Export PDF (public)

- **PDF seul** — pas de CSV public.- Navigateur → `POST /api/export` **Next.js** (honeypot + Origin) → FastAPI avec HMAC.
- FastAPI exige `X-Desinfo-Export-Ts` + `X-Desinfo-Export-Sig` (`DESINFO_EXPORT_HMAC_SECRET`, TTL 5 min).
- Body `{ email, window, consent: true }` → attachment PDF watermarké.
- E-mails stockés en SQLite `exports` (admin) ; dump CSV matin via ingest 05:00 UTC :
  - `data/exports_emails_latest.csv`
  - `data/exports_emails_YYYYMMDD.csv`
  - `data/exports_emails_unique_latest.csv`
- Script manuel : `scripts/export_emails_csv.py`
- Rate-limit IP mémoire (min + heure) + nginx.
- Appels directs FastAPI sans signature → **401**.

## Sécurité API

- Docs OpenAPI désactivés sauf `DESINFO_DEBUG=1`.
- Headers : `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`.
- Rate-limit mémoire : GET `DESINFO_API_RATE_LIMIT_GET` (défaut 120/min), export `DESINFO_API_RATE_LIMIT_EXPORT` (10/min).
- nginx : `limit_req` API 10 r/s ; export 1 r/s ; `client_max_body_size 16k` sur `/api/`.
- IP client via `X-Real-IP` (nginx) ; `/api/export` proxifié vers Next, le reste `/api/` vers FastAPI.
- Pas de fuite `x_api_configured` dans `/api/meta`.

## Dette technique (garde-fous)

- Pas de recalcul ranking dans le frontend ; snapshots = source UI.
- Pas de surface API morte (`/api/media` retiré) ; export uniquement via Next + HMAC.
- Defaults fenêtres = `DESINFO_DEFAULT_WINDOW` / `DESINFO_X_SYNC_WINDOWS` (prod = `7d`) — médias **et** candidats.
- Snapshots : écriture atomique `*.json.tmp` → replace ; uniquement `latest_*.json` (pas d’archives datées).
- `/api/meta` expose `next_x_sync_at` (prochain lundi 06:00 UTC) ; UI : `· moisson lun. 27 juil.`
- `deploy/nginx/*.acme-bootstrap.conf.example` = stub ACME historique, pas le vhost prod.

## Checklist revue

- [ ] `cursor.md` à jour si décision d’archi
- [ ] Pas de secrets committés (`.env`)
- [x] Snapshot atomique (temp → replace) — `latest_*` seulement
- [ ] Diff proportionné ; pas de refactor hors phase
- [ ] Mode métrique explicite dans le snapshot (`cn_only` / `post_cn`)

## Palmarès politiques (parallèle au palmarès médias)

Chemin backend miroir du palmarès médias, sur les mêmes notes HELPFUL — deux
pipelines d'attribution indépendants (aucun ne touche les tables de l'autre) :

| Média | Politiques |
|-------|------------|
| `config/media_roster.yml` | `config/politicians_roster.yml` (candidats déclarés présidentielle 2027, édité à la main) |
| `backend/media_config.py` | `backend/politicians/config.py` (`load_politicians_roster()`) |
| `backend/ingest/attribute.py` (domaines URL → média) | `backend/politicians/attribute.py` (`@handle` ou alias nom, insensible à la casse, dans le texte de la note → politicien) |
| `media`, `note_media` | `politicians`, `note_politician` (mêmes clés/logique, `matched_alias` au lieu de `matched_domain`) |
| `media_posts_daily`, `media_post_windows` | `politician_posts_daily`, `politician_post_windows` |
| `backend/scoring/rank.py` (`compute_ranking`/`write_snapshot`/`score_all_windows`) | `backend/politicians/rank.py` (mêmes fonctions, `score_all_politicians_windows`) — réutilise `WINDOW_DAYS` |
| `data/snapshots/latest_{window}.json` | `data/snapshots/latest_politicians_{window}.json` (+ `"kind": "politicians"`) |

- `backend/ingest/pipeline.py` : `attribute_politicians(conn)` appelé juste après `attribute_notes(conn)` (même transaction) ; résultat inclut `note_politician_links`.
- `backend/x_client/sync.py` : `sync_politicians_post_counts()` + `cascade_politician_windows()` miroir médias ; `run_weekly_harvest()` enchaîne médias puis politiques.
- `scripts/ingest_daily.py` / `scripts/sync_x_weekly.py` : cascade + score politiques après le score médias.
- **UI** : onglets Médias | Candidats 2027 ; `GET /api/ranking?kind=politicians&window=` ; défaut fenêtre = **7d** (même logique que médias).
- Attribution CN candidats = texte/@handles uniquement (pas de lookup tweet).

## Ingest CN (détails)

- URL : `https://ton.twimg.com/birdwatch-public-data/YYYY/MM/DD/{notes|noteStatusHistory}/*.zip`
- Pipeline disque : status → set HELPFUL → delete ; chaque shard notes → upsert HELPFUL only → delete.
- Ne jamais stocker toutes les notes non-HELPFUL en SQLite.

## État prod (2026-07-23)

| Élément | État |
|---------|------|
| Code | `/srv/desinfo` |
| Roster | **21** médias actifs X (trim 2026-07-23) |
| Notes HELPFUL en base | ~248 729 |
| Liens note↔média | ~10 158 |
| metric_mode | `post_cn` sur 7d ; 30/90/365 via cascade quand couverture jours OK |
| X sync | **hebdo lundi 06:00 UTC** (`desinfo-x-sync.timer`) — 7d only |
| Cascade | `media_posts_daily` → 30d/90d/365d sans API |
| Défaut UI | `7d` (médias + candidats) |
| Moisson X UI | `next_x_sync_at` → libellé compact `moisson lun. …` |
| X API | crédits préservés — pas de timeline longue |
| Candidats 2027 | roster `politicians_roster.yml` ; UI onglet ; attribution @handle/alias |
| `desinfo-api` | active `:8700` |
| `desinfo-frontend` | active `:8710` |
| `desinfo-ingest.timer` | daily 05:00 UTC (CN + score + emails CSV) |
| `desinfo-x-sync.timer` | weekly Mon 06:00 UTC |
| DNS `desinfo.electronlibre.info` | A → `163.172.185.4` (DNS only) |
| TLS | Let's Encrypt OK — https://desinfo.electronlibre.info |

Top 30 j (CN) au premier calcul : Reuters, AFP, BFMTV, France 24, Le Figaro.
