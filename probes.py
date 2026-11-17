"""
Ölçüm motorları: ping, traceroute ve hız testi (Ookla CLI + Cloudflare).

Her ölçüm isteğe bağlı olarak belirli bir ağ arayüzüne (Wi-Fi / Ethernet)
bağlanabilir. Böylece iki bağlantı aynı anda takılıyken ikisi ayrı ayrı
ölçülüp karşılaştırılabilir.

  Platform   | ping           | traceroute      | Ookla CLI          | Cloudflare
  -----------+----------------+-----------------+--------------------+-------------------
  Windows    | -S <kaynak IP> | (sistem rotası) | --ip=<kaynak IP>   | bind(kaynak IP)
  macOS      | -b <arayüz>    | -i <arayüz>     | --interface=<ad>   | IP_BOUND_IF
  Linux      | -I <arayüz>    | -i <arayüz>     | --interface=<ad>   | SO_BINDTODEVICE/bind
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import socket
import ssl
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from netinfo import IPV4_RE, IS_LINUX, IS_MAC, IS_WINDOWS, OEM_ENCODING, SUBPROCESS_FLAGS


IP_BOUND_IF = 25  # macOS <netinet/in.h>
SO_BINDTODEVICE = getattr(socket, "SO_BINDTODEVICE", 25)


@dataclass
class Binding:
    iface_name: Optional[str]
    iface_type: str  # wifi | ethernet | other | unknown
    src_ip: Optional[str] = None
    gateway: Optional[str] = None
    bound: bool = False  # True ise trafik bu arayüze zorlanır
    wifi_rssi: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        names = {"wifi": "Wi-Fi", "ethernet": "Ethernet", "other": "Diğer", "unknown": "Bilinmiyor"}
        return names.get(self.iface_type, self.iface_type)


# "Tüm testleri durdur" için: çalışan alt süreçler ve iptal sinyali
STOP = threading.Event()
_ACTIVE: "set[subprocess.Popen]" = set()
_ACTIVE_LOCK = threading.Lock()


def _run(cmd: List[str], timeout: float, encoding: Optional[str] = None) -> subprocess.CompletedProcess:
    """subprocess.run benzeri; ancak süreç kaydedilir ki kill_all() ile durdurulabilsin."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding=encoding or OEM_ENCODING, errors="ignore", creationflags=SUBPROCESS_FLAGS)
    with _ACTIVE_LOCK:
        _ACTIVE.add(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err)
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(proc)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def kill_all() -> int:
    """Çalışan tüm ping/traceroute/speedtest süreçlerini sonlandırır."""
    with _ACTIVE_LOCK:
        procs = list(_ACTIVE)
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    return len(procs)


def bound_socket(binding: Optional["Binding"], family=socket.AF_INET, stype=socket.SOCK_STREAM, timeout: float = 10.0) -> socket.socket:
    """Seçilen arayüze (Wi-Fi/Ethernet) bağlı soket oluşturur."""
    s = socket.socket(family, stype)
    s.settimeout(timeout)
    b = binding
    if b and b.bound:
        if IS_MAC and b.iface_name:
            s.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, socket.if_nametoindex(b.iface_name))
        elif IS_LINUX and b.iface_name:
            try:
                s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, b.iface_name.encode() + b"\0")
            except OSError:
                pass
        if b.src_ip and family == socket.AF_INET:
            s.bind((b.src_ip, 0))
    return s


# ---------------------------------------------------------------------------
# PING
# ---------------------------------------------------------------------------

# "time=12.3 ms", "time<1ms", "süre=12ms", "zeit=12ms", "temps=12 ms" ...
PING_TIME_RE = re.compile(r"(?:time|s[üu]re|zaman|zeit|temps|tiempo|tempo|czas|tijd)\s*([=<])\s*([\d]+(?:[.,]\d+)?)\s*ms", re.IGNORECASE)


def build_ping_cmd(host: str, binding: Optional[Binding], count: int, timeout_ms: int) -> List[str]:
    if IS_WINDOWS:
        cmd = ["ping", "-4", "-n", str(count), "-w", str(timeout_ms)]
        if binding and binding.bound and binding.src_ip:
            cmd += ["-S", binding.src_ip]
    elif IS_MAC:
        # macOS'ta -W milisaniyedir (Linux'ta saniye). Orijinal koddaki "-W 1" macOS'ta 1 ms demekti.
        cmd = ["ping", "-n", "-c", str(count), "-W", str(timeout_ms)]
        if binding and binding.bound and binding.iface_name:
            cmd += ["-b", binding.iface_name]
    else:
        cmd = ["ping", "-n", "-c", str(count), "-W", str(max(1, round(timeout_ms / 1000)))]
        if binding and binding.bound and binding.iface_name:
            cmd += ["-I", binding.iface_name]
    return cmd + [host]


