"""
Ağ arayüzü algılama katmanı (Windows / macOS / Linux).

Her platform için şunları toplar:
  * Fiziksel arayüzler ve türleri (wifi / ethernet / other)
  * IPv4 adresi, MAC, durum, link hızı, MTU
  * Arayüz bazlı varsayılan ağ geçidi (gateway) ve sistemin varsayılan arayüzü
  * Wi-Fi detayları: SSID, BSSID, RSSI (dBm), gürültü, sinyal %, kanal, bant,
    kanal genişliği, PHY modu, iletim/alma hızı, güvenlik

Komut çıktıları dil bağımsız olacak şekilde ayrıştırılır (Türkçe ve İngilizce
Windows çıktıları desteklenir). Ağır komutlar (PowerShell, system_profiler)
yalnızca arka plan iş parçacığından çağrılır; API her zaman önbelleği okur.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import psutil  # type: ignore
except Exception:  # psutil yoksa da çalışmaya devam et
    psutil = None

SYSTEM = platform.system().lower()
IS_WINDOWS = SYSTEM == "windows"
IS_MAC = SYSTEM == "darwin"
IS_LINUX = SYSTEM == "linux"

SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0  # type: ignore[attr-defined]
OEM_ENCODING = "cp857" if IS_WINDOWS else "utf-8"

IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Sanal / tünel arayüzlerini ayıklamak için isim kalıpları
VIRTUAL_PATTERNS = re.compile(
    r"(loopback|^lo\d*$|vethernet|hyper-v|virtualbox|vmware|vmnet|vbox|docker|br-|veth|"
    r"virbr|utun|awdl|llw|gif|stf|anpi|ap\d|bridge|tailscale|zerotier|wireguard|wg\d|tun|tap|"
    r"teredo|isatap|6to4|pseudo|npcap|wan miniport|bluetooth|hamachi|wsl|virtual|wi-fi direct)",
    re.IGNORECASE,
)


def run_cmd(cmd: List[str], timeout: float = 10.0, encoding: Optional[str] = None) -> str:
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding=encoding or OEM_ENCODING,
            errors="ignore",
            timeout=timeout,
            creationflags=SUBPROCESS_FLAGS,
        )
        return (res.stdout or "") + ("\n" + res.stderr if res.returncode != 0 and res.stderr else "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def rssi_to_percent(rssi: Optional[float]) -> Optional[int]:
    if rssi is None:
        return None
    return int(max(0, min(100, 2 * (rssi + 100))))


def percent_to_rssi(pct: Optional[float]) -> Optional[int]:
    """Windows'un sinyal kalitesi (%) → yaklaşık dBm dönüşümü (Microsoft eşlemesi)."""
    if pct is None:
        return None
    return int(round(pct / 2 - 100))


def signal_quality(rssi: Optional[float]) -> Optional[str]:
    if rssi is None:
        return None
    if rssi >= -55:
        return "Mükemmel"
    if rssi >= -67:
        return "İyi"
    if rssi >= -75:
        return "Orta"
    return "Zayıf"


def freq_to_channel(freq_mhz: Optional[float]):
    if not freq_mhz:
        return None, None
    f = int(round(freq_mhz))
    if 2412 <= f <= 2472:
        return (f - 2407) // 5, "2.4 GHz"
    if f == 2484:
        return 14, "2.4 GHz"
    if 5160 <= f <= 5885:
        return (f - 5000) // 5, "5 GHz"
    if 5955 <= f <= 7115:
        return (f - 5950) // 5, "6 GHz"
    return None, None


def channel_to_band(ch: Optional[int]) -> Optional[str]:
    if ch is None:
        return None
    if 1 <= ch <= 14:
        return "2.4 GHz"
    if 32 <= ch <= 177:
        return "5 GHz"
    return None


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ".").strip().strip("%"))
    except ValueError:
        m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
        return float(m.group(0).replace(",", ".")) if m else None


def _norm_key(k: str) -> str:
    table = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
                           "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})
    k = k.translate(table).strip().lower().replace("\u0307", "")
    return re.sub(r"\s+", " ", k)


