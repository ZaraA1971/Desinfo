# Observatoire de la désinformation

Palmarès roulant des médias FR via Community Notes (X).

## Démarrage local

```bash
cd /srv/desinfo
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp -n .env.example .env
./venv/bin/python scripts/bootstrap_year.py   # download + roster 365j + snapshots
cd frontend && npm install && npm run build
./venv/bin/uvicorn backend.api.app:app --host 127.0.0.1 --port 8700
# autre terminal :
cd frontend && npm start
```

## Production

```bash
sudo bash infra/systemd/install.sh
sudo bash scripts/deploy_frontend.sh
DESINFO_SSL_EMAIL=you@example.com sudo bash scripts/setup_domain.sh
```

DNS requis : `desinfo.electronlibre.info` A → IP du serveur.

Voir `cursor.md` pour l’architecture et les commandements agent.
