"""
job-agent Dashboard Server

Serves the web dashboard at http://localhost:5000
Auto-reads from ~/.job_agent/jobs.db

Usage:
    job-agent dashboard
    # or directly:
    python -m job_agent.dashboard
"""

import json
import sqlite3
import webbrowser
from pathlib import Path
from threading import Timer

try:
    from flask import Flask, jsonify, request, render_template_string
except ImportError:
    raise ImportError("Flask not installed. Run: pip install flask")

DB_PATH = Path.home() / ".job_agent" / "jobs.db"

app = Flask(__name__)



# ── Workday URL fixer ──────────────────────────────────────────────────────────
# Fixes broken URLs stored in DB before the workday.py patch.
# Handles all three formats:
#   /job/...                          → /en-US/{site}/job/...
#   /wday/cxs/{tenant}/{site}/job/... → /en-US/{site}/job/...
#   /en-US/{site}/job/...             → unchanged (already correct)

_WORKDAY_SITE_MAP = {
    "cisco":            "Cisco_Careers",
    "intel":            "External",
    "nvidia":           "NVIDIAExternalCareerSite",
    "qualcomm":         "External",
    "broadcom":         "External",
    "marvell":          "MarvellCareers",
    "paloaltonetworks": "External",
    "fortinet":         "External",
    "hpe":              "Jobsathpe",
    "purestorage":      "External",
    "juniper":          "JuniperCareers",
    "waymo":            "waymo",
    "rivian":           "careers",
}

def fix_workday_url(url):
    import re as _re
    if not url or "myworkdayjobs.com" not in url:
        return url
    if "/en-US/" in url:
        return url
    # API format: /wday/cxs/{tenant}/{site}/job/...
    m = _re.match(r"(https://(\w+)\.wd\d+\.myworkdayjobs\.com)/wday/cxs/[^/]+/([^/]+)(/.+)", url)
    if m:
        return f"{m.group(1)}/en-US/{m.group(3)}{m.group(4)}"
    # Old broken format: /job/... (missing /en-US/{site}/)
    m = _re.match(r"(https://(\w+)\.wd\d+\.myworkdayjobs\.com)(/job/.+)", url)
    if m:
        site = _WORKDAY_SITE_MAP.get(m.group(2), "External")
        return f"{m.group(1)}/en-US/{site}{m.group(3)}"
    return url


_WORKDAY_SITE_MAP = {
    "cisco": "Cisco_Careers", "intel": "External",
    "nvidia": "NVIDIAExternalCareerSite", "qualcomm": "External",
    "broadcom": "External", "marvell": "MarvellCareers",
    "paloaltonetworks": "External", "fortinet": "External",
    "hpe": "Jobsathpe", "purestorage": "External",
    "juniper": "JuniperCareers", "waymo": "waymo", "rivian": "careers",
}

def fix_workday_url(url):
    import re as _re
    if not url or "myworkdayjobs.com" not in url or "/en-US/" in url:
        return url
    m = _re.match(r"(https://(\w+)\.wd\d+\.myworkdayjobs\.com)/wday/cxs/[^/]+/([^/]+)(/.+)", url)
    if m:
        return f"{m.group(1)}/en-US/{m.group(3)}{m.group(4)}"
    m = _re.match(r"(https://(\w+)\.wd\d+\.myworkdayjobs\.com)(/job/.+)", url)
    if m:
        site = _WORKDAY_SITE_MAP.get(m.group(2), "External")
        return f"{m.group(1)}/en-US/{site}{m.group(3)}"
    return url

# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    d = dict(row)
    if d.get('apply_url'):
        d['apply_url'] = fix_workday_url(d['apply_url'])
    if d.get('apply_url'):
        d['apply_url'] = fix_workday_url(d['apply_url'])
    for field in ("matched_skills", "missing_skills"):
        try:
            d[field] = json.loads(d.get(field) or "[]")
        except Exception:
            d[field] = []
    return d


# ── API routes ─────────────────────────────────────────────────────────────────