def classify_by_name(name: str, desc: str = "") -> str:
    text = f"{name} {desc}".lower()
    if re.search(r"wi-?fi|wlan|wireless|802\.11|airport|kablosuz|wlp|^wl", text):
        return "wifi"
    if re.search(r"ethernet|^eth|^en[ops]|^em\d|gigabit|lan|realtek pcie|intel\(r\) ethernet|usb 10/100", text):
        return "ethernet"
    return "other"


def empty_iface(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "label": name,
        "description": "",
        "type": "other",
        "up": False,
        "connected": False,
        "ipv4": None,
        "netmask": None,
        "mac": None,
        "gateway": None,
        "is_default": False,
        "link_speed_mbps": None,
        "duplex": None,
        "mtu": None,
        "virtual": False,
        "wifi": None,
    }


def empty_wifi() -> Dict[str, Any]:
    return {
        "ssid": None,
        "bssid": None,
        "rssi_dbm": None,
        "rssi_estimated": False,
        "noise_dbm": None,
        "snr_db": None,
        "signal_pct": None,
        "quality": None,
        "channel": None,
        "band": None,
        "width_mhz": None,
        "phy": None,
        "tx_rate_mbps": None,
        "rx_rate_mbps": None,
        "security": None,
        "note": None,
    }


def finalize_wifi(w: Dict[str, Any]) -> Dict[str, Any]:
    if w.get("rssi_dbm") is None and w.get("signal_pct") is not None:
        w["rssi_dbm"] = percent_to_rssi(w["signal_pct"])
        w["rssi_estimated"] = True
    if w.get("signal_pct") is None and w.get("rssi_dbm") is not None:
        w["signal_pct"] = rssi_to_percent(w["rssi_dbm"])
    if w.get("rssi_dbm") is not None and w.get("noise_dbm") is not None:
        w["snr_db"] = int(w["rssi_dbm"] - w["noise_dbm"])
    if w.get("band") is None and w.get("channel") is not None:
        w["band"] = channel_to_band(w["channel"])
    w["quality"] = signal_quality(w.get("rssi_dbm"))
    if w.get("ssid") in ("", "<redacted>", "<private>"):
        w["ssid"] = None
        w["note"] = w.get("note") or "SSID gizli (konum izni gerekli)"
    return w


# ---------------------------------------------------------------------------
# psutil temel katmanı (tüm platformlar)
# ---------------------------------------------------------------------------

def base_interfaces() -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    if psutil is None:
        return result
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return result
    link_family = getattr(psutil, "AF_LINK", None)
    for name, alist in addrs.items():
        it = empty_iface(name)
        for a in alist:
            if a.family == socket.AF_INET and not it["ipv4"]:
                if not a.address.startswith("169.254."):
                    it["ipv4"] = a.address
                    it["netmask"] = a.netmask
            elif link_family is not None and a.family == link_family and a.address:
                mac = a.address.replace("-", ":").lower()
                if mac and mac != "00:00:00:00:00:00":
                    it["mac"] = mac
        st = stats.get(name)
        if st:
            it["up"] = bool(st.isup)
            it["mtu"] = st.mtu or None
            if st.speed:
                it["link_speed_mbps"] = st.speed
            duplex_map = {2: "full", 1: "half"}
            it["duplex"] = duplex_map.get(int(st.duplex)) if st.duplex else None
        result[name] = it
    return result


# ---------------------------------------------------------------------------
# WINDOWS
# ---------------------------------------------------------------------------

WIN_PS_SCRIPT = r"""
$ErrorActionPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$a = @(Get-NetAdapter -IncludeHidden:$false | Select-Object Name,InterfaceDescription,InterfaceIndex,Status,MacAddress,ReceiveLinkSpeed,TransmitLinkSpeed,NdisPhysicalMedium,MediaConnectionState,FullDuplex,Virtual,HardwareInterface,MtuSize)
$ipif = @{}
Get-NetIPInterface -AddressFamily IPv4 | ForEach-Object { $ipif[[int]$_.InterfaceIndex] = $_.InterfaceMetric }
$r = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | ForEach-Object {
  [pscustomobject]@{InterfaceIndex=$_.InterfaceIndex; NextHop=$_.NextHop; RouteMetric=$_.RouteMetric; IfMetric=$ipif[[int]$_.InterfaceIndex]}
})
$i = @(Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceIndex,IPAddress,PrefixLength)
@{adapters=$a;routes=$r;ips=$i} | ConvertTo-Json -Depth 4 -Compress
"""

