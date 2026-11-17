/* NetMonitor v2 — ön yüz */
'use strict';

const S = {
  cfg: null, meta: null, live: null, data: null,
  range: localStorage.getItem('nm.range') || 'daily',
  iface: localStorage.getItem('nm.iface') || 'all',
  tab: (location.hash || '#overview').slice(1),
  targetsDraft: [], sig: {}, online: false,
};
const charts = {};
const COLORS = { wifi: '#a78bfa', ethernet: '#38bdf8', unknown: '#94a3b8', other: '#f472b6' };
const IFACE_LABEL = { wifi: 'Wi-Fi', ethernet: 'Ethernet', unknown: 'Bilinmiyor', other: 'Diğer' };

const ICON = {
  wifi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 8.8a15 15 0 0 1 20 0"/><path d="M5 12.5a10 10 0 0 1 14 0"/><path d="M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1" fill="currentColor"/></svg>',
  ethernet: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5" width="16" height="12" rx="2"/><path d="M8 17v3h8v-3M8 9v3M11 9v3M14 9v3M17 9v3"/></svg>',
  unknown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>',
  gauge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 14l4-4"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/></svg>',
  pulse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
  route: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="5" r="2.5"/><path d="M8.5 19H16a3.5 3.5 0 0 0 0-7H8a3.5 3.5 0 0 1 0-7h7.5"/></svg>',
  down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5 9-10"/></svg>',
  swap: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18v.5"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
  server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>',
};

// ---------------------------------------------------------------- yardımcılar
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const isNum = (v) => v !== null && v !== undefined && !Number.isNaN(Number(v));
const fx = (v, d = 1) => (isNum(v) ? Number(v).toLocaleString('tr-TR', { maximumFractionDigits: d, minimumFractionDigits: 0 }) : '—');
const fms = (v) => (isNum(v) ? `${fx(v, v < 10 ? 2 : 1)} ms` : '—');
const fpct = (v) => (isNum(v) ? `%${fx(v, 1)}` : '—');
const fspeed = (v) => (!isNum(v) ? '—' : v >= 1000 ? `${fx(v / 1000, 2)} Gbps` : `${fx(v, v < 100 ? 1 : 0)} Mbps`);
const ilabel = (t) => IFACE_LABEL[t] || t || '—';
const chip = (t) => `<span class="chip ${esc(t)}">${ICON[t] || ''}${esc(ilabel(t))}</span>`;
const th = () => (S.cfg && S.cfg.thresholds) || { ping_good: 30, ping_warn: 80, jitter_good: 5, jitter_warn: 15, loss_alert: 5, rssi_weak: -75 };

function grade(kind, v) {
  if (!isNum(v)) return '';
  const t = th();
  if (kind === 'ping') return v < t.ping_good ? 'good' : v <= t.ping_warn ? 'warn' : 'bad';
  if (kind === 'jitter') return v < t.jitter_good ? 'good' : v <= t.jitter_warn ? 'warn' : 'bad';
  if (kind === 'loss') return v === 0 ? 'good' : v <= t.loss_alert ? 'warn' : 'bad';
  if (kind === 'rssi') return v >= -60 ? 'good' : v >= t.rssi_weak ? 'warn' : 'bad';
  return '';
}
const gcol = (g) => ({ good: 'var(--good)', warn: 'var(--warn)', bad: 'var(--bad)' }[g] || 'var(--dim)');
const gv = (kind, v, f) => `<span class="c-${grade(kind, v)}">${f(v)}</span>`;

function tlabel(ts) {
  if (!ts) return '';
  const [d, t] = ts.split(' ');
  const [, m, day] = d.split('-');
  if (S.range === 'hourly') return t.slice(0, 8);
  if (S.range === 'daily') return t.slice(0, 5);
  return `${day}.${m} ${t.slice(0, 5)}`;
}
function ago(ts) {
  if (!ts) return '—';
  const d = (Date.now() - new Date(ts.replace(' ', 'T')).getTime()) / 1000;
  if (d < 60) return 'az önce';
  if (d < 3600) return `${Math.round(d / 60)} dk önce`;
  if (d < 86400) return `${Math.round(d / 3600)} sa önce`;
  return `${Math.round(d / 86400)} gün önce`;
}
function dur(sec) {
  if (sec === null || sec === undefined) return '';
  if (sec < 60) return `${sec} sn`;
  if (sec < 3600) return `${Math.round(sec / 60)} dk`;
  return `${(sec / 3600).toFixed(1)} sa`;
}
function bars(rssi) {
  const q = !isNum(rssi) ? 0 : rssi >= -55 ? 4 : rssi >= -67 ? 3 : rssi >= -75 ? 2 : 1;
  return `<span class="bars q${q}" style="color:${gcol(grade('rssi', rssi))}"><i></i><i></i><i></i><i></i></span>`;
}
function toast(msg, err = false) {
  const el = document.createElement('div');
  el.className = 'toast' + (err ? ' err' : '');
  el.textContent = msg;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) { /* */ }
    throw new Error(msg);
  }
  return res.json();
}
const targetName = (id) => (S.data?.targets || S.cfg?.targets || []).find((t) => t.id === id)?.name || id;

// ---------------------------------------------------------------- grafikler
Chart.defaults.color = '#8a99ab';
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.font.size = 11;
Chart.defaults.borderColor = 'rgba(138,153,171,.12)';

function baseOpts(extra = {}) {
  return {
    responsive: true, maintainAspectRatio: false, animation: false, spanGaps: true, normalized: true,
    interaction: { mode: 'index', intersect: false },
    elements: { point: { radius: 0, hoverRadius: 4, hitRadius: 6 }, line: { borderWidth: 2, tension: 0.25 } },
    plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'rectRounded', padding: 14 } },
      tooltip: { backgroundColor: '#171f2a', borderColor: '#2c3949', borderWidth: 1, padding: 10, titleColor: '#e6edf5', bodyColor: '#c7d2de' },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxTicksLimit: 9, maxRotation: 0, autoSkip: true } },
      y: { beginAtZero: true, grid: { color: 'rgba(138,153,171,.1)' } },
    },
    ...extra,
  };
}
function chart(id, type, data, options) {
  const el = $(id);
  if (!el) return null;
  let c = charts[id];
  if (c && c.canvas !== el) { c.destroy(); c = null; }
  if (!c) { c = new Chart(el, { type, data, options }); charts[id] = c; return c; }
  // görünürlük tercihlerini koru
  const hidden = {};
  c.data.datasets.forEach((d, i) => { hidden[d.label] = !c.isDatasetVisible(i); });
  data.datasets.forEach((d) => { if (d.label in hidden) d.hidden = hidden[d.label]; });
  c.data = data;
  c.update('none');
  return c;
}
function alpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// ---------------------------------------------------------------- canlı durum
async function pollLive() {
  try {
    S.live = await api('/api/live');
    S.online = true;
    renderLive();
  } catch (e) {
    S.online = false;
    const l = $('live');
    l.className = 'live err';
    l.querySelector('span').textContent = 'Sunucuya ulaşılamıyor';
  }
}

function defaultIface() {
  const n = S.live?.network;
  return n?.interfaces?.find((i) => i.name === n.default_iface) || null;
}
const physical = () => (S.live?.network?.interfaces || []).filter((i) => !i.virtual && (i.type === 'wifi' || i.type === 'ethernet'));

function renderLive() {
  const L = S.live;
  const l = $('live');
  const anyRunning = Object.values(L.jobs).some((j) => j.running && j !== L.jobs.netinfo);
  l.className = 'live on';
  l.querySelector('span').textContent = anyRunning ? 'Test çalışıyor…' : `Canlı · ${L.time.slice(11)}`;

  // bağlantı hapı
  const d = defaultIface();
  const pill = $('conn-pill');
  if (d) {
    const w = d.wifi || {};
    const parts = [ilabel(d.type)];
    if (d.type === 'wifi') { if (w.ssid) parts.push(w.ssid); if (isNum(w.rssi_dbm)) parts.push(`${w.rssi_dbm} dBm`); }
    else if (d.link_speed_mbps) parts.push(fspeed(d.link_speed_mbps));
    parts.push(d.ipv4 || '');
    pill.innerHTML = `<span class="ico" style="background:${alpha(COLORS[d.type] || COLORS.unknown, .15)};color:${COLORS[d.type] || COLORS.unknown}">${ICON[d.type] || ICON.unknown}</span>
      <span class="txt">${parts.filter(Boolean).map(esc).join(' <span class="dim">·</span> ')}</span>
      ${d.type === 'wifi' ? bars(w.rssi_dbm) : ''}`;
  } else {
    pill.innerHTML = `<span class="ico" style="background:rgba(248,113,113,.15);color:var(--bad)">${ICON.down}</span><span class="txt c-bad">Ağ bağlantısı yok</span>`;
  }

  const modeNames = { auto: 'Otomatik', wifi: 'Yalnızca Wi-Fi', ethernet: 'Yalnızca Ethernet', both: 'Wi-Fi + Ethernet' };
  $('mode-chip').innerHTML = `Test modu: <b style="color:var(--text)">${modeNames[L.mode]}</b>`;

  // uyarılar
  const warns = [...L.warnings];
  physical().forEach((i) => { if (i.type === 'wifi' && i.connected && i.wifi?.note) warns.push(`Wi-Fi: ${i.wifi.note}`); });
  if (L.paused_for_heavy_test) warns.push('Hız testi sürüyor — ping ölçümleri geçici olarak beklemede.');
  $('warnings').innerHTML = [...new Set(warns)].map((w) => `<div class="alert warn">${ICON.warn}<span>${esc(w)}</span></div>`).join('');

  renderStartStop();
  renderUpdate();
  renderJobs();
  renderKpis();
  renderIfaces();
  renderModeAvailability();
}

function renderJobs() {
  const J = S.live.jobs;
  const def = [
    ['ping', 'Ping & Jitter', ICON.pulse, '#fbbf24', 'ping_running', 'ping_interval', 1],
    ['speedtest', 'Hız Testi', ICON.gauge, '#3dd6c6', 'speedtest_running', 'speedtest_interval', 60],
    ['trace', 'Traceroute', ICON.route, '#a78bfa', 'trace_running', 'trace_interval', 60],
    ['site', 'Site Testi', ICON.globe, '#60a5fa', 'site_running', 'site_interval', 60],
    ['cdn', 'CDN Önbellek', ICON.server, '#f472b6', 'cdn_running', 'cdn_interval', 60],
  ];
  $('jobs').innerHTML = def.map(([k, name, ico, col, en, iv]) => {
    const j = J[k];
    const every = S.cfg ? dur(S.cfg[iv]) : '';
    let line;
    if (j.running) line = `<span><span class="spin"></span> Çalışıyor…</span>`;
    else if (j.last_error) line = `<span class="err" title="${esc(j.last_error)}">⚠ ${esc(j.last_error)}</span>`;
    else if (j.enabled) line = `<span>Her ${every} · sonraki ${dur(j.next_in)} sonra${j.last_run ? ' · son ' + ago(j.last_run) : ''}</span>`;
    else line = `<span>Kapalı${j.last_run ? ' · son çalışma ' + ago(j.last_run) : ''}</span>`;
    return `<div class="job">
      <div class="ico" style="background:${alpha(col, .13)};color:${col}">${ico.replace('<svg', '<svg width="19" height="19"')}</div>
      <div class="meta"><b>${name}</b>${line}</div>
      <button class="btn sm" ${j.running ? 'disabled' : ''} onclick="runNow('${k}')" title="Şimdi çalıştır">${ICON.play.replace('<svg', '<svg width="12" height="12"')} Şimdi</button>
      <label class="switch" title="Zamanlayıcı"><input type="checkbox" ${j.enabled ? 'checked' : ''} onchange="toggleJob('${en}', this.checked)"><span></span></label>
    </div>`;
  }).join('');
}

// n ağırlıklı ortalama; değeri olmayan satırları yok sayar
function wavg(rows, k) {
  const ok = rows.filter((r) => isNum(r[k]));
  const n = ok.reduce((a, r) => a + r.n, 0);
  return n ? ok.reduce((a, r) => a + r[k] * r.n, 0) / n : null;
}

