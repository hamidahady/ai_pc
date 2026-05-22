"""pcd_page_html.py — the dashboard's body HTML (between <body> and <script>).

Extracted from pcd_page.py. Imported by pcd_page.py.
"""

BODY_HTML = r"""
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
  <div class="card"><h2>GPU</h2><div id="nvidia"></div></div>
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
"""
