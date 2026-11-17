"""
İnternetten güncelleme (GitHub Releases veya kendi sunucunuzdaki version.json).

Kaynak biçimleri (Ayarlar → Güncelleme):
  * "kullanici/depo"                 → https://api.github.com/repos/kullanici/depo/releases/latest
      Yayında iki dosya olmalı: netmonitor-<sürüm>.zip ve netmonitor-<sürüm>.zip.sha256
  * "https://.../version.json"       → {"version": "3.0.1", "url": "https://.../netmonitor-3.0.1.zip",
                                         "sha256": "...", "notes": "..."}

Güvenlik: SHA-256 doğrulaması zorunludur; doğrulanmayan paket kurulmaz. Kurulumdan önce mevcut
kod .backup/<sürüm>/ klasörüne yedeklenir. Ayarlar (config.json), veritabanı ve .venv korunur.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

PRESERVE = {"config.json", ".venv", ".backup", "backups", "dist", ".git", "__pycache__"}
PRESERVE_PREFIX = ("network_monitor.db",)
MAX_SIZE = 60 * 1024 * 1024

state: Dict[str, Any] = {"state": "idle", "message": "", "last_check": None, "info": None}
_lock = threading.Lock()


def parse_version(v: str):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def _get(url: str, timeout: float = 20, limit: int = MAX_SIZE) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "NetMonitor-Updater", "Accept": "application/vnd.github+json, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("paket çok büyük")
    return data


def check(source: str, current: str) -> Dict[str, Any]:
    source = (source or "").strip()
    info: Dict[str, Any] = {"current": current, "available": False, "source": source}
    if not source:
        info["error"] = "Güncelleme kaynağı ayarlanmamış"
        return info
    try:
        if source.startswith("https://"):
            m = json.loads(_get(source, limit=1_000_000).decode("utf-8"))
            info.update(latest=str(m["version"]).lstrip("v"), url=m["url"], sha256=m.get("sha256"),
                        notes=m.get("notes", ""), published=m.get("date"))
        elif re.fullmatch(r"[\w.-]+/[\w.-]+", source):
            rel = json.loads(_get(f"https://api.github.com/repos/{source}/releases/latest", limit=2_000_000).decode("utf-8"))
            assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
            # Özeti (.sha256) olan zip'i tercih et (ör. netmonitor-3.0.1.zip); "netmonitor.zip" kurulum kopyasıdır
            zip_name = next((n for n in assets if n.endswith(".zip") and n + ".sha256" in assets), None) \
                or next((n for n in assets if n.endswith(".zip")), None)
            if not zip_name:
                raise ValueError("yayında .zip dosyası yok")
            info.update(latest=str(rel.get("tag_name", "")).lstrip("v"), url=assets[zip_name],
                        sha_url=assets.get(zip_name + ".sha256"), notes=rel.get("body") or "",
                        published=rel.get("published_at"), page=rel.get("html_url"))
        else:
            raise ValueError("kaynak 'kullanici/depo' veya https://…/version.json olmalı")
        info["available"] = parse_version(info["latest"]) > parse_version(current)
    except urllib.error.HTTPError as e:
        info["error"] = "Yayın bulunamadı (404)" if e.code == 404 else f"HTTP {e.code}"
    except Exception as e:
        info["error"] = str(e)[:200]
    with _lock:
        state["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
        state["info"] = info
    return info


def _set(st: str, msg: str):
    with _lock:
        state["state"], state["message"] = st, msg
    print(f"[güncelleme] {msg}")


def _safe_extract(zf: zipfile.ZipFile, dest: Path):
    for m in zf.infolist():
        target = (dest / m.filename).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise ValueError(f"güvensiz yol: {m.filename}")
    zf.extractall(dest)


def apply(info: Dict[str, Any], base_dir: Path, current_version: str) -> bool:
    """Paketi indirir, doğrular, kurar. Başarılıysa True (ardından yeniden başlatma gerekir)."""
    try:
        _set("downloading", f"v{info['latest']} indiriliyor…")
        data = _get(info["url"], timeout=120)
        expected = (info.get("sha256") or "").strip().lower()
        if not expected and info.get("sha_url"):
            expected = _get(info["sha_url"], limit=10_000).decode().split()[0].strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
            raise ValueError("SHA-256 özeti bulunamadı; paket doğrulanamadığı için kurulmadı")
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError("SHA-256 uyuşmuyor; paket bozuk veya değiştirilmiş")

        _set("installing", "Paket açılıyor…")
        tmp = Path(tempfile.mkdtemp(prefix="netmon_upd_"))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            _safe_extract(zf, tmp)
        root = next((p.parent for p in tmp.rglob("main.py") if (p.parent / "static").is_dir()), None)
        if root is None:
            raise ValueError("pakette main.py bulunamadı")

        backup = base_dir / ".backup" / f"v{current_version}_{time.strftime('%Y%m%d%H%M%S')}"
        backup.mkdir(parents=True, exist_ok=True)
        for item in base_dir.iterdir():
            if item.name in PRESERVE or item.name.startswith(PRESERVE_PREFIX):
                continue
            dst = backup / item.name
            if item.is_dir():
                shutil.copytree(item, dst, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(item, dst)

        _set("installing", "Dosyalar güncelleniyor…")
        for item in root.iterdir():
            if item.name in PRESERVE or item.name.startswith(PRESERVE_PREFIX):
                continue
            dst = base_dir / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)
                if item.suffix in (".command", ".sh"):
                    os.chmod(dst, 0o755)
        shutil.rmtree(tmp, ignore_errors=True)

        req = base_dir / "requirements.txt"
        if req.exists():
            _set("installing", "Python paketleri güncelleniyor…")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                            "--prefer-binary", "-r", str(req)], timeout=600,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        _set("restarting", f"v{info['latest']} kuruldu, yeniden başlatılıyor…")
        return True
    except Exception as e:
        _set("error", f"Güncelleme başarısız: {e}")
        return False


def restart(base_dir: Path, delay: float = 1.5):
    """Uygulamayı aynı argümanlarla yeniden başlatır. LaunchAgent altında çalışıyorsa launchd yeniden başlatır."""
    def go():
        time.sleep(delay)
        if os.environ.get("NETMON_SUPERVISED") != "1":
            args = [sys.executable, str(base_dir / "main.py")] + [a for a in sys.argv[1:] if a != "--no-browser"] + ["--no-browser"]
            kw: Dict[str, Any] = {"cwd": str(base_dir)}
            if os.name == "nt":
                kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            else:
                kw["start_new_session"] = True
            kw["env"] = {**os.environ, "NETMON_RESTART": "1"}
            subprocess.Popen(args, **kw)
        os._exit(0)
    threading.Thread(target=go, daemon=True).start()
