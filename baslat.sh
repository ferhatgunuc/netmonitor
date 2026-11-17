#!/bin/bash
# NetMonitor — Linux başlatıcı
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9+ bulunamadı."
  echo "Kurulum: sudo apt install python3 python3-venv"
  read -r -p "Kapatmak için Enter'a basın..." _
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[NetMonitor] İlk kurulum: sanal ortam oluşturuluyor..."
  "$PY" -m venv .venv || exit 1
fi
.venv/bin/python -m pip install -q --disable-pip-version-check --upgrade pip
.venv/bin/python -m pip install -q --disable-pip-version-check --prefer-binary -r requirements.txt || {
  echo "Paketler kurulamadı (internet bağlantısını kontrol edin)."; read -r -p "Enter..." _; exit 1; }

if ! command -v speedtest >/dev/null 2>&1 || ! speedtest --version 2>/dev/null | grep -qi ookla; then
  echo "[NetMonitor] Bilgi: Ookla CLI yok → Cloudflare hız testi kullanılacak."
  echo "            Kurmak için: https://www.speedtest.net/apps/cli"
fi

exec .venv/bin/python main.py "$@"