@app.route("/api/jobs")
def api_jobs():
    conn = get_db()
    if not conn:
        return jsonify([])
    try:
        decision = request.args.get("decision")
        search   = request.args.get("search", "").strip().lower()
        min_score = int(request.args.get("min_score", 0))

        q = "SELECT * FROM jobs WHERE score >= ?"
        params = [min_score]
        if decision:
            q += " AND decision = ?"
            params.append(decision)
        q += " ORDER BY score DESC, date_found DESC"

        rows = conn.execute(q, params).fetchall()
        jobs = [row_to_dict(r) for r in rows]

        if search:
            jobs = [j for j in jobs if search in j.get("company","").lower()
                    or search in j.get("role","").lower()]
        return jsonify(jobs)
    finally:
        conn.close()


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    conn = get_db()
    if not conn:
        return jsonify({}), 404
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return jsonify({}), 404
        return jsonify(row_to_dict(row))
    finally:
        conn.close()


@app.route("/api/jobs/<job_id>/status", methods=["POST"])
def api_update_status(job_id):
    conn = get_db()
    if not conn:
        return jsonify({"error": "no db"}), 500
    try:
        data = request.get_json()
        status = data.get("status", "shortlisted")
        notes  = data.get("notes", "")
        conn.execute(
            "UPDATE jobs SET status = ?, notes = ? WHERE job_id = ?",
            (status, notes, job_id)
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/stats")
def api_stats():
    conn = get_db()
    if not conn:
        return jsonify({"total": 0})
    try:
        total    = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        apply    = conn.execute("SELECT COUNT(*) FROM jobs WHERE decision='apply_now'").fetchone()[0]
        review   = conn.execute("SELECT COUNT(*) FROM jobs WHERE decision='review'").fetchone()[0]
        applied  = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='applied'").fetchone()[0]
        interview= conn.execute("SELECT COUNT(*) FROM jobs WHERE status='interview'").fetchone()[0]
        avg      = conn.execute("SELECT AVG(score) FROM jobs").fetchone()[0] or 0
        cached   = 0
        cache_db = Path.home() / ".job_agent" / "ai_cache.db"
        if cache_db.exists():
            cc = sqlite3.connect(cache_db)
            cached = cc.execute("SELECT COUNT(*) FROM ai_scores").fetchone()[0]
            cc.close()
        return jsonify({
            "total": total, "apply_now": apply, "review": review,
            "applied": applied, "interview": interview,
            "avg_score": round(avg, 1), "cached": cached
        })
    finally:
        conn.close()


# ── Main page ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


# ── HTML ───────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobPilot — Riya's Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,300;0,500;0,700;1,300&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root {
  --cream: #faf8f4;
  --paper: #f4f1eb;
  --warm-white: #ffffff;
  --ink: #1a1814;
  --ink-soft: #4a4540;
  --ink-faint: #9a9490;
  --border: #e5e0d8;
  --border-dark: #ccc8c0;
  --green: #2d6a4f;
  --green-bg: #eaf4ee;
  --green-light: #d8eedf;
  --yellow: #b5580f;
  --yellow-bg: #fdf3e7;
  --yellow-light: #fde8c8;
  --red: #c0392b;
  --red-bg: #fdf0ee;
  --blue: #1a5276;
  --blue-bg: #eaf0f8;
  --gold: #c9913a;
  --shadow-sm: 0 1px 4px rgba(26,24,20,.06);
  --shadow-md: 0 4px 20px rgba(26,24,20,.09);
  --shadow-lg: 0 8px 40px rgba(26,24,20,.12);
  --radius: 12px;
  --radius-sm: 8px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'DM Sans', sans-serif;
  background: var(--cream);
  color: var(--ink);
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Top bar ── */
.topbar {
  background: var(--warm-white);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  height: 60px;
  display: flex;
  align-items: center;
  gap: 24px;
  flex-shrink: 0;
  box-shadow: var(--shadow-sm);
}

.logo {
  font-family: 'Fraunces', serif;
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.5px;
  white-space: nowrap;
}
.logo span { color: var(--gold); }

.stats-bar {
  display: flex;
  gap: 16px;
  align-items: center;
  flex: 1;
}

.stat-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}
.stat-pill.green { background: var(--green-bg); color: var(--green); }
.stat-pill.yellow { background: var(--yellow-bg); color: var(--yellow); }
.stat-pill.blue { background: var(--blue-bg); color: var(--blue); }
.stat-pill.gray { background: var(--paper); color: var(--ink-soft); border: 1px solid var(--border); }

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: var(--ink);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-family: 'DM Sans', sans-serif;
  font-weight: 500;
  cursor: pointer;
  transition: opacity .15s;
}
.refresh-btn:hover { opacity: .8; }

