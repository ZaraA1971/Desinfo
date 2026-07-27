# Security Policy

Desinfo is a public observatory. The **source code** is open under AGPL-3.0; **secrets, personal data, and runtime databases must never enter git**.

## Reporting a vulnerability

Email **security@electronlibre.info** (or open a private GitHub Security Advisory on [ZaraA1971/Desinfo](https://github.com/ZaraA1971/Desinfo) if available).

Please include:

- Affected component (API, export proxy, ingest, deploy)
- Steps to reproduce
- Impact assessment

We aim to acknowledge within a few business days. Do not open a public issue for unpatched secrets or RCE.

## Never commit

| Path / secret | Why |
|---------------|-----|
| `.env` | X API, OpenAI, HMAC, tokens |
| `data/desinfo.db*` | Full note corpus + export metadata |
| `data/exports_emails*.csv` | Email addresses (consent exports) |
| `data/snapshots/`, `data/raw/` | Runtime artefacts |
| `*.pem`, `*.key`, TLS material | Certificates / private keys |

Use [`.env.example`](.env.example) as the template only.

## Secret rotation (before / after going public)

Rotate these in production `.env`, then restart services:

1. `X_BEARER_TOKEN` (and X API key/secret if used) — [developer.x.com](https://developer.x.com)
2. `OPENAI_API_KEY` — OpenAI dashboard
3. `DESINFO_EXPORT_HMAC_SECRET` — generate a new random value, update `.env` for **API and Next** (`frontend` env / systemd)

```bash
# Example HMAC secret
openssl rand -hex 32
sudo systemctl restart desinfo-api desinfo-frontend
```

## Security model (summary)

- FastAPI and Next bind **127.0.0.1** only; nginx terminates TLS.
- OpenAPI docs off unless `DESINFO_DEBUG=1`.
- PDF export: Next honeypot + Origin check → FastAPI HMAC (`X-Desinfo-Export-Ts` / `X-Desinfo-Export-Sig`).
- Rate limits: in-app + nginx `limit_req`.
- Community Notes: only `CURRENTLY_RATED_HELPFUL` counted.

See [`cursor.md`](cursor.md) for architecture details.
