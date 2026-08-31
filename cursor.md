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
8. **Métrique** — Principale : `CN / posts` (`rate_cn_per_post`, plus haut = plus densément noté). Secondaire : `posts / CN`. Sans API X : `metric_mode=cn_only`. **Fenêtre opérationnelle = `7d`** = **données de la moisson** (remplacées chaque lundi). `30d` / `90d` / `365d` = **accumulation** des moissons (cascade posts `*_posts_daily` + CN coupés à `last_ingest_at`) — jamais de sync X longue.
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
| `backend/gov/` | Demandes des États : lecture du code public X (`x-algorithm`) |
| `config/gov_measures.yml` | Mesures déjà identifiées (Brésil 2026, etc.) |
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
| Moisson hebdo | oneshot Mon 06:00 UTC | `desinfo-x-sync.timer` → `run_weekly.py` |

## Relance services

```bash
sudo systemctl restart desinfo-api desinfo-frontend
# Après build frontend :
cd /srv/desinfo/frontend && npm run build && sudo systemctl restart desinfo-frontend
# Moisson manuelle (CN seul, sans X) :
sudo systemctl start desinfo-ingest.service
# Pipeline complet (CN + X + score) :
sudo systemctl start desinfo-x-sync.service
```

| Changement | Action |
|------------|--------|
| `backend/api/` | `systemctl restart desinfo-api` |
| `backend/ingest/` / `scoring/` | prochain timer hebdo ou `start desinfo-x-sync` |
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
X_BEARER_TOKEN=     # seul credential X (app-only)
DESINFO_X_SYNC_WINDOWS=7d
DESINFO_CASCADE_WINDOWS=30d,90d,365d
DESINFO_CASCADE_COVERAGE=0.7
DESINFO_DEBUG=0
DESINFO_EXPORT_MAX_PER_HOUR=5
DESINFO_PUBLIC_URL=https://desinfo.electronlibre.info
DESINFO_EXPORT_HMAC_SECRET=
DESINFO_API_RATE_LIMIT_GET=120
DESINFO_API_RATE_LIMIT_EXPORT=10
OPENAI_API_KEY=          # thèmes radar
OPENAI_MODEL=gpt-5.4
DESINFO_THEME_BATCH_SIZE=20
DESINFO_THEME_MAX_PER_RUN=800
DESINFO_X_ALLOW_TIMELINE=0
DESINFO_X_SYNC_MIN_AGE_HOURS=168
DESINFO_THEME_X_FETCH=cache_only
```

## Harvest X (crédits)

Tarification X (pay-per-use, juil. 2026) — **ordre de coût** :

| Opération | Coût | Usage desinfo |
|-----------|------|---------------|
| `GET /2/tweets/counts/recent` | **$0,005 / requête** | **1 req / @handle / semaine** (Post/CN 7j) |
| Cascade 30/90/365 | $0 | somme `media_posts_daily` |
| `GET /2/tweets?ids=` | $0,005 / tweet lu | radar thèmes **optionnel** |
| Timeline `/users/{id}/tweets` | $0,005 / tweet paginé | **interdit** (`DESINFO_X_ALLOW_TIMELINE=0`) |
| `counts/all` | $0,010 / req | **jamais** |

**Budget type hebdo** (~44 handles) : ~**$0,22** en counts/recent. Thèmes : `DESINFO_THEME_X_FETCH=cache_only` (défaut) = **$0** ; `fetch` = ~$0,005 × tweets non cachés.

Variables :
- `DESINFO_X_ALLOW_TIMELINE=0` — pas de fallback timeline.
- `DESINFO_X_SYNC_MIN_AGE_HOURS=168` — skip resync si déjà fait cette semaine.
- `DESINFO_THEME_X_FETCH=cache_only|fetch|never` — texte tweet pour LLM.

- **API X = 7d only** via `counts/recent` (1 req/handle unique, médias+candidats dédupliqués).
- **Timer** : `desinfo-x-sync.timer` — **lundi 06:00 UTC** → `scripts/run_weekly.py`.
- Stocke les buckets jour dans `media_posts_daily` + fenêtre `7d`.
- **Cascade** (0 crédit) : somme des jours → `30d` / `90d` / `365d` dès que couverture ≥ `DESINFO_CASCADE_COVERAGE` (défaut 0.7). Remplissage **semaine par semaine** (1 moisson 7j = ~7 buckets/jour/compte).
- UI : fenêtres 30/90/365 **grisées et non cliquables** tant que `windows_status[w].available` est false (`/api/meta`).
- CN + posts : tout est coupé à la **dernière moisson** (`last_ingest_at`). `7d` = cette moisson (on remplace). `30d`/`90d`/`365d` = accumulation des semaines. Un rescore en semaine ne glisse pas les fenêtres. Pas d’ingest quotidien. **Toujours parler CN sur la fenêtre demandée** (prod = `7d`) ; ne pas citer `cn_365d` du roster comme métrique live.

## Procédure — ajouter des comptes

Deux rosters distincts. **Ne pas** lancer `bootstrap_roster()` / `--bootstrap` après un ajout manuel : ça **écrase** `media_roster.yml`.

### A. Média (palmarès Médias)

**Fichiers** (les deux, toujours) :

| Fichier | Rôle |
|---------|------|
| `config/media_domains.yml` | Attribution CN (domaine URL dans le texte de la note → média). Change le hash → rebuild attribution au prochain ingest. |
| `config/media_roster.yml` | Périmètre palmarès + moisson X (`x_handle`). Sans entrée ici = pas dans l’UI. |

**Champs** :

```yaml
# media_domains.yml  +  media_roster.yml (même id / name / domains / handles)
- id: mon_media          # snake_case, stable, unique
  name: Mon Média        # libellé UI (marque ombrelle)
  domains:
  - monmedia.fr          # sans www. ; sous-domaines matchés (ex. pro.monmedia.fr)
  x_handle: MonMedia     # sans @ ; un seul compte
  # OU plusieurs comptes sous la même marque (posts 7d = somme) :
  # x_handles:
  # - Bloomberg
  # - business