function aggregateStats(iface) {
  const rows = (S.data?.ping_stats || []).filter((r) => r.target_id !== 'gateway' && (!iface || r.iface_type === iface));
  if (!rows.length) return null;
  const w = (k) => wavg(rows, k);
  return { avg: w('avg'), jitter: w('jitter'), loss: w('loss'), uptime: w('uptime'), p95: Math.max(...rows.map((r) => r.p95 ?? 0)), outages: rows.reduce((a, r) => a + r.outages, 0) };
}

function renderKpis() {
  if (!S.live) return;
  const d = defaultIface();
  const wifi = physical().find((i) => i.type === 'wifi');
  const eth = physical().find((i) => i.type === 'ethernet' && i.connected) || physical().find((i) => i.type === 'ethernet');
  const st = S.live.last_speedtest;
  const cards = [];

  // Aktif bağlantı
  cards.push(`<div class="card kpi"><i class="accent-bar" style="background:${COLORS[d?.type] || 'var(--bad)'}"></i>
    <div class="eyebrow">Aktif bağlantı</div>
    <div class="big" style="color:${COLORS[d?.type] || 'var(--bad)'}">${d ? ilabel(d.type) : 'Yok'}</div>
    <div class="row"><span>Arayüz</span><span>${esc(d ? `${d.label}${d.label !== d.name ? ` (${d.name})` : ''}` : '—')}</span></div>
    <div class="row"><span>IP adresi</span><span class="mono">${esc(d?.ipv4 || '—')}</span></div>
    <div class="row"><span>Ağ geçidi</span><span class="mono">${esc(d?.gateway || '—')}</span></div></div>`);

  // Wi-Fi
  if (wifi) {
    const w = wifi.wifi || {};
    const on = wifi.connected;
    cards.push(`<div class="card kpi"><i class="accent-bar" style="background:var(--wifi)"></i>
      <div class="eyebrow">Wi-Fi ${wifi.is_default ? '<span class="chip wifi" style="margin-left:4px">varsayılan</span>' : ''}</div>
      <div class="big">${on && isNum(w.rssi_dbm) ? `<span style="color:${gcol(grade('rssi', w.rssi_dbm))}">${w.rssi_dbm}</span><small>dBm${w.rssi_estimated ? ' ≈' : ''}</small>` : on ? '<span class="c-good">Bağlı</span>' : '<span class="dim">Bağlı değil</span>'}</div>
      ${on ? `<div class="meter"><i style="width:${w.signal_pct ?? 0}%;background:${gcol(grade('rssi', w.rssi_dbm))}"></i></div>
      <div class="row" style="margin-top:6px"><span>Ağ (SSID)</span><span>${esc(w.ssid || 'gizli')}</span></div>
      <div class="row"><span>Kanal / bant</span><span>${w.channel ?? '—'} · ${esc(w.band || '—')}${w.width_mhz ? ` · ${w.width_mhz} MHz` : ''}</span></div>
      <div class="row"><span>Bağlantı hızı</span><span>${fspeed(w.tx_rate_mbps)} ${w.phy ? `<span class="dim">${esc(w.phy)}</span>` : ''}</span></div>
      ${isNum(w.snr_db) ? `<div class="row"><span>SNR</span><span>${w.snr_db} dB</span></div>` : ''}` : `<div class="row"><span>Adaptör</span><span>${esc(wifi.description || wifi.name)}</span></div>`}
    </div>`);
  } else {
    cards.push(`<div class="card kpi"><i class="accent-bar" style="background:var(--line-2)"></i><div class="eyebrow">Wi-Fi</div><div class="big dim">—</div><div class="row"><span>Wi-Fi adaptörü bulunamadı</span><span></span></div></div>`);
  }

  // Ethernet
  if (eth) {
    const on = eth.connected;
    cards.push(`<div class="card kpi"><i class="accent-bar" style="background:var(--eth)"></i>
      <div class="eyebrow">Ethernet ${eth.is_default ? '<span class="chip ethernet" style="margin-left:4px">varsayılan</span>' : ''}</div>
      <div class="big">${on ? `<span style="color:var(--eth)">${eth.link_speed_mbps ? fspeed(eth.link_speed_mbps).replace(' ', '</span><small>') + '</small>' : 'Bağlı</span>'}` : '<span class="dim">Kablo yok</span>'}</div>
      <div class="row"><span>Arayüz</span><span>${esc(eth.label)}</span></div>
      <div class="row"><span>IP adresi</span><span class="mono">${esc(eth.ipv4 || '—')}</span></div>
      <div class="row"><span>Çift yön</span><span>${eth.duplex === 'full' ? 'Full duplex' : eth.duplex === 'half' ? '<span class="c-warn">Half duplex</span>' : '—'}</span></div></div>`);
  } else {
    cards.push(`<div class="card kpi"><i class="accent-bar" style="background:var(--line-2)"></i><div class="eyebrow">Ethernet</div><div class="big dim">—</div><div class="row"><span>Ethernet adaptörü bulunamadı</span><span></span></div></div>`);
  }

  // Son hız testi
  cards.push(`<div class="card kpi"><i class="accent-bar" style="background:var(--accent)"></i>
    <div class="eyebrow">Son hız testi</div>
    ${st ? `<div class="big">${fx(st.download_mbps, 0)}<small>↓ Mbps</small> <span style="font-size:20px;color:var(--muted)">${fx(st.upload_mbps, 0)}<small>↑</small></span></div>
    <div class="row"><span>Ping / jitter</span><span>${gv('ping', st.ping_ms, fms)} · ${gv('jitter', st.jitter_ms, fms)}</span></div>
    <div class="row"><span>Bağlantı</span><span>${chip(st.iface_type || 'unknown')}</span></div>
    <div class="row"><span>Zaman</span><span>${ago(st.timestamp)} · ${esc(st.engine || '')}</span></div>`
    : '<div class="big dim">—</div><div class="row"><span>Henüz hız testi yapılmadı</span><span></span></div>'}</div>`);

  // Gecikme özeti
  const groups = ['wifi', 'ethernet', 'unknown'].map((t) => [t, aggregateStats(t)]).filter(([, a]) => a);
  const all = aggregateStats(null);
  cards.push(`<div class="card kpi"><i class="accent-bar" style="background:var(--warn)"></i>
    <div class="eyebrow">İnternet gecikmesi · ${rangeName()}</div>
    ${all ? `<div class="big">${gv('ping', all.avg, (v) => fx(v, 1))}<small>ms ort.</small></div>
      ${groups.length > 1 ? groups.map(([t, a]) => `<div class="row"><span>${chip(t)}</span><span>${gv('ping', a.avg, fms)} · kayıp ${gv('loss', (isNum(a.loss) ? +a.loss.toFixed(2) : null), fpct)}</span></div>`).join('')
        : `<div class="row"><span>P95 (en kötü hedef)</span><span>${fms(all.p95)}</span></div>
           <div class="row"><span>Jitter</span><span>${gv('jitter', all.jitter, fms)}</span></div>
           <div class="row"><span>Paket kaybı</span><span>${gv('loss', (isNum(all.loss) ? +all.loss.toFixed(2) : null), fpct)}</span></div>`}
      <div class="row"><span>Erişilebilirlik</span><span>${fpct(all.uptime)}</span></div>`
    : '<div class="big dim">—</div><div class="row"><span>Ping ölçümü yok</span><span></span></div>'}</div>`);

  $('kpis').innerHTML = cards.join('');
}

function renderIfaces() {
  const list = physical();
  if (!list.length) { $('ifaces').innerHTML = '<div class="card empty"><b>Fiziksel ağ arayüzü bulunamadı</b>Ağ bağlantınızı kontrol edin.</div>'; return; }
  $('ifaces').innerHTML = list.map((i) => {
    const w = i.wifi || {};
    const col = COLORS[i.type];
    const status = i.connected ? '<span class="chip good">Bağlı</span>' : i.up ? '<span class="chip warn">IP yok</span>' : '<span class="chip">Bağlı değil</span>';
    const rows = [
      ['Arayüz', `${esc(i.name)}`], ['IPv4', `<span class="mono">${esc(i.ipv4 || '—')}</span>`],
      ['Ağ geçidi', `<span class="mono">${esc(i.gateway || '—')}</span>`], ['MAC', `<span class="mono">${esc(i.mac || '—')}</span>`],
    ];
    if (i.type === 'wifi' && i.connected) {
      rows.push(['SSID', esc(w.ssid || (w.note ? 'gizli' : '—'))], ['BSSID', `<span class="mono">${esc(w.bssid || '—')}</span>`],
        ['Sinyal', isNum(w.rssi_dbm) ? `${bars(w.rssi_dbm)} <span style="color:${gcol(grade('rssi', w.rssi_dbm))}">${w.rssi_dbm} dBm${w.rssi_estimated ? ' (tahmini)' : ''}</span> · %${w.signal_pct} · ${esc(w.quality || '')}` : '—'],
        ['Gürültü / SNR', isNum(w.noise_dbm) ? `${w.noise_dbm} dBm · ${w.snr_db} dB` : '—'],
        ['Kanal', `${w.channel ?? '—'} · ${esc(w.band || '—')}${w.width_mhz ? ` · ${w.width_mhz} MHz` : ''}`],
        ['Standart', esc(w.phy || '—')], ['TX / RX hızı', `${fspeed(w.tx_rate_mbps)} / ${fspeed(w.rx_rate_mbps)}`],
        ['Güvenlik', esc(w.security || '—')]);
    } else {
      rows.push(['Link hızı', fspeed(i.link_speed_mbps)], ['Çift yön', i.duplex === 'full' ? 'Full' : i.duplex === 'half' ? '<span class="c-warn">Half</span>' : '—'], ['MTU', i.mtu ?? '—']);
    }
    return `<div class="card iface">
      <div class="ih"><div class="ico" style="background:${alpha(col, .14)};color:${col}">${ICON[i.type].replace('<svg', '<svg width="19" height="19"')}</div>
        <div style="min-width:0;flex:1"><b>${esc(ilabel(i.type))}${i.label && i.label.toLowerCase() !== ilabel(i.type).toLowerCase() ? ` · ${esc(i.label)}` : ''}</b><small>${esc(i.description || i.name)}</small></div>
        <div style="display:grid;gap:4px;justify-items:end">${status}${i.is_default ? '<span class="chip" style="color:var(--accent)">varsayılan</span>' : ''}</div></div>
      <dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
      ${w.note && i.connected ? `<div class="kpi"><div class="note">${esc(w.note)}</div></div>` : ''}
    </div>`;
  }).join('');
}

function renderModeAvailability() {
  const wifi = physical().find((i) => i.type === 'wifi' && i.connected);
  const eth = physical().find((i) => i.type === 'ethernet' && i.connected);
  const d = defaultIface();
  const fmt = (i) => (i ? `<span class="c-good">● Bağlı: ${esc(i.label)} · ${esc(i.ipv4)}</span>` : '<span class="c-bad">● Bağlı değil</span>');
  $('m-auto').innerHTML = d ? `Şu an: ${ilabel(d.type)} (${esc(d.label)})` : 'Bağlantı yok';
  $('m-wifi').innerHTML = fmt(wifi);
  $('m-ethernet').innerHTML = fmt(eth);
  $('m-both').innerHTML = wifi && eth ? '<span class="c-good">● İki bağlantı da hazır</span>' : '<span class="c-warn">● İkisinin de bağlı olması gerekir</span>';
}

// ---------------------------------------------------------------- veri
const rangeName = () => ({ hourly: 'son 1 saat', daily: 'son 24 saat', weekly: 'son 7 gün', monthly: 'son 30 gün' }[S.range]);

let dataBusy = false;
async function refreshData() {
  if (dataBusy) return;
  dataBusy = true;
  try {
    S.data = await api(`/api/data?range=${S.range}&iface=${S.iface}`);
    renderData();
  } catch (e) {
    console.error(e);
  } finally {
    dataBusy = false;
  }
}

function renderData() {
  renderKpis();
  renderTiles();
  renderPingCards();
  renderPingTable();
  renderSpeed();
  renderWifi();
  renderCompare();
  renderTraces();
  renderEvents();
  renderSites();
  renderCdn();
}