def parse_ping_output(output: str, sent: int) -> Dict[str, Any]:
    times = [0.5 if op == "<" else float(t.replace(",", ".")) for op, t in PING_TIME_RE.findall(output)]
    received = min(len(times), sent)
    loss = round((sent - received) * 100.0 / sent, 1) if sent else 100.0
    if times:
        avg = round(sum(times) / len(times), 2)
        mn = round(min(times), 2)
        mx = round(max(times), 2)
        jitter = round(sum(abs(times[i] - times[i - 1]) for i in range(1, len(times))) / (len(times) - 1), 2) if len(times) > 1 else 0.0
    else:
        avg = mn = mx = jitter = None
    return {"avg": avg, "min": mn, "max": mx, "jitter": jitter, "loss": loss, "sent": sent, "received": received, "samples": times}


def run_ping(host: str, binding: Optional[Binding] = None, count: int = 5, timeout_ms: int = 1000) -> Dict[str, Any]:
    cmd = build_ping_cmd(host, binding, count, timeout_ms)
    try:
        res = _run(cmd, timeout=count * (timeout_ms / 1000 + 1) + 5)
        out = res.stdout + "\n" + res.stderr
        r = parse_ping_output(out, count)
        if r["received"] == 0 and res.returncode not in (0, 1, 2):
            r["error"] = (res.stderr or res.stdout).strip()[:200]
        return r
    except FileNotFoundError:
        return {**parse_ping_output("", count), "error": "ping komutu bulunamadı"}
    except subprocess.TimeoutExpired:
        return {**parse_ping_output("", count), "error": "zaman aşımı"}


# ---------------------------------------------------------------------------
# TRACEROUTE
# ---------------------------------------------------------------------------

def build_trace_cmd(host: str, binding: Optional[Binding], max_hops: int = 20) -> Optional[List[str]]:
    if IS_WINDOWS:
        # tracert IPv4 için kaynak adres seçeneği sunmaz → sistem rotası kullanılır
        return ["tracert", "-d", "-4", "-h", str(max_hops), "-w", "800", host]
    exe = shutil.which("traceroute")
    if not exe:
        if IS_LINUX and shutil.which("tracepath"):
            cmd = ["tracepath", "-n", "-m", str(max_hops), host]
            return cmd
        return None
    cmd = [exe, "-n", "-q", "3", "-m", str(max_hops), "-w", "1"]
    if binding and binding.bound and binding.iface_name:
        cmd += ["-i", binding.iface_name]
    return cmd + [host]


HOP_LINE_RE = re.compile(r"^\s*(\d{1,2})[\s:?]+(.*)$")
RTT_RE = re.compile(r"(<?\s*\d+(?:[.,]\d+)?)\s*ms", re.IGNORECASE)


def parse_traceroute(output: str) -> List[Dict[str, Any]]:
    hops: Dict[int, Dict[str, Any]] = {}
    for line in output.splitlines():
        m = HOP_LINE_RE.match(line)
        if not m:
            continue
        n = int(m.group(1))
        rest = m.group(2)
        # Başlık satırlarını atla ("1 hops max" / "over a maximum of 30 hops")
        if re.search(r"hops? max|maximum|en fazla|azami", rest, re.IGNORECASE):
            continue
        ips = IPV4_RE.findall(rest)
        rtts = []
        for r in RTT_RE.findall(rest):
            r = r.replace(" ", "").replace(",", ".")
            rtts.append(0.5 if r.startswith("<") else float(r))
        timeouts = rest.count("*")
        hop = hops.setdefault(n, {"hop": n, "ip": None, "rtts": [], "timeouts": 0})
        if ips and not hop["ip"]:
            hop["ip"] = ips[0]
        hop["rtts"].extend(rtts)
        hop["timeouts"] += timeouts
    result = []
    for n in sorted(hops):
        h = hops[n]
        h["avg"] = round(sum(h["rtts"]) / len(h["rtts"]), 2) if h["rtts"] else None
        h["best"] = round(min(h["rtts"]), 2) if h["rtts"] else None
        h["worst"] = round(max(h["rtts"]), 2) if h["rtts"] else None
        total = len(h["rtts"]) + h["timeouts"]
        h["loss"] = round(h["timeouts"] * 100 / total, 0) if total else 100
        result.append(h)
    return result


