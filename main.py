"""
NetMonitor — Ağ Kalitesi Sürekli İzleme Sistemi (v2)

Çalıştırma:
    python main.py                 # yalnızca bu bilgisayardan erişim (127.0.0.1:8000)
    python main.py --lan           # yerel ağdaki diğer cihazlardan da erişim
    python main.py --port 8080 --no-browser
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import io
import json
import os
import re
import smtplib
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import netinfo as ni
import probes
import storage as db
import updater
import webprobe as wp

VERSION = "3.1.0"
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("NETMON_DATA_DIR", BASE_DIR))
DB_FILE = DATA_DIR / "network_monitor.db"
CONFIG_FILE = DATA_DIR / "config.json"
PASS_MASK = "********"

DEFAULT_TARGETS = [
    {"id": "gateway", "name": "Lokal Gateway (Modem)", "host": "@gateway", "ping": True, "trace": False},
    {"id": "google_dns", "name": "Google DNS", "host": "8.8.8.8", "ping": True, "trace": True},
    {"id": "cloudflare", "name": "Cloudflare DNS", "host": "1.1.1.1", "ping": True, "trace": True},
    {"id": "riot_tr", "name": "Riot Games (TR/İstanbul)", "host": "104.160.143.212", "ping": True, "trace": True},
    {"id": "valve_eu", "name": "Valve CS2 (Viyana)", "host": "146.66.155.1", "ping": True, "trace": False},
    {"id": "quad9", "name": "Quad9 DNS", "host": "9.9.9.9", "ping": True, "trace": False},
]

DEFAULT_SITES = [
    {"id": "google", "name": "Google", "target": "www.google.com", "enabled": True, "trace": True},
    {"id": "youtube", "name": "YouTube", "target": "www.youtube.com", "enabled": True, "trace": True},
    {"id": "instagram", "name": "Instagram", "target": "www.instagram.com", "enabled": True, "trace": True},
    {"id": "facebook", "name": "Facebook", "target": "www.facebook.com", "enabled": True, "trace": True},
    {"id": "wikipedia", "name": "Wikipedia", "target": "www.wikipedia.org", "enabled": True, "trace": True},
    {"id": "netflix", "name": "Netflix", "target": "www.netflix.com", "enabled": False, "trace": True},
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "speedtest_running": False,
    "speedtest_interval": 1800,
    "speedtest_server_id": "auto",
    "speedtest_engine": "auto",
    "cf_max_mb": 100,
    "ping_running": False,
    "ping_interval": 10,
    "ping_count": 5,
    "ping_timeout_ms": 1000,
    "trace_running": False,
    "trace_interval": 300,
    "trace_max_hops": 20,
    "iface_mode": "auto",  # auto | wifi | ethernet | both
    "wifi_interval": 15,
    "pause_ping_during_speedtest": True,
    "retention_days": 90,
    "thresholds": {
        "ping_good": 30, "ping_warn": 80,
        "jitter_good": 5, "jitter_warn": 15,
        "loss_alert": 5, "rssi_weak": -75,
    },
    "email_enabled": False,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_pass": "",
    "recipient_email": "",
    "alert_on_loss": True,
    "alert_on_link_down": True,
    "alert_on_weak_wifi": False,
    "alert_cooldown_min": 15,
    "targets": DEFAULT_TARGETS,
    # v3
    "ookla_servers": [],          # [{"id","name","location"}] — boşsa en yakın sunucu
    "site_running": False,
    "site_interval": 300,
    "site_resolvers": True,       # her testte DNS sunucularını karşılaştır
    "sites": DEFAULT_SITES,
    "cdn_running": False,
    "cdn_interval": 900,
    "cdn_services": {"youtube": True, "facebook": True, "instagram": True},
    "cdn_custom": [],             # [{"label","host"}] — bilinen GGC/FNA sunucuları
    "update_repo": "ferhatgunuc/netmonitor",
    "update_auto_check": True,
    "session_start": None,
    "last_report": None,
}

HOST_RE = re.compile(r"^(?!-)[A-Za-z0-9.\-:]{1,253}$")
config_lock = threading.RLock()
config: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Yapılandırma (config.json — uygulama yeniden başlasa da korunur)
# ---------------------------------------------------------------------------

def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in saved.items():
                if k == "thresholds" and isinstance(v, dict):
                    cfg["thresholds"].update(v)
                elif k in cfg:
                    cfg[k] = v
        except Exception as e:
            print(f"config.json okunamadı ({e}), varsayılanlar kullanılıyor")
    config.clear()
    config.update(cfg)


def save_config():
    with config_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_FILE)


def public_config() -> Dict[str, Any]:
    with config_lock:
        c = copy.deepcopy(config)
    c["smtp_pass"] = PASS_MASK if c.get("smtp_pass") else ""
    return c


def validate_targets(targets: Any) -> List[Dict[str, Any]]:
    if not isinstance(targets, list):
        raise HTTPException(400, "targets bir liste olmalı")
    out, seen = [], set()
    for t in targets:
        name = str(t.get("name", "")).strip()[:60]
        host = str(t.get("host", "")).strip()
        if not name or not (host == "@gateway" or HOST_RE.match(host)):
            raise HTTPException(400, f"Geçersiz hedef: {name or host}")
        tid = str(t.get("id") or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or host)[:40]
        base, i = tid, 2
        while tid in seen:
            tid, i = f"{base}_{i}", i + 1
        seen.add(tid)
        out.append({"id": tid, "name": name, "host": host, "ping": bool(t.get("ping", True)), "trace": bool(t.get("trace", False))})
    return out


INT_LIMITS = {
    "speedtest_interval": (60, 86400 * 7), "ping_interval": (2, 3600), "ping_count": (1, 50),
    "ping_timeout_ms": (200, 10000), "trace_interval": (60, 86400), "trace_max_hops": (5, 40),
    "wifi_interval": (5, 600), "retention_days": (0, 3650), "smtp_port": (1, 65535),
    "cf_max_mb": (10, 2000), "alert_cooldown_min": (1, 1440),
    "site_interval": (30, 86400), "cdn_interval": (120, 86400),
}

RUN_KEYS = ("ping_running", "trace_running", "speedtest_running", "site_running", "cdn_running")


def validate_sites(sites: Any) -> List[Dict[str, Any]]:
    if not isinstance(sites, list):
        raise HTTPException(400, "sites bir liste olmalı")
    out, seen = [], set()
    for s in sites:
        raw = str(s.get("target", "")).strip()
        if not raw:
            continue
        try:
            host, _ = wp.normalize_target(raw)
        except ValueError as e:
            raise HTTPException(400, f"Geçersiz site: {raw} ({e})")
        name = str(s.get("name") or host).strip()[:60]
        sid = str(s.get("id") or re.sub(r"[^a-z0-9]+", "_", host.lower()).strip("_"))[:40]
        base, i = sid, 2
        while sid in seen:
            sid, i = f"{base}_{i}", i + 1
        seen.add(sid)
        out.append({"id": sid, "name": name, "target": raw, "enabled": bool(s.get("enabled", True)),
                    "trace": bool(s.get("trace", True))})
    return out


def validate_cdn_custom(items: Any) -> List[Dict[str, str]]:
    out = []
    for it in items or []:
        host = str(it.get("host", "")).strip().lower()
        if not host:
            continue
        if not HOST_RE.match(host):
            raise HTTPException(400, f"Geçersiz sunucu: {host}")
        out.append({"label": str(it.get("label") or host)[:60], "host": host})
    return out


def apply_config_patch(patch: Dict[str, Any]):
    with config_lock:
        before = copy.deepcopy(config)
        for k, v in patch.items():
            if k not in DEFAULT_CONFIG:
                continue
            if k in ("session_start", "last_report"):
                continue
            if k == "targets":
                config["targets"] = validate_targets(v)
            elif k == "sites":
                config["sites"] = validate_sites(v)
            elif k == "cdn_custom":
                config["cdn_custom"] = validate_cdn_custom(v)
            elif k == "cdn_services":
                config["cdn_services"] = {sk: bool(v.get(sk)) for sk in wp.CDN_SERVICES} if isinstance(v, dict) else config["cdn_services"]
            elif k == "ookla_servers":
                config["ookla_servers"] = [{"id": str(x["id"]), "name": str(x.get("name", ""))[:80],
                                            "location": str(x.get("location", ""))[:80]}
                                           for x in (v or []) if str(x.get("id", "")).isdigit()][:12]
            elif k == "thresholds":
                if isinstance(v, dict):
                    for tk, tv in v.items():
                        if tk in DEFAULT_CONFIG["thresholds"]:
                            config["thresholds"][tk] = float(tv)
            elif k == "smtp_pass":
                if v != PASS_MASK:
                    config["smtp_pass"] = str(v)
            elif k == "iface_mode":
                if v not in ("auto", "wifi", "ethernet", "both"):
                    raise HTTPException(400, "iface_mode geçersiz")
                config[k] = v
            elif k == "speedtest_engine":
                if v not in ("auto", "ookla", "cloudflare"):
                    raise HTTPException(400, "speedtest_engine geçersiz")
                config[k] = v
            elif isinstance(DEFAULT_CONFIG[k], bool):
                config[k] = bool(v)
            elif isinstance(DEFAULT_CONFIG[k], int):
                lo, hi = INT_LIMITS.get(k, (-10**9, 10**9))
                config[k] = max(lo, min(hi, int(v)))
            else:
                config[k] = str(v)
        if not any(before.get(k) for k in RUN_KEYS) and any(config.get(k) for k in RUN_KEYS):
            config["session_start"] = db.now_str()
            probes.STOP.clear()
        save_config()
    # Yeni açılan zamanlayıcıları hemen başlat
    for job in JOBS.values():
        if job.enabled_key and config.get(job.enabled_key) and not before.get(job.enabled_key):
            job.next_run = 0
        if config.get("iface_mode") != before.get("iface_mode") and job.name == "ping":
            job.next_run = 0


# ---------------------------------------------------------------------------
# Durum, olaylar ve e-posta uyarıları
# ---------------------------------------------------------------------------

netinfo = ni.NetInfo()
ping_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ping")
last_alert_times: Dict[str, float] = {}
_prev_links: Dict[str, Dict[str, Any]] = {}
_prev_default: Dict[str, Any] = {"name": None, "init": False}


def send_email(subject: str, body: str, key: Optional[str] = None, force: bool = False) -> Optional[str]:
    with config_lock:
        c = copy.deepcopy(config)
    if not force and (not c["email_enabled"] or not c["smtp_user"] or not c["recipient_email"]):
        return "E-posta bildirimi kapalı veya eksik ayar"
    if key and not force:
        last = last_alert_times.get(key)
        if last and time.time() - last < c["alert_cooldown_min"] * 60:
            return None
    try:
        msg = MIMEText(body + f"\n\n— NetMonitor {VERSION} · {db.now_str()}", "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = c["smtp_user"]
        msg["To"] = c["recipient_email"]
        port = int(c["smtp_port"])
        if port == 465:
            server = smtplib.SMTP_SSL(c["smtp_server"], port, timeout=15)
        else:
            server = smtplib.SMTP(c["smtp_server"], port, timeout=15)
            server.starttls()
        with server:
            server.login(c["smtp_user"], c["smtp_pass"])
            server.sendmail(c["smtp_user"], [c["recipient_email"]], msg.as_string())
        if key:
            last_alert_times[key] = time.time()
        return None
    except Exception as e:
        print(f"E-posta gönderme hatası: {e}")
        return str(e)


def alert_async(subject: str, body: str, key: str):
    threading.Thread(target=send_email, args=(subject, body, key), daemon=True).start()


def log_event(kind: str, severity: str, message: str, iface: Optional[Dict[str, Any]] = None):
    db.insert("link_events", {
        "timestamp": db.now_str(),
        "iface_name": iface["name"] if iface else None,
        "iface_type": iface["type"] if iface else None,
        "kind": kind, "severity": severity, "message": message,
    })
    if kind == "down" and config.get("alert_on_link_down"):
        alert_async(f"🔌 NetMonitor: {message}", message, f"link_{iface['name'] if iface else ''}")


def type_label(t: Optional[str]) -> str:
    return {"wifi": "Wi-Fi", "ethernet": "Ethernet"}.get(t or "", t or "?")


def detect_link_events(snap: Dict[str, Any]):
    phys = [i for i in snap["interfaces"] if not i["virtual"] and i["type"] in ("wifi", "ethernet")]
    thr = config["thresholds"]["rssi_weak"]
    if not _prev_default["init"]:
        parts = []
        for i in phys:
            if i["connected"]:
                extra = f" ({i['wifi']['ssid']})" if i.get("wifi") and i["wifi"].get("ssid") else ""
                parts.append(f"{type_label(i['type'])} {i['label']}{extra}")
        log_event("start", "info", "İzleme başlatıldı — bağlı: " + (", ".join(parts) or "bağlantı yok"))
        _prev_default.update(name=snap["default_iface"], init=True)
        for i in phys:
            _prev_links[i["name"]] = _link_state(i)
        return

    for i in phys:
        prev = _prev_links.get(i["name"])
        cur = _link_state(i)
        label = f"{type_label(i['type'])} ({i['label']})"
        if prev is None:
            if cur["connected"]:
                log_event("up", "info", f"{label} eklendi ve bağlandı — {i['ipv4']}", i)
        else:
            if prev["connected"] and not cur["connected"]:
                log_event("down", "error", f"{label} bağlantısı koptu", i)
            elif not prev["connected"] and cur["connected"]:
                log_event("up", "info", f"{label} bağlandı — {i['ipv4']}", i)
            if cur["connected"] and prev["connected"] and i["type"] == "wifi":
                if prev["ssid"] and cur["ssid"] and prev["ssid"] != cur["ssid"]:
                    log_event("ssid", "warn", f"Wi-Fi ağı değişti: {prev['ssid']} → {cur['ssid']}", i)
                elif prev["bssid"] and cur["bssid"] and prev["bssid"] != cur["bssid"]:
                    log_event("roam", "info", f"Wi-Fi erişim noktası değişti (roaming): {prev['bssid']} → {cur['bssid']}"
                              + (f", kanal {cur['channel']}" if cur["channel"] else ""), i)
                elif prev["channel"] and cur["channel"] and prev["channel"] != cur["channel"]:
                    log_event("channel", "info", f"Wi-Fi kanalı değişti: {prev['channel']} → {cur['channel']}", i)
                if cur["rssi"] is not None and prev["rssi"] is not None:
                    if cur["rssi"] < thr <= prev["rssi"]:
                        log_event("weak", "warn", f"Wi-Fi sinyali zayıfladı: {cur['rssi']} dBm (eşik {int(thr)} dBm)", i)
                        if config.get("alert_on_weak_wifi"):
                            alert_async("📶 NetMonitor: Zayıf Wi-Fi sinyali", f"{label}: {cur['rssi']} dBm", f"weak_{i['name']}")
                    elif prev["rssi"] < thr and cur["rssi"] >= thr + 3:
                        log_event("weak_ok", "info", f"Wi-Fi sinyali düzeldi: {cur['rssi']} dBm", i)
            if cur["connected"] and i["type"] == "ethernet" and prev["speed"] and cur["speed"] and prev["speed"] != cur["speed"]:
                log_event("speed", "warn", f"{label} link hızı değişti: {prev['speed']} → {cur['speed']} Mbps", i)
        _prev_links[i["name"]] = cur

    if snap["default_iface"] != _prev_default["name"]:
        old = next((x for x in phys if x["name"] == _prev_default["name"]), None)
        new = next((x for x in phys if x["name"] == snap["default_iface"]), None)
        if new or old:
            log_event("default", "warn",
                      f"Varsayılan bağlantı değişti: {type_label(old['type']) if old else 'yok'} → {type_label(new['type']) if new else 'yok'}",
                      new or old)
        _prev_default["name"] = snap["default_iface"]


def _link_state(i: Dict[str, Any]) -> Dict[str, Any]:
    w = i.get("wifi") or {}
    return {"connected": i["connected"], "ssid": w.get("ssid"), "bssid": w.get("bssid"),
            "channel": w.get("channel"), "rssi": w.get("rssi_dbm"), "speed": i.get("link_speed_mbps")}


# ---------------------------------------------------------------------------
# Arayüz bağlama (hangi testin hangi bağlantıdan yapılacağı)
# ---------------------------------------------------------------------------

def _binding_from(iface: Dict[str, Any], bound: bool) -> probes.Binding:
    w = iface.get("wifi") or {}
    return probes.Binding(iface_name=iface["name"], iface_type=iface["type"], src_ip=iface.get("ipv4"),
                          gateway=iface.get("gateway"), bound=bound, wifi_rssi=w.get("rssi_dbm"))


def resolve_bindings(mode: Optional[str] = None) -> Dict[str, Any]:
    mode = mode or config["iface_mode"]
    snap = netinfo.snapshot()
    warnings: List[str] = []
    bindings: List[probes.Binding] = []
    if mode == "auto":
        d = netinfo.by_name(snap["default_iface"]) if snap["default_iface"] else None
        if d:
            bindings.append(_binding_from(d, bound=False))
        else:
            bindings.append(probes.Binding(None, "unknown", gateway=snap.get("default_gateway")))
    else:
        wanted = ["wifi", "ethernet"] if mode == "both" else [mode]
        for t in wanted:
            it = netinfo.first(t)
            if it:
                bindings.append(_binding_from(it, bound=True))
            else:
                warnings.append(f"{type_label(t)} bağlı değil — bu bağlantı için test yapılamıyor")
        if not bindings and mode != "both":
            warnings.append("Seçili bağlantı yok; testler duraklatıldı")
    return {"mode": mode, "bindings": bindings, "warnings": warnings}


# ---------------------------------------------------------------------------
# Test işleri
# ---------------------------------------------------------------------------

def job_netinfo():
    snap = netinfo.refresh()
    ts = db.now_str()
    for i in snap["interfaces"]:
        w = i.get("wifi")
        if i["type"] == "wifi" and i["connected"] and w and (w.get("rssi_dbm") is not None or w.get("tx_rate_mbps")):
            db.insert("wifi_samples", {
                "timestamp": ts, "iface_name": i["name"], "ssid": w.get("ssid"), "bssid": w.get("bssid"),
                "rssi_dbm": w.get("rssi_dbm"), "noise_dbm": w.get("noise_dbm"), "signal_pct": w.get("signal_pct"),
                "channel": w.get("channel"), "band": w.get("band"), "width_mhz": w.get("width_mhz"),
                "phy": w.get("phy"), "tx_rate": w.get("tx_rate_mbps"), "rx_rate": w.get("rx_rate_mbps"),
            })
    detect_link_events(snap)
    return None


def _ping_one(target: Dict[str, Any], b: probes.Binding, ts: str):
    host = target["host"]
    if host == "@gateway":
        host = b.gateway or netinfo.snapshot().get("default_gateway")
        if not host:
            return
    ip = host
    if not wp._is_ip(host):
        r0 = wp.resolve_system(host)
        if not r0["ips"]:
            db.insert("pings", {"timestamp": ts, "target_name": target["name"], "host": host, "target_id": target["id"],
                                "packet_loss": 100.0, "iface_type": b.iface_type, "iface_name": b.iface_name})
            return
        ip = r0["ips"][0]
    r = probes.run_ping(ip, b, count=int(config["ping_count"]), timeout_ms=int(config["ping_timeout_ms"]))
    if probes.STOP.is_set():
        return  # kullanıcı durdurdu: yarım ölçümü kaydetme
    db.insert("pings", {
        "timestamp": ts, "target_name": target["name"], "host": host, "target_id": target["id"], "ip": ip,
        "avg_ping": r["avg"], "max_ping": r["max"], "min_ping": r["min"], "jitter": r["jitter"],
        "packet_loss": r["loss"], "iface_type": b.iface_type, "iface_name": b.iface_name, "wifi_rssi": b.wifi_rssi,
    })
    thr = config["thresholds"]["loss_alert"]
    if config.get("alert_on_loss") and r["loss"] > thr:
        alert_async(
            f"🚨 NetMonitor: {target['name']} ({b.label}) yüksek paket kaybı %{r['loss']}",
            f"Hedef: {target['name']} ({host})\nBağlantı: {b.label} {b.iface_name or ''}\n"
            f"Paket kaybı: %{r['loss']}\nOrtalama ping: {r['avg']} ms (Max: {r['max']} ms)\nJitter: {r['jitter']} ms",
            f"ping_{target['id']}_{b.iface_type}",
        )


def job_ping():
    res = resolve_bindings()
    targets = [t for t in config["targets"] if t.get("ping")]
    if not res["bindings"] or not targets:
        return "; ".join(res["warnings"]) or "Ping hedefi seçilmedi"
    ts = db.now_str()
    futures = [ping_executor.submit(_ping_one, t, b, ts) for b in res["bindings"] for t in targets]
    for f in futures:
        f.result()
    return "; ".join(res["warnings"]) or None


trace_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="trace")


def trace_items() -> List[Dict[str, str]]:
    """Traceroute yapılacak hedefler: Hedefler listesi + traceroute'u açık siteler."""
    items = [{"id": t["id"], "name": t["name"], "host": t["host"]} for t in config["targets"] if t.get("trace")]
    for s in config.get("sites", []):
        if s.get("enabled") and s.get("trace", True):
            try:
                host, _ = wp.normalize_target(s["target"])
            except ValueError:
                continue
            items.append({"id": f"site:{s['id']}", "name": s["name"], "host": host})
    return items