# netsh wlan anahtarları (normalize edilmiş, TR + EN)
NETSH_KEYS = {
    "name": ["name", "ad"],
    "description": ["description", "aciklama"],
    "mac": ["physical address", "fiziksel adres"],
    "state": ["state", "durum"],
    "ssid": ["ssid"],
    "bssid": ["bssid", "ap bssid"],
    "band": ["band", "bant"],
    "channel": ["channel", "kanal"],
    "radio": ["radio type", "radyo turu"],
    "auth": ["authentication", "kimlik dogrulama"],
    "rx": ["receive rate (mbps)", "alma hizi (mbps)"],
    "tx": ["transmit rate (mbps)", "iletim hizi (mbps)", "gonderme hizi (mbps)"],
    "signal": ["signal", "sinyal"],
    "rssi": ["rssi"],
    "profile": ["profile", "profil"],
}


def parse_netsh_wlan(output: str) -> List[Dict[str, Any]]:
    """`netsh wlan show interfaces` çıktısını ayrıştırır (TR/EN)."""
    lookup = {}
    for field, keys in NETSH_KEYS.items():
        for k in keys:
            lookup[k] = field

    blocks: List[Dict[str, str]] = []
    cur: Dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        nk = _norm_key(key)
        field = lookup.get(nk)
        if field is None:
            continue
        val = val.strip()
        if field == "name" and cur.get("name"):
            blocks.append(cur)
            cur = {}
        if field not in cur:
            cur[field] = val
    if cur:
        blocks.append(cur)

    result = []
    for b in blocks:
        w = empty_wifi()
        w["ssid"] = b.get("ssid") or None
        w["bssid"] = (b.get("bssid") or "").lower() or None
        w["channel"] = int(_to_float(b.get("channel")) or 0) or None
        band = b.get("band")
        if band:
            m = re.search(r"(2[.,]4|5|6)\s*GHz", band, re.IGNORECASE)
            w["band"] = (m.group(1).replace(",", ".") + " GHz") if m else band
        w["phy"] = b.get("radio")
        w["security"] = b.get("auth")
        w["rx_rate_mbps"] = _to_float(b.get("rx"))
        w["tx_rate_mbps"] = _to_float(b.get("tx"))
        w["signal_pct"] = int(_to_float(b.get("signal"))) if b.get("signal") else None
        rssi = _to_float(b.get("rssi"))
        w["rssi_dbm"] = int(rssi) if rssi is not None else None
        connected = bool(w["ssid"]) or bool(w["bssid"])
        result.append({
            "name": b.get("name"),
            "description": b.get("description"),
            "mac": (b.get("mac") or "").lower() or None,
            "connected": connected,
            "state": b.get("state"),
            "wifi": finalize_wifi(w),
        })
    return result