def run_traceroute(host: str, binding: Optional[Binding] = None, max_hops: int = 20) -> Dict[str, Any]:
    cmd = build_trace_cmd(host, binding, max_hops)
    if cmd is None:
        return {"output": "traceroute bulunamadı (Linux: sudo apt install traceroute)", "hops": [], "bound": False}
    try:
        res = _run(cmd, timeout=max_hops * 4 + 10)
        out = (res.stdout or "").strip() or (res.stderr or "").strip()
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else "zaman aşımı"
    except FileNotFoundError:
        out = "traceroute bulunamadı"
    bound = bool(binding and binding.bound and not IS_WINDOWS)
    return {"output": out, "hops": parse_traceroute(out), "bound": bound}


# ---------------------------------------------------------------------------
# HIZ TESTİ — Ookla CLI
# ---------------------------------------------------------------------------

def ookla_available() -> bool:
    return shutil.which("speedtest") is not None


def ookla_search(query: str, limit: int = 100) -> List[Dict[str, Any]]:
    """speedtest.net sunucu araması (ör. "Türksat", "Ankara"). Ookla CLI'nin --server-id ile kullanılır."""
    import urllib.parse
    import urllib.request
    url = ("https://www.speedtest.net/api/js/servers?engine=js&https_functional=true&limit=%d&search=%s"
           % (limit, urllib.parse.quote(query)))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NetMonitor", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    out = []
    for s in data if isinstance(data, list) else []:
        out.append({
            "id": str(s.get("id")), "name": s.get("sponsor") or s.get("name"), "location": s.get("name"),
            "country": s.get("country"), "host": s.get("host"),
            "distance": round(float(s.get("distance") or 0)),
        })
    return out


def ookla_cli_servers() -> List[Dict[str, Any]]:
    """Ookla CLI'nin önerdiği en yakın sunucular."""
    try:
        res = _run(["speedtest", "--servers", "--format=json", "--accept-license", "--accept-gdpr"], timeout=25, encoding="utf-8")
        data = json.loads(res.stdout)
        return [{"id": str(s["id"]), "name": s["name"], "location": s.get("location", ""),
                 "country": s.get("country", ""), "host": s.get("host"), "distance": round(s.get("distance", 0))}
                for s in data.get("servers", [])]
    except Exception:
        return []


def run_ookla(binding: Optional[Binding], server_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    cmd = ["speedtest", "--format=json", "--accept-license", "--accept-gdpr", "--progress=no"]
    if server_id and server_id not in ("auto", "cloudflare"):
        cmd += ["--server-id", str(server_id)]
    if binding and binding.bound:
        if IS_WINDOWS and binding.src_ip:
            cmd += ["--ip", binding.src_ip]
        elif binding.iface_name:
            cmd += ["--interface", binding.iface_name]
    try:
        res = _run(cmd, timeout=150, encoding="utf-8")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode != 0 or not res.stdout.strip():
        return None
    # Ookla bazen satır satır JSON loglar basar; son "result" nesnesini al
    data = None
    for line in res.stdout.strip().splitlines()[::-1]:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") == "result" or "download" in obj:
            data = obj
            break
    if not data:
        return None
    srv = data.get("server", {})
    return {
        "engine": "ookla",
        "server": f"{srv.get('name', '?')} ({srv.get('location', '?')})",
        "server_id": str(srv.get("id", "")),
        "dl": round(data["download"]["bandwidth"] * 8 / 1_000_000, 2),
        "ul": round(data["upload"]["bandwidth"] * 8 / 1_000_000, 2),
        "ping": round(data["ping"]["latency"], 2),
        "jitter": round(data["ping"].get("jitter", 0), 2),
        "loss": round(data["packetLoss"], 2) if data.get("packetLoss") is not None else None,
        "isp": data.get("isp"),
        "result_url": (data.get("result") or {}).get("url"),
    }


# ---------------------------------------------------------------------------
# HIZ TESTİ — Cloudflare (kotasız, arayüze bağlanabilir)
# ---------------------------------------------------------------------------

CF_HOST = "speed.cloudflare.com"


class BoundHTTPSConnection(http.client.HTTPSConnection):
    """Kaynak IP / arayüz bağlamalı HTTPS bağlantısı."""

    def __init__(self, host: str, binding: Optional[Binding] = None, timeout: float = 15):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.binding = binding

    def connect(self):
        b = self.binding
        last_err: Optional[Exception] = None
        for af, st, proto, _, sa in socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM):
            s = bound_socket(b, af, st, self.timeout)
            try:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.connect(sa)
                self.sock = self._context.wrap_socket(s, server_hostname=self.host)  # type: ignore[attr-defined]
                return
            except Exception as e:
                last_err = e
                s.close()
        raise last_err or OSError("bağlantı kurulamadı")


def _cf_headers():
    return {"User-Agent": "NetMonitor/2.0", "Accept-Encoding": "identity", "Connection": "keep-alive"}


def _server_timing(resp) -> float:
    st = resp.getheader("Server-Timing") or ""
    m = re.search(r"dur=([\d.]+)", st)
    return float(m.group(1)) if m else 0.0