```

`x_handles: [A, B]` : 1 req X par handle, **somme** dans un seul `media_id`. UI : `name` = marque ; `x_handle` affiché = le premier.

Dans le **roster seulement**, garder aussi (métadonnées bootstrap, **pas** la métrique live) :

```yaml
  rank_bootstrap: 99     # rang indicatif ; incrémenter
  cn_365d: 0             # placeholder OK ; ne pas rapporter comme score UI
```

**Checklist ajout** :

1. Vérifier domaine officiel + handle X (compte vérifié / bio cohérente). Pas de faux `@…_fr` amateurs.
2. Éditer `media_domains.yml` **et** `media_roster.yml` (entrées miroir).
3. Activer en prod (attribution + **thèmes radar LLM** + score + API) — **obligatoire** pour un nouvel entrant :

```bash
cd /srv/desinfo
./venv/bin/python <<'PY'
NEW_MEDIA_IDS = {"mon_media"}  # ids ajoutés

from backend.db import db_session, init_db, set_meta
from backend.ingest.attribute import attribute_notes
from backend.ingest.incremental import roster_config_hash
from backend.scoring.rank import score_all_windows
from backend.themes.classify import classify_pending_notes
from backend.x_client.sync import cascade_longer_windows

init_db()
with db_session() as conn:
    links = attribute_notes(conn, rebuild=True)  # obligatoire si domains.yml a changé
    set_meta(conn, "roster_config_hash", roster_config_hash())
    print("note_media_links:", links)

# Radar : classer les CN 7d du nouvel entrant (notes sans note_theme)
# Ne pas attendre la moisson hebdo — sinon radar vide / couverture 0.
themes = classify_pending_notes(media_ids=NEW_MEDIA_IDS)
print("themes:", themes)

