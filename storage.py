"""SQLite katmanı: şema, eski veritabanı göçü, sorgular ve özetleme (downsampling)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_local = threading.local()
DB_PATH: Path = Path("network_monitor.db")

SCHEMA = {
    "speedtests": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "server_name": "TEXT",
        "download_mbps": "REAL",
        "upload_mbps": "REAL",
        "ping_ms": "REAL",
        "jitter_ms": "REAL",
        "packet_loss": "REAL",
        "engine": "TEXT",
        "iface_type": "TEXT",
        "iface_name": "TEXT",
        "wifi_rssi": "INTEGER",
        "isp": "TEXT",
        "result_url": "TEXT",
        "server_id": "TEXT",
    },
    "pings": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "target_name": "TEXT",
        "host": "TEXT",
        "avg_ping": "REAL",
        "max_ping": "REAL",
        "jitter": "REAL",
        "packet_loss": "REAL",
        "min_ping": "REAL",
        "target_id": "TEXT",
        "iface_type": "TEXT",
        "iface_name": "TEXT",
        "wifi_rssi": "INTEGER",
        "ip": "TEXT",
    },
    "traceroutes": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "target_name": "TEXT",
        "host": "TEXT",
        "output": "TEXT",
        "target_id": "TEXT",
        "iface_type": "TEXT",
        "iface_name": "TEXT",
        "hops_json": "TEXT",
        "bound": "INTEGER",
    },
    "wifi_samples": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "iface_name": "TEXT",
        "ssid": "TEXT",
        "bssid": "TEXT",
        "rssi_dbm": "INTEGER",
        "noise_dbm": "INTEGER",
        "signal_pct": "INTEGER",
        "channel": "INTEGER",
        "band": "TEXT",
        "width_mhz": "INTEGER",
        "phy": "TEXT",
        "tx_rate": "REAL",
        "rx_rate": "REAL",
    },
    "site_checks": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "site_id": "TEXT",
        "host": "TEXT",
        "url": "TEXT",
        "iface_type": "TEXT",
        "iface_name": "TEXT",
        "ip": "TEXT",
        "dns_ms": "REAL",
        "tcp_ms": "REAL",
        "tls_ms": "REAL",
        "ttfb_ms": "REAL",
        "total_ms": "REAL",
        "status": "INTEGER",
        "ok": "INTEGER",
        "bytes": "INTEGER",
        "server": "TEXT",
        "cdn": "TEXT",
        "asn": "INTEGER",
        "as_name": "TEXT",
        "ptr": "TEXT",
        "dns_json": "TEXT",
        "dns_mismatch": "INTEGER",
        "error": "TEXT",
    },
    "cdn_checks": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "service": "TEXT",
        "label": "TEXT",
        "host": "TEXT",
        "kind": "TEXT",
        "ip": "TEXT",
        "iface_type": "TEXT",
        "iface_name": "TEXT",
        "asn": "INTEGER",
        "as_name": "TEXT",
        "ptr": "TEXT",
        "where_": "TEXT",
        "local": "INTEGER",
        "cluster": "TEXT",
        "dns_ms": "REAL",
        "ping_ms": "REAL",
        "ping_loss": "REAL",
        "jitter": "REAL",
        "tcp_ms": "REAL",
        "tls_ms": "REAL",
        "ttfb_ms": "REAL",
        "mbps": "REAL",
        "status": "INTEGER",
        "error": "TEXT",
        "note": "TEXT",
    },
    "link_events": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp": "TEXT",
        "iface_name": "TEXT",
        "iface_type": "TEXT",
        "kind": "TEXT",
        "severity": "TEXT",
        "message": "TEXT",
    },
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pings_ts ON pings (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_pings_series ON pings (target_id, iface_type, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_pings_host_id ON pings (host, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_speedtests_ts ON speedtests (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_trace_ts ON traceroutes (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_wifi_ts ON wifi_samples (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON link_events (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_site_ts ON site_checks (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_cdn_ts ON cdn_checks (timestamp)",
]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(DB_PATH), timeout=15.0, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        _local.conn = c
    return c


def init_db(path: Path, legacy_targets: Optional[List[Dict[str, Any]]] = None):
    global DB_PATH
    DB_PATH = path
    c = conn()
    c.execute("PRAGMA journal_mode=WAL")
    for table, cols in SCHEMA.items():
        c.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(f'{k} {v}' for k, v in cols.items())})")
        existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in existing:
                # Eski sürüm veritabanı: eksik kolonları ekle (veri kaybı olmadan)
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ.replace('PRIMARY KEY AUTOINCREMENT', '')}")
    # Eski kayıtların hedef kimliğini host üzerinden doldur
    if legacy_targets:
        for t in legacy_targets:
            if t["host"] != "@gateway":
                c.execute("UPDATE pings SET target_id=? WHERE target_id IS NULL AND host=?", (t["id"], t["host"]))
                c.execute("UPDATE traceroutes SET target_id=? WHERE target_id IS NULL AND host=?", (t["id"], t["host"]))
        c.execute("UPDATE pings SET target_id='gateway' WHERE target_id IS NULL AND target_name LIKE '%Gateway%'")
    c.execute("UPDATE pings SET target_id=host WHERE target_id IS NULL")
    for sql in INDEXES:
        c.execute(sql)
    c.commit()


def insert(table: str, row: Dict[str, Any]) -> int:
    cols = [k for k in row if k in SCHEMA[table]]
    c = conn()
    cur = c.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [row[k] for k in cols],
    )
    c.commit()
    return cur.lastrowid


RANGE_DAYS = {"hourly": 1 / 24, "daily": 1, "weekly": 7, "monthly": 30, "all": 3650}


FMT = "%Y-%m-%d %H:%M:%S"


def range_cutoff(rng: str) -> datetime:
    return datetime.now() - timedelta(days=RANGE_DAYS.get(rng, 1))


def window(rng: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None):
    """(başlangıç, bitiş) zaman penceresi. Açık tarih verilirse periyot yok sayılır."""
    if start:
        return start, end or datetime.now().strftime(FMT)
    return range_cutoff(rng or "daily").strftime(FMT), "9999-12-31 23:59:59"


def _span(win) -> float:
    end = datetime.now() if win[1].startswith("9999") else datetime.strptime(win[1], FMT)
    return max(60.0, (end - datetime.strptime(win[0], FMT)).total_seconds())


def bucket_seconds(win, base_interval: int) -> int:
    """Grafik başına ~360 nokta; kovalar dakikaya hizalanır ki Wi-Fi/Ethernet serileri çakışsın."""
    b = max(base_interval, int(_span(win) / 360))
    return b if b < 60 else (b // 60) * 60


def iface_clause(iface: str, col: str = "iface_type"):
    if iface in ("wifi", "ethernet"):
        return f" AND {col} = ?", [iface]
    return "", []


def ping_series(win, iface: str, base_interval: int) -> List[Dict[str, Any]]:
    cutoff, end = win
    b = bucket_seconds(win, base_interval)
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"""SELECT target_id, COALESCE(iface_type,'unknown') AS iface_type,
                   CAST(strftime('%s', timestamp) AS INTEGER) / ? AS bucket,
                   datetime((CAST(strftime('%s', timestamp) AS INTEGER) / ?) * ?, 'unixepoch') AS ts,
                   ROUND(AVG(avg_ping), 2) AS avg_ping,
                   ROUND(MAX(COALESCE(max_ping, avg_ping)), 2) AS max_ping,
                   ROUND(AVG(jitter), 2) AS jitter,
                   ROUND(AVG(packet_loss), 2) AS packet_loss,
                   COUNT(*) AS n
            FROM pings WHERE timestamp BETWEEN ? AND ? {extra}
            GROUP BY target_id, iface_type, bucket ORDER BY bucket""",
        [b, b, b, cutoff, end, *params],
    ).fetchall()
    series: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r['target_id']}|{r['iface_type']}"
        s = series.setdefault(key, {"target_id": r["target_id"], "iface_type": r["iface_type"], "points": []})
        s["points"].append([r["ts"], r["avg_ping"], r["max_ping"], r["jitter"], r["packet_loss"]])
    return list(series.values())


def ping_stats(win, iface: str) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    c = conn()
    rows = c.execute(
        f"""SELECT target_id, COALESCE(iface_type,'unknown') AS iface_type, COUNT(*) AS n,
                   ROUND(AVG(avg_ping), 2) AS avg, ROUND(MIN(COALESCE(min_ping, avg_ping)), 2) AS min,
                   ROUND(MAX(COALESCE(max_ping, avg_ping)), 2) AS max, ROUND(AVG(jitter), 2) AS jitter,
                   ROUND(AVG(packet_loss), 2) AS loss,
                   ROUND(100.0 * SUM(CASE WHEN packet_loss < 100 THEN 1 ELSE 0 END) / COUNT(*), 2) AS uptime,
                   SUM(CASE WHEN packet_loss >= 100 THEN 1 ELSE 0 END) AS outages
            FROM pings WHERE timestamp BETWEEN ? AND ? {extra}
            GROUP BY target_id, iface_type""",
        [cutoff, end, *params],
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        cnt = c.execute(
            "SELECT COUNT(*) FROM pings WHERE timestamp BETWEEN ? AND ? AND target_id = ? AND COALESCE(iface_type,'unknown') = ? AND avg_ping IS NOT NULL",
            (cutoff, end, r["target_id"], r["iface_type"]),
        ).fetchone()[0]
        p95 = None
        if cnt:
            row = c.execute(
                """SELECT avg_ping FROM pings WHERE timestamp BETWEEN ? AND ? AND target_id = ? AND COALESCE(iface_type,'unknown') = ?
                   AND avg_ping IS NOT NULL ORDER BY avg_ping LIMIT 1 OFFSET ?""",
                (cutoff, end, r["target_id"], r["iface_type"], max(0, int(cnt * 0.95) - 1)),
            ).fetchone()
            p95 = row[0] if row else None
        d["p95"] = p95
        last = c.execute(
            """SELECT timestamp, avg_ping, max_ping, jitter, packet_loss FROM pings
               WHERE target_id = ? AND COALESCE(iface_type,'unknown') = ? AND timestamp BETWEEN ? AND ?
               ORDER BY id DESC LIMIT 1""",
            (r["target_id"], r["iface_type"], cutoff, end),
        ).fetchone()
        d["last"] = dict(last) if last else None
        out.append(d)
    return out


def recent_pings(win, iface: str, limit: int = 150) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"SELECT * FROM pings WHERE timestamp BETWEEN ? AND ? {extra} ORDER BY id DESC LIMIT ?",
        [cutoff, end, *params, limit],
    ).fetchall()
    return [dict(r) for r in rows]


def speedtests(win, iface: str) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"SELECT * FROM speedtests WHERE timestamp BETWEEN ? AND ? {extra} ORDER BY timestamp, id", [cutoff, end, *params]
    ).fetchall()
    return [dict(r) for r in rows]


def traceroutes(win, iface: str, limit: int = 40) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"SELECT * FROM traceroutes WHERE timestamp BETWEEN ? AND ? {extra} ORDER BY id DESC LIMIT ?", [cutoff, end, *params, limit]
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["hops"] = json.loads(d.pop("hops_json") or "[]")
        except ValueError:
            d["hops"] = []
        out.append(d)
    return out


def wifi_series(win, base_interval: int) -> List[Dict[str, Any]]:
    cutoff, end = win
    b = bucket_seconds(win, base_interval)
    rows = conn().execute(
        """SELECT iface_name, CAST(strftime('%s', timestamp) AS INTEGER) / ? AS bucket,
                  datetime((CAST(strftime('%s', timestamp) AS INTEGER) / ?) * ?, 'unixepoch') AS ts,
                  ROUND(AVG(rssi_dbm), 1) AS rssi, MIN(rssi_dbm) AS rssi_min, ROUND(AVG(noise_dbm), 1) AS noise,
                  ROUND(AVG(tx_rate), 1) AS tx, MAX(channel) AS channel, MAX(ssid) AS ssid
           FROM wifi_samples WHERE timestamp BETWEEN ? AND ? GROUP BY iface_name, bucket ORDER BY bucket""",
        (b, b, b, cutoff, end),
    ).fetchall()
    series: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        s = series.setdefault(r["iface_name"], {"iface_name": r["iface_name"], "points": []})
        s["points"].append([r["ts"], r["rssi"], r["rssi_min"], r["noise"], r["tx"], r["channel"]])
    return list(series.values())


def wifi_summary(win) -> Optional[Dict[str, Any]]:
    cutoff, end = win
    r = conn().execute(
        """SELECT COUNT(*) AS n, ROUND(AVG(rssi_dbm),1) AS avg_rssi, MIN(rssi_dbm) AS min_rssi, MAX(rssi_dbm) AS max_rssi,
                  ROUND(AVG(tx_rate),1) AS avg_tx, COUNT(DISTINCT bssid) AS bssids, COUNT(DISTINCT channel) AS channels
           FROM wifi_samples WHERE timestamp BETWEEN ? AND ?""",
        (cutoff, end,),
    ).fetchone()
    return dict(r) if r and r["n"] else None


def events(win, limit: int = 200) -> List[Dict[str, Any]]:
    cutoff, end = win
    rows = conn().execute(
        "SELECT * FROM link_events WHERE timestamp BETWEEN ? AND ? ORDER BY id DESC LIMIT ?", (cutoff, end, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def speed_by_iface(win) -> List[Dict[str, Any]]:
    cutoff, end = win
    rows = conn().execute(
        """SELECT COALESCE(iface_type,'unknown') AS iface_type, COUNT(*) AS n,
                  ROUND(AVG(download_mbps),2) AS dl, ROUND(MAX(download_mbps),2) AS dl_max,
                  ROUND(AVG(upload_mbps),2) AS ul, ROUND(AVG(ping_ms),2) AS ping, ROUND(AVG(jitter_ms),2) AS jitter
           FROM speedtests WHERE timestamp BETWEEN ? AND ? GROUP BY iface_type""",
        (cutoff, end,),
    ).fetchall()
    return [dict(r) for r in rows]


def purge_older_than(days: int) -> int:
    if days <= 0:
        return 0
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c = conn()
    n = 0
    for t in SCHEMA:
        n += c.execute(f"DELETE FROM {t} WHERE timestamp < ?", (cutoff,)).rowcount
    c.commit()
    return n


def export_rows(table: str, win) -> Tuple[List[str], List[sqlite3.Row]]:
    cutoff, end = win
    cols = [k for k in SCHEMA[table] if k not in ("hops_json", "dns_json")]
    rows = conn().execute(
        f"SELECT {', '.join(cols)} FROM {table} WHERE timestamp BETWEEN ? AND ? ORDER BY id DESC", (cutoff, end)
    ).fetchall()
    return cols, rows


def site_checks(win, iface: str, limit: int = 300) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"SELECT * FROM site_checks WHERE timestamp BETWEEN ? AND ? {extra} ORDER BY timestamp DESC, id DESC LIMIT ?",
        [cutoff, end, *params, limit]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["dns"] = json.loads(d.pop("dns_json") or "{}")
        except ValueError:
            d["dns"] = {}
        out.append(d)
    return out


def site_stats(win, iface: str) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"""SELECT site_id, host, COALESCE(iface_type,'unknown') AS iface_type, COUNT(*) AS n,
                   ROUND(100.0 * SUM(ok) / COUNT(*), 1) AS success,
                   ROUND(AVG(dns_ms), 1) AS dns, ROUND(AVG(tcp_ms), 1) AS tcp, ROUND(AVG(tls_ms), 1) AS tls,
                   ROUND(AVG(ttfb_ms), 1) AS ttfb, ROUND(AVG(total_ms), 1) AS total, ROUND(MAX(total_ms), 1) AS total_max,
                   COUNT(DISTINCT ip) AS ip_count, SUM(dns_mismatch) AS mismatches
            FROM site_checks WHERE timestamp BETWEEN ? AND ? {extra}
            GROUP BY site_id, iface_type ORDER BY site_id""", [cutoff, end, *params]).fetchall()
    return [dict(r) for r in rows]


def site_series(win, iface: str, base_interval: int) -> List[Dict[str, Any]]:
    cutoff, end = win
    b = bucket_seconds(win, base_interval)
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"""SELECT site_id, COALESCE(iface_type,'unknown') AS iface_type,
                   datetime((CAST(strftime('%s', timestamp) AS INTEGER) / ?) * ?, 'unixepoch') AS ts,
                   ROUND(AVG(dns_ms),1), ROUND(AVG(tcp_ms),1), ROUND(AVG(tls_ms),1), ROUND(AVG(ttfb_ms),1),
                   ROUND(AVG(total_ms),1), MIN(ok)
            FROM site_checks WHERE timestamp BETWEEN ? AND ? {extra}
            GROUP BY site_id, iface_type, ts ORDER BY ts""", [b, b, cutoff, end, *params]).fetchall()
    series: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r[0]}|{r[1]}"
        s = series.setdefault(key, {"site_id": r[0], "iface_type": r[1], "points": []})
        s["points"].append(list(r[2:]))
    return list(series.values())


def cdn_checks(win, iface: str, limit: int = 300) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"SELECT * FROM cdn_checks WHERE timestamp BETWEEN ? AND ? {extra} ORDER BY timestamp DESC, id DESC LIMIT ?",
        [cutoff, end, *params, limit]).fetchall()
    return [dict(r) for r in rows]


def cdn_stats(win, iface: str) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"""SELECT service, COALESCE(iface_type,'unknown') AS iface_type, COUNT(*) AS n,
                   ROUND(100.0 * SUM(local) / COUNT(*), 1) AS local_pct,
                   ROUND(AVG(ping_ms), 2) AS ping, ROUND(AVG(ping_loss), 2) AS loss, ROUND(AVG(jitter), 2) AS jitter,
                   ROUND(AVG(ttfb_ms), 1) AS ttfb, ROUND(AVG(mbps), 1) AS mbps,
                   COUNT(DISTINCT host) AS hosts, COUNT(DISTINCT ip) AS ips,
                   SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
            FROM cdn_checks WHERE timestamp BETWEEN ? AND ? {extra}
            GROUP BY service, iface_type ORDER BY service""", [cutoff, end, *params]).fetchall()
    return [dict(r) for r in rows]


def speed_by_server(win, iface: str) -> List[Dict[str, Any]]:
    cutoff, end = win
    extra, params = iface_clause(iface)
    rows = conn().execute(
        f"""SELECT server_name, engine, COALESCE(iface_type,'unknown') AS iface_type, COUNT(*) AS n,
                   ROUND(AVG(download_mbps),1) AS dl, ROUND(MIN(download_mbps),1) AS dl_min, ROUND(MAX(download_mbps),1) AS dl_max,
                   ROUND(AVG(upload_mbps),1) AS ul, ROUND(AVG(ping_ms),2) AS ping, ROUND(AVG(jitter_ms),2) AS jitter,
                   ROUND(AVG(packet_loss),2) AS loss
            FROM speedtests WHERE timestamp BETWEEN ? AND ? {extra}
            GROUP BY server_name, iface_type ORDER BY dl DESC""", [cutoff, end, *params]).fetchall()
    return [dict(r) for r in rows]


def data_bounds(win) -> Dict[str, Any]:
    cutoff, end = win
    r = conn().execute(
        """SELECT MIN(t), MAX(t) FROM (
             SELECT MIN(timestamp) t FROM pings WHERE timestamp BETWEEN ? AND ? UNION ALL
             SELECT MAX(timestamp) FROM pings WHERE timestamp BETWEEN ? AND ? UNION ALL
             SELECT MIN(timestamp) FROM speedtests WHERE timestamp BETWEEN ? AND ? UNION ALL
             SELECT MAX(timestamp) FROM speedtests WHERE timestamp BETWEEN ? AND ? UNION ALL
             SELECT MIN(timestamp) FROM site_checks WHERE timestamp BETWEEN ? AND ? UNION ALL
             SELECT MAX(timestamp) FROM site_checks WHERE timestamp BETWEEN ? AND ?)""",
        (cutoff, end) * 6).fetchone()
    return {"first": r[0], "last": r[1]}
