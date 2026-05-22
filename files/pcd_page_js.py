"""pcd_page_js.py — the dashboard's inline JavaScript.

Largest of the page sub-modules. Imported by pcd_page.py and inserted
inside the <script> tag of the assembled PAGE.
"""

JS = r"""
const REFRESH_MS = 2000;
let suppressSlider = {};

function tempColor(c) {
  if (c == null) return '#30363d';
  if (c < 50) return '#2ea043';
  if (c < 70) return '#d29922';
  if (c < 85) return '#db6d28';
  return '#f85149';
}
function bar(value, max, color) {
  const pct = value == null ? 0 : Math.min(100, Math.max(0, (value / max) * 100));
  return `<div class="bar"><div style="width:${pct}%;background:${color}"></div></div>`;
}
function esc(s) {
  return String(s).replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
}
function row(name, valueStr, value, max, color) {
  return `<div class="row"><div class="name" title="${esc(name)}">${esc(name)}</div>` +
         `<div class="value">${esc(valueStr)}</div>${bar(value, max, color)}</div>`;
}
function fmt(v, digits, suffix) {
  return (v == null ? '—' : Number(v).toFixed(digits)) + (suffix ? ' ' + suffix : '');
}

const ZONE_LABELS = {
  'bagz': 'Battery Bay', 'batz': 'Battery', 'chgz': 'Charger',
  'cpuz': 'CPU', 'extz': 'Exhaust', 'gfxz': 'GPU (NVIDIA)',
  'ihsz': 'CPU Heat Spreader', 'locz': 'Mainboard',
  'pchz': 'PCH', 'pgtz': 'CPU Package',
  'sk1z': 'Skin Palm Rest', 'sk2z': 'Skin Underside', 'sknz': 'Skin',
};
function shortZone(path) {
  const m = path.match(/\(([^)]+)\)/);
  if (!m) return path;
  const code = m[1].replace(/^\\?_?tz\.?/i, '').toLowerCase();
  return ZONE_LABELS[code] || m[1];
}

const COOLING_LABELS = {0: 'Passive (Quiet)', 1: 'Active (Fans first)'};
const TURBO_LABELS = {0: 'Disabled', 1: 'Enabled', 2: 'Aggressive',
                      3: 'Eff Enabled', 4: 'Eff Aggressive', 5: 'Aggressive at guaranteed'};
const OVERLAY_LABELS = {'best-efficiency': 'Best efficiency',
                        'balanced': 'Balanced',
                        'best-performance': 'Best performance'};

function setCurrent(id, label) {
  const el = document.getElementById(id);
  if (!el) return;
  if (label == null || label === '') {
    el.className = 'current unknown';
    el.innerHTML = '<b>unknown</b>';
  } else {
    el.className = 'current';
    el.innerHTML = `<b>${esc(label)}</b>`;
  }
}

function metricTile(label, value, sub, cls) {
  return `<div class="metric-tile ${cls || ''}">` +
         `<div class="ml">${esc(label)}</div>` +
         `<div class="mv">${esc(value)}</div>` +
         `<div class="ms">${esc(sub || ' ')}</div></div>`;
}
function tempTileClass(c) {
  if (c == null) return '';
  if (c >= 85) return 'crit';
  if (c >= 70) return 'hot';
  if (c >= 50) return 'warm';
  return 'good';
}
function detectActivePreset(c) {
  if (!c) return null;
  const cp = c.cooling_policy, tb = c.turbo_boost,
        mx = c.cpu_max_pct, mn = c.cpu_min_pct, ov = c.overlay;
  if (cp === 0 && tb === 0 && mx === 80 && ov === 'best-efficiency') return 'quiet';
  if (cp === 1 && tb === 2 && mx === 100 && mn === 100 && ov === 'best-performance') return 'performance';
  if (cp === 1 && tb === 2 && mx === 100 && ov === 'balanced') return 'balanced';
  return null;
}
function paintKeyMetrics(d) {
  const s = d.sources || {};
  const c = d.controls || {};
  const zones = s.thermal_zones || [];
  const cpuZone = zones.find(z => /cpuz/i.test(z.name));
  const gpu = (s.nvidia || [])[0];
  const cp = s.cpu_proxy || {};
  const b = s.battery || {};
  const tiles = [];
  const cpuTemp = cpuZone ? cpuZone.value : null;
  tiles.push(metricTile('CPU temp',
    cpuTemp != null ? cpuTemp.toFixed(1) + ' °C' : '—',
    cp.freq_mhz != null ? (cp.freq_mhz/1000).toFixed(2) + ' GHz' : '',
    tempTileClass(cpuTemp)));
  if (gpu) tiles.push(metricTile('GPU temp',
    gpu.temp_c != null ? gpu.temp_c.toFixed(0) + ' °C' : '—',
    gpu.power_w != null ? gpu.power_w.toFixed(0) + ' W draw' : '',
    tempTileClass(gpu.temp_c)));
  tiles.push(metricTile('CPU load',
    cp.util_pct != null ? cp.util_pct.toFixed(0) + ' %' : '—',
    cp.perf_pct != null ? cp.perf_pct.toFixed(0) + '% perf' + (cp.perf_pct > 105 ? ' · turbo' : '') : '',
    ''));
  if (b.charge_pct != null) tiles.push(metricTile('Battery',
    b.charge_pct.toFixed(0) + ' %', b.status || '',
    b.charge_pct < 20 ? 'crit' : (b.charge_pct < 50 ? 'warm' : 'good')));
  const preset = detectActivePreset(c);
  tiles.push(metricTile('Profile',
    preset ? preset.charAt(0).toUpperCase() + preset.slice(1) : 'Custom',
    OVERLAY_LABELS[c.overlay] || c.overlay || '—', ''));
  document.getElementById('key-metrics').innerHTML = tiles.join('');
}

function flash(msg, isError) {
  const f = document.getElementById('flash');
  f.textContent = msg;
  f.classList.toggle('error', !!isError);
  f.classList.add('show');
  setTimeout(() => f.classList.remove('show'), 2500);
}
async function post(url, body) {
  try {
    const r = await fetch(url, {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)});
    const d = await r.json();
    if (!r.ok || !d.ok) flash(d.error || (d.errors && d.errors.join('; ')) || 'failed', true);
    else flash('applied');
    refresh();
    setTimeout(refresh, 700);
    return d;
  } catch (e) {
    flash(String(e), true);
  }
}
function optimistic(groupId, attr, value) {
  document.querySelectorAll(`#${groupId} button[${attr}]`).forEach(b => {
    b.classList.toggle('active', String(b.getAttribute(attr)) === String(value));
  });
}

document.getElementById('overlay').addEventListener('click', e => {
  const b = e.target.closest('button[data-name]');
  if (!b) return;
  optimistic('overlay', 'data-name', b.dataset.name);
  setCurrent('overlay-current', OVERLAY_LABELS[b.dataset.name] || b.dataset.name);
  post('/api/control/overlay', {name: b.dataset.name});
});
document.getElementById('cooling').addEventListener('click', e => {
  const b = e.target.closest('button[data-val]');
  if (!b) return;
  optimistic('cooling', 'data-val', b.dataset.val);
  setCurrent('cooling-current', COOLING_LABELS[Number(b.dataset.val)]);
  post('/api/control/cooling-policy', {value: Number(b.dataset.val)});
});
document.getElementById('turbo').addEventListener('click', e => {
  const b = e.target.closest('button[data-val]');
  if (!b) return;
  optimistic('turbo', 'data-val', b.dataset.val);
  setCurrent('turbo-current', TURBO_LABELS[Number(b.dataset.val)]);
  post('/api/control/turbo', {value: Number(b.dataset.val)});
});
document.getElementById('presets').addEventListener('click', e => {
  const b = e.target.closest('button[data-preset]');
  if (!b) return;
  document.querySelectorAll('#presets button[data-preset]').forEach(x =>
    x.classList.toggle('active', x === b));
  setTimeout(() => b.classList.remove('active'), 4000);
  post('/api/control/preset', {name: b.dataset.preset});
});

function bindSlider(id, url, suffix) {
  const el = document.getElementById(id);
  const lbl = document.getElementById(id + '-lbl');
  el.addEventListener('input', () => {
    lbl.textContent = el.value + ' ' + suffix;
    suppressSlider[id] = Date.now();
  });
  el.addEventListener('change', () => {
    suppressSlider[id] = Date.now();
    post(url, {value: Number(el.value)});
  });
}
bindSlider('cpumax', '/api/control/cpu-max', '%');
bindSlider('cpumin', '/api/control/cpu-min', '%');
bindSlider('gpupl',  '/api/control/gpu-power', 'W');

function setActive(groupId, attr, value) {
  document.querySelectorAll(`#${groupId} button[${attr}]`).forEach(b => {
    b.classList.toggle('active', String(b.getAttribute(attr)) === String(value));
  });
}
function syncSlider(id, value) {
  if (suppressSlider[id] && Date.now() - suppressSlider[id] < 2000) return;
  const el = document.getElementById(id);
  if (value != null && el) {
    el.value = value;
    const lbl = document.getElementById(id + '-lbl');
    if (lbl) {
      const suffix = id === 'gpupl' ? 'W' : '%';
      lbl.textContent = value + ' ' + suffix;
    }
  }
}
function paintSystem(sys) {
  if (!sys || !Object.keys(sys).length) return;
  const host = document.getElementById('hostname');
  if (sys.hostname && !host.textContent) host.textContent = '· ' + sys.hostname;
  const bar = document.getElementById('sysinfo');
  if (bar.dataset.painted === '1') return;
  const fields = [
    ['Manufacturer', sys.Manufacturer], ['Model', sys.Model || sys.SystemFamily],
    ['CPU', sys.cpu_Name], ['Cores', sys.cpu_NumberOfCores],
    ['RAM', sys.ram_gb ? sys.ram_gb + ' GB' : null],
    ['OS', sys.os_Caption ? `${sys.os_Caption} (${sys.os_BuildNumber || ''})` : null],
    ['BIOS', sys.bios_SMBIOSBIOSVersion],
  ].filter(([_, v]) => v);
  bar.innerHTML = fields.map(([k, v]) =>
    `<div><span class="si-key">${esc(k)}:</span><span class="si-val">${esc(v)}</span></div>`).join('');
  bar.dataset.painted = '1';
}

async function refresh() {
  try {
    const r = await fetch('/api/thermal', {cache: 'no-store'});
    const d = await r.json();
    paintSystem(d.system);
    paintKeyMetrics(d);
    document.getElementById('updated').textContent =
      'updated ' + (d.updated || '—') + '  ·  refresh ' + (REFRESH_MS/1000) + 's';
    const s = d.sources || {};
    const c = d.controls || {};

    const activePreset = detectActivePreset(c);
    document.querySelectorAll('#presets button[data-preset]').forEach(b => {
      b.classList.toggle('active', b.dataset.preset === activePreset);
    });

    document.getElementById('admin-banner').style.display =
      c.is_admin === false ? 'block' : 'none';

    const planHolder = document.getElementById('powerplans');
    const plans = c.power_plans || [];
    if (planHolder.dataset.signature !== plans.map(p => p.guid).join(',')) {
      planHolder.innerHTML = plans.map(p =>
        `<button class="ctrl" data-guid="${esc(p.guid)}">${esc(p.name)}</button>`).join('');
      planHolder.dataset.signature = plans.map(p => p.guid).join(',');
      planHolder.querySelectorAll('button').forEach(b => {
        b.addEventListener('click', () => {
          optimistic('powerplans', 'data-guid', b.dataset.guid);
          setCurrent('powerplans-current', b.textContent);
          post('/api/control/powerplan', {guid: b.dataset.guid});
        });
      });
    }
    const active = plans.find(p => p.active);
    setActive('powerplans', 'data-guid', active ? active.guid : '');
    setCurrent('powerplans-current', active ? active.name : null);

    setActive('overlay', 'data-name', c.overlay);
    setCurrent('overlay-current', OVERLAY_LABELS[c.overlay] || c.overlay);
    setActive('cooling', 'data-val', c.cooling_policy);
    setCurrent('cooling-current', COOLING_LABELS[c.cooling_policy]);
    setActive('turbo', 'data-val', c.turbo_boost);
    setCurrent('turbo-current', TURBO_LABELS[c.turbo_boost]);
    syncSlider('cpumax', c.cpu_max_pct);
    syncSlider('cpumin', c.cpu_min_pct);

    const gpu = c.gpu;
    const gpupl = document.getElementById('gpupl');
    const gpunote = document.getElementById('gpupl-note');
    const gpuRow = gpupl.closest('.slider-row');
    if (gpu) {
      if (gpu.limit_locked) {
        gpupl.disabled = true;
        gpuRow.classList.add('locked');
        gpunote.className = 'note locked';
        gpunote.textContent = `Locked at ${gpu.limit_w} W by the NVIDIA driver.`;
      } else {
        gpupl.disabled = false;
        gpuRow.classList.remove('locked');
        gpunote.className = 'note';
        if (gpu.min_w != null) gpupl.min = Math.floor(gpu.min_w);
        if (gpu.max_w != null) gpupl.max = Math.ceil(gpu.max_w);
        syncSlider('gpupl', gpu.limit_w != null ? Math.round(gpu.limit_w) : null);
        gpunote.textContent = `range ${gpu.min_w}–${gpu.max_w} W, default ${gpu.default_w} W, drawing ${gpu.draw_w != null ? gpu.draw_w.toFixed(1) : '—'} W`;
      }
    } else {
      gpupl.disabled = true;
      gpuRow.classList.add('locked');
      // gpu_info is NVIDIA-only (uses nvidia-smi -q). Other vendors don't
      // expose a programmable power limit, so the slider is permanently
      // disabled there — the GPU card still shows util/VRAM from the
      // provider chain.
      const firstGpu = (s.nvidia || [])[0];
      if (firstGpu && firstGpu.vendor && firstGpu.vendor !== 'NVIDIA') {
        gpunote.textContent = `GPU power limit not adjustable on ${firstGpu.vendor} hardware`;
      } else {
        gpunote.textContent = 'nvidia-smi unavailable';
      }
    }

    const zones = s.thermal_zones || [];
    document.getElementById('zones').innerHTML = zones.length
      ? zones.map(z => row(shortZone(z.name), z.value.toFixed(1) + ' °C',
                           z.value, 100, tempColor(z.value))).join('')
      : '<div class="empty">no data</div>';

    const gpus = s.nvidia || [];
    document.getElementById('nvidia').innerHTML = gpus.length
      ? gpus.map(g => {
          const srcLabel = g.source === 'nvidia-smi' ? '' :
                           g.source === 'perf_counters'
                             ? '<div class="note">Windows generic counters only — vendor tools (nvidia-smi / ADLX / etc.) did not respond. Temp / power / clocks not available.</div>'
                             : `<div class="note">source: ${esc(g.source || 'unknown')} — limited telemetry</div>`;
          let html = `<div class="gpu-name">${esc(g.name)}${g.vendor ? ` <span class="muted">[${esc(g.vendor)}]</span>` : ''}</div>` + srcLabel;
          if (g.temp_c != null)         html += row('Temp', fmt(g.temp_c, 0, '°C'), g.temp_c, 100, tempColor(g.temp_c));
          if (g.fan_pct != null)        html += row('Fan', fmt(g.fan_pct, 0, '%'), g.fan_pct, 100, '#58a6ff');
          if (g.power_w != null)        html += row('Power', fmt(g.power_w, 0, 'W'), g.power_w, 80, '#bc8cff');
          if (g.util_pct != null)       html += row('Util', fmt(g.util_pct, 0, '%'), g.util_pct, 100, '#8b949e');
          if (g.clock_gr_mhz != null)   html += row('Graphics', fmt(g.clock_gr_mhz, 0, 'MHz'), g.clock_gr_mhz, 2500, '#3fb950');
          if (g.clock_mem_mhz != null)  html += row('Memory', fmt(g.clock_mem_mhz, 0, 'MHz'), g.clock_mem_mhz, 8000, '#3fb950');
          if (g.vram_used_mb != null && g.vram_total_mb != null) {
            html += row('VRAM', `${g.vram_used_mb} / ${g.vram_total_mb} MB`, g.vram_used_mb, g.vram_total_mb, '#d29922');
          } else if (g.vram_used_mb != null) {
            html += row('VRAM used', `${g.vram_used_mb} MB`, g.vram_used_mb, 16384, '#d29922');
          }
          return html;
        }).join('')
      : '<div class="empty">GPU telemetry not available on this hardware</div>';

    const drives = s.storage || [];
    document.getElementById('storage').innerHTML = drives.length
      ? drives.map(d2 => {
          const label = (d2.media && d2.media !== 'Unspecified')
            ? `${d2.name} (${d2.media})` : d2.name;
          return row(label, fmt(d2.temp_c, 0, '°C'), d2.temp_c, 100, tempColor(d2.temp_c));
        }).join('')
      : '<div class="empty">no SMART temperature exposed</div>';

    const b = s.battery || {};
    let bhtml = '';
    if (b.charge_pct != null) bhtml += row('Charge', fmt(b.charge_pct, 0, '%'), b.charge_pct, 100, '#2ea043');
    if (b.temp_c != null) bhtml += row('Temp (firmware)', fmt(b.temp_c, 1, '°C'), b.temp_c, 100, tempColor(b.temp_c));
    const batZone = zones.find(z => /batz/i.test(z.name));
    if (batZone) bhtml += row('Temp (ACPI batz)', batZone.value.toFixed(1) + ' °C', batZone.value, 100, tempColor(batZone.value));
    if (b.status) bhtml += `<div class="row"><div class="name">Status</div><div class="value" style="flex:1;text-align:left">${esc(b.status)}</div></div>`;
    if (b.runtime_min != null) bhtml += row('Runtime', fmt(b.runtime_min, 0, 'min'), b.runtime_min, 600, '#8b949e');
    document.getElementById('battery').innerHTML = bhtml || '<div class="empty">no battery info</div>';

    const cp = s.cpu_proxy || {};
    let chtml = '';
    if (cp.util_pct != null) chtml += row('CPU Util', fmt(cp.util_pct, 0, '%'), cp.util_pct, 100, '#58a6ff');
    if (cp.perf_pct != null) chtml += row('Perf (turbo)', fmt(cp.perf_pct, 0, '%'), cp.perf_pct, 200, '#db6d28');
    if (cp.freq_mhz != null) chtml += row('Frequency', fmt(cp.freq_mhz, 0, 'MHz'), cp.freq_mhz, 5500, '#bc8cff');
    const cpuZone = zones.find(z => /cpuz/i.test(z.name));
    if (cpuZone) chtml += row('CPU Zone', cpuZone.value.toFixed(1) + ' °C', cpuZone.value, 100, tempColor(cpuZone.value));
    chtml += `<div class="note">Higher load / turbo → EC spins fans harder.</div>`;
    document.getElementById('cpuproxy').innerHTML = chtml;

    const oem = s.oem || [];
    document.getElementById('oem').innerHTML = oem.length
      ? oem.map(h => {
          const kv = h.records.map(rec => Object.entries(rec).map(([k,v]) =>
            `<div class="oem-kv">${esc(k)}: ${esc(v)}</div>`).join('')).join('<hr style="border:0;border-top:1px solid #21262d;margin:6px 0">');
          return `<div class="oem-block"><div class="oem-class">${esc(h.class)}</div><div class="oem-ns">${esc(h.namespace)}</div>${kv}</div>`;
        }).join('')
      : '<div class="empty">no vendor-specific fan/thermal classes exposed</div>';
  } catch (e) {
    document.getElementById('updated').textContent = 'error: ' + e;
  }
}
refresh();
setInterval(refresh, REFRESH_MS);

(function initChat() {
  const fab = document.getElementById('chat-fab');
  const panel = document.getElementById('chat-panel');
  const closeBtn = document.getElementById('chat-close');
  const resetBtn = document.getElementById('chat-reset');
  const sendBtn = document.getElementById('chat-send');
  const input = document.getElementById('chat-input');
  const log = document.getElementById('chat-messages');
  const modelLbl = document.getElementById('chat-model-label');

  function appendMsg(cls, text) {
    const div = document.createElement('div');
    div.className = 'chat-msg ' + cls;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  fetch('/api/chat/status').then(r => r.json()).then(s => {
    if (modelLbl && s.model) modelLbl.textContent = '· ' + s.model;
    if (s.active_source === 'claude_code_cli') {
      appendMsg('tool', 'Connected via Claude Code CLI · uses your subscription, no API key needed.');
    } else if (!s.claude_cli_available) {
      appendMsg('error', 'Claude Code CLI not found on PATH. Install it from https://claude.com/code, then run "claude" once in a terminal to log in.');
    }
  }).catch(() => {});

  fab.addEventListener('click', () => {
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) input.focus();
  });
  closeBtn.addEventListener('click', () => panel.classList.remove('open'));
  resetBtn.addEventListener('click', async () => {
    if (!confirm('Clear?')) return;
    await fetch('/api/chat/reset', {method: 'POST'});
    log.innerHTML = '';
    appendMsg('assistant', 'Cleared.');
  });

  async function send() {
    const msg = input.value.trim();
    if (!msg) return;
    appendMsg('user', msg);
    input.value = '';
    sendBtn.disabled = true;
    sendBtn.textContent = '...';
    const thinking = appendMsg('tool', 'Thinking…');
    try {
      const r = await fetch('/api/chat', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: msg})});
      const d = await r.json();
      thinking.remove();
      if (!r.ok) appendMsg('error', d.error || 'request failed');
      else {
        (d.tool_calls || []).forEach(tc => {
          const args = (tc.input && Object.keys(tc.input).length) ? JSON.stringify(tc.input).slice(0, 80) : '';
          appendMsg('tool', '→ ' + tc.name + (args ? ' ' + args : ''));
        });
        appendMsg('assistant', d.reply || '(no reply)');
        refresh();
        setTimeout(refresh, 800);
      }
    } catch (e) {
      thinking.remove();
      appendMsg('error', String(e));
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
      input.focus();
    }
  }
  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
})();

// ───────────────────────── Diagnostic recorder ─────────────────────────
(function initRecorder() {
  const ivGroup    = document.getElementById('rec-interval');
  const controls   = document.getElementById('rec-controls');
  const startBtn   = document.getElementById('rec-start-btn');
  const statSpan   = document.getElementById('rec-stat');
  const fileLine   = document.getElementById('rec-file');
  let selectedIv = 10;

  // Interval picker
  ivGroup.addEventListener('click', e => {
    const b = e.target.closest('button[data-iv]');
    if (!b) return;
    selectedIv = Number(b.dataset.iv);
    ivGroup.querySelectorAll('button').forEach(x =>
      x.classList.toggle('active', x === b));
  });

  function fmtElapsed(s) {
    s = Math.floor(s || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m ${sec}s`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
  }

  function renderState(s) {
    if (!s || !s.active) {
      // Idle — Start button enabled, no live stats
      controls.innerHTML = '';
      const btn = document.createElement('button');
      btn.className = 'rec-start';
      btn.id = 'rec-start-btn';
      btn.textContent = '● Start Recording';
      btn.addEventListener('click', startRecording);
      controls.appendChild(btn);
      statSpan.textContent = '';
      controls.appendChild(statSpan);
      fileLine.textContent = '';
      return;
    }
    // Active — show stop button + live stats
    controls.innerHTML = '';
    const btn = document.createElement('button');
    btn.className = 'rec-stop';
    btn.textContent = '■ Stop Recording';
    btn.addEventListener('click', stopRecording);
    controls.appendChild(btn);
    const stat = document.createElement('span');
    stat.className = 'rec-stat';
    stat.innerHTML = `<span class="rec-dot"></span> ${s.samples} samples · ${fmtElapsed(s.elapsed_s)} · every ${s.interval_s}s`;
    controls.appendChild(stat);
    fileLine.textContent = s.file || '';
  }

  async function startRecording() {
    try {
      const r = await fetch('/api/recorder/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interval_s: selectedIv}),
      });
      const d = await r.json();
      if (!d.ok) flash(d.error || 'could not start', true);
      else flash('Recording started');
      pollStatus();
    } catch (e) { flash(String(e), true); }
  }

  async function stopRecording() {
    try {
      const r = await fetch('/api/recorder/stop', {method: 'POST'});
      const d = await r.json();
      if (!d.ok) flash(d.error || 'could not stop', true);
      else flash(`Saved ${d.samples} samples (${fmtElapsed(d.duration_s)})`);
      pollStatus();
    } catch (e) { flash(String(e), true); }
  }

  async function pollStatus() {
    try {
      const r = await fetch('/api/recorder/status');
      const s = await r.json();
      renderState(s);
    } catch (e) {
      // ignore — recorder is optional
    }
  }

  pollStatus();
  setInterval(pollStatus, 2000);
})();

// ───────────────────────── AI Auto-Optimize ─────────────────────────
(function initOptimizer() {
  const ivGroup     = document.getElementById('opt-interval');
  const controls    = document.getElementById('opt-controls');
  const stateBadge  = document.getElementById('opt-state');
  const timing      = document.getElementById('opt-timing');
  const reasonLine  = document.getElementById('opt-reasoning');
  const actionsLine = document.getElementById('opt-actions');
  const historyBox  = document.getElementById('opt-history');
  let selectedIv = 30;

  ivGroup.addEventListener('click', e => {
    const b = e.target.closest('button[data-iv]');
    if (!b) return;
    selectedIv = Number(b.dataset.iv);
    ivGroup.querySelectorAll('button').forEach(x =>
      x.classList.toggle('active', x === b));
  });

  function fmtState(s) {
    if (!s) return ['unknown', 'idle'];
    const klass = 'opt-state-' + s.replace(/[^a-z_]/g, '');
    const label = s.replace(/_/g, ' ');
    return [klass, label];
  }

  function renderActions(actions, results) {
    if (!actions || !actions.length) return '(no changes)';
    return actions.map((a, i) => {
      const r = (results && results[i]) || {};
      const status = r.skipped ? '↷ skipped' : (r.ok ? '✓' : '✗');
      const args = a.args ? JSON.stringify(a.args) : '';
      const err = (!r.ok && r.error) ? ` (${r.error})` : '';
      return `${status} ${a.name}${args ? ' ' + args : ''}${err}`;
    }).join('  ');
  }

  function renderState(s) {
    if (!s) return;
    // Toggle Start/Stop button
    controls.innerHTML = '';
    if (!s.active) {
      const startBtn = document.createElement('button');
      startBtn.className = 'opt-start';
      startBtn.textContent = 'Start Auto-Optimize';
      startBtn.addEventListener('click', start);
      controls.appendChild(startBtn);
    } else {
      const stopBtn = document.createElement('button');
      stopBtn.className = 'opt-stop';
      stopBtn.textContent = 'Stop';
      stopBtn.addEventListener('click', stop);
      controls.appendChild(stopBtn);
    }
    const runNowBtn = document.createElement('button');
    runNowBtn.className = 'opt-runnow';
    runNowBtn.textContent = 'Run Once Now';
    runNowBtn.addEventListener('click', runNow);
    controls.appendChild(runNowBtn);

    // State badge
    const ld = s.last_decision;
    if (ld) {
      const [klass, label] = fmtState(ld.state);
      stateBadge.className = 'opt-state-badge ' + klass;
      stateBadge.textContent = label + (ld.confidence ? ` · ${ld.confidence}` : '');
      reasonLine.textContent = ld.reasoning || '';
      actionsLine.textContent = renderActions(ld.actions, ld.results);
    } else {
      stateBadge.className = 'opt-state-badge opt-state-unknown';
      stateBadge.textContent = s.active ? 'running…' : 'idle';
      reasonLine.textContent = '';
      actionsLine.textContent = '';
    }

    // Timing
    const bits = [];
    if (s.active) bits.push(`every ${s.interval_minutes} min`);
    if (s.last_run_at) bits.push(`last: ${s.last_run_at}`);
    if (s.active && s.next_run_at) bits.push(`next: ${s.next_run_at}`);
    timing.textContent = bits.join(' · ');

    // History
    const hist = (s.history || []).slice(-6).reverse();
    historyBox.innerHTML = hist.map(h => {
      const [klass] = fmtState(h.state || 'unknown');
      const state = h.state || (h.error ? 'error' : 'unknown');
      const reason = h.error || h.reasoning || '';
      return `<div class="opt-history-row"><span class="opt-state-badge ${klass}" style="font-size:0.75em">${esc(state)}</span> <span style="color:#7d8590">${esc(h.started_at || '')}</span> ${esc(reason.slice(0, 100))}</div>`;
    }).join('');
  }

  async function start() {
    try {
      const r = await fetch('/api/optimizer/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({interval_minutes: selectedIv}),
      });
      const d = await r.json();
      if (!d.ok) flash(d.error || 'could not start', true);
      else flash('AI Auto-Optimize started');
      poll();
    } catch (e) { flash(String(e), true); }
  }

  async function stop() {
    try {
      const r = await fetch('/api/optimizer/stop', {method: 'POST'});
      const d = await r.json();
      if (!d.ok) flash(d.error || 'could not stop', true);
      else flash('Auto-Optimize stopped');
      poll();
    } catch (e) { flash(String(e), true); }
  }

  async function runNow() {
    flash('Asking Claude…');
    try {
      const r = await fetch('/api/optimizer/run-now', {method: 'POST'});
      const d = await r.json();
      if (!d.ok) flash(d.error || 'run failed', true);
      else flash(`Claude → ${d.state || '?'}`);
      poll();
    } catch (e) { flash(String(e), true); }
  }

  async function poll() {
    try {
      const r = await fetch('/api/optimizer/status');
      const s = await r.json();
      renderState(s);
    } catch (e) {
      // ignore
    }
  }

  poll();
  setInterval(poll, 3000);
})();
"""
