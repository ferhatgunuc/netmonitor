"""
Site ve CDN (önbellek) ölçümleri.

  * DNS çözümleme: işletim sistemi, ISS DNS'i (sistemde tanımlı sunucu, önbelleksiz), Google, Cloudflare
  * HTTP(S) zamanlaması: DNS → TCP bağlantı → TLS el sıkışma → ilk bayt (TTFB) → toplam
  * IP sahibi (ASN) ve ters DNS (PTR) — Team Cymru DNS servisi ile
  * Bağlantının kendi ISS bilgisi (Cloudflare /meta)
  * YouTube (Google Global Cache), Facebook / Instagram (Meta FNA) önbellek sunucusu keşfi

Tüm ölçümler seçili arayüze (Wi-Fi / Ethernet) bağlanabilir.
"""

from __future__ import annotations

import html
import json
import re
import socket
import ssl
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from probes import Binding, bound_socket

try:
    import dns.exception  # type: ignore
    import dns.resolver  # type: ignore
    import dns.reversename  # type: ignore
    HAVE_DNSPY = True
except Exception:  # dnspython yoksa yalnızca sistem çözümleyicisi kullanılır
    HAVE_DNSPY = False

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

PUBLIC_RESOLVERS = {"google": ("Google DNS", "8.8.8.8"), "cloudflare": ("Cloudflare DNS", "1.1.1.1")}
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$")

# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def normalize_target(text: str) -> Tuple[str, str]:
    """'youtube.com', 'https://www.x.com/yol' gibi girdileri (alan_adı, url) çiftine çevirir."""
    t = (text or "").strip()
    if not t:
        raise ValueError("boş adres")
    if "://" not in t:
        t = "https://" + t
    parts = urlsplit(t)
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or not (DOMAIN_RE.match(host) or _is_ip(host)):
        raise ValueError(f"geçersiz alan adı: {text}")
    if parts.scheme not in ("http", "https"):
        raise ValueError("yalnızca http/https desteklenir")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    port = f":{parts.port}" if parts.port else ""
    return host, f"{parts.scheme}://{host}{port}{path}"


def _is_ip(s: str) -> bool:
    try:
        socket.inet_aton(s)
        return s.count(".") == 3
    except OSError:
        return False


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------


def resolve_system(host: str) -> Dict[str, Any]:
    """İşletim sisteminin çözümleyicisi (uygulamaların gördüğü yol; OS önbelleği dahil)."""
    t0 = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        ips = list(dict.fromkeys(i[4][0] for i in infos))
        return {"ips": ips, "ms": _ms(t0), "error": None}
    except socket.gaierror as e:
        return {"ips": [], "ms": _ms(t0), "error": f"çözümlenemedi ({e.strerror or e})"}


def resolve_with(host: str, nameserver: Optional[str], timeout: float = 3.0) -> Dict[str, Any]:
    """dnspython ile tek bir DNS sunucusuna doğrudan sorgu (önbelleksiz). nameserver=None → sistemdeki DNS."""
    if not HAVE_DNSPY:
        return {"ips": [], "ms": None, "error": "dnspython kurulu değil", "server": nameserver}
    try:
        r = dns.resolver.Resolver(configure=nameserver is None)
    except Exception as e:
        return {"ips": [], "ms": None, "error": f"DNS ayarı okunamadı: {e}", "server": None}
    if nameserver:
        r.nameservers = [nameserver]
    r.lifetime = timeout
    r.cache = None
    server = r.nameservers[0] if r.nameservers else None
    t0 = time.perf_counter()
    try:
        ans = r.resolve(host, "A")
        ips = [a.address for a in ans]
        cname = str(ans.canonical_name).rstrip(".")
        return {"ips": ips, "ms": _ms(t0), "error": None, "server": str(server),
                "cname": cname if cname != host else None, "ttl": ans.rrset.ttl if ans.rrset else None}
    except dns.resolver.NXDOMAIN:
        return {"ips": [], "ms": _ms(t0), "error": "alan adı yok (NXDOMAIN)", "server": str(server)}
    except dns.exception.Timeout:
        return {"ips": [], "ms": _ms(t0), "error": "zaman aşımı", "server": str(server)}
    except Exception as e:
        return {"ips": [], "ms": _ms(t0), "error": str(e)[:120], "server": str(server)}