def trace_one(item: Dict[str, str], b: probes.Binding) -> Optional[Dict[str, Any]]:
    host = item["host"] if item["host"] != "@gateway" else (b.gateway or netinfo.snapshot().get("default_gateway"))
    if not host or probes.STOP.is_set():
        return None
    r = probes.run_traceroute(host, b, int(config["trace_max_hops"]))
    if probes.STOP.is_set():
        return None
    db.insert("traceroutes", {
        "timestamp": db.now_str(), "target_name": item["name"], "host": host, "target_id": item["id"],
        "output": r["output"], "hops_json": json.dumps(r["hops"]), "iface_type": b.iface_type,
        "iface_name": b.iface_name, "bound": int(r["bound"]),
    })
    return {**r, "host": host, "iface_type": b.iface_type, "iface_name": b.iface_name}


def job_trace():
    res = resolve_bindings()
    bindings = res["bindings"]
    if ni.IS_WINDOWS:
        # tracert arayüz seçemez → sistemin varsayılan rotası ile tek tur
        bindings = resolve_bindings("auto")["bindings"]
    items = trace_items()
    if not bindings or not items:
        return "; ".join(res["warnings"]) or "Traceroute hedefi seçilmedi"
    futures = [trace_executor.submit(trace_one, it, b) for b in bindings for it in items]
    for f in futures:
        try:
            f.result()
        except Exception as e:
            print(f"[trace] {e}")
    return "; ".join(res["warnings"]) or None


