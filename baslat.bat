@echo off
chcp 65001 >nul
title NetMonitor - Ag Kalitesi Izleme
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo [NetMonitor] Ilk kurulum: sanal ortam olusturuluyor...
    %PY% -m venv .venv || goto :nopython
)
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || goto :piperr

where speedtest >nul 2>nul || echo [NetMonitor] Bilgi: Ookla CLI yok, Cloudflare hiz testi kullanilacak. Kurmak icin: winget install Ookla.Speedtest.CLI

".venv\Scripts\python.exe" main.py %*
pause
exit /b

:nopython
echo Python bulunamadi. https://www.python.org/downloads/ adresinden Python 3.10+ kurun ("Add to PATH" isaretli).
pause
exit /b 1

:piperr
echo Paketler kurulamadi. Internet baglantinizi kontrol edin.
pause
exit /b 1