function seriesKey(s) { return `${s.target_id}|${s.iface_type}`; }

function renderTiles() {
  const stats = S.data.ping_stats;
  const series = Object.fromEntries(S.data.ping_series.map((s) => [seriesKey(s), s]));
  const order = (S.data.targets || []).map((t) => t.id);
  stats.sort((a, b) => (order.indexOf(a.target_id) - order.indexOf(b.target_id)) || a.iface_type.localeCompare(b.iface_type));
  const el = $('tiles');
  if (!stats.length) {
    el.innerHTML = `<div class="empty" style="grid-column:1/-1"><b>Henüz ping ölçümü yok</b>Yukarıdaki "Ping &amp; Jitter" zamanlayıcısını açın veya "Şimdi" ile tek seferlik ölçüm yapın.</div>`;
    S.sig.tiles = '';
    return;
  }
  const sig = stats.map(seriesKey).join(',');
  if (S.sig.tiles !== sig) {
    el.innerHTML = stats.map((s, i) => `<div class="tile" id="tile-${i}">
      <div class="t-head"><span class="dot"></span><b>${esc(targetName(s.target_id))}</b>${chip(s.iface_type)}</div>
      <div class="vals"><span class="main"></span><span class="sub"></span></div>
      <div class="spark"><canvas id="spark-${i}"></canvas></div></div>`).join('');
    Object.keys(charts).filter((k) => k.startsWith('spark-')).forEach((k) => { charts[k].destroy(); delete charts[k]; });
    S.sig.tiles = sig;
  }
  stats.forEach((s, i) => {
    const tile = $(`tile-${i}`);
    const last = s.last || {};
    const g = last.packet_loss >= 100 ? 'bad' : grade('ping', last.avg_ping);
    tile.querySelector('.dot').style.background = gcol(g);
    tile.querySelector('.main').innerHTML = last.packet_loss >= 100 ? '<span class="c-bad">Erişilemiyor</span>' : `${gv('ping', last.avg_ping, (v) => fx(v, 1))}<small> ms</small>`;
    tile.querySelector('.sub').innerHTML = `jitter ${fms(last.jitter)} · kayıp ${gv('loss', last.packet_loss, fpct)}<br><span class="dim">ort. ${fms(s.avg)} · %${fx(s.uptime, 1)} erişim</span>`;
    const pts = (series[seriesKey(s)]?.points || []).slice(-120);
    const col = COLORS[s.iface_type] || COLORS.unknown;
    chart(`spark-${i}`, 'line', {
      labels: pts.map((p) => tlabel(p[0])),
      datasets: [{ data: pts.map((p) => p[1]), borderColor: col, backgroundColor: alpha(col, .12), fill: true, borderWidth: 1.5, tension: .3 }],
    }, { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false, beginAtZero: true } }, elements: { point: { radius: 0 } } });
  });
}

function renderPingCards() {
  const groups = {};
  S.data.ping_series.forEach((s) => { (groups[s.target_id] ||= []).push(s); });
  const statsBy = {};
  S.data.ping_stats.forEach((s) => { statsBy[seriesKey(s)] = s; });
  const order = (S.data.targets || []).map((t) => t.id);
  const ids = Object.keys(groups).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const el = $('ping-cards');
  if (!ids.length) { el.innerHTML = '<div class="card empty"><b>Bu periyotta ping verisi yok</b>Ayarlar\'dan ping zamanlayıcısını açabilirsiniz.</div>'; S.sig.ping = ''; return; }
  const sig = ids.map((id) => id + ':' + groups[id].map((s) => s.iface_type).sort().join('+')).join(',');
  if (S.sig.ping !== sig) {
    el.innerHTML = ids.map((id, i) => `<div class="card"><div class="card-h"><h2>${esc(targetName(id))}</h2>
      <span class="sub mono">${esc(((S.data.targets || []).find((t) => t.id === id) || {}).host || '')}</span></div>
      <div id="pstats-${i}"></div><div class="chart-box sm"><canvas id="pchart-${i}"></canvas></div></div>`).join('');
    Object.keys(charts).filter((k) => k.startsWith('pchart-')).forEach((k) => { charts[k].destroy(); delete charts[k]; });
    S.sig.ping = sig;
  }
  ids.forEach((id, i) => {
    const ss = groups[id].sort((a, b) => a.iface_type.localeCompare(b.iface_type));
    $(`pstats-${i}`).innerHTML = ss.map((s) => {
      const st = statsBy[seriesKey(s)] || {};
      return `<div class="stat-group">${ss.length > 1 ? `<div class="lbl">${chip(s.iface_type)}</div>` : ''}<div class="stats">
        <div class="stat"><div class="k">Ortalama</div><div class="v">${gv('ping', st.avg, fms)}</div></div>
        <div class="stat"><div class="k">P95</div><div class="v">${gv('ping', st.p95, fms)}</div></div>
        <div class="stat"><div class="k">Min / Max</div><div class="v">${fx(st.min, 1)} / ${fx(st.max, 0)}</div></div>
        <div class="stat"><div class="k">Jitter</div><div class="v">${gv('jitter', st.jitter, fms)}</div></div>
        <div class="stat"><div class="k">Kayıp</div><div class="v">${gv('loss', st.loss, fpct)}</div></div>
        <div class="stat"><div class="k">Erişilebilirlik</div><div class="v">${fpct(st.uptime)}</div></div>
        <div class="stat"><div class="k">Kesinti</div><div class="v ${st.outages ? 'c-bad' : ''}">${st.outages ?? 0}</div></div></div></div>`;
    }).join('');
    const labelsTs = [...new Set(ss.flatMap((s) => s.points.map((p) => p[0])))].sort();
    const idx = Object.fromEntries(labelsTs.map((t, k) => [t, k]));
    const datasets = [];
    ss.forEach((s) => {
      const col = COLORS[s.iface_type] || COLORS.unknown;
      const arr = (k) => { const a = new Array(labelsTs.length).fill(null); s.points.forEach((p) => { a[idx[p[0]]] = p[k]; }); return a; };
      const name = ss.length > 1 ? `${ilabel(s.iface_type)} ` : '';
      datasets.push({ label: `${name}Ort. ping`, data: arr(1), borderColor: col, backgroundColor: alpha(col, .1), fill: ss.length === 1, yAxisID: 'y' });
      datasets.push({ label: `${name}Max ping`, data: arr(2), borderColor: alpha(col, .55), borderDash: [4, 4], borderWidth: 1.2, yAxisID: 'y', hidden: ss.length > 1 });
      datasets.push({ label: `${name}Jitter`, data: arr(3), borderColor: s.iface_type === 'ethernet' ? '#facc15' : '#f472b6', borderWidth: 1.2, yAxisID: 'y', hidden: true });
      datasets.push({ type: 'bar', label: `${name}Kayıp %`, data: arr(4).map((v) => (v ? v : null)), backgroundColor: alpha('#f87171', ss.length > 1 && s.iface_type === 'wifi' ? .45 : .6), yAxisID: 'y2', barPercentage: 1, categoryPercentage: 1 });
    });
    const opts = baseOpts();
    opts.scales.y.title = { display: true, text: 'ms' };
    opts.scales.y2 = { position: 'right', min: 0, max: 100, grid: { display: false }, ticks: { callback: (v) => `%${v}` }, title: { display: true, text: 'kayıp' } };
    opts.plugins.tooltip.callbacks = { label: (c) => `${c.dataset.label}: ${c.parsed.y === null ? '—' : fx(c.parsed.y, 2)}${c.dataset.yAxisID === 'y2' ? ' %' : ' ms'}` };
    chart(`pchart-${i}`, 'line', { labels: labelsTs.map(tlabel), datasets }, opts);
  });
}

function renderPingTable() {
  const rows = S.data.recent_pings;
  $('ping-table').innerHTML = rows.length ? rows.map((p) => `<tr>
    <td>${esc(p.timestamp)}</td><td>${esc(p.target_name)} <span class="dim mono">${esc(p.host)}</span></td><td>${chip(p.iface_type || 'unknown')}</td>
    <td class="r">${gv('ping', p.avg_ping, fms)}</td><td class="r">${fms(p.min_ping)}</td><td class="r">${fms(p.max_ping)}</td>
    <td class="r">${gv('jitter', p.jitter, fms)}</td><td class="r">${gv('loss', p.packet_loss, fpct)}</td>
    <td class="r">${isNum(p.wifi_rssi) ? `${p.wifi_rssi} dBm` : '<span class="dim">—</span>'}</td></tr>`).join('')
    : '<tr><td colspan="9" class="empty">Kayıt yok</td></tr>';
}

function renderSpeed() {
  const rows = S.data.speedtests;
  // KPI'lar
  const by = S.data.speed_by_iface.filter((r) => S.iface === 'all' || r.iface_type === S.iface);
  $('speed-kpis').innerHTML = by.length ? by.map((r) => `<div class="card kpi"><i class="accent-bar" style="background:${COLORS[r.iface_type] || COLORS.unknown}"></i>
    <div class="eyebrow">${esc(ilabel(r.iface_type))} · ${r.n} test · ${rangeName()}</div>
    <div class="big">${fx(r.dl, 0)}<small>↓ Mbps ort.</small></div>
    <div class="row"><span>Upload ort.</span><span>${fx(r.ul, 1)} Mbps</span></div>
    <div class="row"><span>En yüksek download</span><span>${fx(r.dl_max, 0)} Mbps</span></div>
    <div class="row"><span>Ping / jitter</span><span>${gv('ping', r.ping, fms)} · ${gv('jitter', r.jitter, fms)}</span></div></div>`).join('')
    : '<div class="card empty" style="grid-column:1/-1"><b>Bu periyotta hız testi yok</b>"Şimdi test et" ile başlatabilirsiniz.</div>';

  const types = [...new Set(rows.map((r) => r.iface_type || 'unknown'))];
  const labels = rows.map((r) => tlabel(r.timestamp));
  const datasets = [];
  types.forEach((t) => {
    const col = COLORS[t] || COLORS.unknown;
    const pre = types.length > 1 ? `${ilabel(t)} ` : '';
    datasets.push({ label: `${pre}Download`, data: rows.map((r) => ((r.iface_type || 'unknown') === t ? r.download_mbps : null)), borderColor: col, backgroundColor: alpha(col, .12), fill: types.length === 1, pointRadius: 3 });
    datasets.push({ label: `${pre}Upload`, data: rows.map((r) => ((r.iface_type || 'unknown') === t ? r.upload_mbps : null)), borderColor: types.length > 1 ? alpha(col, .6) : '#34d399', borderDash: types.length > 1 ? [5, 4] : [], pointRadius: 3 });
  });
  const opts = baseOpts();
  opts.scales.y.title = { display: true, text: 'Mbps' };
  chart('speedChart', 'line', { labels, datasets }, opts);

  $('speed-table').innerHTML = rows.length ? [...rows].reverse().map((r) => `<tr>
    <td>${esc(r.timestamp)}</td><td>${chip(r.iface_type || 'unknown')}</td>
    <td>${esc(r.engine || '')} <span class="dim">${esc(r.server_name || '')}</span>${r.result_url ? ` <a href="${esc(r.result_url)}" target="_blank" rel="noopener">↗</a>` : ''}</td>
    <td class="r c-eth" style="font-weight:700">${fx(r.download_mbps, 1)}</td><td class="r c-good" style="font-weight:700">${fx(r.upload_mbps, 1)}</td>
    <td class="r">${gv('ping', r.ping_ms, fms)}</td><td class="r">${gv('jitter', r.jitter_ms, fms)}</td>
    <td class="r">${isNum(r.packet_loss) ? gv('loss', r.packet_loss, fpct) : '<span class="dim">—</span>'}</td>
    <td class="r">${isNum(r.wifi_rssi) ? `${r.wifi_rssi} dBm` : '<span class="dim">—</span>'}</td></tr>`).join('')
    : '<tr><td colspan="9" class="empty">Kayıt yok</td></tr>';
}