def windows_snapshot() -> Dict[str, Any]:
    base = base_interfaces()
    out = run_cmd(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", WIN_PS_SCRIPT],
        timeout=20,
        encoding="utf-8",
    )
    data: Dict[str, Any] = {}
    try:
        start = out.find("{")
        data = json.loads(out[start:]) if start >= 0 else {}
    except Exception:
        data = {}

    def as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    adapters = as_list(data.get("adapters"))
    routes = as_list(data.get("routes"))
    ips = as_list(data.get("ips"))

    ifaces: Dict[str, Dict[str, Any]] = {}
    idx_to_name: Dict[int, str] = {}
    for ad in adapters:
        name = ad.get("Name")
        if not name:
            continue
        it = base.get(name) or empty_iface(name)
        it["label"] = name
        it["description"] = ad.get("InterfaceDescription") or ""
        medium = ad.get("NdisPhysicalMedium")
        if medium == 9:
            it["type"] = "wifi"
        elif medium == 14:
            it["type"] = "ethernet"
        else:
            it["type"] = classify_by_name(name, it["description"])
        it["virtual"] = bool(ad.get("Virtual")) or ad.get("HardwareInterface") is False or bool(
            VIRTUAL_PATTERNS.search(name + " " + it["description"])
        )
        status = str(ad.get("Status") or "").lower()
        it["up"] = status == "up" or ad.get("MediaConnectionState") == 1
        sp = ad.get("ReceiveLinkSpeed") or ad.get("TransmitLinkSpeed")
        if sp:
            it["link_speed_mbps"] = int(int(sp) / 1_000_000)
        if ad.get("FullDuplex") is not None:
            it["duplex"] = "full" if ad.get("FullDuplex") else "half"
        if ad.get("MacAddress"):
            it["mac"] = str(ad["MacAddress"]).replace("-", ":").lower()
        if ad.get("MtuSize"):
            it["mtu"] = ad.get("MtuSize")
        idx = ad.get("InterfaceIndex")
        if idx is not None:
            idx_to_name[int(idx)] = name
        ifaces[name] = it

    for ip in ips:
        name = idx_to_name.get(int(ip.get("InterfaceIndex", -1)))
        addr = ip.get("IPAddress")
        if name and addr and not str(addr).startswith(("169.254.", "127.")):
            ifaces[name]["ipv4"] = addr

    best = None
    for r in routes:
        name = idx_to_name.get(int(r.get("InterfaceIndex", -1)))
        if not name:
            continue
        hop = r.get("NextHop")
        if hop and hop != "0.0.0.0":
            ifaces[name]["gateway"] = hop
        metric = (r.get("RouteMetric") or 0) + (r.get("IfMetric") or 0)
        if ifaces[name]["up"] and (best is None or metric < best[0]):
            best = (metric, name)
    if best:
        ifaces[best[1]]["is_default"] = True

    # PowerShell başarısızsa psutil verisine düş
    if not ifaces:
        for name, it in base.items():
            it["type"] = classify_by_name(name)
            it["virtual"] = bool(VIRTUAL_PATTERNS.search(name))
            ifaces[name] = it
        gw = _windows_ipconfig_gateway()
        if gw:
            for it in ifaces.values():
                if it["ipv4"] and it["type"] != "other" and not it["virtual"]:
                    it["gateway"] = gw
                    it["is_default"] = True
                    break

    # Wi-Fi detayları
    wl_out = run_cmd(["netsh", "wlan", "show", "interfaces"], timeout=10)
    location_needed = bool(re.search(r"location|konum", wl_out, re.IGNORECASE)) and "SSID" not in wl_out
    for wl in parse_netsh_wlan(wl_out):
        it = ifaces.get(wl["name"] or "")
        if it is None:
            # isim eşleşmezse MAC ile eşle
            it = next((x for x in ifaces.values() if x["mac"] and x["mac"] == wl.get("mac")), None)
        if it is None:
            continue
        it["type"] = "wifi"
        it["wifi"] = wl["wifi"] if wl["connected"] else None
        if wl["connected"] and wl["wifi"].get("tx_rate_mbps"):
            it["link_speed_mbps"] = wl["wifi"]["tx_rate_mbps"]
    if location_needed:
        for it in ifaces.values():
            if it["type"] == "wifi" and it["up"]:
                w = it["wifi"] or empty_wifi()
                w["note"] = "Windows konum izni kapalı: Ayarlar > Gizlilik > Konum'dan açın"
                it["wifi"] = w
    return {"interfaces": list(ifaces.values())}


def _windows_ipconfig_gateway() -> Optional[str]:
    out = run_cmd(["ipconfig"], timeout=10)
    m = re.search(r"(?:Default Gateway|Varsay[ıi]lan A[ğg] Ge[çc]idi)[ .]*:\s*([\d.]+)", out)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

