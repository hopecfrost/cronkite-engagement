#!/usr/bin/env python3
"""
Cronkite News Bureau — Engagement Scoring System
-------------------------------------------------
Scores stories published 7-14 days ago on three pillars:
  Depth (50%)     — avg. engaged minutes vs. section baseline  ← professor priority
  Reach (30%)     — views vs. section baseline
  Discovery (20%) — % traffic from search vs. section baseline

Results are appended to scores.json (cumulative archive).
The dashboard displays ALL historically scored stories.
Section baselines: Dec 2024–Jul 2026, N=9,483 stories.
"""

import os, math, json, datetime, smtplib, requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Credentials ───────────────────────────────────────────────────────────────
PARSELY_KEY    = os.getenv("PARSELY_KEY")    or "cronkitenews.azpbs.org"
PARSELY_SECRET = os.getenv("PARSELY_SECRET") or "tAytVAdJCyLdFHatqOOHLVXTrdHpUm5kQusX8ZWzHoA"
SMTP_EMAIL     = os.getenv("SMTP_EMAIL")     or ""
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD")  or ""

BASE_URL    = "https://api.parsely.com/v2"
SCORES_FILE = "scores.json"

# ── Section name normalization ────────────────────────────────────────────────
SECTION_MAP = {
    "Sport":    "Sports",
    "Politics": "Politics & Policy",
}

# ── Historical baselines (Dec 2024–Jul 2026, N=9,483 stories with ≥5 views) ──
SECTION_BASELINES = {
    "Borderlands": {
        "log_views_mean": 3.671606, "log_views_std": 1.436332,
        "avg_min_mean":   0.697908, "avg_min_std":   0.611949,
        "search_pct_mean":0.460599, "search_pct_std":0.210653,
    },
    "Consumer": {
        "log_views_mean": 3.219035, "log_views_std": 0.991867,
        "avg_min_mean":   0.625226, "avg_min_std":   0.556691,
        "search_pct_mean":0.480429, "search_pct_std":0.217487,
    },
    "Editor's Picks": {
        "log_views_mean": 3.865954, "log_views_std": 1.274660,
        "avg_min_mean":   0.708420, "avg_min_std":   0.706522,
        "search_pct_mean":0.438840, "search_pct_std":0.245947,
    },
    "Education": {
        "log_views_mean": 2.982955, "log_views_std": 0.663295,
        "avg_min_mean":   0.552804, "avg_min_std":   0.500613,
        "search_pct_mean":0.466558, "search_pct_std":0.210623,
    },
    "Future": {
        "log_views_mean": 3.103329, "log_views_std": 0.879452,
        "avg_min_mean":   0.537443, "avg_min_std":   0.427121,
        "search_pct_mean":0.522230, "search_pct_std":0.215371,
    },
    "Government": {
        "log_views_mean": 3.252397, "log_views_std": 1.240195,
        "avg_min_mean":   0.572901, "avg_min_std":   0.657332,
        "search_pct_mean":0.407253, "search_pct_std":0.208569,
    },
    "Health": {
        "log_views_mean": 3.759307, "log_views_std": 1.325098,
        "avg_min_mean":   0.760348, "avg_min_std":   0.622188,
        "search_pct_mean":0.430614, "search_pct_std":0.219331,
    },
    "Indian Country": {
        "log_views_mean": 3.535323, "log_views_std": 1.144236,
        "avg_min_mean":   0.748788, "avg_min_std":   0.629560,
        "search_pct_mean":0.443391, "search_pct_std":0.202855,
    },
    "Legal": {
        "log_views_mean": 3.128222, "log_views_std": 0.946644,
        "avg_min_mean":   0.605515, "avg_min_std":   0.642207,
        "search_pct_mean":0.445525, "search_pct_std":0.206567,
    },
    "Longform hero image slim": {
        "log_views_mean": 3.743740, "log_views_std": 0.945399,
        "avg_min_mean":   0.781611, "avg_min_std":   0.554762,
        "search_pct_mean":0.465867, "search_pct_std":0.202534,
    },
    "Money": {
        "log_views_mean": 3.317479, "log_views_std": 1.150074,
        "avg_min_mean":   0.584026, "avg_min_std":   0.611846,
        "search_pct_mean":0.452737, "search_pct_std":0.215953,
    },
    "New Long Form": {
        "log_views_mean": 4.673951, "log_views_std": 1.420944,
        "avg_min_mean":   1.150780, "avg_min_std":   0.690418,
        "search_pct_mean":0.485400, "search_pct_std":0.190455,
    },
    "Newscast": {
        "log_views_mean": 2.563769, "log_views_std": 0.392002,
        "avg_min_mean":   0.597629, "avg_min_std":   0.804936,
        "search_pct_mean":0.333642, "search_pct_std":0.237354,
    },
    "Next Gen": {
        "log_views_mean": 3.795024, "log_views_std": 1.154852,
        "avg_min_mean":   0.694788, "avg_min_std":   0.628472,
        "search_pct_mean":0.483059, "search_pct_std":0.211593,
    },
    "Noticias": {
        "log_views_mean": 3.691104, "log_views_std": 1.014322,
        "avg_min_mean":   0.711699, "avg_min_std":   0.469350,
        "search_pct_mean":0.512309, "search_pct_std":0.258930,
    },
    "Politics & Policy": {
        "log_views_mean": 4.182386, "log_views_std": 1.683267,
        "avg_min_mean":   0.669487, "avg_min_std":   0.554743,
        "search_pct_mean":0.435819, "search_pct_std":0.209615,
    },
    "Social Justice": {
        "log_views_mean": 3.810295, "log_views_std": 1.244262,
        "avg_min_mean":   0.739607, "avg_min_std":   0.635379,
        "search_pct_mean":0.460744, "search_pct_std":0.209787,
    },
    "Sports": {
        "log_views_mean": 4.229719, "log_views_std": 1.389051,
        "avg_min_mean":   0.729208, "avg_min_std":   0.500631,
        "search_pct_mean":0.490636, "search_pct_std":0.211517,
    },
    "Sustainability": {
        "log_views_mean": 3.611491, "log_views_std": 1.214433,
        "avg_min_mean":   0.696243, "avg_min_std":   0.612033,
        "search_pct_mean":0.438929, "search_pct_std":0.214009,
    },
    "Uncategorized": {
        "log_views_mean": 3.119279, "log_views_std": 0.831170,
        "avg_min_mean":   0.508384, "avg_min_std":   0.600251,
        "search_pct_mean":0.394178, "search_pct_std":0.225519,
    },
}