function renderWifi() {
  const series = S.data.wifi_series;
  const has = series.some((s) => s.points.length);
  $('wifiChart').parentElement.classList.toggle('hidden', !has);
  $('wifi-empty').classList.toggle('hidden', has);
  const sum = S.data.wifi_summary;
  $('wifi-sum').innerHTML = sum ? `<span class="chip">ort. ${sum.avg_rssi} dBm</span><span class="chip">en kötü ${sum.min_rssi} dBm</span><span class="chip">${sum.bssids} erişim noktası</span><span class="chip">${sum.channels} kanal</span>` : '';
  if (!has) return;
  const labelsTs = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort();
  const idx = Object.fromEntries(labelsTs.map((t, k) => [t, k]));
  const datasets = [];
  series.forEach((s) => {
    const arr = (k) => { const a = new Array(labelsTs.length).fill(null); s.points.forEach((p) => { a[idx[p[0]]] = p[k]; }); return a; };
    const pre = series.length > 1 ? `${s.iface_name} ` : '';
    datasets.push({ label: `${pre}RSSI ort.`, data: arr(1), borderColor: COLORS.wifi, backgroundColor: alpha(COLORS.wifi, .12), fill: 'start', yAxisID: 'y' });
    datasets.push({ label: `${pre}RSSI min`, data: arr(2), borderColor: alpha(COLORS.wifi, .5), borderDash: [4, 4], borderWidth: 1.2, yAxisID: 'y' });
    datasets.push({ label: `${pre}Gürültü`, data: arr(3), borderColor: '#64748b', borderWidth: 1.2, yAxisID: 'y', hidden: true });
    datasets.push({ label: `${pre}Bağlantı hızı`, data: arr(4), borderColor: '#3dd6c6', borderWidth: 1.5, yAxisID: 'y2' });
  });
  const opts = baseOpts();
  opts.scales.y = { min: -95, max: -25, grid: { color: 'rgba(138,153,171,.1)' }, title: { display: true, text: 'dBm' } };
  opts.scales.y2 = { position: 'right', beginAtZero: true, grid: { display: false }, title: { display: true, text: 'Mbps' } };
  opts.plugins.tooltip.callbacks = { label: (c) => `${c.dataset.label}: ${c.parsed.y ?? '—'} ${c.dataset.yAxisID === 'y2' ? 'Mbps' : 'dBm'}` };
  chart('wifiChart', 'line', { labels: labelsTs.map(tlabel), datasets }, opts);
}

function renderCompare() {
  const el = $('compare');
  if (S.iface !== 'all') { el.innerHTML = '<div class="alert info">' + ICON.info + '<span>Karşılaştırma için üstteki <b>Bağlantı</b> filtresini "Tümü" yapın.</span></div>'; return; }
  const st = {};
  S.data.ping_stats.forEach((s) => { (st[s.target_id] ||= {})[s.iface_type] = s; });
  const ids = Object.keys(st).filter((id) => st[id].wifi && st[id].ethernet);
  const sp = Object.fromEntries(S.data.speed_by_iface.map((r) => [r.iface_type, r]));
  if (!ids.length && !(sp.wifi && sp.ethernet)) {
    el.innerHTML = `<div class="alert info">${ICON.info}<span>Henüz iki bağlantıdan da ölçüm yok. Wi-Fi ve Ethernet'i aynı anda bağlayıp
      <a href="#settings" onclick="showTab('settings')">Ayarlar → Test Bağlantısı</a> bölümünden <b>İkisi birden · Karşılaştır</b> modunu seçin.
      Ölçümler her iki bağlantı üzerinden eşzamanlı yapılır ve burada yan yana gösterilir.</span></div>`;
    return;
  }
  const cell = (a, b, f, lowerBetter = true) => {
    const w = isNum(a) && isNum(b) && a !== b ? ((a < b) === lowerBetter ? 'a' : 'b') : '';
    return `<td class="r ${w === 'a' ? 'win' : ''}">${f(a)}</td><td class="r ${w === 'b' ? 'win' : ''}">${f(b)}</td>`;
  };
  let html = '<div class="table-wrap cmp" style="max-height:none"><table><thead><tr><th rowspan="2">Hedef</th>' +
    ['Ort. ping', 'P95', 'Jitter', 'Kayıp', 'Erişim'].map((h) => `<th colspan="2" class="r" style="text-align:center">${h}</th>`).join('') +
    '</tr><tr>' + '<th class="r wifi">Wi-Fi</th><th class="r ethernet">Eth</th>'.repeat(5) + '</tr></thead><tbody>';
  html += ids.map((id) => {
    const a = st[id].wifi; const b = st[id].ethernet;
    return `<tr><td>${esc(targetName(id))}</td>${cell(a.avg, b.avg, fms)}${cell(a.p95, b.p95, fms)}${cell(a.jitter, b.jitter, fms)}${cell(a.loss, b.loss, fpct)}${cell(a.uptime, b.uptime, fpct, false)}</tr>`;
  }).join('');
  html += '</tbody></table></div>';
  if (sp.wifi && sp.ethernet) {
    const a = sp.wifi; const b = sp.ethernet;
    html += `<div class="table-wrap cmp" style="max-height:none;margin-top:12px"><table><thead><tr><th>Hız testi ortalaması</th><th class="r wifi">Wi-Fi</th><th class="r ethernet">Ethernet</th><th class="r">Fark</th></tr></thead><tbody>
      ${[['Download', 'dl', false, 'Mbps'], ['Upload', 'ul', false, 'Mbps'], ['Ping', 'ping', true, 'ms'], ['Jitter', 'jitter', true, 'ms']].map(([n, k, lb, u]) => {
        const w = a[k] !== b[k] ? ((a[k] < b[k]) === lb ? 'a' : 'b') : '';
        const diff = isNum(a[k]) && isNum(b[k]) && b[k] ? `${a[k] > b[k] ? '+' : ''}${fx(((a[k] - b[k]) / b[k]) * 100, 0)}%` : '—';
        return `<tr><td>${n}</td><td class="r ${w === 'a' ? 'win' : ''}">${fx(a[k], 1)} ${u}</td><td class="r ${w === 'b' ? 'win' : ''}">${fx(b[k], 1)} ${u}</td><td class="r dim">${diff} <span class="dim">(Wi-Fi)</span></td></tr>`;
      }).join('')}</tbody></table></div>`;
  }
  el.innerHTML = html + '<div class="legend-inline" style="margin-top:10px"><span><b class="c-good">Yeşil</b> = o metrikte daha iyi olan bağlantı</span></div>';
}

function renderTraces() {
  const tr = S.data.traceroutes;
  const note = $('trace-note');
  if (S.meta && !S.meta.trace_bindable) {
    note.classList.remove('hidden');
    note.innerHTML = `${ICON.info}<span>Windows'ta <code>tracert</code> kaynak arayüz seçemediği için traceroute her zaman sistemin varsayılan bağlantısı üzerinden yapılır. Ping ve hız testi seçilen arayüze bağlanır.</span>`;
  }
  const latest = {};
  tr.forEach((t) => { const k = `${t.target_id}|${t.iface_type}`; if (!latest[k]) latest[k] = t; });
  const L = Object.values(latest);
  $('trace-latest').innerHTML = L.length ? L.map((t) => {
    const max = Math.max(1, ...t.hops.map((h) => h.avg || 0));
    return `<div class="card"><div class="card-h"><h3>${esc(t.target_name)}</h3><span class="sub mono">${esc(t.host)}</span>
      <div class="right">${chip(t.iface_type || 'unknown')}<span class="chip">${ago(t.timestamp)}</span></div></div>
      ${t.hops.length ? `<div class="table-wrap hops" style="max-height:340px"><table><thead><tr><th>#</th><th>IP</th><th class="r">Ort.</th><th class="r">En iyi</th><th class="r">Kayıp</th><th></th></tr></thead><tbody>
      ${t.hops.map((h) => `<tr><td class="dim">${h.hop}</td><td class="mono">${h.ip ? esc(h.ip) : '<span class="dim">* * *</span>'}</td>
        <td class="r">${h.avg !== null ? gv('ping', h.avg, fms) : '<span class="dim">—</span>'}</td><td class="r">${fms(h.best)}</td>
        <td class="r">${h.loss ? `<span class="${h.loss >= 100 ? 'dim' : 'c-warn'}">%${h.loss}</span>` : '%0'}</td>
        <td class="bar"><div class="hopbar"><i style="width:${((h.avg || 0) / max) * 100}%;background:${gcol(grade('ping', h.avg))}"></i></div></td></tr>`).join('')}
      </tbody></table></div>` : '<div class="empty">Çıktı ayrıştırılamadı</div>'}
      <details class="raw"><summary>Ham çıktı</summary><pre>${esc(t.output)}</pre></details></div>`;
  }).join('') : '<div class="card empty" style="grid-column:1/-1"><b>Traceroute kaydı yok</b>Ayarlar\'dan traceroute hedeflerini seçip zamanlayıcıyı açın.</div>';

  $('trace-table').innerHTML = tr.length ? tr.map((t) => {
    const last = [...t.hops].reverse().find((h) => h.avg !== null);
    return `<tr><td>${esc(t.timestamp)}</td><td>${esc(t.target_name)}</td><td>${chip(t.iface_type || 'unknown')}</td><td class="r">${t.hops.length}</td>
      <td class="r">${last ? fms(last.avg) : '—'}</td><td class="mono dim">${t.hops.slice(0, 6).map((h) => esc(h.ip || '*')).join(' → ')}</td></tr>`;
  }).join('') : '<tr><td colspan="6" class="empty">Kayıt yok</td></tr>';
}

function renderEvents() {
  const ev = S.data.events;
  const downs = ev.filter((e) => e.kind === 'down').length;
  const c = $('ev-count');
  c.textContent = downs;
  c.classList.toggle('hidden', !downs);
  const icon = { down: ICON.down, up: ICON.up, default: ICON.swap, roam: ICON.swap, ssid: ICON.wifi, channel: ICON.wifi, weak: ICON.warn, weak_ok: ICON.up, speed: ICON.ethernet, start: ICON.play };
  $('events').innerHTML = ev.length ? ev.map((e) => `<div class="ev ${esc(e.severity)}">
    <div class="when">${esc(e.timestamp)}</div><div class="badge">${icon[e.kind] || ICON.info}</div>
    <div class="msg">${esc(e.message)} ${e.iface_type ? chip(e.iface_type) : ''}</div></div>`).join('')
    : '<div class="empty"><b>Bu periyotta olay yok</b>Bağlantı kopmaları ve Wi-Fi değişiklikleri burada listelenir.</div>';
}

// ---------------------------------------------------------------- eylemler
async function runNow(job) {
  try {
    const r = await api(`/api/run-now/${job}`, { method: 'POST' });
    toast(r.status === 'already_running' ? 'Bu test zaten çalışıyor' : ({ ping: 'Ping', speedtest: 'Hız testi', trace: 'Traceroute', site: 'Site testi', cdn: 'CDN testi' }[job] + ' başlatıldı'));
    setTimeout(pollLive, 600);
    const wait = { ping: 9000, trace: 30000, speedtest: 40000, site: 9000, cdn: 30000 }[job] || 8000;
    setTimeout(refreshData, wait);
    setTimeout(refreshData, wait * 2);
  } catch (e) { toast(e.message, true); }
}

async function toggleJob(key, val) {
  try {
    const r = await api('/api/config', { method: 'POST', body: JSON.stringify({ [key]: val }) });
    S.cfg = r.config;
    fillSettings();
    toast(val ? 'Zamanlayıcı açıldı' : 'Zamanlayıcı kapatıldı');
    setTimeout(pollLive, 400);
  } catch (e) { toast(e.message, true); }
}

function toggleMenu(ev) {
  ev.stopPropagation();
  $('export-menu').classList.toggle('open');
}
document.addEventListener('click', () => $('export-menu').classList.remove('open'));

