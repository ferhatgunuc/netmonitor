#!/bin/bash
# NetMonitor kurulum / güncelleme (macOS ve Linux)
#   curl -fsSL https://raw.githubusercontent.com/ferhatgunuc/netmonitor/main/install.sh | bash
set -euo pipefail
REPO="ferhatgunuc/netmonitor"
DEST="${NETMON_DIR:-$HOME/netmonitor}"
URL="https://github.com/$REPO/releases/latest/download/netmonitor.zip"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "NetMonitor indiriliyor…"
curl -fsSL "$URL" -o "$TMP/nm.zip"
unzip -q "$TMP/nm.zip" -d "$TMP"
mkdir -p "$DEST"
# Ayarlar, veritabanı ve sanal ortam korunur
( cd "$TMP/netmonitor" && tar cf - . ) | ( cd "$DEST" && tar xf - )
chmod +x "$DEST"/baslat.command "$DEST"/baslat.sh "$DEST"/install.sh "$DEST"/macos/*.sh 2>/dev/null || true
[ "$(uname)" = "Darwin" ] && xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
echo "Kuruldu: $DEST"
echo "Başlatılıyor…"
if [ "$(uname)" = "Darwin" ]; then exec "$DEST/baslat.command"; else exec "$DEST/baslat.sh"; fi
