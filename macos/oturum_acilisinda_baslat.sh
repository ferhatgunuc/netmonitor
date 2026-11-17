#!/bin/bash
# NetMonitor'u Mac açıldığında arka planda otomatik başlatır (LaunchAgent).
#   ./macos/oturum_acilisinda_baslat.sh            → kur
#   ./macos/oturum_acilisinda_baslat.sh --kaldir   → kaldır
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.netmonitor.agent.plist"
SUPPORT="$HOME/Library/Application Support/NetMonitor"

if [ "${1:-}" = "--kaldir" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"; echo "Otomatik başlatma kaldırıldı."; exit 0
fi

[ -x "$ROOT/.venv/bin/python" ] || { echo "Önce bir kez baslat.command ile çalıştırın (kurulum için)."; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$SUPPORT" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.netmonitor.agent</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>$ROOT/main.py</string><string>--no-browser</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>NETMON_SUPERVISED</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/NetMonitor.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/NetMonitor.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Kuruldu. NetMonitor arka planda çalışıyor: http://localhost:8000"
echo "Not: Uyku modunda ölçüm yapılmaz. Sürekli izleme için Sistem Ayarları > Pil/Enerji'den uykuyu kısıtlayın."