function printReport(onlyReport = false) {
  document.body.classList.toggle('print-report', !!onlyReport);
  if (onlyReport) { setTimeout(() => { Object.values(charts).forEach((c) => c.resize()); window.print(); }, 200); return; }
  $('print-meta').textContent = `${rangeName()} · ${S.iface === 'all' ? 'tüm bağlantılar' : ilabel(S.iface)} · oluşturulma ${new Date().toLocaleString('tr-TR')}`;
  document.querySelectorAll('.tab').forEach((t) => t.classList.add('active'));
  setTimeout(() => {
    Object.values(charts).forEach((c) => c.resize());
    window.print();
    showTab(S.tab);
  }, 250);
}

function showTab(tab) {
  if (!$(`tab-${tab}`)) tab = 'overview';
  S.tab = tab;
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.id === `tab-${tab}`));
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  $('toolbar').style.display = tab === 'settings' || tab === 'report' ? 'none' : '';
  if (tab === 'report' && !S.report) loadReport(null);
  if (location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
  requestAnimationFrame(() => Object.values(charts).forEach((c) => c.resize()));
}

function setSeg(id, val) {
  document.querySelectorAll(`#${id} button`).forEach((b) => b.classList.toggle('active', b.dataset.v === val));
}
function updateExportLinks() {
  $('exp-xlsx').href = `/api/export/excel?range=${S.range === 'hourly' ? 'daily' : S.range}`;
  $('exp-csv').href = `/api/export/csv?range=${S.range === 'hourly' ? 'daily' : S.range}`;
}

// ---------------------------------------------------------------- ayarlar
const FIELDS = ['speedtest_running', 'speedtest_engine', 'speedtest_server_id', 'speedtest_interval', 'cf_max_mb', 'pause_ping_during_speedtest',
  'ping_running', 'ping_interval', 'ping_count', 'ping_timeout_ms', 'wifi_interval', 'trace_running', 'trace_interval', 'trace_max_hops',
  'retention_days', 'email_enabled', 'smtp_server', 'smtp_port', 'smtp_user', 'smtp_pass', 'recipient_email', 'alert_cooldown_min',
  'alert_on_loss', 'alert_on_link_down', 'alert_on_weak_wifi', 'site_running', 'site_interval', 'site_resolvers',
  'cdn_running', 'cdn_interval', 'update_repo', 'update_auto_check'];
const TH_FIELDS = ['ping_good', 'ping_warn', 'jitter_good', 'jitter_warn', 'loss_alert', 'rssi_weak'];

function fillSettings() {
  const c = S.cfg;
  FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!c[k];
    else if (el.dataset.scale) el.value = Math.round(c[k] / +el.dataset.scale);
    else el.value = c[k] ?? '';
  });
  TH_FIELDS.forEach((k) => { $(`th_${k}`).value = c.thresholds[k]; });
  document.querySelectorAll('input[name=iface_mode]').forEach((r) => { r.checked = r.value === c.iface_mode; });
}

async function loadSettings() {
  const r = await api('/api/config');
  S.cfg = r.config; S.meta = r.meta; S.defaults = r.defaults;
  $('ver').textContent = `v${r.meta.version}`;
  S.targetsDraft = JSON.parse(JSON.stringify(S.cfg.targets));
  S.sitesDraft = JSON.parse(JSON.stringify(S.cfg.sites || []));
  S.cdnCustomDraft = JSON.parse(JSON.stringify(S.cfg.cdn_custom || []));
  S.ookSel = JSON.parse(JSON.stringify(S.cfg.ookla_servers || []));
  fillSettings();
  renderTargetsEditor();
  renderSitesEditor();
  renderCdnSettings();
  renderOoklaSelected();
  $('upd-current').textContent = `Kurulu sürüm: v${r.meta.version}`;
  $('save-state').textContent = '';
}

function renderTargetsEditor() {
  $('targets-body').innerHTML = S.targetsDraft.map((t, i) => `<tr>
    <td><input class="input sm" value="${esc(t.name)}" oninput="S.targetsDraft[${i}].name=this.value"></td>
    <td><input class="input sm mono" value="${esc(t.host)}" oninput="S.targetsDraft[${i}].host=this.value.trim()" placeholder="8.8.8.8 veya alan adı" ${t.host === '@gateway' ? 'readonly title="Her bağlantının kendi ağ geçidi otomatik kullanılır"' : ''}></td>
    <td><label class="switch"><input type="checkbox" ${t.ping ? 'checked' : ''} onchange="S.targetsDraft[${i}].ping=this.checked"><span></span></label></td>
    <td><label class="switch"><input type="checkbox" ${t.trace ? 'checked' : ''} onchange="S.targetsDraft[${i}].trace=this.checked"><span></span></label></td>
    <td class="r"><button class="btn sm ghost danger" onclick="removeTarget(${i})" title="Sil">Sil</button></td></tr>`).join('');
}
function addTarget() { S.targetsDraft.push({ name: 'Yeni hedef', host: '', ping: true, trace: false }); renderTargetsEditor(); }
function removeTarget(i) { S.targetsDraft.splice(i, 1); renderTargetsEditor(); }
function resetTargets() { S.targetsDraft = JSON.parse(JSON.stringify(S.defaults.targets)); renderTargetsEditor(); toast('Varsayılan hedefler yüklendi — kaydetmeyi unutmayın'); }

async function saveSettings() {
  const patch = {};
  FIELDS.forEach((k) => {
    const el = $(k);
    if (!el) return;
    if (el.type === 'checkbox') patch[k] = el.checked;
    else if (el.type === 'number') patch[k] = Math.round((parseFloat(el.value) || 0) * (+el.dataset.scale || 1));
    else patch[k] = el.value;
  });
  patch.thresholds = Object.fromEntries(TH_FIELDS.map((k) => [k, parseFloat($(`th_${k}`).value)]));
  patch.iface_mode = document.querySelector('input[name=iface_mode]:checked')?.value || 'auto';
  patch.targets = S.targetsDraft.filter((t) => t.name || t.host);
  patch.sites = S.sitesDraft.filter((t) => t.target);
  patch.cdn_custom = S.cdnCustomDraft.filter((t) => t.host);
  patch.cdn_services = Object.fromEntries(Object.keys(S.meta.cdn_services).map((k) => [k, !!$(`cdnsvc-${k}`)?.checked]));
  patch.ookla_servers = S.ookSel;
  try {
    const r = await api('/api/config', { method: 'POST', body: JSON.stringify(patch) });
    S.cfg = r.config;
    S.targetsDraft = JSON.parse(JSON.stringify(S.cfg.targets));
    S.sitesDraft = JSON.parse(JSON.stringify(S.cfg.sites));
    S.cdnCustomDraft = JSON.parse(JSON.stringify(S.cfg.cdn_custom));
    fillSettings();
    renderTargetsEditor();
    renderSitesEditor();
    renderCdnSettings();
    $('save-state').textContent = `Kaydedildi · ${new Date().toLocaleTimeString('tr-TR')}`;
    toast('Ayarlar kaydedildi');
    pollLive();
    refreshData();
  } catch (e) { toast(`Kaydedilemedi: ${e.message}`, true); }
}

async function testEmail() {
  await saveSettings();
  try { await api('/api/test-email', { method: 'POST' }); toast('Test e-postası gönderildi'); } catch (e) { toast(e.message, true); }
}

async function loadServers() {
  try {
    const r = await api('/api/servers');
    const sel = $('speedtest_server_id');
    r.servers.forEach((s) => {
      const o = document.createElement('option');
      o.value = s.id;
      o.textContent = `${s.name} — ${s.location}${s.distance ? ` (${s.distance} km)` : ''}`;
      sel.appendChild(o);
    });
    sel.value = S.cfg.speedtest_server_id;
    if (!r.ookla) {
      const opt = $('speedtest_engine').querySelector('option[value=ookla]');
      opt.textContent += ' — kurulu değil';
    }
  } catch (_) { /* */ }
}

// ---------------------------------------------------------------- başlat
async function init() {
  document.querySelectorAll('#nav button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
  window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));
  document.querySelectorAll('#range-seg button').forEach((b) => b.addEventListener('click', () => {
    S.range = b.dataset.v; localStorage.setItem('nm.range', S.range); setSeg('range-seg', S.range); updateExportLinks(); S.sig = {}; refreshData();
  }));
  document.querySelectorAll('#iface-seg button').forEach((b) => b.addEventListener('click', () => {
    S.iface = b.dataset.v; localStorage.setItem('nm.iface', S.iface); setSeg('iface-seg', S.iface); S.sig = {}; refreshData();
  }));
  setSeg('range-seg', S.range); setSeg('iface-seg', S.iface); updateExportLinks();
  showTab(S.tab);
  try { await loadSettings(); } catch (e) { toast('Ayarlar yüklenemedi: ' + e.message, true); }
  loadServers();
  await pollLive();
  await refreshData();
  setInterval(pollLive, 3000);
  setInterval(() => { if (!document.hidden) refreshData(); }, 10000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { pollLive(); refreshData(); } });
}


// ================================================================ v3
// ---------------------------------------------------------------- başlat / durdur
function renderStartStop() {
  const b = $('startstop');
  if (S.live.any_running) {
    b.className = 'btn stop';
    b.innerHTML = `${ICON.stop.replace('<svg', '<svg width="13" height="13"')} Tümünü durdur`;
    b.title = 'Tüm testleri durdurur ve oturum raporunu açar' + (S.live.session_start ? ` (oturum: ${S.live.session_start})` : '');
  } else {
    b.className = 'btn primary';
    b.innerHTML = `${ICON.play.replace('<svg', '<svg width="13" height="13"')} Tümünü başlat`;
    b.title = 'Ping, hız testi, traceroute, site ve CDN testlerini başlatır';
  }
}

async function startStop() {
  const b = $('startstop');
  b.disabled = true;
  try {
    if (S.live?.any_running) {
      const r = await api('/api/stop-all', { method: 'POST' });
      toast('Tüm testler durduruldu — rapor hazırlanıyor');
      S.report = null;
      await loadSettings();
      showTab('report');
      await loadReport(r.report);
    } else {
      await api('/api/start-all', { method: 'POST' });
      await loadSettings();
      toast('Tüm testler başlatıldı');
    }
    await pollLive();
  } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
}

// ---------------------------------------------------------------- güncelleme
function renderUpdate() {
  const u = S.live.update || {};
  const info = u.info || {};
  const badge = $('upd-badge');
  badge.classList.toggle('hidden', !info.available);
  if (info.available) badge.textContent = `Yeni sürüm v${info.latest}`;
  const st = $('upd-status');
  if (!st) return;
  if (['downloading', 'installing', 'restarting', 'error'].includes(u.state)) st.innerHTML = (u.state === 'error' ? '<span class="c-bad">' : '<span class="spin"></span> <span>') + esc(u.message) + '</span>';
  else if (info.error) st.innerHTML = `<span class="c-warn">${esc(info.error)}</span>${u.last_check ? ` · son kontrol ${esc(u.last_check)}` : ''}`;
  else if (info.latest) st.innerHTML = info.available ? `<span class="c-good">v${esc(info.latest)} yayında</span>` : `Güncel (v${esc(info.current)})${u.last_check ? ` · son kontrol ${esc(u.last_check)}` : ''}`;
  $('upd-apply').classList.toggle('hidden', !info.available || ['downloading', 'installing', 'restarting'].includes(u.state));
  const notes = $('upd-notes');
  notes.classList.toggle('hidden', !(info.available && info.notes));
  notes.textContent = info.notes || '';
  if (u.state === 'restarting' && !S.waitRestart) waitForRestart(info.latest);
}

async function checkUpdate() {
  await saveSettings();
  $('upd-status').innerHTML = '<span class="spin"></span> Kontrol ediliyor…';
  try {
    const r = await api('/api/update/check', { method: 'POST' });
    S.live.update = { ...(S.live.update || {}), info: r, state: 'idle', last_check: new Date().toLocaleString('tr-TR') };
    renderUpdate();
    toast(r.error ? `Güncelleme kontrolü: ${r.error}` : r.available ? `Yeni sürüm: v${r.latest}` : 'Uygulama güncel', !!r.error);
  } catch (e) { toast(e.message, true); }
}

async function applyUpdate() {
  if (!confirm('Uygulama güncellenip yeniden başlatılacak. Ayarlarınız ve ölçüm verileriniz korunur. Devam edilsin mi?')) return;
  try {
    await api('/api/update/apply', { method: 'POST' });
    toast('Güncelleme başladı');
    pollLive();
  } catch (e) { toast(e.message, true); }
}