.last-refresh {
  font-size: 11px;
  color: var(--ink-faint);
}

/* ── Main layout ── */
.main {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Left sidebar ── */
.sidebar {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--warm-white);
}

.sidebar-controls {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.search-box {
  position: relative;
}

.search-box input {
  width: 100%;
  padding: 9px 12px 9px 36px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-family: 'DM Sans', sans-serif;
  background: var(--cream);
  color: var(--ink);
  outline: none;
  transition: border-color .15s;
}
.search-box input:focus { border-color: var(--ink-soft); }
.search-icon {
  position: absolute;
  left: 10px; top: 50%;
  transform: translateY(-50%);
  color: var(--ink-faint);
  font-size: 14px;
}

.filter-tabs {
  display: flex;
  gap: 4px;
}
.filter-tab {
  padding: 5px 12px;
  border-radius: 100px;
  border: 1px solid var(--border);
  background: transparent;
  font-size: 12px;
  font-family: 'DM Sans', sans-serif;
  font-weight: 500;
  cursor: pointer;
  color: var(--ink-soft);
  transition: all .15s;
}
.filter-tab.active {
  background: var(--ink);
  color: white;
  border-color: var(--ink);
}
.filter-tab:hover:not(.active) { background: var(--paper); }

.score-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ink-soft);
}
.score-filter input[type=range] {
  flex: 1;
  accent-color: var(--ink);
}

/* ── Job list ── */
.job-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.job-card {
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background .12s;
  border: 1px solid transparent;
  margin-bottom: 4px;
}
.job-card:hover { background: var(--paper); }
.job-card.active {
  background: var(--cream);
  border-color: var(--border-dark);
}

.job-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 6px;
}

.score-badge {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Fraunces', serif;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}
.score-badge.green { background: var(--green-light); color: var(--green); }
.score-badge.yellow { background: var(--yellow-light); color: var(--yellow); }
.score-badge.red { background: var(--red-bg); color: var(--red); }

.job-card-info { flex: 1; min-width: 0; }
.job-card-company {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  margin-bottom: 2px;
}
.job-card-role {
  font-size: 12px;
  color: var(--ink-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.decision-tag {
  padding: 2px 8px;
  border-radius: 100px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .3px;
  text-transform: uppercase;
  flex-shrink: 0;
}
.decision-tag.apply { background: var(--green-bg); color: var(--green); }
.decision-tag.review { background: var(--yellow-bg); color: var(--yellow); }

.job-card-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--ink-faint);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--ink-faint);
  font-size: 13px;
  text-align: center;
  gap: 8px;
}
.empty-state .icon { font-size: 32px; }

/* ── Detail panel ── */
.detail-panel {
  flex: 1;
  overflow-y: auto;
  background: var(--cream);
  display: flex;
  flex-direction: column;
}

.detail-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ink-faint);
  gap: 12px;
}
.detail-empty .big-icon { font-size: 48px; opacity: .4; }
.detail-empty p { font-family: 'Fraunces', serif; font-size: 18px; font-style: italic; }

.detail-content {
  padding: 28px 32px;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

/* Detail header */
.detail-header {
  margin-bottom: 24px;
}

.detail-company {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-faint);
  letter-spacing: .5px;
  text-transform: uppercase;
  margin-bottom: 6px;
}

