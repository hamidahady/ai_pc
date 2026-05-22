"""
pcd_page.py — HTML/CSS/JS for the dashboard UI.
"""

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>System Dashboard</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, "Segoe UI", sans-serif;
         background: #0f1419; color: #e6edf3; margin: 0; padding: 24px; }
  h1 { margin: 0 0 4px; font-size: 1.4em; }
  .updated { color: #7d8590; font-size: 0.85em; }
  .banner { background: #4d1f00; border: 1px solid #db6d28; color: #ffd29a;
            padding: 10px 14px; margin: 14px 0; border-radius: 6px; font-size: 0.9em; }
  .section-title { color: #7d8590; font-size: 0.8em; text-transform: uppercase;
                   letter-spacing: 0.08em; margin: 24px 0 8px; }
  .grid { display: grid; gap: 16px; }
  .grid.controls { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  .grid.metrics  { grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 14px 16px; }
  .card h2 { margin: 0 0 10px; font-size: 1.0em; color: #79c0ff;
             font-weight: 600; letter-spacing: 0.02em; }
  .card h2 small { color: #7d8590; font-weight: 400;
                   font-size: 0.85em; margin-left: 8px; }
  .btn-group { display: flex; flex-wrap: wrap; gap: 6px; }
  button.ctrl { background: #21262d; border: 1px solid #30363d; color: #e6edf3;
                padding: 6px 10px; border-radius: 5px; font-size: 0.85em;
                cursor: pointer; transition: background 0.15s, border 0.15s; }
  button.ctrl:hover { background: #2d333b; }
  button.ctrl.active { background: #1f6feb; border-color: #388bfd; color: #fff; }
  button.ctrl:disabled { opacity: 0.5; cursor: not-allowed; }
  button.preset { font-weight: 600; padding: 8px 14px; }
  .slider-row { display: flex; align-items: center; gap: 12px; margin: 4px 0; }
  .slider-row input[type=range] { flex: 1; accent-color: #58a6ff; }
  .slider-row .lbl { flex: 0 0 90px; text-align: right;
                     font-variant-numeric: tabular-nums; font-size: 0.9em; }
  .slider-row.locked input[type=range] { opacity: 0.4; pointer-events: none; }
  .row { display: flex; align-items: center; gap: 12px; margin: 6px 0; }
  .name { flex: 0 0 170px; color: #b1bac4; font-size: 0.9em;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .value { flex: 0 0 88px; text-align: right;
           font-variant-numeric: tabular-nums; font-size: 0.95em; }
  .bar { flex: 1; height: 8px; background: #21262d;
         border-radius: 4px; overflow: hidden; }
  .bar > div { height: 100%; transition: width 0.4s ease, background 0.4s ease; }
  .gpu-name { color: #f0f6fc; font-size: 0.95em; margin: 0 0 8px; }
  .empty { color: #7d8590; font-style: italic; font-size: 0.9em; }
  .oem-block { margin-bottom: 12px; }
  .oem-block .oem-class { color: #f0f6fc; font-size: 0.9em; }
  .oem-block .oem-ns { color: #7d8590; font-size: 0.75em; margin-bottom: 4px; }
  .oem-block .oem-kv { font-size: 0.85em; color: #b1bac4; }
  .sysinfo { display: flex; flex-wrap: wrap; gap: 6px 22px;
             color: #b1bac4; font-size: 0.85em; margin: 8px 0 4px; }
  .sysinfo .si-key { color: #7d8590; }
  .sysinfo .si-val { color: #f0f6fc; margin-left: 4px; }
  .note { color: #7d8590; font-style: italic; font-size: 0.8em; margin-top: 8px; }
  .note.locked { color: #db6d28; font-style: normal; }
  .current { margin-top: 10px; font-size: 0.85em; color: #7d8590; }
  .current b { color: #fff; background: #1f6feb;
               padding: 3px 10px; border-radius: 4px;
               font-weight: 600; font-size: 0.92em; display: inline-block; }
  .current.unknown b { background: #30363d; color: #7d8590; font-style: italic; font-weight: 400; }
  .flash { position: fixed; top: 18px; right: 18px; padding: 14px 22px;
           background: #1f6feb; color: #fff; border-radius: 8px;
           font-size: 1.0em; font-weight: 600; opacity: 0;
           transform: translateY(-6px);
           transition: opacity 0.25s, transform 0.25s;
           pointer-events: none; z-index: 100;
           box-shadow: 0 6px 24px rgba(0,0,0,0.4); }
  .flash.show { opacity: 1; transform: translateY(0); }
  .flash.error { background: #da3633; }
  .key-metrics { display: grid;
                 grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                 gap: 12px; margin: 16px 0 20px; }
  .metric-tile { background: #161b22; border: 1px solid #30363d;
                 border-radius: 10px; padding: 12px 16px; }
  .metric-tile .ml { color: #7d8590; font-size: 0.72em;
                     text-transform: uppercase; letter-spacing: 0.08em;
                     font-weight: 600; }
  .metric-tile .mv { font-size: 1.9em; font-weight: 700; margin: 4px 0 2px;
                     font-variant-numeric: tabular-nums; line-height: 1.1;
                     color: #f0f6fc; }
  .metric-tile .ms { color: #7d8590; font-size: 0.82em; }
  .metric-tile.warm { border-color: #d29922; }
  .metric-tile.warm .mv { color: #f1c40f; }
  .metric-tile.hot  { border-color: #db6d28; }
  .metric-tile.hot .mv  { color: #ff9558; }
  .metric-tile.crit { border-color: #f85149; box-shadow: 0 0 18px rgba(248,81,73,0.25); }
  .metric-tile.crit .mv { color: #ff7b72; }
  .metric-tile.good { border-color: #2ea043; }
  .metric-tile.good .mv { color: #56d364; }
  .chat-fab { position: fixed; bottom: 22px; right: 22px;
              width: 60px; height: 60px; border-radius: 30px;
              background: #1f6feb; color: white; border: none;
              font-size: 16px; font-weight: 700; cursor: pointer;
              box-shadow: 0 6px 20px rgba(0,0,0,0.45); z-index: 95; }
  .chat-fab:hover { background: #388bfd; }
  .chat-panel { position: fixed; bottom: 96px; right: 22px;
                width: 440px; height: 600px;
                background: #161b22; border: 1px solid #30363d;
                border-radius: 12px; display: none;
                flex-direction: column; z-index: 95; overflow: hidden;
                box-shadow: 0 10px 40px rgba(0,0,0,0.55); }
  .chat-panel.open { display: flex; }
  .chat-header { padding: 12px 16px; border-bottom: 1px solid #30363d;
                 display: flex; justify-content: space-between; align-items: center;
                 background: #0f1419; }
  .chat-header b { color: #79c0ff; }
  .chat-header .chat-sub { color: #7d8590; font-size: 0.78em; margin-left: 6px; }
  .chat-header-btns button { background: none; border: none; color: #7d8590;
                             cursor: pointer; font-size: 1.0em; padding: 4px 8px;
                             border-radius: 4px; }
  .chat-header-btns button:hover { background: #21262d; color: #e6edf3; }
  .chat-messages { flex: 1; overflow-y: auto; padding: 12px 14px;
                   display: flex; flex-direction: column; gap: 8px; }
  .chat-msg { padding: 9px 12px; border-radius: 10px; line-height: 1.45;
              font-size: 0.88em; max-width: 92%; white-space: pre-wrap;
              word-wrap: break-word; }
  .chat-msg.user { background: #1f6feb; color: white; align-self: flex-end; }
  .chat-msg.assistant { background: #21262d; color: #e6edf3; align-self: flex-start; }
  .chat-msg.tool { background: transparent; color: #7d8590; align-self: flex-start;
                   font-family: Consolas, monospace; font-size: 0.78em; }
  .chat-msg.error { background: #4d1f00; color: #ffd29a; border: 1px solid #db6d28; }
  .chat-input { display: flex; padding: 10px 12px; border-top: 1px solid #30363d;
                gap: 8px; background: #0f1419; }
  .chat-input textarea { flex: 1; background: #21262d; color: #e6edf3;
                         border: 1px solid #30363d; border-radius: 6px;
                         padding: 8px 10px; resize: none; font-family: inherit;
                         font-size: 0.9em; }
  .chat-input button { background: #1f6feb; color: white; border: none;
                       padding: 8px 16px; border-radius: 6px; cursor: pointer;
                       font-weight: 600; }

  /* Diagnostic recording card */
  .rec-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 6px 0; }
  .rec-interval { display: flex; gap: 4px; flex-wrap: wrap; }
  .rec-interval button { background: #21262d; border: 1px solid #30363d; color: #e6edf3;
                         padding: 4px 8px; border-radius: 4px; font-size: 0.8em; cursor: pointer; }
  .rec-interval button.active { background: #1f6feb; border-color: #388bfd; color: #fff; }
  button.rec-start { background: #2ea043; color: white; border: none;
                     padding: 8px 14px; border-radius: 5px; font-weight: 600;
                     cursor: pointer; font-size: 0.9em; }
  button.rec-start:hover { background: #3fb950; }
  button.rec-stop  { background: #da3633; color: white; border: none;
                     padding: 8px 14px; border-radius: 5px; font-weight: 600;
                     cursor: pointer; font-size: 0.9em; }
  button.rec-stop:hover { background: #f85149; }
  .rec-stat { color: #b1bac4; font-size: 0.85em; font-variant-numeric: tabular-nums; }
  .rec-file { color: #79c0ff; font-size: 0.82em;
              font-family: Consolas, monospace; word-break: break-all; margin-top: 6px; }
  .rec-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
             background: #f85149; margin-right: 6px; vertical-align: middle;
             animation: rec-pulse 1.4s ease-in-out infinite; }
  @keyframes rec-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

  /* AI Auto-Optimize card */
  .opt-state-badge { display: inline-block; padding: 3px 10px; border-radius: 4px;
                     font-weight: 700; font-size: 0.85em; }
  .opt-state-active     { background: #2ea043; color: white; }
  .opt-state-working    { background: #f85149; color: white; }
  .opt-state-brief_away { background: #d29922; color: #0f1419; }
  .opt-state-long_away  { background: #db6d28; color: white; }
  .opt-state-screen_off { background: #6e7681; color: white; }
  .opt-state-locked     { background: #30363d; color: #f0f6fc; }
  .opt-state-unknown    { background: #21262d; color: #7d8590; font-style: italic; font-weight: 400; }
  .opt-reasoning { color: #b1bac4; font-size: 0.85em; margin-top: 8px;
                   font-style: italic; line-height: 1.4; }
  .opt-actions   { color: #b1bac4; font-size: 0.82em; margin-top: 6px;
                   font-family: Consolas, monospace; }
  .opt-meta { color: #7d8590; font-size: 0.78em; margin-top: 4px;
              font-variant-numeric: tabular-nums; }
  button.opt-start { background: #1f6feb; color: white; border: none;
                     padding: 8px 14px; border-radius: 5px; font-weight: 600;
                     cursor: pointer; font-size: 0.9em; }
  button.opt-start:hover { background: #388bfd; }
  button.opt-stop  { background: #da3633; color: white; border: none;
                     padding: 8px 14px; border-radius: 5px; font-weight: 600;
                     cursor: pointer; font-size: 0.9em; }
  button.opt-stop:hover { background: #f85149; }
  button.opt-runnow { background: #21262d; color: #79c0ff; border: 1px solid #30363d;
                     padding: 6px 10px; border-radius: 5px; font-size: 0.82em;
                     cursor: pointer; }
  button.opt-runnow:hover { background: #2d333b; }
  button.opt-runnow:disabled { opacity: 0.5; cursor: not-allowed; }
  .opt-history { margin-top: 8px; max-height: 110px; overflow-y: auto;
                 font-size: 0.78em; color: #b1bac4; }
  .opt-history-row { padding: 3px 0; border-top: 1px dashed #30363d; }
  .opt-history-row:first-child { border-top: none; }
</style></head>
<body>
<h1>System Dashboard <small id="hostname" style="color:#7d8590;font-size:0.65em;font-weight:400"></small></h1>
<div class="sysinfo" id="sysinfo"></div>
<div class="updated"><span id="updated">connecting...</span></div>
<div id="admin-banner" class="banner" style="display:none">
  Not running as Administrator. Power-plan and overlay buttons should work,
  but the CPU / GPU / Cooling / Turbo controls will fail silently.
</div>

<div class="key-metrics" id="key-metrics"></div>

<div class="section-title">Controls</div>
<div class="grid controls">
  <div class="card"><h2>Quick Presets</h2>
    <div class="btn-group" id="presets">
      <button class="ctrl preset" data-preset="quiet">Quiet</button>
      <button class="ctrl preset" data-preset="balanced">Balanced</button>
      <button class="ctrl preset" data-preset="performance">Performance</button>
    </div>
    <div class="note">Combines cooling policy, turbo, CPU cap, GPU power, Win11 overlay.</div>
  </div>

  <div class="card"><h2>AI Auto-Optimize <small>Claude Code</small></h2>
    <div class="rec-row">
      <span class="rec-stat">Check every</span>
      <div class="rec-interval" id="opt-interval">
        <button data-iv="1">1 min</button>
        <button data-iv="5">5 min</button>
        <button data-iv="10">10 min</button>
        <button data-iv="30" class="active">30 min</button>
      </div>
    </div>
    <div class="rec-row" id="opt-controls"></div>
    <div id="opt-state-line">
      <span class="opt-state-badge opt-state-unknown" id="opt-state">idle</span>
      <span class="opt-meta" id="opt-timing"></span>
    </div>
    <div class="opt-reasoning" id="opt-reasoning"></div>
    <div class="opt-actions" id="opt-actions"></div>
    <div class="opt-history" id="opt-history"></div>
    <div class="note">Claude reads live state + recent recording + control log every N minutes and adjusts power settings to match how you're using the PC (active / away / locked / screen-off).</div>
  </div>

  <div class="card"><h2>Diagnostic Recording <small>pc_status_*.txt</small></h2>
    <div class="rec-row">
      <span class="rec-stat">Sample every</span>
      <div class="rec-interval" id="rec-interval">
        <button data-iv="5">5 s</button>
        <button data-iv="10" class="active">10 s</button>
        <button data-iv="30">30 s</button>
        <button data-iv="60">1 min</button>
      </div>
    </div>
    <div class="rec-row" id="rec-controls">
      <button class="rec-start" id="rec-start-btn">● Start Recording</button>
      <span class="rec-stat" id="rec-stat"></span>
    </div>
    <div class="rec-file" id="rec-file"></div>
    <div class="note">Captures temperatures, fan speeds, CPU load, power state to a text file you can hand off for diagnosis (e.g. fans staying loud during idle).</div>
  </div>
  <div class="card"><h2>Power Plan <small>powercfg</small></h2>
    <div class="btn-group" id="powerplans"></div>
    <div class="current unknown" id="powerplans-current"><b>unknown</b></div>
  </div>
  <div class="card"><h2>Power Mode <small>Win11 overlay</small></h2>
    <div class="btn-group" id="overlay">
      <button class="ctrl" data-name="best-efficiency">Best efficiency</button>
      <button class="ctrl" data-name="balanced">Balanced</button>
      <button class="ctrl" data-name="best-performance">Best performance</button>
    </div>
    <div class="current unknown" id="overlay-current"><b>unknown</b></div>
  </div>
  <div class="card"><h2>System Cooling Policy</h2>
    <div class="btn-group" id="cooling">
      <button class="ctrl" data-val="0">Passive (Quiet)</button>
      <button class="ctrl" data-val="1">Active (Fans first)</button>
    </div>
    <div class="current unknown" id="cooling-current"><b>unknown</b></div>
  </div>
  <div class="card"><h2>Turbo Boost</h2>
    <div class="btn-group" id="turbo">
      <button class="ctrl" data-val="0">Disabled</button>
      <button class="ctrl" data-val="1">Enabled</button>
      <button class="ctrl" data-val="2">Aggressive</button>
      <button class="ctrl" data-val="3">Eff Enabled</button>
      <button class="ctrl" data-val="4">Eff Aggressive</button>
    </div>
    <div class="current unknown" id="turbo-current"><b>unknown</b></div>
  </div>
  <div class="card"><h2>CPU Max State</h2>
    <div class="slider-row">
      <input type="range" id="cpumax" min="30" max="100" step="1" value="100">
      <div class="lbl" id="cpumax-lbl">100 %</div>
    </div>
  </div>
  <div class="card"><h2>CPU Min State</h2>
    <div class="slider-row">
      <input type="range" id="cpumin" min="5" max="100" step="1" value="5">
      <div class="lbl" id="cpumin-lbl">5 %</div>
    </div>
  </div>
  <div class="card"><h2>GPU Power Limit</h2>
    <div class="slider-row">
      <input type="range" id="gpupl" min="5" max="300" step="1" value="35">
      <div class="lbl" id="gpupl-lbl">— W</div>
    </div>
    <div class="note" id="gpupl-note"></div>
  </div>
</div>

<div class="section-title">Live Readings</div>
<div class="grid metrics">
  <div class="card"><h2>CPU / Skin</h2><div id="zones"></div></div>
  <div class="card"><h2>NVIDIA GPU</h2><div id="nvidia"></div></div>
  <div class="card"><h2>Storage</h2><div id="storage"></div></div>
  <div class="card"><h2>Battery</h2><div id="battery"></div></div>
  <div class="card"><h2>Fan Proxy</h2><div id="cpuproxy"></div></div>
  <div class="card"><h2>OEM Sensors</h2><div id="oem"></div></div>
</div>

<div id="flash" class="flash"></div>

<button class="chat-fab" id="chat-fab" title="Ask the AI assistant">AI</button>
<div class="chat-panel" id="chat-panel">
  <div class="chat-header">
    <div><b>AI Assistant</b><span class="chat-sub" id="chat-model-label">Claude</span></div>
    <div class="chat-header-btns">
      <button id="chat-reset" title="Clear">&#x21bb;</button>
      <button id="chat-close" title="Close">&times;</button>
    </div>
  </div>
  <div class="chat-messages" id="chat-messages">
    <div class="chat-msg assistant">Hi! I can read your PC's live state and adjust settings.
Try: "Make it quieter" or "What's running hot?".</div>
  </div>
  <div class="chat-input">
    <textarea id="chat-input" placeholder="Ask anything..." rows="2"></textarea>
    <button id="chat-send">Send</button>
  </div>
</div>

<script>
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
      gpunote.textContent = 'nvidia-smi unavailable';
    }

    const zones = s.thermal_zones || [];
    document.getElementById('zones').innerHTML = zones.length
      ? zones.map(z => row(shortZone(z.name), z.value.toFixed(1) + ' °C',
                           z.value, 100, tempColor(z.value))).join('')
      : '<div class="empty">no data</div>';

    const gpus = s.nvidia || [];
    document.getElementById('nvidia').innerHTML = gpus.length
      ? gpus.map(g => `<div class="gpu-name">${esc(g.name)}</div>` +
          row('Temp', fmt(g.temp_c, 0, '°C'), g.temp_c, 100, tempColor(g.temp_c)) +
          row('Fan', fmt(g.fan_pct, 0, '%'), g.fan_pct, 100, '#58a6ff') +
          row('Power', fmt(g.power_w, 0, 'W'), g.power_w, 80, '#bc8cff') +
          row('Util', fmt(g.util_pct, 0, '%'), g.util_pct, 100, '#8b949e') +
          row('Graphics', fmt(g.clock_gr_mhz, 0, 'MHz'), g.clock_gr_mhz, 2500, '#3fb950') +
          row('Memory', fmt(g.clock_mem_mhz, 0, 'MHz'), g.clock_mem_mhz, 8000, '#3fb950')).join('')
      : '<div class="empty">nvidia-smi not available</div>';

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
</script>
</body></html>"""