function waitForRestart(target) {
  S.waitRestart = true;
  const t0 = Date.now();
  const iv = setInterval(async () => {
    try {
      const r = await fetch('/api/live');
      if (r.ok) {
        const d = await r.json();
        if (d.version === target) { clearInterval(iv); toast(`v${target} kuruldu`); setTimeout(() => location.reload(), 600); }
      }
    } catch (_) { /* yeniden başlıyor */ }
    if (Date.now() - t0 > 120000) { clearInterval(iv); S.waitRestart = false; toast('Yeniden başlatma uzun sürdü; sayfayı yenileyin', true); }
  }, 2000);
}

// ---------------------------------------------------------------- siteler
const siteName = (id) => (S.data?.sites || S.cfg?.sites || []).find((s) => s.id === id)?.name || id;
const RESOLVER_LABEL = { system: 'İşletim sistemi', isp: 'ISS DNS', google: 'Google (8.8.8.8)', cloudflare: 'Cloudflare (1.1.1.1)' };

function waterfall(r) {
  const parts = [['dns', r.dns_ms], ['tcp', r.tcp_ms], ['tls', r.tls_ms], ['ttfb', r.ttfb_ms]];
  const sum = parts.reduce((a, [, v]) => a + (v || 0), 0);
  const total = Math.max(sum, r.total_ms || 0) || 1;
  const rest = Math.max(0, (r.total_ms || 0) - sum);
  const title = parts.map(([k, v]) => `${k.toUpperCase()}: ${fms(v)}`).join(' · ');
  return `<div class="wf" title="${title}">${parts.map(([k, v]) => `<i class="${k}" style="width:${((v || 0) / total) * 100}%"></i>`).join('')}<i class="rest" style="width:${(rest / total) * 100}%"></i></div>`;
}
const WF_LEGEND = '<div class="legend-inline" style="margin-top:8px"><span><i style="background:#a78bfa"></i>DNS</span><span><i style="background:#38bdf8"></i>TCP</span><span><i style="background:#fbbf24"></i>TLS</span><span><i style="background:#34d399"></i>İlk bayt</span><span><i style="background:#64748b"></i>Gövde</span></div>';
const httpChip = (st, ok) => !st ? '<span class="chip bad">hata</span>' : `<span class="chip ${st < 400 ? 'good' : st < 500 ? 'warn' : 'bad'}">${st}</span>`;
const netLabel = (r) => r.as_name ? `${esc(r.as_name)}${r.asn ? ` <span class="dim">AS${r.asn}</span>` : ''}` : (r.cdn ? esc(r.cdn) : '<span class="dim">—</span>');

function dnsTable(dns) {
  const keys = ['system', 'isp', 'google', 'cloudflare'].filter((k) => dns[k]);
  const sets = keys.map((k) => (dns[k].ips || []).slice().sort().join(','));
  return `<div class="table-wrap dns-cmp" style="max-height:none"><table><thead><tr><th>DNS çözümleyici</th><th class="r">Süre</th><th>IP adresleri</th></tr></thead><tbody>
    ${keys.map((k, i) => { const d = dns[k]; const diff = d.ips?.length && sets.filter(Boolean).some((x) => x !== sets[i]);
      return `<tr><td>${RESOLVER_LABEL[k]}${d.server && k === 'isp' ? ` <span class="dim mono">${esc(d.server)}</span>` : ''}</td>
      <td class="r">${d.error && !d.ips?.length ? '—' : fms(d.ms)}</td>
      <td>${d.ips?.length ? `<span class="ips">${d.ips.map(esc).join(', ')}</span>${d.cname ? ` <span class="dim">(CNAME ${esc(d.cname)})</span>` : ''}${diff ? ' <span class="chip warn">farklı</span>' : ''}` : `<span class="c-bad">${esc(d.error || 'yanıt yok')}</span>`}</td></tr>`; }).join('')}
  </tbody></table></div>`;
}