print("cascade:", cascade_longer_windows())
print("snapshots:", [str(p) for p in score_all_windows()])
PY
sudo systemctl restart desinfo-api
```

`classify_pending_notes(media_ids=…)` : fenêtre **7d** seulement, notes HELPFUL déjà attribuées au média, sans thème. Si `OPENAI_API_KEY` absent → `status=skipped` (à refaire). 0 CN sur 7d → `classified=0` (normal).

4. **Posts 7d** — soit attendre le timer lundi 06:00 UTC, soit (si crédits X OK) :

```bash
cd /srv/desinfo
./venv/bin/python -c "
from backend.x_client.sync import sync_all_post_counts, cascade_longer_windows
from backend.scoring.rank import score_all_windows
print(sync_all_post_counts(windows=['7d'], force_media_ids={'mon_media'}))
print(cascade_longer_windows())
print(score_all_windows(['7d']))
"
sudo systemctl restart desinfo-api
```

Les **médias** déjà sync < `DESINFO_X_SYNC_MIN_AGE_HOURS` (168 h) sont **skippés** (tous leurs handles ombrelle inclus). Forcer : `force_media_ids={'id'}`. **1 req / @handle** unique. Pas de timeline.

5. Contrôle (fenêtre live = **7d**) :

```bash
curl -s 'http://127.0.0.1:8700/api/ranking?window=7d&kind=media' \
  | ./venv/bin/python -c "import sys,json; d=json.load(sys.stdin); print('n=',len(d.get('items')or[]));
[print(i['rank'], i['media_id'], i['name'], 'cn=',i['cn_count'], 'posts=',i['post_count'],
      'radar_cov=',(i.get('radar') or {}).get('coverage')) for i in d.get('items')or[] if i['media_id']=='mon_media']"
```

**Attentes normales** :

| Délai | CN 7d | posts 7d | radar 7d | 30/90/365 |
|-------|-------|----------|----------|-----------|
| Juste après attribution + thèmes | oui (si notes HELPFUL avec URL) | `null` → souvent bas de liste | axes renseignés si CN>0 | indisponibles / cascade incomplete |
| Après 1 moisson X hebdo | idem | rempli (`counts/recent`) | idem | commence à se remplir |
| Après plusieurs moissons | idem | idem | thèmes stockés réutilisés | cascade OK si couverture ≥ 0.7 |

Ne jamais sync X sur 30/90/365. Ne pas citer `cn_365d` du YAML comme score. Frontend : **pas** de rebuild (données via API/snapshots).

### B. Candidat 2027 (onglet Candidats)

**Fichier unique** : `config/politicians_roster.yml` (pas de bootstrap auto).

```yaml
  - id: prenom_nom
    name: Prénom Nom
    party: Parti
    x_handle: HandleX          # sans @
    aliases: ["Prénom Nom", "@HandleX"]   # formes dans le texte des CN
```

Puis même enchaînement attribution / **thèmes radar** / score / X, côté politiques :

```bash
cd /srv/desinfo
./venv/bin/python <<'PY'
NEW_POL_IDS = {"prenom_nom"}  # ids ajoutés

from backend.db import db_session, init_db, set_meta
from backend.politicians.attribute import attribute_politicians
from backend.ingest.incremental import roster_config_hash
from backend.politicians.rank import score_all_politicians_windows
from backend.themes.classify import classify_pending_notes
from backend.x_client.sync import cascade_politician_windows

init_db()
with db_session() as conn:
    links = attribute_politicians(conn, rebuild=True)
    set_meta(conn, "roster_config_hash", roster_config_hash())
    print("note_politician_links:", links)

themes = classify_pending_notes(politician_ids=NEW_POL_IDS)
print("themes:", themes)