def job_speedtest():
    res = resolve_bindings()
    if not res["bindings"]:
        return "; ".join(res["warnings"])
    errors = list(res["warnings"])
    servers = [s["id"] for s in config.get("ookla_servers") or []] or [config["speedtest_server_id"]]
    if config["speedtest_engine"] == "cloudflare":
        servers = ["cloudflare"]
    runs = [(b, sid) for b in res["bindings"] for sid in servers]
    for b, sid in runs:
        if probes.STOP.is_set():
            break
        r = probes.run_speedtest(b, config["speedtest_engine"], sid, int(config["cf_max_mb"]))
        if probes.STOP.is_set():
            break
        if "error" in r:
            errors.append(f"{b.label}{' / ' + sid if len(servers) > 1 else ''}: {r['error']}")
            continue
        db.insert("speedtests", {
            "timestamp": db.now_str(), "server_name": r["server"], "download_mbps": r["dl"], "upload_mbps": r["ul"],
            "ping_ms": r["ping"], "jitter_ms": r["jitter"], "packet_loss": r["loss"], "engine": r["engine"],
            "iface_type": b.iface_type, "iface_name": b.iface_name, "wifi_rssi": b.wifi_rssi,
            "isp": r.get("isp"), "result_url": r.get("result_url"), "server_id": r.get("server_id"),
        })
        thr = config["thresholds"]["loss_alert"]
        if config.get("alert_on_loss") and r["loss"] is not None and r["loss"] > thr:
            alert_async("🚨 NetMonitor: Hız testinde yüksek paket kaybı",
                        f"Sunucu: {r['server']}\nBağlantı: {b.label}\nPaket kaybı: %{r['loss']}", "speedtest")
    return "; ".join(errors) or None