.detail-role {
  font-family: 'Fraunces', serif;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--ink);
  margin-bottom: 12px;
}

.detail-meta-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.meta-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ink-soft);
}

.detail-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.apply-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 11px 22px;
  background: var(--green);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: 'DM Sans', sans-serif;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  transition: opacity .15s, transform .1s;
}
.apply-btn:hover { opacity: .9; transform: translateY(-1px); }
.apply-btn:active { transform: translateY(0); }

.status-select {
  padding: 9px 14px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-family: 'DM Sans', sans-serif;
  background: white;
  color: var(--ink);
  cursor: pointer;
  outline: none;
}
.status-select:focus { border-color: var(--ink-soft); }

.status-saved {
  font-size: 12px;
  color: var(--green);
  opacity: 0;
  transition: opacity .3s;
}
.status-saved.show { opacity: 1; }

/* Score section */
.score-section {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 16px;
}

.score-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}

.big-score {
  font-family: 'Fraunces', serif;
  font-size: 48px;
  font-weight: 700;
  line-height: 1;
}
.big-score.green { color: var(--green); }
.big-score.yellow { color: var(--yellow); }
.big-score.red { color: var(--red); }

.score-label { font-size: 13px; color: var(--ink-faint); }

.score-bar-wrap {
  flex: 1;
}
.score-bar-bg {
  height: 8px;
  background: var(--paper);
  border-radius: 100px;
  overflow: hidden;
}
.score-bar-fill {
  height: 100%;
  border-radius: 100px;
  transition: width .6s ease;
}
.score-bar-fill.green { background: var(--green); }
.score-bar-fill.yellow { background: var(--gold); }
.score-bar-fill.red { background: var(--red); }

/* AI section */
.ai-section {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 16px;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin-bottom: 14px;
}

.ai-verdict-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.verdict-badge {
  padding: 4px 12px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 600;
}
.verdict-badge.strong { background: var(--green-bg); color: var(--green); }
.verdict-badge.good { background: #e8f4e8; color: #3a7d44; }
.verdict-badge.viable { background: var(--yellow-bg); color: var(--yellow); }
.verdict-badge.stretch { background: #fef3e2; color: #c67c0e; }
.verdict-badge.weak { background: var(--red-bg); color: var(--red); }

.confidence-chip {
  padding: 4px 10px;
  border-radius: 100px;
  font-size: 11px;
  font-weight: 500;
  background: var(--paper);
  color: var(--ink-soft);
  border: 1px solid var(--border);
}

.model-chip {
  font-size: 11px;
  color: var(--ink-faint);
  display: flex;
  align-items: center;
  gap: 4px;
}

.reasons-block { margin-bottom: 14px; }
.reasons-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--green);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.blockers-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--yellow);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.reason-item {
  display: flex;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--ink-soft);
  line-height: 1.5;
  margin-bottom: 4px;
}
.reason-item.match { background: var(--green-bg); }
.reason-item.gap { background: var(--yellow-bg); }
.reason-dot { flex-shrink: 0; margin-top: 3px; }

/* Skills section */
.skills-section {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 16px;
}

.skills-group { margin-bottom: 14px; }
.skills-group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-faint);
  letter-spacing: .5px;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.skills-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.skill-tag {
  padding: 4px 10px;
  border-radius: 100px;
  font-size: 12px;
  font-weight: 500;
}
.skill-tag.matched { background: var(--green-light); color: var(--green); }
.skill-tag.missing { background: var(--paper); color: var(--ink-soft); border: 1px solid var(--border); }

/* Job description */
.desc-section {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 16px;
}

.desc-content {
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-soft);
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

mark {
  background: #fffacd;
  color: var(--ink);
  border-radius: 2px;
  padding: 0 2px;
}

/* Loading */
.loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--ink-faint);
  font-size: 13px;
  gap: 8px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
