#!/usr/bin/env python3
"""
Cronkite News Bureau — Engagement Scoring System
-------------------------------------------------
Scores recently published articles on three pillars (equal thirds):
  Reach      — views, vs. section historical baseline
  Depth      — avg. engaged minutes (or recirculation fallback), vs. baseline
  Discovery  — % traffic from search, vs. section baseline

Section baselines are pre-computed from a Jan–Jun 2026 Parse.ly CSV export
(10,000 stories). Each story is z-scored against its own section's history
and converted to a 0–100 percentile, so Sports vs. Sports, Politics vs. Politics.
"""

import os, math, datetime, smtplib, requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Credentials ───────────────────────────────────────────────────────────────
PARSELY_KEY    = os.getenv("PARSELY_KEY")    or "cronkitenews.azpbs.org"
PARSELY_SECRET = os.getenv("PARSELY_SECRET") or "tAytVAdJCyLdFHatqOOHLVXTrdHpUm5kQusX8ZWzHoA"
SMTP_EMAIL     = os.getenv("SMTP_EMAIL")     or ""
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD")  or ""

BASE_URL      = "https://api.parsely.com/v2"
LOOKBACK_DAYS = 7

# ── Section name normalization ────────────────────────────────────────────────
SECTION_MAP = {
    "Sport":    "Sports",
    "Politics": "Politics & Policy",
}

# ── Historical baselines (Jan–Jun 2026, N=5,727 stories with ≥5 views) ───────
# Metrics: log(views+1), avg engaged minutes, search_refs/views
SECTION_BASELINES = {
    "Borderlands": {
        "log_views_mean": 3.392171, "log_views_std": 1.673097,
        "avg_min_mean":   0.784076, "avg_min_std":   0.584826,
        "search_pct_mean":0.387499, "search_pct_std":0.200671,
    },
    "Consumer": {
        "log_views_mean": 2.699786, "log_views_std": 1.056338,
        "avg_min_mean":   0.675313, "avg_min_std":   0.624236,
        "search_pct_mean":0.394898, "search_pct_std":0.194016,
    },
    "Editor's Picks": {
        "log_views_mean": 3.012368, "log_views_std": 1.116498,
        "avg_min_mean":   0.849015, "avg_min_std":   1.216072,
        "search_pct_mean":0.419033, "search_pct_std":0.191819,
    },
    "Education": {
        "log_views_mean": 2.300706, "log_views_std": 0.613824,
        "avg_min_mean":   0.617887, "avg_min_std":   0.559177,
        "search_pct_mean":0.374727, "search_pct_std":0.215951,
    },
    "Future": {
        "log_views_mean": 2.506078, "log_views_std": 0.873671,
        "avg_min_mean":   0.572636, "avg_min_std":   0.669512,
        "search_pct_mean":0.464016, "search_pct_std":0.219670,
    },
    "Government": {
        "log_views_mean": 3.076055, "log_views_std": 1.544022,
        "avg_min_mean":   0.835559, "avg_min_std":   1.386113,
        "search_pct_mean":0.376059, "search_pct_std":0.192622,
    },
    "Health": {
        "log_views_mean": 3.173419, "log_views_std": 1.217133,
        "avg_min_mean":   0.910601, "avg_min_std":   1.136368,
        "search_pct_mean":0.381702, "search_pct_std":0.203987,
    },
    "Indian Country": {
        "log_views_mean": 2.831174, "log_views_std": 1.100916,
        "avg_min_mean":   0.818061, "avg_min_std":   0.772331,
        "search_pct_mean":0.419051, "search_pct_std":0.219897,
    },
    "Legal": {
        "log_views_mean": 2.678030, "log_views_std": 0.932649,
        "avg_min_mean":   0.723993, "avg_min_std":   0.773026,
        "search_pct_mean":0.398760, "search_pct_std":0.182248,
    },
    "Money": {
        "log_views_mean": 2.795731, "log_views_std": 0.977346,
        "avg_min_mean":   0.634683, "avg_min_std":   0.677319,
        "search_pct_mean":0.397906, "search_pct_std":0.183955,
    },
    "New Long Form": {
        "log_views_mean": 3.364925, "log_views_std": 1.057386,
        "avg_min_mean":   1.134732, "avg_min_std":   0.948600,
        "search_pct_mean":0.372067, "search_pct_std":0.178678,
    },
    "Next Gen": {
        "log_views_mean": 2.944713, "log_views_std": 0.931226,
        "avg_min_mean":   0.707842, "avg_min_std":   0.718319,
        "search_pct_mean":0.426652, "search_pct_std":0.183315,
    },
    "Noticias": {
        "log_views_mean": 2.892463, "log_views_std": 0.845092,
        "avg_min_mean":   0.745000, "avg_min_std":   0.834512,
        "search_pct_mean":0.384748, "search_pct_std":0.205182,
    },
    "Politics & Policy": {
        "log_views_mean": 3.331664, "log_views_std": 1.409402,
        "avg_min_mean":   0.705708, "avg_min_std":   0.675630,
        "search_pct_mean":0.384509, "search_pct_std":0.180810,
    },
    "Social Justice": {
        "log_views_mean": 2.970686, "log_views_std": 1.033295,
        "avg_min_mean":   0.868691, "avg_min_std":   1.025006,
        "search_pct_mean":0.411789, "search_pct_std":0.207443,
    },
    "Sports": {
        "log_views_mean": 3.309887, "log_views_std": 1.261144,
        "avg_min_mean":   0.737760, "avg_min_std":   0.617084,
        "search_pct_mean":0.377031, "search_pct_std":0.174784,
    },
    "Sustainability": {
        "log_views_mean": 2.860009, "log_views_std": 0.963413,
        "avg_min_mean":   0.865624, "avg_min_std":   1.078021,
        "search_pct_mean":0.402875, "search_pct_std":0.196399,
    },
    "Uncategorized": {
        "log_views_mean": 2.526087, "log_views_std": 0.703459,
        "avg_min_mean":   0.539763, "avg_min_std":   0.554189,
        "search_pct_mean":0.360636, "search_pct_std":0.206526,
    },
}