async function quickSiteTest() {
  const target = $('qs-input').value.trim();
  if (!target) return;
  const btn = $('qs-btn');
  btn.disabled = true;
  $('qs-result').innerHTML = '<div class="muted"><span class="spin"></span> Çözümleniyor ve ölçülüyor…</div>';
  try {
    const d = await api('/api/site-test', { method: 'POST', body: JSON.stringify({ target }) });
    $('qs-result').innerHTML = d.results.map((r) => `
      <div class="card" style="background:var(--bg-2)">
        <div class="card-h"><h3>${esc(r.host)}</h3>${chip(r.iface_type || 'unknown')}${httpChip(r.status)}
          <div class="right">${r.cdn ? `<span class="chip">${esc(r.cdn)}</span>` : ''}${r.tls_version ? `<span class="chip">${esc(r.tls_version)}</span>` : ''}</div></div>
        ${r.error ? `<div class="alert warn" style="margin-bottom:12px">${ICON.warn}<span>${esc(r.error)}</span></div>` : ''}
        <div class="stats">
          <div class="stat"><div class="k">DNS</div><div class="v">${fms(r.dns_ms)}</div></div>
          <div class="stat"><div class="k">TCP bağlantı</div><div class="v">${gv('ping', r.tcp_ms, fms)}</div></div>
          <div class="stat"><div class="k">TLS</div><div class="v">${fms(r.tls_ms)}</div></div>
          <div class="stat"><div class="k">İlk bayt</div><div class="v">${fms(r.ttfb_ms)}</div></div>
          <div class="stat"><div class="k">Toplam</div><div class="v">${fms(r.total_ms)}</div></div>
          <div class="stat"><div class="k">Bağlanılan IP</div><div class="v mono" style="font-size:13px">${esc(r.ip || '—')}</div></div>
        </div>
        ${r.total_ms ? waterfall(r) + WF_LEGEND : ''}
        <div class="kv" style="margin:14px 0">
          <dt>Ağ (ASN)</dt><dd>${netLabel(r)}</dd>
          <dt>Ters DNS</dt><dd class="mono">${esc(r.ptr || '—')}</dd>
          <dt>Sunucu</dt><dd>${esc(r.server || '—')}</dd>
          ${r.headers?.Location || r.headers?.location ? `<dt>Yönlendirme</dt><dd class="mono">${esc(r.headers.Location || r.headers.location)}</dd>` : ''}
        </div>
        ${r.dns_mismatch ? `<div class="alert info" style="margin-bottom:10px">${ICON.info}<span>DNS sunucuları farklı IP döndürdü. CDN kullanan sitelerde bu normaldir (her çözümleyici size en yakın sunucuyu verir); ancak ISS DNS'i yavaş veya hatalıysa site daha uzaktaki bir sunucuya gidebilir.</span></div>` : ''}
        ${dnsTable(r.dns || {})}
      </div>`).join('') + (d.warnings || []).map((w) => `<div class="alert warn">${ICON.warn}<span>${esc(w)}</span></div>`).join('');
    refreshData();
  } catch (e) {
    $('qs-result').innerHTML = `<div class="alert warn">${ICON.warn}<span>${esc(e.message)}</span></div>`;
  } finally { btn.disabled = false; }
}

async function addQuickToSites() {
  const t = $('qs-input').value.trim();
  if (!t) return;
  const host = t.replace(/^https?:\/\//, '').split('/')[0];
  S.sitesDraft.push({ name: host.replace(/^www\./, ''), target: t, enabled: true });
  try {
    const r = await api('/api/config', { method: 'POST', body: JSON.stringify({ sites: S.sitesDraft }) });
    S.cfg = r.config; S.sitesDraft = JSON.parse(JSON.stringify(S.cfg.sites)); renderSitesEditor();
    toast(`${host} periyodik test listesine eklendi`);
  } catch (e) { S.sitesDraft.pop(); toast(e.message, true); }
}

function renderSites() {
  const st = S.data.site_stats || [];
  $('site-sub').textContent = `${rangeName()} · ${st.length ? st.reduce((a, r) => a + r.n, 0) + ' ölçüm' : ''}`;
  $('site-stats').innerHTML = st.length ? `<div class="table-wrap" style="max-height:none"><table><thead><tr>
      <th>Site</th><th>Bağlantı</th><th class="r">Başarı</th><th class="r">DNS</th><th class="r">TCP</th><th class="r">TLS</th><th class="r">İlk bayt</th><th class="r">Toplam ort.</th><th class="r">En kötü</th><th class="r">Farklı IP</th></tr></thead><tbody>
      ${st.map((r) => `<tr><td><b>${esc(siteName(r.site_id))}</b> <span class="dim">${esc(r.host || '')}</span></td><td>${chip(r.iface_type)}</td>
        <td class="r ${r.success >= 99 ? 'c-good' : r.success >= 90 ? 'c-warn' : 'c-bad'}">%${fx(r.success, 1)}</td>
        <td class="r">${fms(r.dns)}</td><td class="r">${gv('ping', r.tcp, fms)}</td><td class="r">${fms(r.tls)}</td><td class="r">${fms(r.ttfb)}</td>
        <td class="r"><b>${fms(r.total)}</b></td><td class="r">${fms(r.total_max)}</td><td class="r">${r.ip_count}</td></tr>`).join('')}
    </tbody></table></div>`
    : '<div class="empty"><b>Bu periyotta site testi yok</b>Yukarıdan tek seferlik test yapabilir veya Ayarlar → Siteler\'den periyodik testi açabilirsiniz.</div>';

  const series = S.data.site_series || [];
  const labelsTs = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort();
  const idx = Object.fromEntries(labelsTs.map((t, k) => [t, k]));
  const palette = ['#3dd6c6', '#a78bfa', '#38bdf8', '#fbbf24', '#f472b6', '#34d399', '#fb923c', '#e879f9', '#94a3b8'];
  const multi = new Set(series.map((s) => s.iface_type)).size > 1;
  const datasets = series.map((s, i) => {
    const a = new Array(labelsTs.length).fill(null);
    s.points.forEach((p) => { a[idx[p[0]]] = p[5]; });
    const col = palette[i % palette.length];
    return { label: `${siteName(s.site_id)}${multi ? ` (${ilabel(s.iface_type)})` : ''}`, data: a, borderColor: col, backgroundColor: col, borderDash: s.iface_type === 'wifi' && multi ? [5, 4] : [] };
  });
  const opts = baseOpts();
  opts.scales.y.title = { display: true, text: 'ms' };
  chart('siteChart', 'line', { labels: labelsTs.map(tlabel), datasets }, opts);

  const rows = S.data.site_checks || [];
  $('site-table').innerHTML = rows.length ? rows.slice(0, 150).map((r) => `<tr>
    <td>${esc(r.timestamp)}</td><td>${esc(siteName(r.site_id))}</td><td>${chip(r.iface_type || 'unknown')}</td>
    <td><span class="mono">${esc(r.ip || '—')}</span> <span class="dim">${esc(r.as_name || r.cdn || '')}</span></td>
    <td class="r">${r.error && !r.status ? `<span class="c-bad" title="${esc(r.error)}">hata</span>` : httpChip(r.status)}</td>
    <td>${r.total_ms ? waterfall(r) : ''}</td>
    <td class="r">${fms(r.dns_ms)}</td><td class="r">${fms(r.tcp_ms)}</td><td class="r">${fms(r.tls_ms)}</td><td class="r">${fms(r.ttfb_ms)}</td><td class="r"><b>${fms(r.total_ms)}</b></td></tr>`).join('')
    : '<tr><td colspan="11" class="empty">Kayıt yok</td></tr>';
}

function renderSitesEditor() {
  $('sites-body').innerHTML = S.sitesDraft.map((t, i) => `<tr>
    <td><input class="input sm" value="${esc(t.name)}" oninput="S.sitesDraft[${i}].name=this.value"></td>
    <td><input class="input sm mono" value="${esc(t.target)}" placeholder="ornek.com" oninput="S.sitesDraft[${i}].target=this.value.trim()" onchange="resolvePreview(${i})"></td>
    <td><span class="resolve-prev" id="rp-${i}"><button class="btn sm ghost" onclick="resolvePreview(${i})">Çözümle</button></span></td>
    <td><label class="switch"><input type="checkbox" ${t.enabled ? 'checked' : ''} onchange="S.sitesDraft[${i}].enabled=this.checked"><span></span></label></td>
    <td class="r"><button class="btn sm ghost danger" onclick="S.sitesDraft.splice(${i},1);renderSitesEditor()">Sil</button></td></tr>`).join('');
}
function addSite() { S.sitesDraft.push({ name: '', target: '', enabled: true }); renderSitesEditor(); }
function resetSites() { S.sitesDraft = JSON.parse(JSON.stringify(S.defaults.sites)); renderSitesEditor(); toast('Varsayılan siteler yüklendi — kaydetmeyi unutmayın'); }

async function resolvePreview(i) {
  const t = S.sitesDraft[i]?.target;
  const el = $(`rp-${i}`);
  if (!t || !el) return;
  el.innerHTML = '<span class="spin"></span>';
  try {
    const r = await api(`/api/resolve?host=${encodeURIComponent(t)}`);
    const sys = r.dns.system || {};
    if (!S.sitesDraft[i].name) { S.sitesDraft[i].name = r.host.replace(/^www\./, ''); renderSitesEditor(); return resolvePreview(i); }
    const ip = (sys.ips || [])[0];
    const inf = ip ? r.ip_info[ip] || {} : {};
    el.innerHTML = sys.ips?.length ? `${esc(sys.ips.slice(0, 3).join(', '))}${sys.ips.length > 3 ? ` +${sys.ips.length - 3}` : ''} · ${fms(sys.ms)}${inf.as_name ? `<br>${esc(inf.as_name)}` : ''}` : `<span class="c-bad">${esc(sys.error || 'çözümlenemedi')}</span>`;
  } catch (e) { el.innerHTML = `<span class="c-bad">${esc(e.message)}</span>`; }
}

// ---------------------------------------------------------------- CDN
const SVC_COLOR = { youtube: '#f87171', facebook: '#60a5fa', instagram: '#f472b6', custom: '#94a3b8' };
function renderCdn() {
  const rows = S.data.cdn_checks || [];
  const isp = S.live?.isp;
  $('cdn-intro').innerHTML = `${ICON.info}<span>Uygulama YouTube, Facebook ve Instagram'ın size atadığı medya sunucularını otomatik bulur; sunucunun IP'si
    ${isp?.as_name ? `sizin ISS'nizin ağındaysa (<b>${esc(isp.as_name)}</b>, AS${esc(isp.asn)})` : "ISS'nizin ağındaysa"} <b>yerel önbellek</b> (GGC / FNA) olarak işaretlenir.
    Bilinen önbellek IP'lerinizi Ayarlar → CDN / Önbellek bölümünden ekleyebilirsiniz.</span>`;
  const latest = {};
  rows.forEach((r) => { const k = `${r.service}|${r.iface_type}`; (latest[k] ||= []); if (latest[k].length < 3 && !latest[k].some((x) => x.host === r.host) && (latest[k].length === 0 || latest[k][0].timestamp === r.timestamp)) latest[k].push(r); });
  const stats = Object.fromEntries((S.data.cdn_stats || []).map((s) => [`${s.service}|${s.iface_type}`, s]));
  const keys = Object.keys(latest);
  $('cdn-cards').innerHTML = keys.length ? keys.map((k) => {
    const nodes = latest[k]; const st = stats[k] || {}; const svc = nodes[0].service;
    const col = SVC_COLOR[svc] || SVC_COLOR.custom;
    return `<div class="card"><i class="accent-bar"></i>
      <div class="card-h"><h3 style="color:${col}">${esc(nodes[0].label)}</h3>${chip(nodes[0].iface_type || 'unknown')}
        <div class="right">${st.n ? `<span class="chip ${st.local_pct >= 50 ? 'good' : ''}">%${fx(st.local_pct, 0)} yerel</span>` : ''}</div></div>
      ${nodes[0].cluster ? `<div class="row muted" style="font-size:12px">Google eşleme kümesi: <b class="mono" style="color:var(--text)">${esc(nodes[0].cluster)}</b></div>` : ''}
      ${nodes[0].note ? `<div class="kpi"><div class="note">${esc(nodes[0].note)}</div></div>` : ''}
      ${nodes.map((n) => `<div class="node">
        <div class="h"><b title="${esc(n.host)}">${esc(n.host)}</b>${n.error && !n.ip ? '<span class="chip bad">hata</span>' : n.local ? '<span class="chip good">ISS içi önbellek</span>' : `<span class="chip">${esc(n.where_ || '—')}</span>`}</div>
        <div class="muted mono" style="font-size:11.5px">${esc(n.ip || '')}${n.ptr ? ` · ${esc(n.ptr)}` : ''}</div>
        <div class="muted" style="font-size:12px">${n.as_name ? `${esc(n.as_name)} (AS${n.asn})` : ''}</div>
        <div class="m">
          <span>ping ${gv('ping', n.ping_ms, fms)}</span><span>kayıp ${gv('loss', n.ping_loss, fpct)}</span><span>ilk bayt ${fms(n.ttfb_ms)}</span>${n.mbps ? `<span>${fspeed(n.mbps)}</span>` : ''}
        </div>${n.error ? `<div class="c-warn" style="font-size:12px">${esc(n.error)}</div>` : ''}</div>`).join('')}
      ${st.n ? `<div class="muted" style="font-size:12px;margin-top:10px">${rangeName()}: ${st.n} ölçüm · ort. ping ${fms(st.ping)} · ${st.hosts} farklı sunucu</div>` : ''}
    </div>`;
  }).join('') : '<div class="card empty" style="grid-column:1/-1"><b>Henüz CDN ölçümü yok</b>"Şimdi test et" ile başlatın; ilk test 20–40 saniye sürebilir.</div>';

  $('cdn-table').innerHTML = rows.length ? rows.slice(0, 150).map((r) => `<tr>
    <td>${esc(r.timestamp)}</td><td style="color:${SVC_COLOR[r.service] || 'inherit'}">${esc(r.label)}</td><td>${chip(r.iface_type || 'unknown')}</td>
    <td class="mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis" title="${esc(r.host)}">${esc(r.host)}</td><td class="mono">${esc(r.ip || '—')}</td>
    <td>${r.as_name ? `${esc(r.as_name)} <span class="dim">AS${r.asn}</span>` : '<span class="dim">—</span>'}</td>
    <td>${r.local ? '<span class="chip good">ISS içi</span>' : esc(r.where_ || (r.error ? 'hata' : '—'))}</td>
    <td class="r">${gv('ping', r.ping_ms, fms)}</td><td class="r">${gv('loss', r.ping_loss, fpct)}</td><td class="r">${fms(r.ttfb_ms)}</td><td class="r">${r.mbps ? fspeed(r.mbps) : '<span class="dim">—</span>'}</td></tr>`).join('')
    : '<tr><td colspan="11" class="empty">Kayıt yok</td></tr>';
}

function renderCdnSettings() {
  const svc = S.cfg.cdn_services || {};
  $('cdn-svc').innerHTML = Object.entries(S.meta.cdn_services).map(([k, v]) => `<div class="sw-row"><div><b>${esc(v.name)}</b><span>${esc(v.operator)}</span></div>
    <label class="switch"><input type="checkbox" id="cdnsvc-${k}" ${svc[k] ? 'checked' : ''}><span></span></label></div>`).join('');
  $('cdn-custom-body').innerHTML = S.cdnCustomDraft.length ? S.cdnCustomDraft.map((t, i) => `<tr>
    <td><input class="input sm" value="${esc(t.label)}" placeholder="ör. Türksat GGC Ankara" oninput="S.cdnCustomDraft[${i}].label=this.value"></td>
    <td><input class="input sm mono" value="${esc(t.host)}" placeholder="IP veya sunucu adı" oninput="S.cdnCustomDraft[${i}].host=this.value.trim()"></td>
    <td class="r"><button class="btn sm ghost danger" onclick="S.cdnCustomDraft.splice(${i},1);renderCdnSettings()">Sil</button></td></tr>`).join('')
    : '<tr><td colspan="3" class="dim" style="padding:12px">Eklenmiş sunucu yok</td></tr>';
}
function addCdnCustom() { S.cdnCustomDraft.push({ label: '', host: '' }); renderCdnSettings(); }

// ---------------------------------------------------------------- Ookla sunucuları
function renderOoklaSelected() {
  $('ook-selected').innerHTML = S.ookSel.length ? S.ookSel.map((s, i) => `<span class="chip">${esc(s.name)} · ${esc(s.location)} <span class="dim">#${esc(s.id)}</span><button onclick="S.ookSel.splice(${i},1);renderOoklaSelected()" title="Kaldır">×</button></span>`).join('')
    : '<span class="dim" style="font-size:12.5px">Seçili sunucu yok — en yakın sunucu otomatik kullanılır</span>';
}
async function ooklaSearch() {
  const q = $('ook-q').value.trim();
  const el = $('ook-results');
  el.innerHTML = '<span class="spin"></span> Aranıyor…';
  try {
    const r = await api(`/api/ookla/search?q=${encodeURIComponent(q)}`);
    S.ookResults = r.servers;
    el.innerHTML = r.servers.length ? `<div class="table-wrap" style="max-height:300px"><table><thead><tr><th>Sağlayıcı</th><th>Şehir</th><th class="r">Uzaklık</th><th>ID</th><th></th></tr></thead><tbody>
      ${r.servers.map((s, i) => `<tr><td>${esc(s.name)}</td><td>${esc(s.location)} <span class="dim">${esc(s.country || '')}</span></td><td class="r">${s.distance ? s.distance + ' km' : '—'}</td><td class="mono dim">${esc(s.id)}</td>
        <td class="r">${S.ookSel.some((x) => x.id === s.id) ? '<span class="chip good">seçili</span>' : `<button class="btn sm" onclick="ooklaAdd(${i})">Ekle</button>`}</td></tr>`).join('')}</tbody></table></div>`
      : '<span class="dim">Sonuç yok</span>';
  } catch (e) { el.innerHTML = `<div class="alert warn">${ICON.warn}<span>${esc(e.message)}</span></div>`; }
}
function ooklaAdd(i) {
  const s = S.ookResults[i];
  if (!S.ookSel.some((x) => x.id === s.id)) S.ookSel.push({ id: s.id, name: s.name, location: s.location });
  renderOoklaSelected();
  ooklaSearch();
  toast(`${s.name} (${s.location}) eklendi — kaydetmeyi unutmayın`);
}

// ---------------------------------------------------------------- rapor
function loadReportRange() {
  const now = new Date();
  const days = { hourly: 1 / 24, daily: 1, weekly: 7, monthly: 30 }[S.range] || 1;
  const fmt = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19).replace('T', ' ');
  loadReport({ start: fmt(new Date(now - days * 86400000)), end: fmt(now) });
}

async function loadReport(win) {
  const q = win ? `?start=${encodeURIComponent(win.start)}&end=${encodeURIComponent(win.end)}` : '';
  $('report-body').innerHTML = '<div class="card"><span class="spin"></span> Rapor hazırlanıyor…</div>';
  try {
    const d = await api('/api/report' + q);
    S.report = d;
    const w = `start=${encodeURIComponent(d.window[0])}&end=${encodeURIComponent(d.window[1])}`;
    $('rep-xlsx').href = `/api/export/excel?${w}`;
    $('rep-csv').href = `/api/export/csv?${w}`;
    renderReport(d);
  } catch (e) { $('report-body').innerHTML = `<div class="alert warn">${ICON.warn}<span>${esc(e.message)}</span></div>`; }
}

function fdur(a, b) {
  const s = (new Date(b.replace(' ', 'T')) - new Date(a.replace(' ', 'T'))) / 1000;
  if (!(s > 0)) return '—';
  const h = Math.floor(s / 3600); const m = Math.round((s % 3600) / 60);
  return h ? `${h} sa ${m} dk` : `${m || 1} dk`;
}

function renderReport(d) {
  const [ws, we0] = d.window;
  const we = we0.startsWith('9999') ? d.generated : we0;
  const hasAny = d.ping_stats.length || d.speedtests.length || d.site_stats.length || d.cdn_checks.length;
  const all = (() => { const rows = d.ping_stats.filter((r) => r.target_id !== 'gateway'); if (!rows.length) return null;
    const w = (k) => wavg(rows, k);
    return { avg: w('avg'), jitter: w('jitter'), loss: w('loss'), uptime: w('uptime'), outages: rows.reduce((a, r) => a + r.outages, 0) }; })();
  const sp = d.speedtests; const spAvg = (k) => sp.length ? sp.reduce((a, r) => a + (r[k] || 0), 0) / sp.length : null;
  const sites = d.site_stats; const siteOk = sites.length ? sites.reduce((a, r) => a + r.success * r.n, 0) / sites.reduce((a, r) => a + r.n, 0) : null;
  const cdn = d.cdn_stats; const cdnLocal = cdn.length ? cdn.reduce((a, r) => a + r.local_pct * r.n, 0) / cdn.reduce((a, r) => a + r.n, 0) : null;
  const downs = d.events.filter((e) => e.kind === 'down').length;
  const modeNames = { auto: 'Otomatik', wifi: 'Yalnızca Wi-Fi', ethernet: 'Yalnızca Ethernet', both: 'Wi-Fi + Ethernet' };
  const tbl = (head, rows) => `<div class="table-wrap" style="max-height:none"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;

  let h = `<div class="card"><div class="report-head"><div><div class="eyebrow">NetMonitor v${esc(d.version)} · Test raporu</div><h1>${esc(ws)} → ${esc(we)}</h1></div>
    <div class="meta"><span>Süre <b>${fdur(ws, we)}</b></span><span>Test modu <b>${modeNames[d.config_summary.iface_mode] || '—'}</b></span>
    ${d.isp ? `<span>ISS <b>${esc(d.isp.as_name || '')}</b> AS${esc(d.isp.asn || '')}</span><span>Genel IP <b class="mono">${esc(d.isp.ip || '')}</b></span>` : ''}
    <span>Oluşturulma <b>${esc(d.generated)}</b></span></div></div></div>`;
  if (!hasAny) { $('report-body').innerHTML = h + '<div class="card empty"><b>Bu aralıkta ölçüm yok</b>Testler çalışırken veri toplanır.</div>'; return; }

  h += `<div class="grid kpis">
    <div class="card kpi"><i class="accent-bar" style="background:var(--warn)"></i><div class="eyebrow">İnternet gecikmesi</div><div class="big">${all ? gv('ping', all.avg, (v) => fx(v, 1)) + '<small>ms</small>' : '—'}</div>
      <div class="row"><span>Jitter</span><span>${all ? gv('jitter', all.jitter, fms) : '—'}</span></div><div class="row"><span>Paket kaybı</span><span>${all ? gv('loss', (isNum(all.loss) ? +all.loss.toFixed(2) : null), fpct) : '—'}</span></div></div>
    <div class="card kpi"><i class="accent-bar" style="background:var(--good)"></i><div class="eyebrow">Erişilebilirlik</div><div class="big">${all ? fpct(all.uptime) : '—'}</div>
      <div class="row"><span>Kesinti (tam kayıp)</span><span class="${all?.outages ? 'c-bad' : ''}">${all ? all.outages : '—'}</span></div><div class="row"><span>Bağlantı kopması</span><span class="${downs ? 'c-bad' : ''}">${downs}</span></div></div>
    <div class="card kpi"><i class="accent-bar" style="background:var(--accent)"></i><div class="eyebrow">Hız testi · ${sp.length} test</div><div class="big">${sp.length ? fx(spAvg('download_mbps'), 0) + '<small>↓ Mbps</small>' : '—'}</div>
      <div class="row"><span>Upload</span><span>${sp.length ? fx(spAvg('upload_mbps'), 1) + ' Mbps' : '—'}</span></div><div class="row"><span>Ping</span><span>${sp.length ? fms(spAvg('ping_ms')) : '—'}</span></div></div>
    <div class="card kpi"><i class="accent-bar" style="background:#60a5fa"></i><div class="eyebrow">Siteler</div><div class="big">${siteOk !== null ? `<span class="${siteOk >= 99 ? 'c-good' : siteOk >= 90 ? 'c-warn' : 'c-bad'}">%${fx(siteOk, 1)}</span><small>başarı</small>` : '—'}</div>
      <div class="row"><span>Ort. yanıt</span><span>${sites.length ? fms(wavg(sites, 'total')) : '—'}</span></div><div class="row"><span>Site sayısı</span><span>${new Set(sites.map((r) => r.site_id)).size}</span></div></div>
    <div class="card kpi"><i class="accent-bar" style="background:#f472b6"></i><div class="eyebrow">CDN önbellek</div><div class="big">${cdnLocal !== null ? `%${fx(cdnLocal, 0)}<small>ISS içi</small>` : '—'}</div>
      ${cdn.map((r) => `<div class="row"><span>${esc((S.meta?.cdn_services?.[r.service]||{}).name || r.service)} <span class="dim">${ilabel(r.iface_type)}</span></span><span>${fms(r.ping)} · %${fx(r.local_pct, 0)} yerel</span></div>`).join('')}</div>
  </div>`;

  if (d.ping_stats.length) {
    h += `<div class="card"><div class="card-h"><h2>Ping, Jitter ve Paket Kaybı</h2></div><div class="chart-box sm" style="margin-bottom:14px"><canvas id="rep-ping"></canvas></div>
      ${tbl('<th>Hedef</th><th>Bağlantı</th><th class="r">Ölçüm</th><th class="r">Ort.</th><th class="r">P95</th><th class="r">Max</th><th class="r">Jitter</th><th class="r">Kayıp</th><th class="r">Erişim</th><th class="r">Kesinti</th>',
        d.ping_stats.map((r) => `<tr><td>${esc(targetName(r.target_id))}</td><td>${chip(r.iface_type)}</td><td class="r">${r.n}</td><td class="r">${gv('ping', r.avg, fms)}</td><td class="r">${fms(r.p95)}</td><td class="r">${fms(r.max)}</td>
          <td class="r">${gv('jitter', r.jitter, fms)}</td><td class="r">${gv('loss', r.loss, fpct)}</td><td class="r">${fpct(r.uptime)}</td><td class="r ${r.outages ? 'c-bad' : ''}">${r.outages}</td></tr>`).join(''))}</div>`;
  }
  if (d.speed_by_server.length) {
    h += `<div class="card"><div class="card-h"><h2>Hız Testleri (sunucu bazında)</h2></div>
      ${tbl('<th>Sunucu</th><th>Motor</th><th>Bağlantı</th><th class="r">Test</th><th class="r">Download ort.</th><th class="r">Min / Max</th><th class="r">Upload</th><th class="r">Ping</th><th class="r">Jitter</th><th class="r">Kayıp</th>',
        d.speed_by_server.map((r) => `<tr><td>${esc(r.server_name)}</td><td>${esc(r.engine || '')}</td><td>${chip(r.iface_type)}</td><td class="r">${r.n}</td><td class="r"><b>${fx(r.dl, 1)}</b> Mbps</td><td class="r">${fx(r.dl_min, 0)} / ${fx(r.dl_max, 0)}</td>
          <td class="r">${fx(r.ul, 1)} Mbps</td><td class="r">${gv('ping', r.ping, fms)}</td><td class="r">${gv('jitter', r.jitter, fms)}</td><td class="r">${isNum(r.loss) ? gv('loss', r.loss, fpct) : '—'}</td></tr>`).join(''))}</div>`;
  }
  if (sites.length) {
    h += `<div class="card"><div class="card-h"><h2>Site Testleri</h2></div>
      ${tbl('<th>Site</th><th>Bağlantı</th><th class="r">Test</th><th class="r">Başarı</th><th class="r">DNS</th><th class="r">TCP</th><th class="r">TLS</th><th class="r">İlk bayt</th><th class="r">Toplam</th><th class="r">En kötü</th>',
        sites.map((r) => `<tr><td>${esc(siteName(r.site_id))} <span class="dim">${esc(r.host || '')}</span></td><td>${chip(r.iface_type)}</td><td class="r">${r.n}</td><td class="r ${r.success >= 99 ? 'c-good' : r.success >= 90 ? 'c-warn' : 'c-bad'}">%${fx(r.success, 1)}</td>
          <td class="r">${fms(r.dns)}</td><td class="r">${fms(r.tcp)}</td><td class="r">${fms(r.tls)}</td><td class="r">${fms(r.ttfb)}</td><td class="r"><b>${fms(r.total)}</b></td><td class="r">${fms(r.total_max)}</td></tr>`).join(''))}</div>`;
  }
  if (d.cdn_checks.length) {
    const seen = new Set();
    const nodes = d.cdn_checks.filter((r) => { const k = `${r.service}|${r.host}|${r.iface_type}`; if (seen.has(k)) return false; seen.add(k); return true; });
    h += `<div class="card"><div class="card-h"><h2>CDN / Önbellek Sunucuları</h2><span class="sub">Oturumda görülen sunucular (son ölçüm)</span></div>
      ${tbl('<th>Servis</th><th>Bağlantı</th><th>Sunucu</th><th>IP</th><th>Ağ</th><th>Konum</th><th class="r">Ping</th><th class="r">Kayıp</th><th class="r">İlk bayt</th>',
        nodes.map((r) => `<tr><td>${esc(r.label)}</td><td>${chip(r.iface_type || 'unknown')}</td><td class="mono">${esc(r.host)}</td><td class="mono">${esc(r.ip || '—')}</td><td>${esc(r.as_name || '—')}${r.asn ? ` <span class="dim">AS${r.asn}</span>` : ''}</td>
          <td>${r.local ? '<span class="chip good">ISS içi</span>' : esc(r.where_ || r.error || '—')}</td><td class="r">${gv('ping', r.ping_ms, fms)}</td><td class="r">${gv('loss', r.ping_loss, fpct)}</td><td class="r">${fms(r.ttfb_ms)}</td></tr>`).join(''))}</div>`;
  }
  if (d.events.length) {
    h += `<div class="card"><div class="card-h"><h2>Bağlantı Olayları</h2></div>${tbl('<th>Zaman</th><th>Olay</th>', d.events.map((e) => `<tr><td class="mono">${esc(e.timestamp)}</td><td class="${e.severity === 'error' ? 'c-bad' : e.severity === 'warn' ? 'c-warn' : ''}" style="white-space:normal">${esc(e.message)}</td></tr>`).join(''))}</div>`;
  }
  $('report-body').innerHTML = h;

  if (d.ping_stats.length) {
    const series = d.ping_series.filter((s) => s.target_id !== 'gateway');
    const labelsTs = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort();
    const idx = Object.fromEntries(labelsTs.map((t, k) => [t, k]));
    const palette = ['#3dd6c6', '#a78bfa', '#38bdf8', '#fbbf24', '#f472b6', '#34d399', '#fb923c'];
    const multi = new Set(series.map((s) => s.iface_type)).size > 1;
    const span = labelsTs.length ? (new Date(labelsTs[labelsTs.length - 1].replace(' ', 'T')) - new Date(labelsTs[0].replace(' ', 'T'))) / 3600000 : 0;
    const lab = (t) => (span > 30 ? `${t.slice(8, 10)}.${t.slice(5, 7)} ${t.slice(11, 16)}` : t.slice(11, 16));
    const ds = series.map((s, i) => { const a = new Array(labelsTs.length).fill(null); s.points.forEach((p) => { a[idx[p[0]]] = p[1]; });
      const col = palette[i % palette.length]; return { label: `${targetName(s.target_id)}${multi ? ` (${ilabel(s.iface_type)})` : ''}`, data: a, borderColor: col, backgroundColor: col, borderDash: multi && s.iface_type === 'wifi' ? [5, 4] : [] }; });
    const opts = baseOpts(); opts.scales.y.title = { display: true, text: 'ms' };
    if (charts['rep-ping']) { charts['rep-ping'].destroy(); delete charts['rep-ping']; }
    chart('rep-ping', 'line', { labels: labelsTs.map(lab), datasets: ds }, opts);
  }
}

init();
