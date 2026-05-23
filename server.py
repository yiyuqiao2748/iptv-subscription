"""
HTTP Subscription Server + Web Dashboard
=========================================
Flask + waitress serving M3U subscription and a full web management dashboard.
"""

import json
import logging
import threading
from datetime import datetime, timezone, timedelta

from flask import Flask, Response, request, jsonify
from waitress import serve

from config import (
    BASE_DIR,
    SERVER_HOST,
    SERVER_PORT,
    SUBSCRIPTION_ROUTE,
    OUTPUT_M3U,
    OUTPUT_TXT,
)

logger = logging.getLogger("server")

TZ_CN = timezone(timedelta(hours=8))

app = Flask(__name__, static_folder=None)

# --- Global state ---
pipeline_stats = {
    "last_update": None,
    "total_channels": 0,
    "alive_channels": 0,
    "scan_duration": 0,
    "next_update": None,
    "update_interval_hours": 6,
    "pipeline_running": False,
}
_trigger_callback = None


def set_trigger_callback(cb):
    global _trigger_callback
    _trigger_callback = cb


def read_m3u_content():
    try:
        with open(OUTPUT_M3U, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "#EXTM3U\n# No playlist generated yet.\n"


def parse_channels():
    """Parse M3U file into structured channel list."""
    channels = []
    try:
        with open(OUTPUT_M3U, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return channels

    current_group = ""
    for idx, raw_line in enumerate(lines):
        line = raw_line.rstrip("\n")
        if line.startswith("# ===== ") and line.endswith(" ====="):
            current_group = line[7:-7].strip()
        elif line.startswith("#EXTINF:"):
            name = ""
            group = current_group
            if 'group-title="' in line:
                gt = line.split('group-title="')[1].split('"')[0]
                group = gt
            if "," in line:
                name = line.rsplit(",", 1)[-1].strip()
            # Get URL from next line
            if idx + 1 < len(lines):
                url = lines[idx + 1].strip()
                if url.startswith("http"):
                    channels.append({
                        "name": name,
                        "url": url,
                        "group": group,
                    })
    return channels


# --- API ---

@app.route("/api/stats")
def api_stats():
    return jsonify(pipeline_stats)


@app.route("/api/channels")
def api_channels():
    q = request.args.get("q", "").lower()
    group = request.args.get("group", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 100))

    channels = parse_channels()

    if q:
        channels = [c for c in channels if q in c["name"].lower() or q in c["url"].lower()]
    if group:
        channels = [c for c in channels if c["group"] == group]

    total = len(channels)
    start = (page - 1) * per_page
    page_data = channels[start:start + per_page]

    # Category counts
    cats = {}
    for c in channels:
        cats[c["group"]] = cats.get(c["group"], 0) + 1

    return jsonify({
        "channels": page_data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "categories": cats,
    })


@app.route(SUBSCRIPTION_ROUTE)
def serve_m3u():
    content = read_m3u_content()
    return Response(content, mimetype="audio/x-mpegurl",
                    headers={"Content-Disposition": "inline; filename=iptv.m3u", "Cache-Control": "no-cache"})


@app.route("/iptv.txt")
def serve_txt():
    try:
        with open(OUTPUT_TXT, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = "# No playlist generated yet.\n"
    return Response(content, mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": "inline; filename=iptv.txt", "Cache-Control": "no-cache"})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "channels": pipeline_stats["total_channels"], "alive": pipeline_stats["alive_channels"]})


@app.route("/trigger", methods=["POST"])
def trigger_pipeline():
    if pipeline_stats.get("pipeline_running"):
        return jsonify({"status": "busy", "message": "Pipeline already running"}), 409
    if _trigger_callback is None:
        return jsonify({"status": "error", "message": "Trigger not configured"}), 500
    threading.Thread(target=_trigger_callback, daemon=True).start()
    return jsonify({"status": "ok", "message": "Pipeline started"})


# --- Web Dashboard ---

@app.route("/")
def index():
    return DASHBOARD_HTML


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IPTV Subscription</title>
<style>
:root {
  --bg: #0b0e14; --card: #141821; --border: #1e2430;
  --text: #c9d1d9; --muted: #6b7280; --accent: #f0883e;
  --green: #3fb950; --red: #f85149; --blue: #58a6ff;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg); color: var(--text); min-height: 100vh;
}
.header {
  background: var(--card); border-bottom: 1px solid var(--border);
  padding: 16px 24px; display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 100;
}
.header h1 { font-size: 20px; font-weight: 700; color: #fff; }
.header h1 span { color: var(--accent); }
.status-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 6px; background: var(--green);
}
.status-dot.running { background: #f0a500; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

.container { max-width: 1200px; margin: 0 auto; padding: 20px 24px; }

/* Stats */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
.stat {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px 20px; text-align: center;
}
.stat .value { font-size: 28px; font-weight: 700; color: #fff; }
.stat .value.accent { color: var(--accent); }
.stat .value.green { color: var(--green); }
.stat .label { font-size: 12px; color: var(--muted); margin-top: 4px; }

/* URL bar */
.url-section {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px 20px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px;
  flex-wrap: wrap;
}
.url-section label { font-size: 13px; color: var(--muted); white-space: nowrap; }
.url-box {
  flex: 1; min-width: 200px; background: #0d1117; border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 12px; font-family: "SF Mono", Consolas, monospace;
  font-size: 13px; color: var(--blue); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.btn {
  background: var(--accent); color: #fff; border: none; border-radius: 6px;
  padding: 8px 16px; font-size: 13px; cursor: pointer; white-space: nowrap;
  font-weight: 600; transition: opacity .2s;
}
.btn:hover { opacity: 0.85; }
.btn:disabled { background: #555; cursor: not-allowed; }
.btn-sm { padding: 4px 10px; font-size: 12px; }

/* Search + Filter */
.toolbar {
  display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center;
}
.search {
  flex: 1; min-width: 180px; background: var(--card); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 12px; color: var(--text); font-size: 14px;
  outline: none;
}
.search:focus { border-color: var(--accent); }
.filter-select {
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 8px 12px; color: var(--text); font-size: 13px; outline: none; cursor: pointer;
}
.count { color: var(--muted); font-size: 13px; white-space: nowrap; }

/* Category tags */
.cats { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.cat-tag {
  background: var(--card); border: 1px solid var(--border); border-radius: 20px;
  padding: 4px 14px; font-size: 12px; color: var(--muted); cursor: pointer;
  transition: all .2s; white-space: nowrap;
}
.cat-tag:hover, .cat-tag.active { border-color: var(--accent); color: var(--accent); }
.cat-tag .count { color: var(--accent); margin-left: 4px; }

/* Table */
.table-wrap {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  overflow: hidden;
}
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left; padding: 10px 16px; font-size: 12px; color: var(--muted);
  text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid var(--border);
  background: #0d1117;
}
td { padding: 10px 16px; font-size: 14px; border-bottom: 1px solid #1a1f2b; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1a1f2b; }
.url-cell {
  max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: "SF Mono", Consolas, monospace; font-size: 12px; color: var(--blue);
}
.channel-name { font-weight: 500; }
.group-tag {
  display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
  background: #1a2332; color: var(--blue);
}
.copy-btn {
  background: none; border: 1px solid var(--border); color: var(--muted);
  border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer;
}
.copy-btn:hover { border-color: var(--accent); color: var(--accent); }

/* Pagination */
.pager { display: flex; justify-content: center; gap: 8px; margin-top: 16px; }
.pager button {
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 14px; color: var(--text); font-size: 13px; cursor: pointer;
}
.pager button:disabled { opacity: 0.3; cursor: not-allowed; }
.pager button.active { border-color: var(--accent); color: var(--accent); }

/* Footer */
.footer { text-align: center; padding: 24px; color: var(--muted); font-size: 12px; }

.toast {
  position: fixed; top: 20px; right: 20px; background: var(--green); color: #000;
  padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: 600;
  z-index: 999; opacity: 0; transition: opacity .3s;
}
.toast.show { opacity: 1; }
.toast.err { background: var(--red); color: #fff; }

@media (max-width: 600px) {
  .header { padding: 12px 16px; }
  .container { padding: 12px; }
  .stats { grid-template-columns: 1fr 1fr; }
  .url-section { flex-direction: column; align-items: stretch; }
  td { padding: 8px 10px; font-size: 13px; }
  .url-cell { max-width: 120px; }
}
</style>
</head>
<body>

<div class="header">
  <h1><span>📡</span> IPTV Subscription</h1>
  <div style="font-size:13px;color:var(--muted)">
    <span class="status-dot" id="statusDot"></span>
    <span id="statusText">Loading...</span>
  </div>
</div>

<div class="container">

  <!-- Stats -->
  <div class="stats">
    <div class="stat"><div class="value green" id="statAlive">-</div><div class="label">Alive Channels</div></div>
    <div class="stat"><div class="value" id="statTotal">-</div><div class="label">Total Scanned</div></div>
    <div class="stat"><div class="value" id="statUpdate">-</div><div class="label">Last Update</div></div>
    <div class="stat"><div class="value accent" id="statNext">-</div><div class="label">Next Update</div></div>
  </div>

  <!-- Subscription URL -->
  <div class="url-section">
    <label>🔗 M3U (APTV)</label>
    <div class="url-box" id="m3uUrl">-</div>
    <button class="btn" onclick="copyUrl('m3uUrl')">Copy</button>
    <button class="btn" id="triggerBtn" onclick="triggerUpdate()">Update Now</button>
  </div>

  <!-- Category tags -->
  <div class="cats" id="catTags"></div>

  <!-- Toolbar -->
  <div class="toolbar">
    <input class="search" type="text" id="searchInput" placeholder="Search channels..." oninput="loadChannels(1)">
    <select class="filter-select" id="groupFilter" onchange="loadChannels(1)"></select>
    <span class="count" id="resultCount"></span>
  </div>

  <!-- Channel table -->
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Channel</th><th>URL</th><th>Group</th><th></th></tr>
      </thead>
      <tbody id="channelBody"><tr><td colspan="4" style="text-align:center;color:var(--muted);padding:40px;">Loading...</td></tr></tbody>
    </table>
  </div>

  <!-- Pagination -->
  <div class="pager" id="pager"></div>

</div>

<div class="footer">IPTV Subscription Service · Auto-update · CCTV / Hunan / SAT / Local</div>
<div class="toast" id="toast"></div>

<script>
const API = '/api';
let allCats = {};
let currentPage = 1;

async function loadStats() {
  try {
    const r = await fetch(API + '/stats');
    const s = await r.json();
    document.getElementById('statAlive').textContent = s.alive_channels || 0;
    document.getElementById('statTotal').textContent = s.total_channels || 0;
    document.getElementById('statUpdate').textContent = s.last_update || 'N/A';
    document.getElementById('statNext').textContent = s.next_update || 'N/A';

    const running = s.pipeline_running;
    const dot = document.getElementById('statusDot');
    dot.className = 'status-dot' + (running ? ' running' : '');
    document.getElementById('statusText').textContent = running ? 'Updating...' : 'Online';

    const host = location.host;
    document.getElementById('m3uUrl').textContent = `http://${host}/iptv.m3u`;
  } catch(e) { console.error(e); }
}

async function loadChannels(page) {
  currentPage = page || 1;
  const q = document.getElementById('searchInput').value;
  const group = document.getElementById('groupFilter').value;

  try {
    const params = new URLSearchParams({ page: currentPage, per_page: 50, q, group });
    const r = await fetch(API + '/channels?' + params);
    const data = await r.json();

    allCats = data.categories || {};

    // Category tags
    let tagsHtml = '';
    const sortedCats = Object.entries(allCats).sort((a,b) => b[1] - a[1]);
    for (const [g, cnt] of sortedCats) {
      const active = group === g ? ' active' : '';
      tagsHtml += `<span class="cat-tag${active}" onclick="filterCat('${esc(g)}')">${esc(g)}<span class="count">${cnt}</span></span>`;
    }
    if (group) {
      tagsHtml += `<span class="cat-tag" onclick="filterCat('')" style="border-color:var(--red);color:var(--red)">✕ Clear</span>`;
    }
    document.getElementById('catTags').innerHTML = tagsHtml;

    // Group filter dropdown
    let opts = '<option value="">All Groups</option>';
    for (const [g, cnt] of sortedCats) {
      const sel = group === g ? ' selected' : '';
      opts += `<option value="${esc(g)}"${sel}>${esc(g)} (${cnt})</option>`;
    }
    document.getElementById('groupFilter').innerHTML = opts;

    // Table
    let rows = '';
    if (data.channels.length === 0) {
      rows = '<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:40px;">No channels found</td></tr>';
    }
    for (const c of data.channels) {
      rows += `<tr>
        <td><span class="channel-name">${esc(c.name)}</span></td>
        <td><span class="url-cell" title="${esc(c.url)}">${esc(c.url)}</span></td>
        <td><span class="group-tag">${esc(c.group)}</span></td>
        <td><button class="copy-btn" onclick="copyText('${esc(c.url)}', this)">Copy</button></td>
      </tr>`;
    }
    document.getElementById('channelBody').innerHTML = rows;
    document.getElementById('resultCount').textContent = `${data.total} channels`;

    // Pagination
    const totalPages = Math.ceil(data.total / data.per_page) || 1;
    let pagerHtml = '';
    pagerHtml += `<button onclick="loadChannels(${currentPage - 1})"${currentPage <= 1 ? ' disabled' : ''}>←</button>`;
    for (let i = 1; i <= totalPages; i++) {
      if (i > 1 && i < totalPages && Math.abs(i - currentPage) > 3) {
        if (i === 2) pagerHtml += '<button disabled>...</button>';
        continue;
      }
      pagerHtml += `<button onclick="loadChannels(${i})" class="${i === currentPage ? 'active' : ''}">${i}</button>`;
    }
    pagerHtml += `<button onclick="loadChannels(${currentPage + 1})"${currentPage >= totalPages ? ' disabled' : ''}>→</button>`;
    document.getElementById('pager').innerHTML = pagerHtml;

  } catch(e) { console.error(e); }
}

function filterCat(g) {
  document.getElementById('groupFilter').value = g;
  document.getElementById('searchInput').value = '';
  loadChannels(1);
}

async function triggerUpdate() {
  const btn = document.getElementById('triggerBtn');
  btn.disabled = true; btn.textContent = 'Starting...';
  try {
    const r = await fetch('/trigger', { method: 'POST' });
    const j = await r.json();
    showToast(j.message || 'Started', j.status !== 'ok');
    if (j.status === 'ok') {
      let cnt = 0;
      const iv = setInterval(async () => {
        const sr = await fetch(API + '/stats');
        const ss = await sr.json();
        if (!ss.pipeline_running && cnt > 0) { clearInterval(iv); loadStats(); loadChannels(currentPage); btn.disabled = false; btn.textContent = 'Update Now'; showToast('Update complete!'); }
        cnt++;
        if (cnt > 120) { clearInterval(iv); btn.disabled = false; btn.textContent = 'Update Now'; }
      }, 5000);
    }
  } catch(e) { showToast('Error: ' + e.message, true); btn.disabled = false; btn.textContent = 'Update Now'; }
}

function copyUrl(id) {
  const el = document.getElementById(id);
  navigator.clipboard.writeText(el.textContent).then(() => showToast('Copied!'));
}

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = '✓'; setTimeout(() => btn.textContent = 'Copy', 1500);
  });
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function showToast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast' + (isErr ? ' err' : '') + ' show';
  setTimeout(() => t.className = 'toast', 2500);
}

// Init
loadStats(); loadChannels(1);
setInterval(loadStats, 15000);
</script>
</body>
</html>"""


def update_stats(stats: dict):
    pipeline_stats.update(stats)


def run_server(host=None, port=None):
    host = host or SERVER_HOST
    port = port or SERVER_PORT
    logger.info(f"IPTV server: http://{host}:{port}")
    logger.info(f"  Dashboard: http://{host}:{port}/")
    logger.info(f"  M3U:       http://{host}:{port}{SUBSCRIPTION_ROUTE}")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    serve(app, host=host, port=port, threads=8)