BUREAU_WIDE = {
    "log_views_mean": 3.125668, "log_views_std": 1.228543,
    "avg_min_mean":   0.764152, "avg_min_std":   0.803275,
    "search_pct_mean":0.389818, "search_pct_std":0.188207,
}

# ── Author email map (fill in before sending emails) ─────────────────────────
AUTHOR_EMAILS = {
    # "First Last": "email@asu.edu",
}

# ── Math helpers ──────────────────────────────────────────────────────────────
def norm_cdf(z):
    """Standard normal CDF — uses math.erf, no scipy needed."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def z_to_pct(value, mean, std):
    """Convert a raw value to a 0–100 percentile vs. the given baseline."""
    if std <= 0:
        return 50.0
    z = max(-3.0, min(3.0, (value - mean) / std))
    return round(norm_cdf(z) * 100.0, 1)

def get_baselines(raw_section):
    sec = SECTION_MAP.get(raw_section.strip(), raw_section.strip())
    return SECTION_BASELINES.get(sec, BUREAU_WIDE), sec

# ── Parse.ly API ──────────────────────────────────────────────────────────────
def parsely_get(endpoint, extra_params=None):
    params = {
        "apikey": PARSELY_KEY,
        "secret": PARSELY_SECRET,
        "limit":  50,
    }
    if extra_params:
        params.update(extra_params)
    r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def get_posts():
    """
    Pull last 7 days of posts via 3 API calls (sorted by views / avg_engaged /
    search_refs) and join results by URL so each article gets all metrics.
    """
    now      = datetime.datetime.utcnow()
    week_ago = now - datetime.timedelta(days=LOOKBACK_DAYS)
    date_params = {
        "pub_date_start": week_ago.strftime("%Y-%m-%d"),
        "pub_date_end":   now.strftime("%Y-%m-%d"),
        "period_start":   week_ago.strftime("%Y-%m-%d"),
        "period_end":     now.strftime("%Y-%m-%d"),
    }

    merged = {}

    for sort_key in ["views", "avg_engaged", "search_refs"]:
        try:
            data = parsely_get("/analytics/posts", {**date_params, "sort": sort_key})
            print(f"  sort={sort_key}: {len(data)} posts returned")
        except Exception as e:
            print(f"  Warning: sort={sort_key} call failed — {e}")
            continue

        for item in data:
            url = item.get("url", "").strip()
            if not url:
                continue
            m = item.get("metrics", {})

            if url not in merged:
                merged[url] = {
                    "url":               url,
                    "title":             item.get("title", "Untitled"),
                    "author":            item.get("author", "Unknown"),
                    "section":           item.get("section", ""),
                    "pub_date":          item.get("pub_date", ""),
                    "views":             0,
                    "avg_engaged":       0.0,
                    "search_refs":       0,
                    "recirculation_rate":0.0,
                }

            if m.get("views", 0) > 0:
                merged[url]["views"] = m["views"]
            if m.get("avg_engaged", 0.0) > 0:
                merged[url]["avg_engaged"] = m["avg_engaged"]
            if m.get("search_refs", 0) > 0:
                merged[url]["search_refs"] = m["search_refs"]
            if m.get("recirculation_rate") is not None:
                merged[url]["recirculation_rate"] = m["recirculation_rate"]

    posts = [p for p in merged.values() if p["views"] > 0]
    print(f"  Total unique posts with views: {len(posts)}")
    return posts

# ── Scoring ───────────────────────────────────────────────────────────────────
def score_articles(posts):
    """
    Score each post on Reach / Depth / Discovery (equal thirds).
    If avg_engaged is unavailable for ≥80% of posts, fall back to recirculation.
    """
    has_engaged = sum(1 for p in posts if p["avg_engaged"] > 0)
    use_recirc  = (has_engaged / max(len(posts), 1)) < 0.2
    depth_label = "Recirculation (fallback)" if use_recirc else "Avg. Engaged Minutes"

    if use_recirc:
        print(f"  Note: avg_engaged unavailable for most posts — using recirculation rate for Depth")

    scored = []
    for post in posts:
        baselines, section_norm = get_baselines(post["section"])
        views = max(post["views"], 1)

        # Reach
        reach = z_to_pct(math.log(views + 1),
                          baselines["log_views_mean"],
                          baselines["log_views_std"])

        # Depth
        if use_recirc or post["avg_engaged"] == 0:
            depth = round(min(post["recirculation_rate"] / 0.10, 1.0) * 100, 1)
        else:
            depth = z_to_pct(post["avg_engaged"],
                              baselines["avg_min_mean"],
                              baselines["avg_min_std"])

        # Discovery
        search_pct = post["search_refs"] / views
        discovery  = z_to_pct(search_pct,
                               baselines["search_pct_mean"],
                               baselines["search_pct_std"])

        composite = round((reach + depth + discovery) / 3.0, 1)

        scored.append({
            **post,
            "section_norm":  section_norm,
            "reach":         reach,
            "depth":         depth,
            "discovery":     discovery,
            "composite":     composite,
            "depth_label":   depth_label,
        })

    scored.sort(key=lambda x: x["composite"], reverse=True)
    return scored

# ── Terminal report ───────────────────────────────────────────────────────────
def print_report(scored):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*80}")
    print(f"  CRONKITE ENGAGEMENT REPORT  —  {now}")
    print(f"{'='*80}")
    print(f"  Scoring: Reach 33% | Depth 33% | Discovery 33%")
    print(f"  All scores are section-relative percentiles (0–100)")
    print(f"{'='*80}\n")

    fmt = "{:>3}. {:<42} {:>6} {:>7} {:>7} {:>7} {:>8}  {}"
    print(fmt.format("#", "Title", "Views", "Reach", "Depth", "Discov", "SCORE", "Section"))
    print("-" * 100)

    for i, p in enumerate(scored[:20], 1):
        title = p["title"][:42]
        print(fmt.format(
            i, title,
            f"{p['views']:,}",
            f"{p['reach']:.0f}",
            f"{p['depth']:.0f}",
            f"{p['discovery']:.0f}",
            f"{p['composite']:.1f}",
            p["section_norm"],
        ))

    print(f"\n  Depth metric: {scored[0]['depth_label'] if scored else 'N/A'}")

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
    --gold: #FFC627;
    --maroon: #8C1D40;
    --dark: #1a1a2e;
    --card: #16213e;
    --text: #e0e0e0;
    --muted: #888;
    --border: #2a2a4a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--dark); color: var(--text); font-family: 'Segoe UI', sans-serif; }}

  header {{
    background: linear-gradient(135deg, var(--maroon), #5a0e28);
    padding: 20px 32px;
    display: flex;
    align-items: center;
    gap: 16px;
    border-bottom: 3px solid var(--gold);
  }}
  header h1 {{ font-size: 1.4rem; font-weight: 700; color: #fff; }}
  header .meta {{ font-size: 0.8rem; color: rgba(255,255,255,0.65); margin-top: 4px; }}
  .badge {{
    background: var(--gold); color: var(--maroon);
    font-size: 0.7rem; font-weight: 700;
    padding: 3px 8px; border-radius: 99px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }}

  .layout {{ display: grid; grid-template-columns: 1fr 420px; gap: 16px; padding: 16px; }}

  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
  }}
  .card h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em;
               color: var(--gold); margin-bottom: 14px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th {{ text-align: left; padding: 8px 10px; color: var(--muted);
        font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
        border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; }}
  th:hover {{ color: var(--gold); }}
  td {{ padding: 9px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr {{ cursor: pointer; transition: background 0.15s; }}
  tr:hover td {{ background: rgba(255,198,39,0.06); }}
  tr.active td {{ background: rgba(255,198,39,0.12); }}

  .score-pill {{
    display: inline-block;
    padding: 3px 10px; border-radius: 99px;
    font-weight: 700; font-size: 0.8rem;
  }}
  .score-high   {{ background: rgba(39,174,96,0.2);  color: #2ecc71; }}
  .score-mid    {{ background: rgba(255,198,39,0.2); color: var(--gold); }}
  .score-low    {{ background: rgba(231,76,60,0.15); color: #e74c3c; }}

  .bar-wrap {{ display: flex; align-items: center; gap: 6px; }}
  .bar {{ height: 6px; border-radius: 3px; background: var(--border); flex: 1; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 3px; }}
  .bar-reach     {{ background: #3498db; }}
  .bar-depth     {{ background: #9b59b6; }}
  .bar-discovery {{ background: #1abc9c; }}
  .bar-val {{ font-size: 0.75rem; color: var(--muted); width: 26px; text-align: right; }}

  .side-panel {{ display: flex; flex-direction: column; gap: 16px; }}
  .chart-wrap {{ position: relative; height: 280px; }}

  .pill-legend {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }}
  .pill-legend span {{
    font-size: 0.72rem; padding: 2px 8px; border-radius: 99px; font-weight: 600;
  }}
  .leg-reach     {{ background: rgba(52,152,219,0.2);  color: #3498db; }}
  .leg-depth     {{ background: rgba(155,89,182,0.2);  color: #9b59b6; }}
  .leg-discovery {{ background: rgba(26,188,156,0.2);  color: #1abc9c; }}

  .selected-title {{
    font-size: 0.95rem; font-weight: 600; color: #fff;
    margin-bottom: 6px; line-height: 1.3;
  }}
  .selected-meta {{ font-size: 0.75rem; color: var(--muted); margin-bottom: 12px; }}

  footer {{ text-align: center; padding: 20px; font-size: 0.72rem; color: var(--muted); }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Cronkite News — Engagement Report</h1>
    <div class="meta">Week of {report_date} &nbsp;|&nbsp; {n_posts} stories &nbsp;|&nbsp; Section-relative scoring</div>
  </div>
  <span class="badge">Auto-generated</span>
</header>

<div class="layout">

  <!-- Left: ranked table -->
  <div class="card">
    <h2>Story Rankings</h2>
    <div class="pill-legend">
      <span class="leg-reach">Reach</span>
      <span class="leg-depth">Depth</span>
      <span class="leg-discovery">Discovery</span>
    </div>
    <table id="rankings">
      <thead>
        <tr>
          <th data-col="rank">#</th>
          <th data-col="title">Story</th>
          <th data-col="section">Section</th>
          <th data-col="views">Views</th>
          <th data-col="reach">Reach</th>
          <th data-col="depth">Depth</th>
          <th data-col="discovery">Discovery</th>
          <th data-col="composite">Score</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>

  <!-- Right: charts -->
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
      <h2>Score Distribution</h2>
      <div class="chart-wrap">
        <canvas id="scatterChart"></canvas>
      </div>
    </div>
    <div class="card" style="font-size:0.75rem; color:var(--muted); line-height:1.6;">
      <h2>Methodology</h2>
      Each score is a <strong style="color:var(--text)">section-relative percentile</strong> (0–100)
      comparing this story against its section's Jan–Jun 2026 historical baseline.<br><br>
      <strong style="color:#3498db">Reach</strong> — log(views), vs. section avg<br>
      <strong style="color:#9b59b6">Depth</strong> — {depth_label}, vs. section avg<br>
      <strong style="color:#1abc9c">Discovery</strong> — % traffic from search, vs. section avg<br><br>
      Composite = equal thirds (33 / 33 / 33).
    </div>
  </div>
</div>

<footer>Cronkite Sports Bureau &nbsp;|&nbsp; Audience Engagement Team &nbsp;|&nbsp; Generated {report_date}</footer>

<script>
const posts = {posts_json};

function scoreClass(s) {{
  if (s >= 65) return 'score-high';
  if (s >= 40) return 'score-mid';
  return 'score-low';
}}

function bar(val, cls) {{
  return `<div class="bar-wrap">
    <div class="bar"><div class="bar-fill ${{cls}}" style="width:${{val}}%"></div></div>
    <span class="bar-val">${{Math.round(val)}}</span>
  </div>`;
}}

// Build table
const tbody = document.getElementById('tbody');
posts.forEach((p, i) => {{
  const tr = document.createElement('tr');
  tr.dataset.idx = i;
  tr.innerHTML = `
    <td style="color:var(--muted);font-size:0.75rem">${{i+1}}</td>
    <td><a href="${{p.url}}" target="_blank" style="color:#fff;text-decoration:none;font-size:0.83rem"
          onclick="event.stopPropagation()">${{p.title.length>55 ? p.title.slice(0,55)+'…' : p.title}}</a></td>
    <td style="color:var(--muted);font-size:0.75rem;white-space:nowrap">${{p.section_norm}}</td>
    <td style="color:var(--muted);font-size:0.78rem">${{p.views.toLocaleString()}}</td>
    <td>${{bar(p.reach,'bar-reach')}}</td>
    <td>${{bar(p.depth,'bar-depth')}}</td>
    <td>${{bar(p.discovery,'bar-discovery')}}</td>
    <td><span class="score-pill ${{scoreClass(p.composite)}}">${{p.composite.toFixed(1)}}</span></td>
  `;
  tr.addEventListener('click', () => selectPost(i));
  tbody.appendChild(tr);
}});

// Radar chart
const radarCtx = document.getElementById('radarChart').getContext('2d');
const radarChart = new Chart(radarCtx, {{
  type: 'radar',
  data: {{
    labels: ['Reach','Depth','Discovery'],
    datasets: [{{
      label: 'Score',
      data: [0,0,0],
      backgroundColor: 'rgba(255,198,39,0.15)',
      borderColor: '#FFC627',
      pointBackgroundColor: '#FFC627',
      borderWidth: 2,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{ r: {{
      min: 0, max: 100,
      ticks: {{ stepSize: 25, color: '#888', font: {{size:10}} }},
      grid: {{ color: 'rgba(255,255,255,0.08)' }},
      pointLabels: {{ color: '#e0e0e0', font: {{size:12}} }},
      angleLines: {{ color: 'rgba(255,255,255,0.08)' }},
    }} }},
    plugins: {{ legend: {{ display: false }} }},
  }}
}});

// Scatter chart
const scatterCtx = document.getElementById('scatterChart').getContext('2d');
const scatterChart = new Chart(scatterCtx, {{
  type: 'scatter',
  data: {{
    datasets: [{{
      label: 'Stories',
      data: posts.map(p => ({{ x: p.reach, y: p.depth, post: p }})),
      backgroundColor: posts.map(p =>
        p.composite >= 65 ? 'rgba(46,204,113,0.7)' :
        p.composite >= 40 ? 'rgba(255,198,39,0.7)' :
                            'rgba(231,76,60,0.7)'),
      pointRadius: 5,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      x: {{ min:0, max:100, title:{{display:true,text:'Reach',color:'#3498db',font:{{size:11}}}},
             grid:{{color:'rgba(255,255,255,0.05)'}}, ticks:{{color:'#888'}} }},
      y: {{ min:0, max:100, title:{{display:true,text:'Depth',color:'#9b59b6',font:{{size:11}}}},
             grid:{{color:'rgba(255,255,255,0.05)'}}, ticks:{{color:'#888'}} }},
    }},
    plugins: {{
      legend: {{ display:false }},
      tooltip: {{ callbacks: {{ label: ctx => ctx.raw.post.title.slice(0,40) }} }},
    }},
  }}
}});

// Selection
let activeRow = null;
function selectPost(idx) {{
  if (activeRow !== null) document.querySelectorAll('#tbody tr')[activeRow].classList.remove('active');
  activeRow = idx;
  document.querySelectorAll('#tbody tr')[idx].classList.add('active');
  const p = posts[idx];
  document.getElementById('sel-title').textContent = p.title;
  document.getElementById('sel-meta').textContent =
    `${{p.section_norm}} · ${{p.views.toLocaleString()}} views · ${{p.author}}`;
  radarChart.data.datasets[0].data = [p.reach, p.depth, p.discovery];
  radarChart.update();
}}

// Auto-select top story
if (posts.length > 0) selectPost(0);

// Column sort
let sortCol = 'composite', sortDir = -1;
document.querySelectorAll('th').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    sortDir = (sortCol === col) ? -sortDir : -1;
    sortCol = col;
    const sorted = [...posts].sort((a,b) => sortDir * ((a[col]??0) < (b[col]??0) ? -1 : 1));
    tbody.innerHTML = '';
    sorted.forEach((p, i) => {{
      const origIdx = posts.indexOf(p);
      const tr = tbody.querySelector(`tr[data-idx="${{origIdx}}"]`);
      if (tr) tbody.appendChild(tr);
    }});
  }});
}});
</script>
</body>
</html>"""

