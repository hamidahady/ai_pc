"""pcd_page_css.py — the dashboard's inline CSS.

Extracted from pcd_page.py to keep each file under a few hundred lines.
Imported by pcd_page.py and concatenated into the PAGE template.
"""

CSS = r"""
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
  .muted { color: #7d8590; font-size: 0.85em; font-weight: normal; }
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
"""
