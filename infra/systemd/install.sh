#!/usr/bin/env bash
# Install systemd units for desinfo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
UNIT_DIR=/etc/systemd/system

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Relancez avec sudo" >&2
  exit 1
fi

install -m 644 "$SCRIPT_DIR/desinfo-api.service" "$UNIT_DIR/"
install -m 644 "$SCRIPT_DIR/desinfo-frontend.service" "$UNIT_DIR/"
install -m 644 "$SCRIPT_DIR/desinfo-ingest.service" "$UNIT_DIR/"
install -m 644 "$SCRIPT_DIR/desinfo-ingest.timer" "$UNIT_DIR/"
install -m 644 "$SCRIPT_DIR/desinfo-x-sync.service" "$UNIT_DIR/"
install -m 644 "$SCRIPT_DIR/desinfo-x-sync.timer" "$UNIT_DIR/"

systemctl daemon-reload
systemctl enable desinfo-api.service desinfo-frontend.service desinfo-ingest.timer desinfo-x-sync.timer
systemctl restart desinfo-api.service
# frontend may not be built yet
systemctl restart desinfo-frontend.service || true
systemctl enable --now desinfo-ingest.timer
systemctl enable --now desinfo-x-sync.timer

echo "OK — units installed (ROOT=$ROOT)"
systemctl --no-pager status desinfo-api.service desinfo-ingest.timer desinfo-x-sync.timer || true