def _store_site(site: Dict[str, Any], b: probes.Binding, r: Dict[str, Any]):
    db.insert("site_checks", {
        "timestamp": db.now_str(), "site_id": site["id"], "host": r.get("host"), "url": r.get("url"),
        "iface_type": b.iface_type, "iface_name": b.iface_name, "ip": r.get("ip"), "dns_ms": r.get("dns_ms"),
        "tcp_ms": r.get("tcp_ms"), "tls_ms": r.get("tls_ms"), "ttfb_ms": r.get("ttfb_ms"),
        "total_ms": r.get("total_ms"), "status": r.get("status"), "ok": int(bool(r.get("ok"))),
        "bytes": r.get("bytes"), "server": r.get("server"), "cdn": r.get("cdn"), "asn": r.get("asn"),
        "as_name": r.get("as_name"), "ptr": r.get("ptr"), "dns_json": json.dumps(r.get("dns") or {}),
        "dns_mismatch": int(bool(r.get("dns_mismatch"))), "error": r.get("error"),
    })


def job_sites():
    res = resolve_bindings()
    sites = [s for s in config.get("sites", []) if s.get("enabled")]
    if not res["bindings"] or not sites:
        return "; ".join(res["warnings"]) or "Test edilecek site seçilmedi"
    errors = list(res["warnings"])
    futures = []
    for b in res["bindings"]:
        for s in sites:
            futures.append((s, b, ping_executor.submit(wp.site_check, s["target"], b, bool(config.get("site_resolvers", True)))))
    for s, b, f in futures:
        try:
            r = f.result()
        except Exception as e:
            r = {"host": s["target"], "url": s["target"], "error": str(e), "ok": False}
        _store_site(s, b, r)
        if not r.get("ok"):
            errors.append(f"{s['name']}: {r.get('error') or r.get('status')}")
    failed = len(errors) - len(res["warnings"])
    return f"{failed} site erişilemedi" if failed else ("; ".join(res["warnings"]) or None)


