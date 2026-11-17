"""
Yeni sürüm paketi hazırlar.

  python tools/release.py
    → dist/netmonitor-<sürüm>.zip, .zip.sha256 ve version.json üretir.

GitHub'a yüklemek için (gh CLI):
  gh release create v<sürüm> dist/netmonitor-<sürüm>.zip dist/netmonitor-<sürüm>.zip.sha256 \
      --title "NetMonitor v<sürüm>" --notes "Değişiklikler…"

Sürüm numarası main.py içindeki VERSION değişkeninden okunur; yayınlamadan önce artırın.
"""
import hashlib
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", ".backup", "backups", "dist", ".git", "__pycache__", "docs"}
SKIP_FILES = {"config.json", ".DS_Store"}


def main():
    version = re.search(r'^VERSION\s*=\s*"([^"]+)"', (ROOT / "main.py").read_text(encoding="utf-8"), re.M).group(1)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"netmonitor-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if any(part in SKIP_DIRS for part in rel.parts) or p.name in SKIP_FILES or p.name.startswith("network_monitor.db"):
                continue
            if p.is_file():
                info = zipfile.ZipInfo.from_file(p, Path("netmonitor") / rel)
                with open(p, "rb") as f:
                    zf.writestr(info, f.read(), zipfile.ZIP_DEFLATED)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (dist / "netmonitor.zip").write_bytes(out.read_bytes())  # install.sh / install.ps1 için sabit adlı kopya
    (dist / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n")
    notes = sys.argv[1] if len(sys.argv) > 1 else ""
    (dist / "version.json").write_text(json.dumps({
        "version": version, "url": f"https://BURAYA-SUNUCU/{out.name}", "sha256": digest,
        "notes": notes, "date": date.today().isoformat()}, indent=2, ensure_ascii=False))
    print(f"Paket : {out}\nSHA256: {digest}\n")
    print(f'gh release create v{version} "{out}" "{out}.sha256" "{dist / "netmonitor.zip"}" --title "NetMonitor v{version}" --notes "{notes or "..."}"')


if __name__ == "__main__":
    main()
