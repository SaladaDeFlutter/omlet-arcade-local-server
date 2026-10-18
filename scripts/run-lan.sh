#!/usr/bin/env bash
# Start the local Longdan server for LAN testing with a physical Android device.
#
# The patched APK embeds a server host, and the server must advertise the same
# host so avatar/cover/blob URLs resolve from the device.
#
# Usage:
#   scripts/run-lan.sh [host]
#
# If host is omitted, the primary LAN IPv4 of this machine is detected.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${1:-}"

if [[ -z "$HOST" ]]; then
  HOST="$(ip route get 1.1.1.1 2>/dev/null \
    | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')"
fi

if [[ -z "$HOST" ]]; then
  echo "error: could not detect the LAN IP; pass it explicitly: scripts/run-lan.sh <ip>" >&2
  exit 1
fi

echo "PUBLIC_HOST=$HOST  (WebSocket ws://$HOST:8080, assets http://$HOST:8081)"
echo "Make sure the APK was patched for the same host:"
echo "  scripts/patch-apk.sh /path/to/omlet.apk $HOST:8080"
echo

cd "$ROOT/server-ts"
exec env PUBLIC_HOST="$HOST" npm start