def job_cdn():
    res = resolve_bindings()
    if not res["bindings"]:
        return "; ".join(res["warnings"])
    svc = config.get("cdn_services") or {}
    errors = list(res["warnings"])
    for b in res["bindings"]:
        if probes.STOP.is_set():
            break
        client = wp.client_info(b)
        jobs = []
        for key in wp.CDN_SERVICES:
            if svc.get(key):
                d = wp.discover_youtube(b) if key == "youtube" else wp.discover_meta(key, b)
                for t in d["targets"]:
                    jobs.append((key, wp.CDN_SERVICES[key]["name"], t, d.get("cluster"), d.get("note")))
        for c in config.get("cdn_custom") or []:
            jobs.append(("custom", c["label"], {"host": c["host"], "url": f"https://{c['host']}/", "kind": "custom"}, None, None))
        ping = lambda ip, b=b: probes.run_ping(ip, b, count=4, timeout_ms=1000)
        for key, label, t, cluster, note in jobs:
            if probes.STOP.is_set():
                break
            try:
                r = wp.cdn_measure(key, label, t, b, client, ping)
            except Exception as e:
                r = {"service": key, "label": label, "host": t.get("host"), "error": str(e)}
            if probes.STOP.is_set():
                break
            db.insert("cdn_checks", {
                "timestamp": db.now_str(), "service": key, "label": label, "host": r.get("host"), "kind": r.get("kind"),
                "ip": r.get("ip"), "iface_type": b.iface_type, "iface_name": b.iface_name, "asn": r.get("asn"),
                "as_name": r.get("as_name"), "ptr": r.get("ptr"), "where_": r.get("where"), "local": int(bool(r.get("local"))),
                "cluster": cluster, "dns_ms": r.get("dns_ms"), "ping_ms": r.get("ping_ms"), "ping_loss": r.get("ping_loss"),
                "jitter": r.get("jitter"), "tcp_ms": r.get("tcp_ms"), "tls_ms": r.get("tls_ms"), "ttfb_ms": r.get("ttfb_ms"),
                "mbps": r.get("mbps"), "status": r.get("status"), "error": r.get("error"), "note": note,
            })
            if r.get("error"):
                errors.append(f"{label}: {r['error']}")
    return "; ".join(errors) or None


def job_update_check():
    if config.get("update_auto_check") and config.get("update_repo"):
        updater.check(config["update_repo"], VERSION)
    return None


def job_retention():
    db.purge_older_than(int(config.get("retention_days", 0)))
    return None


class Job:
    def __init__(self, name: str, func: Callable[[], Optional[str]], interval_key: Optional[str],
                 enabled_key: Optional[str], fixed_interval: int = 0):
        self.name, self.func = name, func
        self.interval_key, self.enabled_key, self.fixed_interval = interval_key, enabled_key, fixed_interval
        self.next_run = 0.0
        self.running = False
        self.force = False
        self.last_run: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_duration: Optional[float] = None

    @property
    def interval(self) -> int:
        return int(config.get(self.interval_key, 60)) if self.interval_key else self.fixed_interval

    @property
    def enabled(self) -> bool:
        return bool(config.get(self.enabled_key)) if self.enabled_key else True

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.running, "enabled": self.enabled, "last_run": self.last_run,
            "last_error": self.last_error, "last_duration": self.last_duration,
            "next_in": max(0, int(self.next_run - time.time())) if self.enabled else None,
        }


JOBS: Dict[str, Job] = {
    "netinfo": Job("netinfo", job_netinfo, "wifi_interval", None),
    "ping": Job("ping", job_ping, "ping_interval", "ping_running"),
    "trace": Job("trace", job_trace, "trace_interval", "trace_running"),
    "speedtest": Job("speedtest", job_speedtest, "speedtest_interval", "speedtest_running"),
    "site": Job("site", job_sites, "site_interval", "site_running"),
    "cdn": Job("cdn", job_cdn, "cdn_interval", "cdn_running"),
    "update": Job("update", job_update_check, None, None, fixed_interval=12 * 3600),
    "retention": Job("retention", job_retention, None, None, fixed_interval=6 * 3600),
}


def heavy_running() -> bool:
    return JOBS["speedtest"].running


async def run_job(job: Job):
    job.running = True
    t0 = time.time()
    try:
        job.last_error = await asyncio.to_thread(job.func)
    except Exception as e:
        job.last_error = f"{type(e).__name__}: {e}"
        print(f"[{job.name}] hata: {job.last_error}")
    finally:
        job.last_duration = round(time.time() - t0, 1)
        job.last_run = db.now_str()
        job.next_run = max(t0 + job.interval, time.time() + 1)
        job.running = False


async def scheduler():
    while True:
        for job in JOBS.values():
            if job.running:
                continue
            due = job.enabled and time.time() >= job.next_run
            if not (due or job.force):
                continue
            if job.name == "ping" and heavy_running() and config.get("pause_ping_during_speedtest") and not job.force:
                continue
            if job.name in ("ping", "trace", "speedtest", "site", "cdn") and netinfo.snapshot()["timestamp"] is None:
                continue  # ilk arayüz taraması bitmeden başlama
            job.force = False
            asyncio.create_task(run_job(job))
        await asyncio.sleep(0.5)


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduler())
    yield
    task.cancel()
    ping_executor.shutdown(wait=False)