.spinner {
  width: 16px; height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--ink-soft);
  border-radius: 50%;
  animation: spin .7s linear infinite;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-dark); border-radius: 3px; }
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
  <div class="logo">Job<span>Pilot</span></div>
  <div class="stats-bar" id="statsBar">
    <div class="stat-pill gray">Loading…</div>
  </div>
  <div class="topbar-right">
    <span class="last-refresh" id="lastRefresh"></span>
    <button class="refresh-btn" onclick="loadAll()">↻ Refresh</button>
  </div>
</div>

<!-- Main -->
<div class="main">

  <!-- Sidebar -->
  <div class="sidebar">
    <div class="sidebar-controls">
      <div class="search-box">
        <span class="search-icon">⌕</span>
        <input type="text" id="searchInput" placeholder="Search company or role…" oninput="filterJobs()">
      </div>
      <div class="filter-tabs">
        <button class="filter-tab active" data-filter="all" onclick="setFilter(this)">All</button>
        <button class="filter-tab" data-filter="apply_now" onclick="setFilter(this)">✅ Apply Now</button>
        <button class="filter-tab" data-filter="review" onclick="setFilter(this)">👀 Review</button>
      </div>
      <div class="score-filter">
        <span>Score ≥</span>
        <input type="range" id="scoreRange" min="0" max="100" value="0" oninput="updateScoreLabel()">
        <span id="scoreLabel" style="min-width:30px">0</span>
      </div>
    </div>
    <div class="job-list" id="jobList">
      <div class="loading"><div class="spinner"></div> Loading jobs…</div>
    </div>
  </div>

  <!-- Detail panel -->
  <div class="detail-panel" id="detailPanel">
    <div class="detail-empty">
      <div class="big-icon">📋</div>
      <p>Select a job to view details</p>
    </div>
  </div>
</div>

<script>
let allJobs = [];
let currentFilter = 'all';
let currentJobId = null;
let statusSaveTimer = null;

// ── Boot ────────────────────────────────────────────────────────────────────

async function loadAll() {
  await Promise.all([loadStats(), loadJobs()]);
  document.getElementById('lastRefresh').textContent =
    'Updated ' + new Date().toLocaleTimeString();
}

// ── Stats ────────────────────────────────────────────────────────────────────

async function loadStats() {
  const s = await fetch('/api/stats').then(r => r.json());
  const bar = document.getElementById('statsBar');
  bar.innerHTML = `
    <div class="stat-pill green">✅ ${s.apply_now} Apply Now</div>
    <div class="stat-pill yellow">👀 ${s.review} Review</div>
    <div class="stat-pill blue">📤 ${s.applied} Applied</div>
    ${s.interview > 0 ? `<div class="stat-pill green">🎯 ${s.interview} Interview</div>` : ''}
    <div class="stat-pill gray">Avg ${s.avg_score}</div>
    ${s.cached > 0 ? `<div class="stat-pill gray">♻ ${s.cached} cached</div>` : ''}
  `;
}

// ── Jobs list ────────────────────────────────────────────────────────────────

async function loadJobs() {
  const params = new URLSearchParams();
  if (currentFilter !== 'all') params.set('decision', currentFilter);
  params.set('min_score', document.getElementById('scoreRange').value);
  const search = document.getElementById('searchInput').value.trim();
  if (search) params.set('search', search);

  allJobs = await fetch('/api/jobs?' + params).then(r => r.json());
  renderJobList(allJobs);
}

function renderJobList(jobs) {
  const list = document.getElementById('jobList');
  if (!jobs.length) {
    list.innerHTML = `<div class="empty-state">
      <div class="icon">🔍</div>
      <div>No jobs found</div>
    </div>`;
    return;
  }
  list.innerHTML = jobs.map(j => {
    const sc = scoreClass(j.score);
    const decLabel = j.decision === 'apply_now' ? 'Apply' : 'Review';
    const decClass = j.decision === 'apply_now' ? 'apply' : 'review';
    const date = j.date_found ? j.date_found.slice(0,10) : '';
    return `<div class="job-card ${currentJobId === j.job_id ? 'active' : ''}"
                 onclick="openJob('${j.job_id}')">
      <div class="job-card-top">
        <div class="score-badge ${sc}">${j.score}</div>
        <div class="job-card-info">
          <div class="job-card-company">${esc(j.company)}</div>
          <div class="job-card-role" title="${esc(j.role)}">${esc(j.role)}</div>
        </div>
        <span class="decision-tag ${decClass}">${decLabel}</span>
      </div>
      <div class="job-card-meta">
        <span>📍 ${esc(j.location || 'Unknown')}</span>
        <span>${date}</span>
        <span>${esc(j.status || 'shortlisted')}</span>
      </div>
    </div>`;
  }).join('');
}