def resolve_all(host: str) -> Dict[str, Any]:
    """Alan adını otomatik olarak dört yoldan çözümler ve sonuçları karşılaştırır."""
    if _is_ip(host):
        return {"system": {"ips": [host], "ms": 0, "error": None}}
    out: Dict[str, Any] = {}
    threads = []

    def run(key, fn, *args):
        out[key] = fn(*args)

    threads.append(threading.Thread(target=run, args=("system", resolve_system, host)))
    threads.append(threading.Thread(target=run, args=("isp", resolve_with, host, None)))
    for key, (_, ip) in PUBLIC_RESOLVERS.items():
        threads.append(threading.Thread(target=run, args=(key, resolve_with, host, ip)))
    for t in threads:
        t.start()
    for t in threads:
        t.join(8)
    return out


_asn_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_asname_cache: Dict[int, str] = {}


def _txt(name: str) -> Optional[str]:
    if not HAVE_DNSPY:
        return None
    try:
        r = dns.resolver.Resolver()
        r.lifetime = 3
        ans = r.resolve(name, "TXT")
        return b"".join(ans[0].strings).decode("utf-8", "ignore")
    except Exception:
        return None


def ip_info(ip: str) -> Dict[str, Any]:
    """IP → ASN, AS adı, prefix, ülke, PTR (1 saat önbellek)."""
    now = time.time()
    hit = _asn_cache.get(ip)
    if hit and now - hit[0] < 3600:
        return hit[1]
    info: Dict[str, Any] = {"asn": None, "as_name": None, "prefix": None, "country": None, "ptr": None}
    if _is_ip(ip):
        rev = ".".join(reversed(ip.split(".")))
        txt = _txt(f"{rev}.origin.asn.cymru.com")
        if txt:
            parts = [p.strip() for p in txt.split("|")]
            try:
                info["asn"] = int(parts[0].split()[0])
            except (ValueError, IndexError):
                pass
            info["prefix"] = parts[1] if len(parts) > 1 else None
            info["country"] = parts[2] if len(parts) > 2 else None
        if info["asn"]:
            name = _asname_cache.get(info["asn"])
            if name is None:
                t = _txt(f"AS{info['asn']}.asn.cymru.com")
                name = t.split("|")[-1].strip() if t else ""
                _asname_cache[info["asn"]] = name
            info["as_name"] = name or None
        info["ptr"] = reverse_dns(ip)
    _asn_cache[ip] = (now, info)
    return info


def reverse_dns(ip: str) -> Optional[str]:
    if HAVE_DNSPY:
        try:
            r = dns.resolver.Resolver()
            r.lifetime = 2.5
            ans = r.resolve(dns.reversename.from_address(ip), "PTR")
            return str(ans[0]).rstrip(".")
        except Exception:
            return None
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTTP zamanlaması
# ---------------------------------------------------------------------------


def detect_cdn(headers: Dict[str, str]) -> Optional[str]:
    h = {k.lower(): v for k, v in headers.items()}
    server = h.get("server", "").lower()
    if "cf-ray" in h or server == "cloudflare":
        return "Cloudflare"
    if "x-amz-cf-id" in h or "cloudfront" in h.get("via", "").lower():
        return "Amazon CloudFront"
    if "x-akamai-transformed" in h or "akamai" in server or "akamaighost" in server:
        return "Akamai"
    if "x-fastly-request-id" in h or h.get("x-served-by", "").lower().startswith("cache-") or "fastly" in h.get("x-served-by", "").lower() or "varnish" in h.get("via", "").lower():
        return "Fastly"
    if "x-fb-debug" in h or "proxygen" in server or "x-fb-trip-id" in h:
        return "Meta"
    if server in ("gws", "esf", "gse", "sffe", "ghs") or "google" in server or "x-goog-" in " ".join(h):
        return "Google"
    if "x-azure-ref" in h or "x-msedge-ref" in h:
        return "Azure Front Door"
    if "x-cdn" in h:
        return h["x-cdn"]
    return None