print("cascade:", cascade_politician_windows())
print("snapshots:", [str(p) for p in score_all_politicians_windows()])
PY
sudo systemctl restart desinfo-api
# Posts 7d : moisson hebdo (médias+candidats dédupliqués) ou sync_all_post_counts(force_politician_ids=…)
```

Contrôle : `GET /api/ranking?window=7d&kind=politicians`.

### Interdits

- Inventer `post_count` / hardcoder un ratio.
- `--bootstrap` après trim/ajouts manuels du roster médias.
- Timeline X ou `counts/all` pour « rattraper » un nouveau compte.
- Ajouter un média seulement dans un des deux YAML médias.
- Oublier le LLM thèmes (`classify_pending_notes`) après un nouvel entrant → radar vide sur 7d.

## Radar thématique (médias + candidats)

- Axes : politique, santé, économie, justice, international, science, technologie, faits divers (+ `autre` hors radar).
- Sens : **longueur ∝ nombre de CN** sur le thème (max = bord ; 0 reste à 25 % du rayon).
- Classification : LLM en fin de moisson hebdo — **fenêtre 7j courante seulement** (notes média ou candidat sans thème).
  Prompt agnostique : classer selon le **cœur de la correction** (pas le décor / mots-clés incidental) — `backend/themes/classify.py` `SYSTEM_PROMPT`.
  Modèle : `OPENAI_MODEL` (prod = `gpt-5.4`). Hebdo = **7d** seulement ; 30/90/365 réutilisent `note_theme`.
  **Nouvel entrant** : lancer tout de suite `classify_pending_notes(media_ids=…)` / `(politician_ids=…)` (voir procédure ci-dessus) — ne pas attendre le lundi.
  **Reclassif homogène** (changement prompt/modèle) :
  `DESINFO_THEME_X_FETCH=cache_only ./venv/bin/python scripts/classify_themes.py --reclassify-all-in-window --window 365d`
  (évite de brûler des crédits X ; tweets absents du cache → note seule).
- Agrégation : `build_radar_profiles` (médias), `build_politician_radar_profiles` (candidats).
- Snapshots : chaque item inclut `radar.axes[]` (`cn_count`, `weight`).
- UI : clic ligne → panneau radar (médias et candidats). Script manuel : `scripts/classify_themes.py`.
- Limites : `DESINFO_THEME_BATCH_SIZE` (20), `DESINFO_THEME_MAX_PER_RUN` (800) pour étaler le backlog.

## Export PDF (public)

- **PDF seul** — pas de CSV public.- Navigateur → `POST /api/export` **Next.js** (honeypot + Origin) → FastAPI avec HMAC.
- FastAPI exige `X-Desinfo-Export-Ts` + `X-Desinfo-Export-Sig` (`DESINFO_EXPORT_HMAC_SECRET`, TTL 5 min).
- Body `{ email, window, consent: true }` → attachment PDF watermarké.
- E-mails stockés en SQLite `exports` (admin) ; dump CSV hebdo via moisson lundi :
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

## Ingest — garde-fous SQLite

- Les `IN (?,?,…)` sur des milliers de `note_id` (rattrapage multi-jours) dépassent `SQLITE_MAX_VARIABLE_NUMBER` (souvent 999) → `too many SQL variables`.
- Helper `backend/db.py` : `chunked` / `execute_by_ids` / `fetchall_by_ids` (`SQLITE_IN_CHUNK=500`) pour attribution médias/candidats et scope thèmes.
- Échec d’attribution **après** commit par jour : les dumps sont déjà en base (`last_dump_date` avancé) — relancer un backfill `attribute_notes()` / `attribute_politicians()` (notes sans lien) puis moisson thèmes/X/score.

## CookieYes + analytics

- **CookieYes** : même compte / clé qu’ElectronLibre (`EL_COOKIEYES_WEBSITE_KEY` ou `NEXT_PUBLIC_COOKIEYES_WEBSITE_KEY`) — composant `frontend/src/components/CookieYes.tsx`, chargé `beforeInteractive` **avant** GoatCounter.
- Domaine à autoriser dans le dashboard CookieYes : `desinfo.electronlibre.info` (sinon bannière absente / scripts non gérés).
- **GoatCounter** : même site `electronlibre.goatcounter.com`, path préfixé par host (`frontend/src/components/GoatCounter.tsx`).

## Open source

- Dépôt public : [github.com/ZaraA1971/Desinfo](https://github.com/ZaraA1971/Desinfo)
- Licence : **AGPL-3.0** (`LICENSE`) — service réseau → obligation de fournir le source correspondant.
- Secrets / PII **hors git** : `.env`, `data/desinfo.db*`, `data/exports_emails*.csv`, snapshots, dumps (`SECURITY.md`).
- Avant/après passage en public : **rotation** `X_BEARER_TOKEN`, `OPENAI_API_KEY`, `DESINFO_EXPORT_HMAC_SECRET` puis `systemctl restart desinfo-api desinfo-frontend`.

## Checklist revue

- [x] `cursor.md` à jour si décision d’archi
- [x] Pas de secrets committés (`.env`) — voir `SECURITY.md` + `.gitignore`
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
| `backend/scoring/rank.py` + radar médias | `backend/politicians/rank.py` + `build_politician_radar_profiles` |
| `data/snapshots/latest_{window}.json` | `data/snapshots/latest_politicians_{window}.json` (+ `"kind": "politicians"`) |

- `backend/ingest/pipeline.py` : `attribute_politicians(conn)` appelé juste après `attribute_notes(conn)` (même transaction) ; résultat inclut `note_politician_links`.
- `backend/x_client/sync.py` : `sync_politicians_post_counts()` + `cascade_politician_windows()` miroir médias ; `run_weekly_harvest()` enchaîne médias puis politiques.
- `scripts/run_weekly.py` : pipeline hebdo (CN → thèmes → X → cascade → score). `ingest_daily.py` = CN seul (manuel).
- **UI** : onglets Médias | Candidats 2027 | Demandes des États ; `GET /api/ranking?kind=politicians&window=` ; défaut fenêtre = **7d** (même logique que médias).
- **Demandes des États** : `GET /api/gov` lit `data/snapshots/latest_gov.json`. Source = fichiers publics `xai-org/x-algorithm` (pas d’API X). Catalogue `config/gov_measures.yml` + découverte des nouveaux `*_election_filter.rs`. Moisson dans `run_weekly.py` / `scripts/sync_gov.py`. L’UI **observe** le snapshot. Ce n’est **pas** un inventaire des posts retirés.
- Attribution CN candidats = texte/@handles uniquement (pas de lookup tweet).

## Ingest CN (détails)

- **Incrémental** : scan de chaque jour **après** `last_dump_date` jusqu’à aujourd’hui. Jours absents ou incomplets = skip. Rien de nouveau = ingest `skipped`, la moisson X / score continue. 1ère moisson : dernier dump prêt dans `DESINFO_CN_LOOKBACK_DAYS` (21). Legacy : `last_dump_date` depuis `dump_date`.
- Un jour n’est « prêt » que si `notes-00000.zip` **et** `noteStatusHistory-00000.zip` sont publiés (sinon skip — au petit matin UTC le status peut manquer encore). Commit **par jour** pour ne pas perdre les dumps déjà OK.
- Attribution médias/candidats : **notes touchées uniquement** (rebuild complet si hash roster change).
- Thèmes LLM : **7j courants**, notes sans `note_theme` ; après ingest, filtre sur `touched_note_ids` quand disponible.
- Moisson X : **1 req/@handle/semaine** (`counts/recent`) ; skip si `synced_at` récent ; 30/90/365 = cascade `*_posts_daily` (zéro API).
- URL : `https://ton.twimg.com/birdwatch-public-data/YYYY/MM/DD/{notes|noteStatusHistory}/*.zip`
- Pipeline disque : status → set HELPFUL → delete ; chaque shard notes → upsert HELPFUL only → delete.
- Ne jamais stocker toutes les notes non-HELPFUL en SQLite.

