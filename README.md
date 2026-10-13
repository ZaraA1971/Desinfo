# Desinfo — Observatoire de la désinformation

Palmarès roulant des médias (et candidats 2027) basé sur les [Community Notes](https://communitynotes.x.com/) de X : densité de notes HELPFUL par rapport à l’activité de publication. Signet **Demandes des États** : mesures visibles dans le [code public de X](https://github.com/xai-org/x-algorithm#latest-updates) (pas un inventaire des posts retirés).

- **Site** : [desinfo.electronlibre.info](https://desinfo.electronlibre.info)
- **Licence** : [AGPL-3.0](LICENSE)
- **Sécurité** : [SECURITY.md](SECURITY.md)
- **Architecture / agents** : [cursor.md](cursor.md)

## Transparence

Ce dépôt contient le **code** et la **config métier** (rosters médias / candidats, domaines). Il ne contient **pas** :

- secrets (`.env` — X API, OpenAI, HMAC)
- la base SQLite ni les dumps Community Notes
- les e-mails collectés à l’export PDF
- les snapshots JSON de production

## Architecture (résumé)

```
download CN → parse → attribute → classify thèmes → score → snapshot
→ FastAPI (127.0.0.1:8700) → Next.js (127.0.0.1:8710) → nginx/TLS
```

- Source de vérité : SQLite + `config/*_roster.yml` + snapshots ; l’UI **observe**.
- Moisson hebdo (lundi 06:00 UTC) : CN + counts X 7j + cascade 30/90/365 + score.
- Métrique live : fenêtre **7d** (`CN / posts`).

## Démarrage local

```bash
git clone https://github.com/ZaraA1971/Desinfo.git
cd Desinfo
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp -n .env.example .env   # renseigner les secrets si besoin
./venv/bin/python scripts/bootstrap_year.py
cd frontend && npm install && npm run build && cd ..
./venv/bin/uvicorn backend.api.app:app --host 127.0.0.1 --port 8700
# autre terminal :
cd frontend && npm start   # :8710
```

Sans `X_BEARER_TOKEN`, le ranking peut rester en mode `cn_only`. Sans `OPENAI_API_KEY`, les thèmes radar sont ignorés.

## Production

```bash
sudo bash infra/systemd/install.sh
sudo bash scripts/deploy_frontend.sh
DESINFO_SSL_EMAIL=you@example.com sudo bash scripts/setup_domain.sh
```

Services : `desinfo-api`, `desinfo-frontend`, timer `desinfo-x-sync.timer`.

## Licence

Copyright (C) 2026 ElectronLibre / contributeurs Desinfo.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).

If you run a modified version as a network service, AGPL-3.0 requires you to offer the corresponding source to users of that service.
