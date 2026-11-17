#!/bin/bash
# NetMonitor.app oluşturur (Dock / Launchpad'den açılabilen macOS uygulaması).
#   ./macos/build_app.sh            → ./dist/NetMonitor.app
#   ./macos/build_app.sh --install  → ~/Applications/NetMonitor.app
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
[ "${1:-}" = "--install" ] && OUT="$HOME/Applications"
APP="$OUT/NetMonitor.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
for f in main.py netinfo.py probes.py storage.py webprobe.py updater.py requirements.txt static tools; do
  cp -R "$ROOT/$f" "$APP/Contents/Resources/app/"
done

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>NetMonitor</string>
  <key>CFBundleDisplayName</key><string>NetMonitor</string>
  <key>CFBundleIdentifier</key><string>com.netmonitor.app</string>
  <key>CFBundleVersion</key><string>3.0.1</string>
  <key>CFBundleShortVersionString</key><string>3.0.1</string>
  <key>CFBundleExecutable</key><string>NetMonitor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><false/>
  <key>NSLocationUsageDescription</key><string>Wi-Fi ağ adını (SSID) göstermek için konum izni gerekir.</string>
  <key>NSLocationWhenInUseUsageDescription</key><string>Wi-Fi ağ adını (SSID) göstermek için konum izni gerekir.</string>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/NetMonitor" <<'LAUNCH'
#!/bin/bash
# Uygulama başlatıcı: veri ~/Library/Application Support/NetMonitor altında tutulur
HERE="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
SUPPORT="$HOME/Library/Application Support/NetMonitor"
LOG="$HOME/Library/Logs/NetMonitor.log"
PORT="${NETMON_PORT:-8000}"
mkdir -p "$SUPPORT" "$(dirname "$LOG")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Zaten çalışıyorsa sadece tarayıcıyı aç
if curl -fs "http://127.0.0.1:$PORT/api/config" >/dev/null 2>&1; then
  open "http://localhost:$PORT"; exit 0
fi

PY=$(command -v python3 || true)
if [ -z "$PY" ]; then
  osascript -e "display alert \"NetMonitor\" message \"Python 3 bulunamadı. Terminal'de şunu çalıştırın: xcode-select --install\""
  exit 1
fi
if [ ! -x "$SUPPORT/venv/bin/python" ]; then
  osascript -e 'display notification "İlk açılış: gerekli paketler kuruluyor (1-2 dk)…" with title "NetMonitor"'
  "$PY" -m venv "$SUPPORT/venv" >>"$LOG" 2>&1
fi
if [ ! -f "$SUPPORT/venv/.kurulum_tamam" ] || [ "$HERE/requirements.txt" -nt "$SUPPORT/venv/.kurulum_tamam" ]; then
  "$SUPPORT/venv/bin/python" -m pip install -q --disable-pip-version-check --upgrade pip >>"$LOG" 2>&1
  "$SUPPORT/venv/bin/python" -m pip install -q --disable-pip-version-check --prefer-binary -r "$HERE/requirements.txt" >>"$LOG" 2>&1
  "$SUPPORT/venv/bin/python" -m pip install -q --disable-pip-version-check --only-binary=:all: "pyobjc-framework-CoreWLAN<12" >>"$LOG" 2>&1 || true
  touch "$SUPPORT/venv/.kurulum_tamam"
fi

export NETMON_DATA_DIR="$SUPPORT"
exec "$SUPPORT/venv/bin/python" "$HERE/main.py" --port "$PORT" >>"$LOG" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/NetMonitor"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
echo "Oluşturuldu: $APP"
echo "Çalıştırmak için: open \"$APP\""