## État prod (2026-07-23)

| Élément | État |
|---------|------|
| Code | `/srv/desinfo` |
| Roster | **24** médias actifs X (+ Public Sénat, Bloomberg, AFP 2026-07-26) |
| Notes HELPFUL en base | ~248 729 |
| Liens note↔média | ~7 980 (rebuild attribution 2026-07-26) |
| metric_mode | **`post_cn` sur 7d** (fenêtre live) ; 30/90/365 = cascade posts + CN SQLite quand couverture OK |
| X sync | **hebdo lundi 06:00 UTC** (`desinfo-x-sync.timer`) — **7d only** |
| Cascade | `media_posts_daily` → 30d/90d/365d **sans API** (ne pas sync X longue) |
| Défaut UI | **`7d`** (médias + candidats) — ne pas rapporter les CN sur 365d comme métrique prod |
| Moisson X UI | `next_x_sync_at` → libellé compact `moisson lun. …` |
| X API | crédits préservés — pas de timeline longue |
| Candidats 2027 | roster `politicians_roster.yml` ; UI onglet ; attribution @handle/alias |
| `desinfo-api` | active `:8700` |
| `desinfo-frontend` | active `:8710` |
| `desinfo-x-sync.timer` | weekly Mon 06:00 UTC (CN + X + score + emails CSV) |
| DNS `desinfo.electronlibre.info` | A → `163.172.185.4` (DNS only) |
| TLS | Let's Encrypt OK — https://desinfo.electronlibre.info |

Top 30 j (CN) au premier calcul : Reuters, AFP, BFMTV, France 24, Le Figaro.