def http_timing(url: str, binding: Optional[Binding] = None, connect_ip: Optional[str] = None,
                max_bytes: int = 256 * 1024, timeout: float = 10.0, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Tek bir HTTP(S) isteğinin aşama aşama süresini ölçer (yönlendirme takip edilmez)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    https = parts.scheme == "https"
    port = parts.port or (443 if https else 80)
    path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    res: Dict[str, Any] = {"url": url, "ip": None, "dns_ms": None, "tcp_ms": None, "tls_ms": None, "ttfb_ms": None,
                           "total_ms": None, "status": None, "bytes": 0, "mbps": None, "server": None, "cdn": None,
                           "headers": {}, "error": None, "tls_version": None}
    t_start = time.perf_counter()
    sock = None
    try:
        if connect_ip:
            ip = connect_ip
        else:
            t0 = time.perf_counter()
            infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            res["dns_ms"] = _ms(t0)
            ip = infos[0][4][0]
        res["ip"] = ip
        sock = bound_socket(binding, socket.AF_INET, socket.SOCK_STREAM, timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        t0 = time.perf_counter()
        sock.connect((ip, port))
        res["tcp_ms"] = _ms(t0)
        if https:
            ctx = ssl.create_default_context()
            ctx.set_alpn_protocols(["http/1.1"])
            t0 = time.perf_counter()
            sock = ctx.wrap_socket(sock, server_hostname=host)
            res["tls_ms"] = _ms(t0)
            res["tls_version"] = sock.version()
        hdrs = {"Host": host if parts.port in (None, 80, 443) else f"{host}:{port}", "User-Agent": UA,
                "Accept": "*/*", "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8", "Accept-Encoding": "identity",
                "Connection": "close"}
        hdrs.update(extra_headers or {})
        req = f"GET {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hdrs.items()) + "\r\n"
        t_req = time.perf_counter()
        sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            if not buf:
                res["ttfb_ms"] = _ms(t_req)
            buf += chunk
            if len(buf) > 256 * 1024:
                break
        head, _, body = buf.partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1", "ignore").split("\r\n")
        m = re.match(r"HTTP/\d(?:\.\d)?\s+(\d{3})", lines[0] if lines else "")
        res["status"] = int(m.group(1)) if m else None
        headers: Dict[str, str] = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip()] = v.strip()
        res["headers"] = headers
        res["server"] = headers.get("Server") or headers.get("server")
        res["cdn"] = detect_cdn(headers)
        total = len(body)
        t_body = time.perf_counter()
        while total < max_bytes:
            chunk = sock.recv(65536)
            if not chunk:
                break
            body += chunk if len(body) < 3_000_000 else b""
            total += len(chunk)
        body_s = time.perf_counter() - t_body
        res["bytes"] = total
        if total > 64 * 1024 and body_s > 0.02:
            res["mbps"] = round(total * 8 / body_s / 1e6, 2)
        res["_body"] = body
    except socket.gaierror as e:
        res["error"] = f"DNS: {e.strerror or e}"
    except socket.timeout:
        res["error"] = "zaman aşımı"
    except ssl.SSLError as e:
        res["error"] = f"TLS: {e.reason or e}"
    except OSError as e:
        res["error"] = f"{e.strerror or e}"
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass
    res["total_ms"] = _ms(t_start)
    return res


def http_get_text(url: str, binding: Optional[Binding] = None, max_bytes: int = 3_000_000,
                  headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[int], str, Dict[str, str]]:
    r = http_timing(url, binding, max_bytes=max_bytes, timeout=12, extra_headers=headers)
    body = r.pop("_body", b"") or b""
    if r["headers"].get("Transfer-Encoding", "").lower() == "chunked":
        body = _dechunk(body)
    return r["status"], body.decode("utf-8", "ignore"), r["headers"]


def _dechunk(data: bytes) -> bytes:
    out, i = b"", 0
    while i < len(data):
        j = data.find(b"\r\n", i)
        if j < 0:
            break
        try:
            n = int(data[i:j].split(b";")[0], 16)
        except ValueError:
            return data
        if n == 0:
            break
        out += data[j + 2:j + 2 + n]
        i = j + 2 + n + 2
    return out


# ---------------------------------------------------------------------------
# Bağlantının kendi ISS bilgisi
# ---------------------------------------------------------------------------

_client_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def client_info(binding: Optional[Binding] = None) -> Dict[str, Any]:
    key = (binding.iface_name if binding else None) or "default"
    hit = _client_cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    info: Dict[str, Any] = {}
    try:
        status, text, _ = http_get_text("https://speed.cloudflare.com/meta", binding, max_bytes=20000)
        if status == 200:
            d = json.loads(text)
            info = {"ip": d.get("clientIp"), "asn": d.get("asn"), "as_name": d.get("asOrganization"),
                    "city": d.get("city"), "country": d.get("country"), "colo": d.get("colo")}
    except Exception:
        info = {}
    if info:
        _client_cache[key] = (time.time(), info)
    return info


# ---------------------------------------------------------------------------
# Site testi
# ---------------------------------------------------------------------------


def site_check(target: str, binding: Optional[Binding] = None, with_resolvers: bool = True) -> Dict[str, Any]:
    host, url = normalize_target(target)
    dns_all = resolve_all(host) if with_resolvers else {"system": resolve_system(host)}
    sys_ips = (dns_all.get("system") or {}).get("ips") or []
    ip = sys_ips[0] if sys_ips else None
    r = http_timing(url, binding, connect_ip=ip, max_bytes=512 * 1024) if ip else {
        "error": (dns_all.get("system") or {}).get("error") or "çözümlenemedi"}
    r.pop("_body", None)
    r["dns_ms"] = (dns_all.get("system") or {}).get("ms")
    r["host"] = host
    r["dns"] = dns_all
    r["ok"] = bool(r.get("status") and r["status"] < 500 and not r.get("error"))
    if ip:
        r.update({k: v for k, v in ip_info(ip).items() if k in ("asn", "as_name", "ptr")})
    # Farklı DNS sunucuları farklı IP döndürüyorsa (CDN yönlendirmesi / DNS sorunu) belirt
    sets = {k: tuple(sorted(v.get("ips") or [])) for k, v in dns_all.items() if v.get("ips")}
    r["dns_mismatch"] = len(set(sets.values())) > 1
    return r


# ---------------------------------------------------------------------------
# CDN / önbellek (GGC, FNA) keşfi
# ---------------------------------------------------------------------------

YT_PROBE_VIDEOS = ["jNQXAC9IVRw", "dQw4w9WgXcQ"]
GGC_HOST_RE = re.compile(r"(r{1,2}\d{1,2}---sn-[a-z0-9-]{4,40}\.googlevideo\.com)")
META_URL_RE = re.compile(r"https?:(?:\\?/){2}(scontent[a-z0-9.\-]*\.(?:fbcdn\.net|cdninstagram\.com))((?:\\?/)[^\"'\s<>]*)?", re.I)

CDN_SERVICES = {
    "youtube": {"name": "YouTube", "operator": "Google Global Cache (GGC)"},
    "facebook": {"name": "Facebook", "operator": "Meta FNA"},
    "instagram": {"name": "Instagram", "operator": "Meta FNA"},
}
GOOGLE_ASNS = {15169: "Google", 36040: "Google Global Cache", 36492: "Google", 396982: "Google Cloud"}
META_ASNS = {32934: "Meta", 63293: "Meta"}


def discover_youtube(binding: Optional[Binding]) -> Dict[str, Any]:
    found: List[Dict[str, Any]] = []
    note = None
    cluster = None
    try:
        status, text, _ = http_get_text("https://redirector.googlevideo.com/report_mapping?di=no", binding, 20000)
        m = re.search(r"=>\s*([a-z0-9\-]+)", text)
        cluster = m.group(1) if m else None
    except Exception:
        pass
    for vid in YT_PROBE_VIDEOS:
        try:
            status, text, _ = http_get_text(f"https://www.youtube.com/watch?v={vid}&hl=tr", binding, 4_000_000,
                                            {"Cookie": "CONSENT=YES+cb; SOCS=CAI"})
        except Exception:
            continue
        hosts = list(dict.fromkeys(GGC_HOST_RE.findall(text.replace("\\u002d", "-").replace("\\/", "/"))))
        for h in hosts[:3]:
            found.append({"host": h, "url": f"https://{h}/generate_204", "kind": "video"})
        if found:
            break
    if not found:
        note = "Video sunucusu otomatik bulunamadı; YouTube ön yüz sunucuları ölçüldü"
        found = [{"host": "www.youtube.com", "url": "https://www.youtube.com/generate_204", "kind": "edge"},
                 {"host": "i.ytimg.com", "url": "https://i.ytimg.com/generate_204", "kind": "edge"}]
    return {"targets": found, "cluster": cluster, "note": note}


def discover_meta(service: str, binding: Optional[Binding]) -> Dict[str, Any]:
    page = "https://www.facebook.com/facebook" if service == "facebook" else "https://www.instagram.com/instagram/"
    found: Dict[str, Dict[str, Any]] = {}
    note = None
    try:
        status, text, _ = http_get_text(page, binding, 3_000_000)
        text = html.unescape(text)
        for host, path in META_URL_RE.findall(text):
            path = (path or "/").replace("\\/", "/").replace("\\u0025", "%").replace("\\u0026", "&")
            if host not in found:
                found[host] = {"host": host, "url": f"https://{host}{path}", "kind": "media"}
    except Exception:
        pass
    targets = list(found.values())
    # Yerel FNA (ör. scontent.fist4-1.fna.fbcdn.net) varsa öne al
    targets.sort(key=lambda t: (".fna." not in t["host"], t["host"]))
    if not targets:
        note = "Önbellek sunucusu otomatik bulunamadı; genel Meta uç sunucusu ölçüldü"
        h = "scontent.xx.fbcdn.net" if service == "facebook" else "scontent.cdninstagram.com"
        targets = [{"host": h, "url": f"https://{h}/", "kind": "edge"}]
    return {"targets": targets[:2], "cluster": None, "note": note}


def classify_node(info: Dict[str, Any], client: Dict[str, Any], host: str) -> Tuple[str, bool]:
    asn = info.get("asn")
    ptr = (info.get("ptr") or "").lower()
    if asn and client.get("asn") and asn == client.get("asn"):
        return "ISS içi önbellek (yerel)", True
    if asn == 36040 or "cache.google.com" in ptr:
        return "Google Global Cache", asn == client.get("asn")
    if ".fna." in host or ".fna." in ptr:
        return "Meta FNA önbelleği", False
    if asn in GOOGLE_ASNS:
        return f"{GOOGLE_ASNS[asn]} ağı (ISS dışı)", False
    if asn in META_ASNS:
        return "Meta ağı (ISS dışı)", False
    return (info.get("as_name") or "Bilinmeyen ağ"), False


def cdn_measure(service: str, label: str, target: Dict[str, Any], binding: Optional[Binding],
                client: Dict[str, Any], ping_fn) -> Dict[str, Any]:
    host = target["host"]
    res = resolve_system(host) if not _is_ip(host) else {"ips": [host], "ms": 0, "error": None}
    out: Dict[str, Any] = {"service": service, "label": label, "host": host, "kind": target.get("kind"),
                           "dns_ms": res.get("ms"), "error": res.get("error")}
    if not res["ips"]:
        return out
    ip = res["ips"][0]
    info = ip_info(ip)
    where, local = classify_node(info, client, host)
    out.update({"ip": ip, "asn": info.get("asn"), "as_name": info.get("as_name"), "ptr": info.get("ptr"),
                "where": where, "local": local})
    p = ping_fn(ip)
    out.update({"ping_ms": p.get("avg"), "ping_loss": p.get("loss"), "jitter": p.get("jitter")})
    url = target.get("url") or f"https://{host}/"
    h = http_timing(url, binding, connect_ip=ip, max_bytes=8 * 1024 * 1024 if target.get("kind") == "media" else 64 * 1024)
    h.pop("_body", None)
    out.update({k: h.get(k) for k in ("tcp_ms", "tls_ms", "ttfb_ms", "status", "mbps", "bytes")})
    if h.get("error"):
        out["error"] = h["error"]
    return out