BUREAU_WIDE = {
    "log_views_mean": 3.868346, "log_views_std": 1.378027,
    "avg_min_mean":   0.697029, "avg_min_std":   0.573032,
    "search_pct_mean":0.462767, "search_pct_std":0.215110,
}

# ── Author email map ──────────────────────────────────────────────────────────
AUTHOR_EMAILS = {
    # "First Last": "email@asu.edu",
}

# ── Math helpers ──────────────────────────────────────────────────────────────
def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def z_to_pct(value, mean, std):
    if std <= 0:
        return 50.0
    z = max(-3.0, min(3.0, (value - mean) / std))
    return round(norm_cdf(z) * 100.0, 1)

def get_baselines(raw_section):
    sec = SECTION_MAP.get(raw_section.strip(), raw_section.strip())
    return SECTION_BASELINES.get(sec, BUREAU_WIDE), sec

# ── Scores archive ────────────────────────────────────────────────────────────
def load_scores():
    """Load cumulative scores from scores.json. Returns dict keyed by URL."""
    if not os.path.exists(SCORES_FILE):
        return {}
    with open(SCORES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {entry["url"]: entry for entry in data}

def save_scores(scores_by_url):
    """Save all scores to scores.json, sorted newest first."""
    entries = sorted(scores_by_url.values(),
                     key=lambda x: x.get("week_scored", ""), reverse=True)
    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    print(f"  Saved {len(entries)} total stories to {SCORES_FILE}")

# ── Parse.ly API ──────────────────────────────────────────────────────────────
def parsely_get(endpoint, extra_params=None):
    params = {"apikey": PARSELY_KEY, "secret": PARSELY_SECRET, "limit": 50}
    if extra_params:
        params.update(extra_params)
    r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def get_posts():
    """Fetch stories published 7–14 days ago (scored after a full week)."""
    now       = datetime.datetime.utcnow()
    week_ago  = now - datetime.timedelta(days=7)
    two_weeks = now - datetime.timedelta(days=14)

    date_params = {
        "pub_date_start": two_weeks.strftime("%Y-%m-%d"),
        "pub_date_end":   week_ago.strftime("%Y-%m-%d"),
        "period_start":   two_weeks.strftime("%Y-%m-%d"),
        "period_end":     now.strftime("%Y-%m-%d"),
    }

    merged = {}
    for sort_key in ["views", "avg_engaged", "search_refs", "mobile_views", "desktop_views"]:
        try:
            data = parsely_get("/analytics/posts", {**date_params, "sort": sort_key})
            print(f"  sort={sort_key}: {len(data)} posts")
        except Exception as e:
            print(f"  Warning: sort={sort_key} failed — {e}")
            continue

        for item in data:
            url = item.get("url", "").strip()
            if not url:
                continue
            m = item.get("metrics", {})

            if url not in merged:
                pub_raw = item.get("pub_date", "")
                merged[url] = {
                    "url":                url,
                    "title":              item.get("title", "Untitled"),
                    "author":             item.get("author", "Unknown"),
                    "section":            item.get("section", ""),
                    "pub_date":           pub_raw,
                    "pub_date_display":   _fmt_date(pub_raw),
                    "views":              0,
                    "avg_engaged":        0.0,
                    "search_refs":        0,
                    "mobile_views":       0,
                    "desktop_views":      0,
                    "recirculation_rate": 0.0,
                }

            if m.get("views", 0) > 0:
                merged[url]["views"] = m["views"]
            if m.get("avg_engaged", 0.0) > 0:
                merged[url]["avg_engaged"] = m["avg_engaged"]
            if m.get("search_refs", 0) > 0:
                merged[url]["search_refs"] = m["search_refs"]
            if m.get("mobile_views", 0) > 0:
                merged[url]["mobile_views"] = m["mobile_views"]
            if m.get("desktop_views", 0) > 0:
                merged[url]["desktop_views"] = m["desktop_views"]
            if m.get("recirculation_rate") is not None:
                merged[url]["recirculation_rate"] = m["recirculation_rate"]

    posts = [p for p in merged.values() if p["views"] > 0]
    print(f"  Total unique posts: {len(posts)}")
    return posts

def _fmt_date(raw):
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", ""))
        return dt.strftime("%b %-d, %Y")
    except Exception:
        return raw[:10] if raw else ""

# ── Scoring ───────────────────────────────────────────────────────────────────
def score_articles(posts):
    has_engaged = sum(1 for p in posts if p["avg_engaged"] > 0)
    use_recirc  = (has_engaged / max(len(posts), 1)) < 0.2
    depth_label = "Recirculation (fallback)" if use_recirc else "Avg. Engaged Minutes"

    if use_recirc:
        print("  Note: avg_engaged unavailable — falling back to recirculation rate")

    week_scored = datetime.date.today().strftime("%Y-%m-%d")
    scored = []

    for post in posts:
        baselines, section_norm = get_baselines(post["section"])
        views = max(post["views"], 1)

        reach = z_to_pct(math.log(views + 1),
                          baselines["log_views_mean"], baselines["log_views_std"])

        if use_recirc or post["avg_engaged"] == 0:
            depth = round(min(post["recirculation_rate"] / 0.10, 1.0) * 100, 1)
        else:
            depth = z_to_pct(post["avg_engaged"],
                              baselines["avg_min_mean"], baselines["avg_min_std"])

        search_pct = post["search_refs"] / views
        discovery  = z_to_pct(search_pct,
                               baselines["search_pct_mean"], baselines["search_pct_std"])

        composite = round(reach * 0.30 + depth * 0.50 + discovery * 0.20, 1)

        mob  = post["mobile_views"]
        desk = post["desktop_views"]
        mob_pct  = round(mob  / views * 100, 1)
        desk_pct = round(desk / views * 100, 1)
        tab_pct  = round(max(0.0, 100 - mob_pct - desk_pct), 1)

        scored.append({
            "url":             post["url"],
            "title":           post["title"],
            "author":          post["author"],
            "section_norm":    section_norm,
            "pub_date":        post["pub_date"],
            "pub_date_display":post["pub_date_display"],
            "week_scored":     week_scored,
            "views":           post["views"],
            "reach":           reach,
            "depth":           depth,
            "discovery":       discovery,
            "composite":       composite,
            "depth_label":     depth_label,
            "mob_pct":         mob_pct,
            "desk_pct":        desk_pct,
            "tab_pct":         tab_pct,
        })

    scored.sort(key=lambda x: x["composite"], reverse=True)
    return scored

# ── Terminal report ───────────────────────────────────────────────────────────
def print_report(scored):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*85}")
    print(f"  CRONKITE ENGAGEMENT REPORT  —  {now}")
    print(f"{'='*85}")
    print(f"  Scoring: Depth 50% | Reach 30% | Discovery 20%")
    print(f"  Section-relative percentiles  |  Stories scored after 7+ days")
    print(f"{'='*85}\n")
    fmt = "{:>3}. {:<40} {:>7} {:>7} {:>7} {:>7} {:>8}  {}"
    print(fmt.format("#", "Title", "Views", "Reach", "Depth", "Discov", "SCORE", "Section"))
    print("-" * 100)
    for i, p in enumerate(scored[:20], 1):
        print(fmt.format(
            i, p["title"][:40], f"{p['views']:,}",
            f"{p['reach']:.0f}", f"{p['depth']:.0f}",
            f"{p['discovery']:.0f}", f"{p['composite']:.1f}",
            p["section_norm"],
        ))
    if scored:
        print(f"\n  Depth metric: {scored[0]['depth_label']}")

