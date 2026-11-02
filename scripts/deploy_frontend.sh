#!/usr/bin/env bash
# Build Next.js frontend and restart systemd unit
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"

export NODE_ENV=production
export DESINFO_API_HOST="${DESINFO_API_HOST:-127.0.0.1}"
export DESINFO_API_PORT="${DESINFO_API_PORT:-8700}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^(DESINFO_API_HOST|DESINFO_API_PORT)=' "$ROOT/.env" || true)
  set +a
fi

echo "Installing frontend dependencies…"
# Next.js reads tsconfig path aliases via TypeScript (a devDependency).
# Keep NODE_ENV=production for the build, but always install devDependencies.
npm ci --include=dev 2>/dev/null || npm install --include=dev

echo "Building frontend…"
npm run build

if systemctl list-unit-files desinfo-frontend.service &>/dev/null; then
  echo "Restarting desinfo-frontend…"
  systemctl restart desinfo-frontend.service
  systemctl status desinfo-frontend.service --no-pager || true
else
  echo "Build OK. Install units with: sudo bash infra/systemd/install.sh"
fi