AIRPORT_BIN = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
_mac_sp_cache: Dict[str, Any] = {"t": 0.0, "data": {}}


def parse_hardware_ports(output: str) -> Dict[str, str]:
    """`networksetup -listallhardwareports` → {device: hardware_port}"""
    ports: Dict[str, str] = {}
    port = None
    for line in output.splitlines():
        if line.startswith("Hardware Port:"):
            port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and port:
            ports[line.split(":", 1)[1].strip()] = port
            port = None
    return ports


def parse_mac_netstat_routes(output: str) -> Dict[str, str]:
    """`netstat -rn -f inet` → {iface: gateway} (yalnızca default rotalar)"""
    gws: Dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "default" and IPV4_RE.fullmatch(parts[1]):
            iface = parts[3]
            gws.setdefault(iface, parts[1])
    return gws


def parse_mac_ifconfig_media(output: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    m = re.search(r"media:.*?\((\d+)(G|M)?base[^ <)]*\s*(?:<([^>]*)>)?", output, re.IGNORECASE)
    if m:
        speed = int(m.group(1))
        if (m.group(2) or "").upper() == "G":
            speed *= 1000
        info["link_speed_mbps"] = speed
        if m.group(3):
            info["duplex"] = "full" if "full" in m.group(3) else ("half" if "half" in m.group(3) else None)
    s = re.search(r"status:\s*(\w+)", output)
    if s:
        info["active"] = s.group(1) == "active"
    return info


def parse_system_profiler_airport(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """system_profiler SPAirPortDataType -json → {iface: wifi_dict}"""
    result: Dict[str, Dict[str, Any]] = {}
    for top in data.get("SPAirPortDataType", []) or []:
        for itf in top.get("spairport_airport_interfaces", []) or []:
            name = itf.get("_name")
            cur = itf.get("spairport_current_network_information")
            if not name or not cur:
                continue
            w = empty_wifi()
            w["ssid"] = cur.get("_name")
            sn = cur.get("spairport_signal_noise") or ""
            nums = re.findall(r"-?\d+", sn)
            if nums:
                w["rssi_dbm"] = int(nums[0])
                if len(nums) > 1:
                    w["noise_dbm"] = int(nums[1])
            ch = str(cur.get("spairport_network_channel") or "")
            m = re.match(r"\s*(\d+)\s*(?:\(([\d.]+)\s*GHz(?:,\s*(\d+)\s*MHz)?\))?", ch)
            if m:
                w["channel"] = int(m.group(1))
                if m.group(2):
                    g = m.group(2)
                    w["band"] = "2.4 GHz" if g.startswith("2") else f"{g} GHz"
                if m.group(3):
                    w["width_mhz"] = int(m.group(3))
            phy = cur.get("spairport_network_phymode")
            w["phy"] = phy
            rate = cur.get("spairport_network_rate")
            w["tx_rate_mbps"] = _to_float(rate)
            sec = str(cur.get("spairport_security_mode") or "")
            w["security"] = sec.replace("spairport_security_mode_", "").replace("_", " ").upper() or None
            result[name] = w
    return result


def parse_airport_info(output: str) -> Dict[str, Any]:
    kv = {}
    for line in output.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            kv[k.strip()] = v.strip()
    w = empty_wifi()
    if "agrCtlRSSI" in kv:
        w["rssi_dbm"] = int(_to_float(kv.get("agrCtlRSSI")) or 0) or None
        w["noise_dbm"] = int(_to_float(kv.get("agrCtlNoise")) or 0) or None
        w["tx_rate_mbps"] = _to_float(kv.get("lastTxRate"))
        w["ssid"] = kv.get("SSID")
        w["bssid"] = (kv.get("BSSID") or "").lower() or None
        ch = kv.get("channel", "")
        if ch:
            parts = ch.split(",")
            w["channel"] = int(_to_float(parts[0]) or 0) or None
            if len(parts) > 1:
                w["width_mhz"] = int(_to_float(parts[1]) or 0) or None
        w["security"] = kv.get("link auth")
    return w


def parse_ipconfig_summary(output: str) -> Dict[str, Optional[str]]:
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", output, re.MULTILINE)
    bssid = re.search(r"^\s*BSSID\s*:\s*([0-9a-fA-F:]{11,17})", output, re.MULTILINE)
    return {
        "ssid": ssid.group(1).strip() if ssid else None,
        "bssid": bssid.group(1).lower() if bssid else None,
    }


def _mac_corewlan() -> Dict[str, Dict[str, Any]]:
    """pyobjc-framework-CoreWLAN kuruluysa hızlı ve doğrudan okuma."""
    try:
        import CoreWLAN  # type: ignore
    except Exception:
        return {}
    result = {}
    try:
        client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
        for itf in client.interfaces() or []:
            name = str(itf.interfaceName())
            rssi = itf.rssiValue()
            if not rssi:
                continue
            w = empty_wifi()
            w["rssi_dbm"] = int(rssi)
            w["noise_dbm"] = int(itf.noiseMeasurement()) or None
            w["tx_rate_mbps"] = float(itf.transmitRate()) or None
            ssid = itf.ssid()
            bssid = itf.bssid()
            w["ssid"] = str(ssid) if ssid else None
            w["bssid"] = str(bssid).lower() if bssid else None
            ch = itf.wlanChannel()
            if ch is not None:
                w["channel"] = int(ch.channelNumber())
                w["band"] = {1: "2.4 GHz", 2: "5 GHz", 3: "6 GHz"}.get(int(ch.channelBand()))
                w["width_mhz"] = {1: 20, 2: 40, 3: 80, 4: 160}.get(int(ch.channelWidth()))
            phy = {1: "802.11a", 2: "802.11b", 3: "802.11g", 4: "802.11n", 5: "802.11ac", 6: "802.11ax", 7: "802.11be"}
            w["phy"] = phy.get(int(itf.activePHYMode()))
            result[name] = w
    except Exception:
        return {}
    return result


def mac_snapshot(slow_ok: bool = True) -> Dict[str, Any]:
    base = base_interfaces()
    ports = parse_hardware_ports(run_cmd(["networksetup", "-listallhardwareports"], timeout=10))
    gws = parse_mac_netstat_routes(run_cmd(["netstat", "-rn", "-f", "inet"], timeout=10))
    default_out = run_cmd(["route", "-n", "get", "default"], timeout=5)
    m = re.search(r"interface:\s*(\S+)", default_out)
    default_if = m.group(1) if m else None
    g = re.search(r"gateway:\s*([\d.]+)", default_out)
    if default_if and g:
        gws.setdefault(default_if, g.group(1))

    ifaces: Dict[str, Dict[str, Any]] = {}
    names = set(base) | set(ports)
    for name in names:
        it = base.get(name) or empty_iface(name)
        port = ports.get(name)
        if port:
            it["label"] = port
            it["description"] = port
            pl = port.lower()
            if "wi-fi" in pl or "airport" in pl or "wlan" in pl:
                it["type"] = "wifi"
            elif "bridge" in pl or "iphone" in pl or "bluetooth" in pl:
                it["type"] = "other"
                it["virtual"] = "bridge" in pl
            elif "ethernet" in pl or re.search(r"\blan\b", pl):
                it["type"] = "ethernet"
            elif pl.startswith("thunderbolt"):
                it["type"] = "other"  # Thunderbolt köprü üyeleri
            else:
                it["type"] = classify_by_name(name, port)
        else:
            it["virtual"] = True if VIRTUAL_PATTERNS.search(name) or name.startswith("lo") else not name.startswith("en")
        it["gateway"] = gws.get(name)
        it["is_default"] = name == default_if
        ifaces[name] = it

    for name, it in ifaces.items():
        if it["type"] == "ethernet" and not it["virtual"]:
            media = parse_mac_ifconfig_media(run_cmd(["ifconfig", name], timeout=5))
            if media.get("link_speed_mbps"):
                it["link_speed_mbps"] = media["link_speed_mbps"]
            if media.get("duplex"):
                it["duplex"] = media["duplex"]
            if "active" in media:
                it["up"] = it["up"] and media["active"]

    # Wi-Fi detayları: CoreWLAN → airport (eski macOS) → system_profiler
    wifi_info = _mac_corewlan()
    if not wifi_info and os.path.exists(AIRPORT_BIN):
        out = run_cmd([AIRPORT_BIN, "-I"], timeout=5)
        if "agrCtlRSSI" in out and "deprecated" not in out.lower():
            for name, it in ifaces.items():
                if it["type"] == "wifi":
                    wifi_info[name] = parse_airport_info(out)
                    break
    if not wifi_info and slow_ok:
        now = time.time()
        if now - _mac_sp_cache["t"] > 20:
            out = run_cmd(["system_profiler", "SPAirPortDataType", "-json", "-detailLevel", "basic"], timeout=30)
            try:
                _mac_sp_cache["data"] = parse_system_profiler_airport(json.loads(out))
            except Exception:
                _mac_sp_cache["data"] = {}
            _mac_sp_cache["t"] = now
        wifi_info = dict(_mac_sp_cache["data"])

    for name, w in wifi_info.items():
        it = ifaces.get(name)
        if not it:
            continue
        if w.get("ssid") in ("<redacted>", "<private>", ""):
            w["ssid"] = None
        if not w.get("ssid") or not w.get("bssid"):
            summ = parse_ipconfig_summary(run_cmd(["ipconfig", "getsummary", name], timeout=5))
            if not w.get("ssid") and summ["ssid"] and "redacted" not in summ["ssid"]:
                w["ssid"] = summ["ssid"]
            if not w.get("bssid") and summ["bssid"]:
                w["bssid"] = summ["bssid"]
        if w.get("ssid") is None and w.get("note") is None:
            w["note"] = "SSID gizli: Sistem Ayarları > Gizlilik > Konum Servisleri'nden Terminal/Python'a izin verin"
        it["type"] = "wifi"
        it["wifi"] = finalize_wifi(w)
        if w.get("tx_rate_mbps"):
            it["link_speed_mbps"] = w["tx_rate_mbps"]
    return {"interfaces": list(ifaces.values())}


# ---------------------------------------------------------------------------
# LINUX
# ---------------------------------------------------------------------------

def parse_proc_net_route(text: str) -> Dict[str, Any]:
    gws: Dict[str, str] = {}
    best = None
    for line in text.splitlines()[1:]:
        p = line.split()
        if len(p) < 8 or p[1] != "00000000":
            continue
        iface, gw_hex, metric = p[0], p[2], int(p[6])
        gw = socket.inet_ntoa(bytes.fromhex(gw_hex)[::-1])
        gws.setdefault(iface, gw)
        if best is None or metric < best[0]:
            best = (metric, iface)
    return {"gateways": gws, "default": best[1] if best else None}


def parse_iw_link(output: str) -> Optional[Dict[str, Any]]:
    if "Not connected" in output or "Connected to" not in output:
        return None
    w = empty_wifi()
    m = re.search(r"Connected to ([0-9a-f:]{17})", output, re.IGNORECASE)
    w["bssid"] = m.group(1).lower() if m else None
    m = re.search(r"SSID:\s*(.+)", output)
    w["ssid"] = m.group(1).strip() if m else None
    m = re.search(r"freq:\s*([\d.]+)", output)
    if m:
        w["channel"], w["band"] = freq_to_channel(float(m.group(1)))
    m = re.search(r"signal:\s*(-?\d+)", output)
    w["rssi_dbm"] = int(m.group(1)) if m else None
    m = re.search(r"tx bitrate:\s*([\d.]+)", output)
    w["tx_rate_mbps"] = float(m.group(1)) if m else None
    m = re.search(r"rx bitrate:\s*([\d.]+)", output)
    w["rx_rate_mbps"] = float(m.group(1)) if m else None
    m = re.search(r"(\d+)MHz", output)
    w["width_mhz"] = int(m.group(1)) if m else None
    if re.search(r"\bEHT-MCS", output):
        w["phy"] = "802.11be"
    elif re.search(r"\bHE-MCS", output):
        w["phy"] = "802.11ax"
    elif re.search(r"\bVHT-MCS", output):
        w["phy"] = "802.11ac"
    elif re.search(r"\bMCS", output):
        w["phy"] = "802.11n"
    return w


def linux_snapshot() -> Dict[str, Any]:
    base = base_interfaces()
    try:
        with open("/proc/net/route") as f:
            routes = parse_proc_net_route(f.read())
    except Exception:
        routes = {"gateways": {}, "default": None}
    for name, it in base.items():
        sysdir = f"/sys/class/net/{name}"
        if os.path.isdir(f"{sysdir}/wireless") or os.path.exists(f"{sysdir}/phy80211"):
            it["type"] = "wifi"
        elif os.path.exists(f"{sysdir}/device"):
            it["type"] = "ethernet"
        else:
            it["type"] = classify_by_name(name)
            it["virtual"] = True
        if VIRTUAL_PATTERNS.search(name):
            it["virtual"] = True
        it["gateway"] = routes["gateways"].get(name)
        it["is_default"] = name == routes["default"]
        if it["type"] == "wifi":
            w = parse_iw_link(run_cmd(["iw", "dev", name, "link"], timeout=5))
            if w:
                it["wifi"] = finalize_wifi(w)
                if w.get("tx_rate_mbps"):
                    it["link_speed_mbps"] = w["tx_rate_mbps"]
    return {"interfaces": list(base.values())}


# ---------------------------------------------------------------------------
# Ortak API
# ---------------------------------------------------------------------------

def collect_snapshot() -> Dict[str, Any]:
    try:
        if IS_WINDOWS:
            snap = windows_snapshot()
        elif IS_MAC:
            snap = mac_snapshot()
        else:
            snap = linux_snapshot()
    except Exception as e:  # asla çökmesin
        snap = {"interfaces": [], "error": str(e)}

    for it in snap["interfaces"]:
        it["connected"] = bool(it["up"] and it["ipv4"])
        if it["type"] == "wifi" and it.get("wifi") is None and it["connected"]:
            it["wifi"] = finalize_wifi(empty_wifi())

    def sort_key(it):
        order = {"ethernet": 0, "wifi": 1, "other": 2}
        return (it["virtual"], not it["connected"], order.get(it["type"], 3), it["name"])

    snap["interfaces"].sort(key=sort_key)
    default = next((i for i in snap["interfaces"] if i["is_default"]), None)
    if default is None:
        default = next((i for i in snap["interfaces"] if i["connected"] and i["gateway"] and not i["virtual"]), None)
        if default:
            default["is_default"] = True
    snap["default_iface"] = default["name"] if default else None
    snap["default_type"] = default["type"] if default else None
    snap["default_gateway"] = default["gateway"] if default else None
    snap["platform"] = SYSTEM
    snap["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return snap


class NetInfo:
    """Arka planda yenilenen, iş parçacığı güvenli arayüz önbelleği."""

    def __init__(self):
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._snap: Dict[str, Any] = {"interfaces": [], "default_iface": None, "default_type": None,
                                      "default_gateway": None, "platform": SYSTEM, "timestamp": None}

    def refresh(self) -> Dict[str, Any]:
        with self._refresh_lock:
            snap = collect_snapshot()
            with self._lock:
                self._snap = snap
            return snap

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._snap

    def physical(self, connected_only: bool = False) -> List[Dict[str, Any]]:
        res = [i for i in self.snapshot()["interfaces"] if not i["virtual"] and i["type"] in ("wifi", "ethernet")]
        return [i for i in res if i["connected"]] if connected_only else res

    def first(self, iface_type: str) -> Optional[Dict[str, Any]]:
        return next((i for i in self.physical(True) if i["type"] == iface_type), None)

    def by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return next((i for i in self.snapshot()["interfaces"] if i["name"] == name), None)


if __name__ == "__main__":
    print(json.dumps(collect_snapshot(), indent=2, ensure_ascii=False))