# ── HTML Dashboard ────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cronkite Engagement Report — {report_date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --gold: #FFC627; --maroon: #8C1D40;
    --dark: #1a1a2e; --card: #16213e;
    --text: #e0e0e0; --muted: #888; --border: #2a2a4a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--dark); color: var(--text); font-family: 'Segoe UI', sans-serif; }}

  header {{
    background: linear-gradient(135deg, var(--maroon), #5a0e28);
    padding: 18px 28px; display: flex; align-items: center; gap: 16px;
    border-bottom: 3px solid var(--gold);
  }}
  header h1 {{ font-size: 1.35rem; font-weight: 700; color: #fff; }}
  header .meta {{ font-size: 0.78rem; color: rgba(255,255,255,0.6); margin-top: 3px; }}
  .badge {{
    margin-left: auto; background: var(--gold); color: var(--maroon);
    font-size: 0.68rem; font-weight: 700; padding: 3px 8px;
    border-radius: 99px; text-transform: uppercase; letter-spacing: 0.05em;
  }}

  .filter-bar {{
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 12px 16px; background: var(--card);
    border-bottom: 1px solid var(--border);
  }}
  .filter-bar input, .filter-bar select {{
    background: var(--dark); border: 1px solid var(--border);
    color: var(--text); border-radius: 6px; padding: 6px 10px;
    font-size: 0.8rem; outline: none;
  }}
  .filter-bar input {{ width: 220px; }}
  .filter-bar input::placeholder {{ color: var(--muted); }}
  .filter-bar select {{ cursor: pointer; }}
  .filter-bar select:focus, .filter-bar input:focus {{ border-color: var(--gold); }}
  .filter-label {{ font-size: 0.75rem; color: var(--muted); }}
  #result-count {{ font-size: 0.75rem; color: var(--muted); margin-left: auto; }}

  .layout {{ display: grid; grid-template-columns: 1fr 400px; gap: 14px; padding: 14px; }}

  .card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px;
  }}
  .card h2 {{
    font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--gold); margin-bottom: 12px;
  }}

  table {{ width: 100%; border-collapse: collapse; font-size: 0.81rem; }}
  th {{
    text-align: left; padding: 7px 8px; color: var(--muted);
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
    border-bottom: 1px solid var(--border); cursor: pointer; user-select: none;
    white-space: nowrap;
  }}
  th:hover {{ color: var(--gold); }}
  th.sorted {{ color: var(--gold); }}
  td {{ padding: 8px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr {{ cursor: pointer; transition: background 0.12s; }}
  tr:hover td {{ background: rgba(255,198,39,0.05); }}
  tr.active td {{ background: rgba(255,198,39,0.11); }}
  tr.hidden {{ display: none; }}

  .score-pill {{
    display: inline-block; padding: 2px 9px; border-radius: 99px;
    font-weight: 700; font-size: 0.78rem;
  }}
  .score-high {{ background: rgba(39,174,96,0.2);  color: #2ecc71; }}
  .score-mid  {{ background: rgba(255,198,39,0.2); color: var(--gold); }}
  .score-low  {{ background: rgba(231,76,60,0.15); color: #e74c3c; }}

  .bar-wrap {{ display: flex; align-items: center; gap: 5px; }}
  .bar {{ height: 5px; border-radius: 3px; background: var(--border); flex: 1; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 3px; }}
  .bar-reach     {{ background: #3498db; }}
  .bar-depth     {{ background: #9b59b6; }}
  .bar-discovery {{ background: #1abc9c; }}
  .bar-val {{ font-size: 0.72rem; color: var(--muted); width: 24px; text-align: right; }}

  .side-panel {{ display: flex; flex-direction: column; gap: 14px; }}
  .chart-wrap    {{ position: relative; height: 240px; }}
  .chart-wrap-sm {{ position: relative; height: 180px; }}

  .pill-legend {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }}
  .pill-legend span {{
    font-size: 0.7rem; padding: 2px 7px; border-radius: 99px; font-weight: 600;
  }}
  .leg-reach     {{ background: rgba(52,152,219,0.2);  color: #3498db; }}
  .leg-depth     {{ background: rgba(155,89,182,0.2);  color: #9b59b6; }}
  .leg-discovery {{ background: rgba(26,188,156,0.2);  color: #1abc9c; }}

  .selected-title {{
    font-size: 0.92rem; font-weight: 600; color: #fff;
    margin-bottom: 4px; line-height: 1.3;
  }}
  .selected-meta {{ font-size: 0.73rem; color: var(--muted); margin-bottom: 10px; }}

  .device-legend {{
    display: flex; gap: 14px; justify-content: center;
    margin-top: 8px; flex-wrap: wrap;
  }}
  .device-legend span {{ font-size: 0.72rem; display: flex; align-items: center; gap: 5px; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}

  footer {{ text-align: center; padding: 16px; font-size: 0.7rem; color: var(--muted); }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Cronkite News — Engagement Report</h1>
    <div class="meta" id="header-meta">Generated {report_date} &nbsp;|&nbsp; {n_total} stories in archive</div>
  </div>
  <span class="badge">Auto-generated</span>
</header>

<div class="filter-bar">
  <span class="filter-label">Search:</span>
  <input type="text" id="search" placeholder="Title or author…">

  <span class="filter-label">Week:</span>
  <select id="filter-week">
    <option value="all">All time</option>
  </select>

  <span class="filter-label">Section:</span>
  <select id="filter-section">
    <option value="">All sections</option>
  </select>

  <span class="filter-label">Min score:</span>
  <select id="filter-score">
    <option value="0">Any</option>
    <option value="65">65+ (High)</option>
    <option value="40">40+ (Mid)</option>
  </select>

  <span id="result-count"></span>
</div>

<div class="layout">

  <div class="card">
    <h2>Story Rankings</h2>
    <div class="pill-legend">
      <span class="leg-depth">Depth 50%</span>
      <span class="leg-reach">Reach 30%</span>
      <span class="leg-discovery">Discovery 20%</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th data-col="title">Story</th>
          <th data-col="section_norm">Section</th>
          <th data-col="pub_date_display">Published</th>
          <th data-col="week_scored">Week Scored</th>
          <th data-col="views">Views</th>
          <th data-col="reach">Reach</th>
          <th data-col="depth">Depth</th>
          <th data-col="discovery">Discov.</th>
          <th data-col="composite">Score</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>

  <div class="side-panel">

    <div class="card">
      <h2>Pillar Breakdown</h2>
      <div class="selected-title" id="sel-title">Click a story to inspect</div>
      <div class="selected-meta" id="sel-meta"></div>
      <div class="chart-wrap">
        <canvas id="radarChart"></canvas>
      </div>
    </div>

    <div class="card">
      <h2>Device Breakdown</h2>
      <div class="chart-wrap-sm">
        <canvas id="deviceChart"></canvas>
      </div>
      <div class="device-legend">
        <span><span class="dot" style="background:#3498db"></span>Desktop</span>
        <span><span class="dot" style="background:#FFC627"></span>Mobile</span>
        <span><span class="dot" style="background:#9b59b6"></span>Tablet</span>
      </div>
    </div>

    <div class="card">
      <h2>Score Distribution (Reach vs. Depth)</h2>
      <div class="chart-wrap-sm">
        <canvas id="scatterChart"></canvas>
      </div>
    </div>

    <div class="card" style="font-size:0.73rem;color:var(--muted);line-height:1.65;">
      <h2>Methodology</h2>
      Each score is a <strong style="color:var(--text)">section-relative percentile</strong> (0–100)
      vs. the section's Dec 2024–Jul 2026 baseline (N=9,483).<br><br>
      <strong style="color:#9b59b6">Depth 50%</strong> — avg. engaged minutes<br>
      <strong style="color:#3498db">Reach 30%</strong> — log(views)<br>
      <strong style="color:#1abc9c">Discovery 20%</strong> — % traffic from search<br><br>
      Stories are scored after 7+ days so every article has had a full week to accumulate traffic.
      Depth metric: {depth_label}.
    </div>
  </div>
</div>

<footer>Cronkite Sports Bureau &nbsp;|&nbsp; Audience Engagement Team &nbsp;|&nbsp; Generated {report_date}</footer>

<script>
const posts = {posts_json};

function scoreClass(s) {{
  return s >= 65 ? 'score-high' : s >= 40 ? 'score-mid' : 'score-low';
}}
function bar(val, cls) {{
  return `<div class="bar-wrap"><div class="bar"><div class="bar-fill ${{cls}}" style="width:${{val}}%"></div></div><span class="bar-val">${{Math.round(val)}}</span></div>`;
}}

// ── Build table ──
const tbody = document.getElementById('tbody');
posts.forEach((p, i) => {{
  const tr = document.createElement('tr');
  tr.dataset.idx = i;
  tr.innerHTML = `
    <td style="color:var(--muted);font-size:0.72rem">${{i+1}}</td>
    <td>
      <a href="${{p.url}}" target="_blank"
         style="color:#fff;text-decoration:none;font-size:0.81rem;display:block"
         onclick="event.stopPropagation()"
      >${{p.title.length>52?p.title.slice(0,52)+'…':p.title}}</a>
      <span style="font-size:0.7rem;color:var(--muted)">${{p.author}}</span>
    </td>
    <td style="color:var(--muted);font-size:0.72rem;white-space:nowrap">${{p.section_norm}}</td>
    <td style="color:var(--muted);font-size:0.72rem;white-space:nowrap">${{p.pub_date_display}}</td>
    <td style="color:var(--muted);font-size:0.72rem;white-space:nowrap">${{p.week_scored}}</td>
    <td style="color:var(--muted);font-size:0.76rem">${{p.views.toLocaleString()}}</td>
    <td>${{bar(p.reach,'bar-reach')}}</td>
    <td>${{bar(p.depth,'bar-depth')}}</td>
    <td>${{bar(p.discovery,'bar-discovery')}}</td>
    <td><span class="score-pill ${{scoreClass(p.composite)}}">${{p.composite.toFixed(1)}}</span></td>
  `;
  tr.addEventListener('click', () => selectPost(i));
  tbody.appendChild(tr);
}});

// ── Populate dropdowns from data ──
const weeks    = [...new Set(posts.map(p => p.week_scored))].sort().reverse();
const sections = [...new Set(posts.map(p => p.section_norm))].sort();

const weekSel = document.getElementById('filter-week');
weeks.forEach(w => {{
  const o = document.createElement('option');
  o.value = w;
  o.textContent = `Week of ${{w}}`;
  weekSel.appendChild(o);
}});

const secSel = document.getElementById('filter-section');
sections.forEach(s => {{
  const o = document.createElement('option');
  o.value = s; o.textContent = s;
  secSel.appendChild(o);
}});

// ── Filters ──
function applyFilters() {{
  const q     = document.getElementById('search').value.toLowerCase();
  const week  = document.getElementById('filter-week').value;
  const sec   = document.getElementById('filter-section').value;
  const minS  = parseFloat(document.getElementById('filter-score').value) || 0;

  let visible = 0, rank = 0;
  document.querySelectorAll('#tbody tr').forEach(tr => {{
    const p = posts[parseInt(tr.dataset.idx)];
    const show =
      (!q    || p.title.toLowerCase().includes(q) || p.author.toLowerCase().includes(q)) &&
      (!week || week === 'all' || p.week_scored === week) &&
      (!sec  || p.section_norm === sec) &&
      (p.composite >= minS);
    tr.classList.toggle('hidden', !show);
    if (show) {{
      visible++;
      tr.querySelector('td:first-child').textContent = ++rank;
    }}
  }});
  document.getElementById('result-count').textContent =
    `${{visible}} of ${{posts.length}} stories`;
}}

['search','filter-week','filter-section','filter-score'].forEach(id =>
  document.getElementById(id).addEventListener(id === 'search' ? 'input' : 'change', applyFilters)
);
applyFilters();

// ── Charts ──
const radarCtx = document.getElementById('radarChart').getContext('2d');
const radarChart = new Chart(radarCtx, {{
  type: 'radar',
  data: {{
    labels: ['Reach (30%)','Depth (50%)','Discovery (20%)'],
    datasets: [{{ label:'Score', data:[0,0,0],
      backgroundColor:'rgba(255,198,39,0.15)',
      borderColor:'#FFC627', pointBackgroundColor:'#FFC627', borderWidth:2
    }}]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    scales:{{ r:{{ min:0, max:100,
      ticks:{{stepSize:25,color:'#888',font:{{size:9}}}},
      grid:{{color:'rgba(255,255,255,0.07)'}},
      pointLabels:{{color:'#ccc',font:{{size:11}}}},
      angleLines:{{color:'rgba(255,255,255,0.07)'}},
    }} }},
    plugins:{{legend:{{display:false}}}},
  }}
}});

const deviceCtx = document.getElementById('deviceChart').getContext('2d');
const deviceChart = new Chart(deviceCtx, {{
  type: 'doughnut',
  data: {{
    labels: ['Desktop','Mobile','Tablet'],
    datasets: [{{ data:[0,0,0],
      backgroundColor:['#3498db','#FFC627','#9b59b6'],
      borderColor:'var(--card)', borderWidth:2,
    }}]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false, cutout:'65%',
    plugins:{{
      legend:{{display:false}},
      tooltip:{{callbacks:{{label: ctx => ` ${{ctx.label}}: ${{ctx.parsed.toFixed(1)}}%`}}}},
    }},
  }}
}});

const scatterCtx = document.getElementById('scatterChart').getContext('2d');
new Chart(scatterCtx, {{
  type:'scatter',
  data:{{ datasets:[{{ label:'Stories',
    data: posts.map(p => ({{x:p.reach, y:p.depth, post:p}})),
    backgroundColor: posts.map(p =>
      p.composite>=65?'rgba(46,204,113,0.75)':
      p.composite>=40?'rgba(255,198,39,0.75)':'rgba(231,76,60,0.75)'),
    pointRadius:4,
  }}] }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    scales:{{
      x:{{min:0,max:100,title:{{display:true,text:'Reach',color:'#3498db',font:{{size:10}}}},
           grid:{{color:'rgba(255,255,255,0.04)'}},ticks:{{color:'#888',font:{{size:9}}}}}},
      y:{{min:0,max:100,title:{{display:true,text:'Depth',color:'#9b59b6',font:{{size:10}}}},
           grid:{{color:'rgba(255,255,255,0.04)'}},ticks:{{color:'#888',font:{{size:9}}}}}},
    }},
    plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>ctx.raw.post.title.slice(0,38)}}}}}},
  }}
}});

// ── Selection ──
let activeRow = null;
function selectPost(idx) {{
  if (activeRow !== null) {{
    const prev = document.querySelector(`tr[data-idx="${{activeRow}}"]`);
    if (prev) prev.classList.remove('active');
  }}
  activeRow = idx;
  const tr = document.querySelector(`tr[data-idx="${{idx}}"]`);
  if (tr) tr.classList.add('active');
  const p = posts[idx];
  document.getElementById('sel-title').textContent = p.title;
  document.getElementById('sel-meta').textContent =
    `${{p.section_norm}} · ${{p.pub_date_display}} · ${{p.views.toLocaleString()}} views · ${{p.author}}`;
  radarChart.data.datasets[0].data = [p.reach, p.depth, p.discovery];
  radarChart.update();
  deviceChart.data.datasets[0].data = [p.desk_pct, p.mob_pct, p.tab_pct];
  deviceChart.update();
}}
if (posts.length > 0) selectPost(0);

// ── Column sort ──
let sortCol = 'composite', sortDir = -1;
document.querySelectorAll('th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    document.querySelectorAll('th').forEach(t => t.classList.remove('sorted'));
    th.classList.add('sorted');
    sortDir = sortCol === col ? -sortDir : -1;
    sortCol = col;
    const rows = [...document.querySelectorAll('#tbody tr')];
    rows.sort((a,b) => {{
      const av = posts[parseInt(a.dataset.idx)][col] ?? '';
      const bv = posts[parseInt(b.dataset.idx)][col] ?? '';
      return sortDir * (av < bv ? -1 : av > bv ? 1 : 0);
    }});
    rows.forEach(r => tbody.appendChild(r));
    applyFilters();
  }});
}});
</script>
</body>
</html>"""

def generate_dashboard(all_scores):
    import json as _json
    today     = datetime.date.today().strftime("%Y-%m-%d")
    fname     = f"cronkite_report_{today}.html"
    n_total   = len(all_scores)

    # Sort by composite descending for the initial table view
    display   = sorted(all_scores, key=lambda x: x["composite"], reverse=True)
    posts_json = _json.dumps(display, indent=2)

    depth_label = display[0]["depth_label"] if display else "Avg. Engaged Minutes"
    html = HTML_TEMPLATE.format(
        report_date=today, n_total=n_total,
        posts_json=posts_json, depth_label=depth_label,
    )

    for name in (fname, "index.html"):
        with open(name, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Saved: {name}")

    return fname

# ── Author emails ─────────────────────────────────────────────────────────────
EMAIL_TEMPLATE = """Hi {first_name},

Your story published this week has been scored by the Cronkite engagement system:

  "{title}"
  {url}

ENGAGEMENT SCORE: {composite}/100  (vs. {section_norm} section historical average)

  Depth      {depth}/100  (50%) — avg. time readers spent on your story
  Reach      {reach}/100  (30%) — how many readers found it
  Discovery  {discovery}/100  (20%) — % of traffic from search

A score of 50 means exactly average for {section_norm}.
A 70 means you outperformed 70% of {section_norm} stories (Dec 2024–Jul 2026 baseline).

Keep up the great work,
Cronkite Audience Engagement Team
"""

def send_author_email(post, smtp_email, smtp_password):
    author    = post["author"]
    recipient = AUTHOR_EMAILS.get(author)
    if not recipient:
        return
    pub = post.get("pub_date", "")
    try:
        pub_dt = datetime.datetime.fromisoformat(pub.replace("Z", ""))
        age_h  = (datetime.datetime.utcnow() - pub_dt).total_seconds() / 3600
        if not (24 <= age_h <= 72):
            return
    except Exception:
        pass
    first = author.split()[0] if author else "there"
    body  = EMAIL_TEMPLATE.format(
        first_name=first, title=post["title"], url=post["url"],
        composite=post["composite"], section_norm=post["section_norm"],
        reach=post["reach"], depth=post["depth"], discovery=post["discovery"],
    )
    msg = MIMEMultipart()
    msg["From"]    = smtp_email
    msg["To"]      = recipient
    msg["Subject"] = f"Your story engagement score: {post['composite']}/100"
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(smtp_email, smtp_password)
        s.sendmail(smtp_email, recipient, msg.as_string())
    print(f"  Email sent to {recipient} ({author})")

def send_all_author_emails(scored):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print("  Skipping emails — SMTP credentials not set")
        return
    for post in scored:
        try:
            send_author_email(post, SMTP_EMAIL, SMTP_PASSWORD)
        except Exception as e:
            print(f"  Email error for {post['author']}: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("\nFetching posts from Parse.ly (stories published 7–14 days ago)...")
    posts = get_posts()
    if not posts:
        print("No posts found for this window.")
        return

    print(f"\nScoring {len(posts)} articles...")
    new_scored = score_articles(posts)

    print("\nUpdating scores archive...")
    archive = load_scores()
    new_count = 0
    for story in new_scored:
        if story["url"] not in archive:
            archive[story["url"]] = story
            new_count += 1
        else:
            print(f"  Skipping (already scored): {story['title'][:50]}")
    print(f"  {new_count} new stories added to archive")
    save_scores(archive)

    all_scores = list(archive.values())
    print_report(sorted(new_scored, key=lambda x: x["composite"], reverse=True))

    print("\nGenerating dashboard...")
    generate_dashboard(all_scores)

    print("\nSending author emails...")
    send_all_author_emails(new_scored)

    print("\nDone.")

if __name__ == "__main__":
    main()