function filterJobs() { loadJobs(); }

function setFilter(btn) {
  document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentFilter = btn.dataset.filter;
  loadJobs();
}

function updateScoreLabel() {
  document.getElementById('scoreLabel').textContent =
    document.getElementById('scoreRange').value;
  loadJobs();
}

// ── Job detail ───────────────────────────────────────────────────────────────

async function openJob(jobId) {
  currentJobId = jobId;
  renderJobList(allJobs); // update active state

  const panel = document.getElementById('detailPanel');
  panel.innerHTML = `<div class="loading"><div class="spinner"></div> Loading…</div>`;

  const job = await fetch(`/api/jobs/${jobId}`).then(r => r.json());
  renderDetail(job);
}

function renderDetail(job) {
  const panel = document.getElementById('detailPanel');
  const sc = scoreClass(job.score);
  const barPct = job.score + '%';

  // Parse AI details from explanation
  const expl = job.explanation || '';
  const isAI = expl.includes('[OPENAI') || expl.includes('[MOCK');
  let provider = '', model = '', verdictStr = '', confidence = '';
  if (isAI) {
    const provMatch = expl.match(/\[(\w+)\s+([\w.-]+)\]/);
    if (provMatch) { provider = provMatch[1]; model = provMatch[2]; }
    const verdMatch = expl.match(/\]\s+(.+?)\s+\|/);
    if (verdMatch) verdictStr = verdMatch[1];
    const confMatch = expl.match(/\|\s+(\w+)\s+confidence/);
    if (confMatch) confidence = confMatch[1];
  }

  const verdictClass = {
    'strong match': 'strong', 'good match': 'good',
    'viable match': 'viable', 'stretch': 'stretch', 'weak match': 'weak'
  }[verdictStr] || 'viable';

  const matched = Array.isArray(job.matched_skills) ? job.matched_skills : [];
  const missing = Array.isArray(job.missing_skills) ? job.missing_skills : [];

  // Clean description
  let desc = (job.description || '') + '\n\n' + (job.requirements || '');
  desc = desc.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

  // Highlight matched skills in description
  matched.forEach(skill => {
    const re = new RegExp('\\b' + escRe(skill) + '\\b', 'gi');
    desc = desc.replace(re, m => `<mark>${m}</mark>`);
  });

  const statusOptions = ['shortlisted','ready_to_apply','applied','interview','rejected','offer'];
  const statusHtml = statusOptions.map(s =>
    `<option value="${s}" ${job.status===s?'selected':''}>${s.replace(/_/g,' ')}</option>`
  ).join('');

  panel.innerHTML = `<div class="detail-content">

    <!-- Header -->
    <div class="detail-header">
      <div class="detail-company">${esc(job.company)} · ${esc(job.source || '')}</div>
      <div class="detail-role">${esc(job.role)}</div>
      <div class="detail-meta-row">
        <span class="meta-chip">📍 ${esc(job.location || 'Unknown')}</span>
        <span class="meta-chip">📅 ${(job.date_found||'').slice(0,10)}</span>
        ${job.remote ? '<span class="meta-chip">🏠 Remote</span>' : ''}
        ${job.salary_range ? `<span class="meta-chip">💰 ${esc(job.salary_range)}</span>` : ''}
      </div>
      <div class="detail-actions">
        <a class="apply-btn" href="${esc(job.apply_url)}" target="_blank" rel="noopener">
          🚀 Apply Now
        </a>
        <select class="status-select" id="statusSelect" onchange="updateStatus('${job.job_id}')">
          ${statusHtml}
        </select>
        <span class="status-saved" id="statusSaved">✓ Saved</span>
      </div>
    </div>

    <!-- Score -->
    <div class="score-section">
      <div class="section-label">📊 Score</div>
      <div class="score-header">
        <div class="big-score ${sc}">${job.score}</div>
        <div style="flex:1">
          <div class="score-label" style="margin-bottom:8px">out of 100 · ${job.decision==='apply_now'?'✅ Apply Now':'👀 Review'}</div>
          <div class="score-bar-wrap">
            <div class="score-bar-bg">
              <div class="score-bar-fill ${sc}" style="width:${barPct}"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- AI Details -->
    ${isAI ? `<div class="ai-section">
      <div class="section-label">🤖 AI Scoring Details</div>
      <div class="ai-verdict-row">
        <span class="verdict-badge ${verdictClass}">${verdictStr}</span>
        <span class="confidence-chip">${confidence} confidence</span>
        <span class="model-chip">⚡ ${provider} ${model}</span>
      </div>
      ${matched.length ? `
        <div class="reasons-block">
          <div class="reasons-title">✅ Why it's a match</div>
          ${matched.map(r => `<div class="reason-item match">
            <span class="reason-dot">•</span>
            <span>${esc(r)}</span>
          </div>`).join('')}
        </div>` : ''}
      ${missing.length ? `
        <div class="reasons-block">
          <div class="blockers-title">⚠ Gaps / Blockers</div>
          ${missing.map(r => `<div class="reason-item gap">
            <span class="reason-dot">•</span>
            <span>${esc(r)}</span>
          </div>`).join('')}
        </div>` : ''}
    </div>` : `<div class="ai-section">
      <div class="section-label">📊 Keyword Scoring</div>
      <div style="font-size:13px;color:var(--ink-soft)">${esc(expl)}</div>
    </div>`}

    <!-- Skills -->
    <div class="skills-section">
      <div class="section-label">🎯 Skills</div>
      ${matched.length ? `<div class="skills-group">
        <div class="skills-group-label">Matched</div>
        <div class="skills-tags">
          ${matched.map(s => `<span class="skill-tag matched">${esc(s)}</span>`).join('')}
        </div>
      </div>` : ''}
      ${missing.length ? `<div class="skills-group">
        <div class="skills-group-label">Missing / Gaps</div>
        <div class="skills-tags">
          ${missing.map(s => `<span class="skill-tag missing">${esc(s)}</span>`).join('')}
        </div>
      </div>` : ''}
    </div>

    <!-- Description -->
    ${desc.trim() ? `<div class="desc-section">
      <div class="section-label">📄 Job Description</div>
      <div class="desc-content">${desc}</div>
    </div>` : ''}

  </div>`;
}

// ── Status update ────────────────────────────────────────────────────────────

async function updateStatus(jobId) {
  const status = document.getElementById('statusSelect').value;
  await fetch(`/api/jobs/${jobId}/status`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status})
  });
  const saved = document.getElementById('statusSaved');
  saved.classList.add('show');
  setTimeout(() => saved.classList.remove('show'), 2000);
  // Update local cache
  const job = allJobs.find(j => j.job_id === jobId);
  if (job) { job.status = status; renderJobList(allJobs); }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function scoreClass(score) {
  return score >= 70 ? 'green' : score >= 50 ? 'yellow' : 'red';
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function escRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ── Auto-refresh every 60s ───────────────────────────────────────────────────

setInterval(() => {
  loadJobs();
  loadStats();
}, 60000);

// ── Init ─────────────────────────────────────────────────────────────────────
loadAll();
</script>
</body>
</html>
"""


def run(port=5000, open_browser=True):
    if open_browser:
        Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    print(f"\n  🤖 JobPilot Dashboard")
    print(f"  ─────────────────────")
    print(f"  URL:  http://localhost:{port}")
    print(f"  DB:   {DB_PATH}")
    print(f"  Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run()