def generate_dashboard(scored):
    import json
    today = datetime.date.today().strftime("%Y-%m-%d")
    fname = f"cronkite_report_{today}.html"

    posts_json = json.dumps([{
        "url":         p["url"],
        "title":       p["title"],
        "author":      p["author"],
        "section_norm":p["section_norm"],
        "views":       p["views"],
        "reach":       p["reach"],
        "depth":       p["depth"],
        "discovery":   p["discovery"],
        "composite":   p["composite"],
    } for p in scored], indent=2)

    depth_label = scored[0]["depth_label"] if scored else "Avg. Engaged Minutes"

    html = HTML_TEMPLATE.format(
        report_date  = today,
        n_posts      = len(scored),
        posts_json   = posts_json,
        depth_label  = depth_label,
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

ENGAGEMENT SCORE: {composite}/100  (vs. {section_norm} section average)

  Reach      {reach}/100  — how many readers found your story
  Depth      {depth}/100  — how long readers stayed engaged
  Discovery  {discovery}/100 — how much traffic came from search

Scores are section-relative percentiles: a 70 means you outperformed 70% of
{section_norm} stories published Jan–Jun 2026.

Keep up the great work,
Cronkite Audience Engagement Team
"""

def send_author_email(post, smtp_email, smtp_password):
    author = post["author"]
    recipient = AUTHOR_EMAILS.get(author)
    if not recipient:
        return

    pub = post.get("pub_date", "")
    try:
        pub_dt = datetime.datetime.fromisoformat(pub.replace("Z",""))
        age_h = (datetime.datetime.utcnow() - pub_dt).total_seconds() / 3600
        if not (24 <= age_h <= 72):
            return
    except Exception:
        pass

    first = author.split()[0] if author else "there"
    body = EMAIL_TEMPLATE.format(
        first_name   = first,
        title        = post["title"],
        url          = post["url"],
        composite    = post["composite"],
        section_norm = post["section_norm"],
        reach        = post["reach"],
        depth        = post["depth"],
        discovery    = post["discovery"],
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
    print("\nFetching posts from Parse.ly...")
    posts = get_posts()

    if not posts:
        print("No posts found for the past 7 days.")
        return

    print(f"\nScoring {len(posts)} articles...")
    scored = score_articles(posts)

    print_report(scored)

    print("\nGenerating dashboard...")
    generate_dashboard(scored)

    print("\nSending author emails...")
    send_all_author_emails(scored)

    print("\nDone.")

if __name__ == "__main__":
    main()