def cf_latency(binding: Optional[Binding], samples: int = 12) -> Dict[str, Any]:
    conn = BoundHTTPSConnection(CF_HOST, binding, timeout=10)
    lat = []
    try:
        for i in range(samples + 1):
            t0 = time.perf_counter()
            conn.request("GET", "/__down?bytes=0", headers=_cf_headers())
            resp = conn.getresponse()
            resp.read()
            dt = (time.perf_counter() - t0) * 1000 - _server_timing(resp)
            if i > 0:  # ilk istek TCP+TLS el sıkışmasını içerir
                lat.append(max(0.1, dt))
    finally:
        conn.close()
    ping = round(statistics.median(lat), 2)
    jitter = round(sum(abs(lat[i] - lat[i - 1]) for i in range(1, len(lat))) / (len(lat) - 1), 2)
    return {"ping": ping, "jitter": jitter, "samples": lat}


def _cf_transfer(binding: Optional[Binding], direction: str, streams: int, max_bytes: int, max_seconds: float) -> float:
    total = [0]
    first_byte = [None]
    lock = threading.Lock()
    stop = threading.Event()
    deadline = time.perf_counter() + max_seconds
    per_stream = max(1_000_000, max_bytes // streams)
    chunk = b"0" * 65536
    errors: List[Exception] = []

    def add(n):
        with lock:
            if first_byte[0] is None:
                first_byte[0] = time.perf_counter()
            total[0] += n
            if total[0] >= max_bytes:
                stop.set()

    def worker():
        try:
            conn = BoundHTTPSConnection(CF_HOST, binding, timeout=15)
            try:
                while not stop.is_set() and not STOP.is_set() and time.perf_counter() < deadline:
                    if direction == "down":
                        conn.request("GET", f"/__down?bytes={per_stream}", headers=_cf_headers())
                        resp = conn.getresponse()
                        while not stop.is_set() and not STOP.is_set() and time.perf_counter() < deadline:
                            data = resp.read(65536)
                            if not data:
                                break
                            add(len(data))
                        if stop.is_set() or time.perf_counter() >= deadline:
                            break
                    else:
                        size = per_stream
                        conn.putrequest("POST", "/__up", skip_accept_encoding=True)
                        for k, v in _cf_headers().items():
                            conn.putheader(k, v)
                        conn.putheader("Content-Type", "application/octet-stream")
                        conn.putheader("Content-Length", str(size))
                        conn.endheaders()
                        sent = 0
                        while sent < size:
                            n = min(len(chunk), size - sent)
                            conn.send(chunk[:n])
                            sent += n
                            add(n)
                            if time.perf_counter() >= deadline or STOP.is_set():
                                break
                        if sent < size:
                            break
                        conn.getresponse().read()
            finally:
                conn.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(streams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max_seconds + 20)
    stop.set()
    end = time.perf_counter()
    if not total[0] or first_byte[0] is None:
        raise errors[0] if errors else RuntimeError("veri aktarılamadı")
    duration = max(0.05, end - first_byte[0])
    return round(total[0] * 8 / duration / 1_000_000, 2)


def run_cloudflare(binding: Optional[Binding], max_mb: int = 100, seconds: float = 8.0, streams: int = 4) -> Optional[Dict[str, Any]]:
    try:
        lat = cf_latency(binding)
        dl = _cf_transfer(binding, "down", streams, max_mb * 1_000_000, seconds)
        ul = _cf_transfer(binding, "up", max(2, streams // 2), max(10, max_mb // 3) * 1_000_000, seconds)
        return {
            "engine": "cloudflare",
            "server": "Cloudflare Edge",
            "dl": dl,
            "ul": ul,
            "ping": lat["ping"],
            "jitter": lat["jitter"],
            "loss": None,
        }
    except Exception as e:
        return {"error": f"Cloudflare hız testi başarısız: {e}"}


def run_speedtest(binding: Optional[Binding], engine: str = "auto", server_id: str = "auto",
                  cf_max_mb: int = 100) -> Dict[str, Any]:
    """engine: auto (önce Ookla, olmazsa Cloudflare) | ookla | cloudflare"""
    errors = []
    if engine in ("auto", "ookla") and server_id != "cloudflare":
        r = run_ookla(binding, server_id)
        if r:
            return r
        errors.append("Ookla CLI çalışmadı veya kurulu değil")
        if engine == "ookla":
            return {"error": errors[0]}
    r = run_cloudflare(binding, max_mb=cf_max_mb)
    if r and "error" not in r:
        return r
    errors.append((r or {}).get("error", "Cloudflare başarısız"))
    return {"error": " / ".join(errors)}