app = FastAPI(title="NetMonitor", version=VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_ui():
    # Sürüm numarası dosya adreslerine eklenir; güncellemeden sonra tarayıcı eski JS/CSS'i önbellekten kullanmaz
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for f in ("app.js", "app.css", "vendor/chart.umd.js"):
        html = html.replace(f"/static/{f}", f"/static/{f}?v={VERSION}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.middleware("http")
async def static_cache_headers(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"  # her açılışta değişiklik kontrolü (ETag ile hızlı)
    return resp


@app.get("/api/servers")
def get_servers():
    """Ookla CLI'nin önerdiği en yakın sunucular + seçili sunucular."""
    servers = probes.ookla_cli_servers() if probes.ookla_available() else []
    return {"servers": servers, "selected": config.get("ookla_servers", []), "ookla": probes.ookla_available()}


@app.get("/api/ookla/search")
def ookla_search(q: str = ""):
    q = q.strip()[:60]
    if len(q) < 2:
        raise HTTPException(400, "En az 2 karakter girin")
    try:
        found = probes.ookla_search(q)
    except Exception as e:
        # Arama servisine ulaşılamazsa CLI listesinde ara
        cli = probes.ookla_cli_servers() if probes.ookla_available() else []
        found = [x for x in cli if q.lower() in (x["name"] + " " + x["location"]).lower()]
        if not found:
            raise HTTPException(502, f"speedtest.net sunucu listesine ulaşılamadı: {e}")
    return {"servers": found}


@app.get("/api/config")
def get_config():
    return {
        "config": public_config(),
        "defaults": {"targets": DEFAULT_TARGETS, "sites": DEFAULT_SITES},
        "meta": {"version": VERSION, "platform": ni.SYSTEM, "ookla": probes.ookla_available(),
                 "trace_bindable": not ni.IS_WINDOWS, "dnspython": wp.HAVE_DNSPY,
                 "cdn_services": wp.CDN_SERVICES},
    }


@app.post("/api/config")
def update_config(patch: Dict[str, Any] = Body(...)):
    apply_config_patch(patch)
    return {"status": "ok", "config": public_config()}


@app.post("/api/run-now/{job}")
def run_now(job: str):
    if job not in JOBS or job in ("retention", "update"):
        raise HTTPException(404, "Bilinmeyen test")
    j = JOBS[job]
    if j.running:
        return {"status": "already_running"}
    probes.STOP.clear()
    j.force = True
    return {"status": "triggered"}


@app.post("/api/start-all")
def start_all():
    apply_config_patch({k: True for k in RUN_KEYS})
    probes.STOP.clear()
    return {"status": "started", "session_start": config.get("session_start")}


@app.post("/api/stop-all")
def stop_all():
    """Tüm zamanlayıcıları kapatır, çalışan testleri keser ve oturum raporunun zaman aralığını döndürür."""
    with config_lock:
        start = config.get("session_start")
        for k in RUN_KEYS:
            config[k] = False
        end = db.now_str()
        if not start:
            first = db.conn().execute("SELECT MIN(timestamp) FROM pings WHERE timestamp >= ?",
                                      ((datetime.now() - timedelta(days=1)).strftime(db.FMT),)).fetchone()[0]
            start = first or (datetime.now() - timedelta(hours=1)).strftime(db.FMT)
        config["last_report"] = {"start": start, "end": end}
        config["session_start"] = None
        save_config()
    for j in JOBS.values():
        j.force = False
    probes.STOP.set()
    killed = probes.kill_all()
    log_event("stop", "info", "Tüm testler kullanıcı tarafından durduruldu")
    return {"status": "stopped", "killed": killed, "report": config["last_report"]}


@app.get("/api/resolve")
def resolve(host: str):
    """Alan adını anında çözümler (Ayarlar'da site/hedef eklerken önizleme)."""
    try:
        h, url = wp.normalize_target(host)
    except ValueError as e:
        raise HTTPException(400, str(e))
    d = wp.resolve_all(h)
    ips = list(dict.fromkeys(ip for v in d.values() for ip in (v.get("ips") or [])))
    info = {ip: wp.ip_info(ip) for ip in ips[:4]}
    return {"host": h, "url": url, "dns": d, "ip_info": info}


@app.post("/api/site-test")
def site_test(target: str = Body(..., embed=True)):
    """Tek seferlik site testi: girilen alan adı çözümlenir ve tüm aşamaları ölçülür (kaydedilir)."""
    try:
        wp.normalize_target(target)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res = resolve_bindings()
    out = []
    for b in res["bindings"] or [probes.Binding(None, "unknown")]:
        r = wp.site_check(target, b, True)
        site = next((s for s in config["sites"] if s["target"] == target), None) or {"id": r.get("host"), "name": r.get("host")}
        _store_site(site, b, r)
        r["iface_type"], r["iface_name"] = b.iface_type, b.iface_name
        r["headers"] = {k: v for k, v in (r.get("headers") or {}).items()
                        if k.lower() in ("server", "via", "x-cache", "cf-ray", "x-served-by", "location", "content-type", "alt-svc")}
        out.append(r)
    return {"results": out, "warnings": res["warnings"]}


@app.get("/api/live")
def live():
    snap = netinfo.snapshot()
    res = resolve_bindings()
    last_speed = db.conn().execute("SELECT * FROM speedtests ORDER BY id DESC LIMIT 1").fetchone()
    client = next(iter(v[1] for k, v in wp._client_cache.items()), None) if wp._client_cache else None
    return {
        "time": db.now_str(),
        "version": VERSION,
        "jobs": {k: v.status() for k, v in JOBS.items() if k not in ("retention", "update")},
        "any_running": any(config.get(k) for k in RUN_KEYS) or any(JOBS[k].running for k in ("ping", "trace", "speedtest", "site", "cdn")),
        "session_start": config.get("session_start"),
        "last_report": config.get("last_report"),
        "paused_for_heavy_test": heavy_running() and bool(config.get("pause_ping_during_speedtest")),
        "network": snap,
        "isp": client,
        "mode": res["mode"],
        "bindings": [{"iface_name": b.iface_name, "iface_type": b.iface_type, "src_ip": b.src_ip,
                      "gateway": b.gateway, "bound": b.bound} for b in res["bindings"]],
        "warnings": res["warnings"],
        "last_speedtest": dict(last_speed) if last_speed else None,
        "update": {"state": updater.state["state"], "message": updater.state["message"],
                   "info": updater.state["info"], "last_check": updater.state["last_check"]},
    }


def _win(range: str, start: Optional[str], end: Optional[str]):
    if range not in ("hourly", "daily", "weekly", "monthly", "all"):
        range = "daily"
    return db.window(range, start, end)


@app.get("/api/data")
def get_data(range: str = "daily", iface: str = "all", start: Optional[str] = None, end: Optional[str] = None):
    win = _win(range, start, end)
    base = int(config["ping_interval"])
    return {
        "range": range,
        "window": win,
        "iface": iface,
        "ping_series": db.ping_series(win, iface, base),
        "ping_stats": db.ping_stats(win, iface),
        "recent_pings": db.recent_pings(win, iface),
        "speedtests": db.speedtests(win, iface),
        "speed_by_iface": db.speed_by_iface(win),
        "speed_by_server": db.speed_by_server(win, iface),
        "traceroutes": db.traceroutes(win, iface),
        "wifi_series": db.wifi_series(win, int(config["wifi_interval"])),
        "wifi_summary": db.wifi_summary(win),
        "events": db.events(win),
        "site_checks": db.site_checks(win, iface, 200),
        "site_stats": db.site_stats(win, iface),
        "site_series": db.site_series(win, iface, int(config["site_interval"])),
        "cdn_checks": db.cdn_checks(win, iface, 200),
        "cdn_stats": db.cdn_stats(win, iface),
        "targets": config["targets"],
        "sites": config["sites"],
    }


@app.get("/api/report")
def report(start: Optional[str] = None, end: Optional[str] = None, range: str = "daily"):
    """Oturum raporu: verilen zaman aralığındaki tüm ölçümlerin özeti."""
    if not start and config.get("last_report"):
        start, end = config["last_report"]["start"], config["last_report"]["end"]
    win = _win(range, start, end)
    data = get_data(range, "all", win[0], win[1] if not win[1].startswith("9999") else None)
    data["bounds"] = db.data_bounds(win)
    data["isp"] = next(iter(v[1] for v in wp._client_cache.values()), None) if wp._client_cache else None
    data["config_summary"] = {"iface_mode": config["iface_mode"], "ping_interval": config["ping_interval"],
                              "ookla_servers": config.get("ookla_servers", [])}
    data["generated"] = db.now_str()
    data["version"] = VERSION
    return data


@app.post("/api/update/check")
def update_check():
    return updater.check(config.get("update_repo", ""), VERSION)


@app.post("/api/update/apply")
def update_apply():
    info = updater.state.get("info") or updater.check(config.get("update_repo", ""), VERSION)
    if not info.get("available"):
        raise HTTPException(400, info.get("error") or "Yeni sürüm yok")
    if updater.state["state"] in ("downloading", "installing", "restarting"):
        return {"status": "busy"}

    def run():
        if updater.apply(info, BASE_DIR, VERSION):
            updater.restart(BASE_DIR)

    threading.Thread(target=run, daemon=True).start()
    return {"status": "started"}


@app.post("/api/test-email")
def test_email():
    err = send_email("✅ NetMonitor test e-postası", "E-posta bildirim ayarlarınız çalışıyor.", force=True)
    if err:
        raise HTTPException(400, f"Gönderilemedi: {err}")
    return {"status": "sent"}


@app.post("/api/trace-now")
def trace_now(target: str = Body(..., embed=True)):
    """Girilen alan adı/IP için anında traceroute (sonuç kaydedilir ve Traceroute sekmesinde görünür)."""
    try:
        host, _ = wp.normalize_target(target)
    except ValueError as e:
        raise HTTPException(400, str(e))
    probes.STOP.clear()
    bindings = resolve_bindings("auto" if ni.IS_WINDOWS else None)["bindings"] or [probes.Binding(None, "unknown")]
    site = next((s for s in config.get("sites", []) if wp.normalize_target(s["target"])[0] == host), None)
    item = {"id": f"site:{site['id']}" if site else f"site:{host}", "name": site["name"] if site else host, "host": host}
    futures = [trace_executor.submit(trace_one, item, b) for b in bindings]
    return {"results": [r for r in (f.result() for f in futures) if r]}


@app.get("/api/data/info")
def data_info():
    return db.data_info()


@app.post("/api/data/clear")
def data_clear(payload: Dict[str, Any] = Body(...)):
    """Geçmiş ölçümleri siler. Silmeden önce veritabanının yedeği alınır (backups/ klasörü, son 5 yedek)."""
    tables = [t for t in payload.get("tables") or list(db.DATA_TABLES) if t in db.DATA_TABLES]
    days = payload.get("older_than_days")
    days = int(days) if days not in (None, "", 0, "0") else None
    if not tables:
        raise HTTPException(400, "Silinecek veri türü seçilmedi")
    backup = db.backup(DATA_DIR / "backups")
    deleted = db.clear(tables, days)
    log_event("clear", "warn", f"Geçmiş veriler temizlendi ({'%d günden eski' % days if days else 'tümü'}; "
              f"{sum(deleted.values())} kayıt). Yedek: {backup.name}")
    if not days:
        config["last_report"] = None
        save_config()
    return {"deleted": deleted, "backup": str(backup), "info": db.data_info()}


EXPORT_HEADERS = {
    "speedtests": {"id": "ID", "timestamp": "Tarih", "server_name": "Sunucu", "download_mbps": "Download (Mbps)",
                   "upload_mbps": "Upload (Mbps)", "ping_ms": "Ping (ms)", "jitter_ms": "Jitter (ms)",
                   "packet_loss": "Paket Kaybı (%)", "engine": "Motor", "iface_type": "Bağlantı Türü",
                   "iface_name": "Arayüz", "wifi_rssi": "Wi-Fi RSSI (dBm)", "isp": "ISS", "result_url": "Sonuç Linki"},
    "pings": {"id": "ID", "timestamp": "Tarih", "target_name": "Hedef", "host": "IP / Host", "avg_ping": "Ort. Ping (ms)",
              "max_ping": "Max Ping (ms)", "jitter": "Jitter (ms)", "packet_loss": "Paket Kaybı (%)",
              "min_ping": "Min Ping (ms)", "target_id": "Hedef ID", "iface_type": "Bağlantı Türü",
              "iface_name": "Arayüz", "wifi_rssi": "Wi-Fi RSSI (dBm)"},
    "traceroutes": {"id": "ID", "timestamp": "Tarih", "target_name": "Hedef", "host": "IP / Host",
                    "output": "Traceroute Çıktısı", "target_id": "Hedef ID", "iface_type": "Bağlantı Türü",
                    "iface_name": "Arayüz", "bound": "Arayüze Bağlı"},
    "wifi_samples": {"id": "ID", "timestamp": "Tarih", "iface_name": "Arayüz", "ssid": "SSID", "bssid": "BSSID",
                     "rssi_dbm": "RSSI (dBm)", "noise_dbm": "Gürültü (dBm)", "signal_pct": "Sinyal (%)",
                     "channel": "Kanal", "band": "Bant", "width_mhz": "Genişlik (MHz)", "phy": "PHY",
                     "tx_rate": "TX Hızı (Mbps)", "rx_rate": "RX Hızı (Mbps)"},
    "site_checks": {"id": "ID", "timestamp": "Tarih", "site_id": "Site", "host": "Alan adı", "url": "URL",
                    "iface_type": "Bağlantı Türü", "iface_name": "Arayüz", "ip": "IP", "dns_ms": "DNS (ms)",
                    "tcp_ms": "TCP (ms)", "tls_ms": "TLS (ms)", "ttfb_ms": "İlk bayt (ms)", "total_ms": "Toplam (ms)",
                    "status": "HTTP", "ok": "Başarılı", "bytes": "Bayt", "server": "Sunucu", "cdn": "CDN",
                    "asn": "ASN", "as_name": "AS adı", "ptr": "PTR", "dns_mismatch": "DNS farkı", "error": "Hata"},
    "cdn_checks": {"id": "ID", "timestamp": "Tarih", "service": "Servis", "label": "Ad", "host": "Sunucu",
                   "kind": "Tür", "ip": "IP", "iface_type": "Bağlantı Türü", "iface_name": "Arayüz", "asn": "ASN",
                   "as_name": "AS adı", "ptr": "PTR", "where_": "Konum", "local": "ISS içi", "cluster": "Küme",
                   "dns_ms": "DNS (ms)", "ping_ms": "Ping (ms)", "ping_loss": "Kayıp (%)", "jitter": "Jitter (ms)",
                   "tcp_ms": "TCP (ms)", "tls_ms": "TLS (ms)", "ttfb_ms": "İlk bayt (ms)", "mbps": "Hız (Mbps)",
                   "status": "HTTP", "error": "Hata", "note": "Not"},
    "link_events": {"id": "ID", "timestamp": "Tarih", "iface_name": "Arayüz", "iface_type": "Tür", "kind": "Olay",
                    "severity": "Önem", "message": "Açıklama"},
}
SHEET_NAMES = {"speedtests": "Hız Testleri", "pings": "Ping ve Jitter", "traceroutes": "Traceroute",
               "site_checks": "Site Testleri", "cdn_checks": "CDN Önbellek",
               "wifi_samples": "Wi-Fi Sinyal", "link_events": "Bağlantı Olayları"}


@app.get("/api/export/csv")
def export_csv(range: str = "all", start: Optional[str] = None, end: Optional[str] = None):
    win = _win(range, start, end)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    for table in ("speedtests", "pings", "site_checks", "cdn_checks", "wifi_samples", "link_events"):
        cols, rows = db.export_rows(table, win)
        w.writerow([f"--- {SHEET_NAMES[table].upper()} ---"])
        w.writerow([EXPORT_HEADERS[table].get(c, c) for c in cols])
        w.writerows([list(r) for r in rows])
        w.writerow([])
    fn = f"netmonitor_rapor_{datetime.now():%Y%m%d_%H%M}.csv"
    return StreamingResponse(iter([out.getvalue().encode("utf-8-sig")]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={fn}"})


@app.get("/api/export/excel")
def export_excel(range: str = "all", start: Optional[str] = None, end: Optional[str] = None):
    win = _win(range, start, end)
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")

    def style(ws):
        for cell in ws[1]:
            cell.font, cell.fill = head_font, head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for idx, col in enumerate(ws.columns, 1):
            width = max((min(len(str(c.value or "")), 60) for c in list(col)[:500]), default=8)
            ws.column_dimensions[get_column_letter(idx)].width = width + 3

    # Özet sayfası
    ws = wb.active
    ws.title = "Özet"
    ws.append(["Hedef", "Bağlantı", "Ölçüm", "Ort. Ping", "P95", "Min", "Max", "Jitter", "Ort. Kayıp (%)", "Erişilebilirlik (%)", "Kesinti"])
    names = {t["id"]: t["name"] for t in config["targets"]}
    for s in db.ping_stats(win, "all"):
        ws.append([names.get(s["target_id"], s["target_id"]), type_label(s["iface_type"]), s["n"], s["avg"], s["p95"],
                   s["min"], s["max"], s["jitter"], s["loss"], s["uptime"], s["outages"]])
    style(ws)

    for table in ("speedtests", "pings", "site_checks", "cdn_checks", "traceroutes", "wifi_samples", "link_events"):
        cols, rows = db.export_rows(table, win)
        sh = wb.create_sheet(SHEET_NAMES[table])
        sh.append([EXPORT_HEADERS[table].get(c, c) for c in cols])
        for r in rows:
            sh.append([type_label(v) if c == "iface_type" else v for c, v in zip(cols, r)])
        style(sh)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fn = f"netmonitor_rapor_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={fn}"})


@app.exception_handler(Exception)
async def unhandled(request, exc):
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


def startup():
    load_config()
    db.init_db(DB_FILE, config["targets"])
    save_config()
    # İlk arayüz taraması arka planda; zamanlayıcı bitmesini bekler
    JOBS["netinfo"].force = True


startup()


def _port_free(host: str, port: int) -> bool:
    import socket as _s
    with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as t:
        try:
            t.bind((host, port))
            return True
        except OSError:
            return False


def _netmonitor_on(port: int) -> Optional[str]:
    """Portta zaten çalışan bir NetMonitor varsa sürümünü döndürür."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2) as r:
            return json.loads(r.read().decode()).get("meta", {}).get("version") or "?"
    except Exception:
        return None


def pick_port(host: str, port: int, open_browser: bool) -> int:
    """Port doluysa: NetMonitor çalışıyorsa onu açıp çık; değilse sonraki boş portu kullan."""
    if _port_free(host, port):
        return port
    running = _netmonitor_on(port)
    if running:
        if updater.parse_version(running) >= updater.parse_version(VERSION):
            print(f"\n  NetMonitor v{running} zaten çalışıyor → http://localhost:{port}\n")
            if open_browser:
                webbrowser.open(f"http://localhost:{port}")
            sys.exit(0)
        print(f"\n  Eski NetMonitor v{running} {port} portunda çalışıyor. Kapatmak için o Terminal penceresinde Ctrl+C'ye basın.")
    else:
        print(f"\n  {port} portu başka bir program tarafından kullanılıyor.")
    for p in range(port + 1, port + 50):
        if _port_free(host, p):
            print(f"  NetMonitor {p} portunda başlatılıyor.")
            return p
    raise SystemExit("Boş port bulunamadı; --port ile başka bir port deneyin.")


def main():
    parser = argparse.ArgumentParser(description="NetMonitor — Ağ Kalitesi İzleme")
    parser.add_argument("--lan", action="store_true", help="Yerel ağdaki diğer cihazlardan erişime izin ver (0.0.0.0)")
    parser.add_argument("--host", default=os.environ.get("NETMON_HOST"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NETMON_PORT", 8000)))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    if os.environ.get("NETMON_RESTART") != "1":
        args.port = pick_port(host, args.port, not args.no_browser)
    url = f"http://localhost:{args.port}"
    print(f"\n  NetMonitor {VERSION}  —  {url}\n  Platform: {ni.SYSTEM}  ·  Veri: {DATA_DIR}\n  Durdurmak için Ctrl+C\n")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # Güncelleme sonrası yeniden başlatmada eski süreç portu bırakana kadar bekle
    import socket as _s
    for _ in range(30):
        with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as t:
            t.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
            try:
                t.bind((host, args.port))
                break
            except OSError:
                time.sleep(0.5)

    import uvicorn
    uvicorn.run(app, host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
