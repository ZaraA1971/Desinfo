#!/usr/bin/env bash
# Configure desinfo.electronlibre.info (nginx + Let's Encrypt)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="${DESINFO_DOMAIN:-desinfo.electronlibre.info}"
NGINX_AVAILABLE="/etc/nginx/sites-available/${DOMAIN}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${DOMAIN}"
WEBROOT="/var/www/desinfo"
EMAIL="${DESINFO_SSL_EMAIL:-}"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Relancez avec sudo : sudo $0" >&2
  exit 1
fi

if [[ -z "$EMAIL" ]]; then
  echo "Définissez l'e-mail Let's Encrypt : DESINFO_SSL_EMAIL=you@example.com sudo $0" >&2
  exit 1
fi

echo "==> Vérification DNS pour ${DOMAIN}"
RESOLVED="$(getent ahostsv4 "${DOMAIN}" 2>/dev/null | awk '{print $1; exit}' || true)"
if [[ -z "$RESOLVED" ]]; then
  RESOLVED="$(host -t A "${DOMAIN}" 2>/dev/null | awk '/has address/{print $4; exit}' || true)"
fi
if [[ -z "$RESOLVED" ]]; then
  RESOLVED="$(python3 -c "import socket; print(socket.gethostbyname('${DOMAIN}'))" 2>/dev/null || true)"
fi
SERVER_IP="$(curl -4 -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
if [[ -z "$RESOLVED" ]]; then
  echo "ATTENTION : pas d'enregistrement A pour ${DOMAIN}." >&2
  echo "  ${DOMAIN}  A  ${SERVER_IP}" >&2
  echo "Continuez après configuration DNS, ou forcez avec DESINFO_FORCE_DNS=1" >&2
  if [[ "${DESINFO_FORCE_DNS:-}" != "1" ]]; then
    exit 1
  fi
else
  echo "  ${DOMAIN} → ${RESOLVED} (serveur : ${SERVER_IP})"
fi

mkdir -p "$WEBROOT/.well-known/acme-challenge"
chown -R www-data:www-data "$WEBROOT" 2>/dev/null || true

# Ensure map for websocket upgrade exists (nginx.conf often has it)
if ! grep -q 'connection_upgrade' /etc/nginx/nginx.conf 2>/dev/null; then
  echo "Note: \$connection_upgrade may need to be defined in nginx.conf" >&2
fi

echo "==> Bootstrap nginx (HTTP)"
install -m 644 "${ROOT}/deploy/nginx/desinfo.electronlibre.info.bootstrap.conf" "$NGINX_AVAILABLE"
ln -sf "$NGINX_AVAILABLE" "$NGINX_ENABLED"
nginx -t
systemctl reload nginx

echo "==> Certificat Let's Encrypt"
certbot certonly --webroot -w "$WEBROOT" \
  -d "$DOMAIN" \
  --email "$EMAIL" --agree-tos --non-interactive

echo "==> Config nginx production (HTTPS)"
install -m 644 "${ROOT}/deploy/nginx/desinfo.electronlibre.info.conf" "$NGINX_AVAILABLE"
nginx -t
systemctl reload nginx

echo ""
echo "OK — https://${DOMAIN}"
echo "Redémarrez les services : sudo systemctl restart desinfo-api desinfo-frontend"
