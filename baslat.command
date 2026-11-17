#!/bin/bash
# NetMonitor — macOS başlatıcı (Finder'da çift tıklayın)
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9+ bulunamadı."
  echo "Kurulum: 'xcode-select --install' veya 'brew install python' ya da https://www.python.org/downloads/macos/"
  read -r -p "Kapatmak için Enter'a basın..." _
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[NetMonitor] İlk kurulum: sanal ortam oluşturuluyor..."
  "$PY" -m venv .venv || exit 1
fi
if [ ! -f .venv/.kurulum_tamam ] || [ requirements.txt -nt .venv/.kurulum_tamam ]; then
  echo "[NetMonitor] Paketler kuruluyor..."
  .venv/bin/python -m pip install -q --disable-pip-version-check --upgrade pip
  .venv/bin/python -m pip install -q --disable-pip-version-check --prefer-binary -r requirements.txt || {
    echo "Paketler kurulamadı (internet bağlantısını kontrol edin)."; read -r -p "Enter..." _; exit 1; }
  # İsteğe bağlı: Wi-Fi sinyalini doğrudan okumak için CoreWLAN (yalnızca hazır paket; derleme yapılmaz)
  if [ "$(uname)" = "Darwin" ]; then
    .venv/bin/python -m pip install -q --disable-pip-version-check --only-binary=:all: "pyobjc-framework-CoreWLAN<12" >/dev/null 2>&1 \
      || echo "[NetMonitor] Bilgi: CoreWLAN kurulamadı, Wi-Fi bilgisi system_profiler ile okunacak (sorun değil)."
  fi
  touch .venv/.kurulum_tamam
fi

if ! command -v speedtest >/dev/null 2>&1 || ! speedtest --version 2>/dev/null | grep -qi ookla; then
  echo "[NetMonitor] Bilgi: Ookla CLI yok → Cloudflare hız testi kullanılacak."
  echo "            Kurmak için: brew tap teamookla/speedtest && brew install speedtest"
fi

exec .venv/bin/python main.py "$@"
