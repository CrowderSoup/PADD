#!/usr/bin/env bash
# Extracts the Caddy local root CA from the running dev container and trusts it
# in the macOS system keychain. Re-run whenever caddy_data is recreated.
set -euo pipefail

CONTAINER="padd-caddy-1"
CERT_PATH="/tmp/caddy-local-root.crt"

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "error: container '${CONTAINER}' is not running" >&2
  echo "       start it with: docker compose -f docker-compose.dev.yml up -d" >&2
  exit 1
fi

echo "Copying root CA from ${CONTAINER}..."
docker cp "${CONTAINER}:/data/caddy/pki/authorities/local/root.crt" "${CERT_PATH}"

echo "Trusting cert in macOS system keychain (requires sudo)..."
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "${CERT_PATH}"

rm "${CERT_PATH}"
echo "Done. Restart Chrome (chrome://restart) or your browser to pick up the change."
