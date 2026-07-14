#!/usr/bin/env python3
"""
Cronkite News Bureau — Engagement Scoring System
-------------------------------------------------
Scores recently published articles on three pillars (equal thirds):
  Reach      — views, vs. section historical baseline
  Depth      — avg. engaged minutes (or recirculation fallback), vs. baseline
  Discovery  — % traffic from search, vs. section baseline

Section baselines are pre-computed from a Dec 2024–Jul 2026 Parse.ly CSV export
(9,483 stories). Each story is z-scored against its own section's history
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

# ── Historical baselines (Dec 2024–Jul 2026, N=9,483 stories with ≥5 views) ──
# Metrics: log(views+1), avg engaged minutes, search_refs/views
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
    now        = datetime.datetime.utcnow()
    week_ago   = now - datetime.timedelta(days=7)
    two_weeks  = now - datetime.timedelta(days=14)
    date_params = {
        "pub_date_start": two_weeks.strftime("%Y-%m-%d"),
        "pub_date_end":   week_ago.strftime("%Y-%m-%d"),
        "period_start":   two_weeks.strftime("%Y-%m-%d"),
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
        print("  Note: avg_engaged unavailable for most posts — using recirculation rate for Depth")

    scored = []
    for post in posts:
        baselines, section_norm = get_baselines(post["section"])
        views = max(post["views"], 1)

        # Reach: log(views) vs. section baseline
        reach = z_to_pct(math.log(views + 1),
                          baselines["log_views_mean"],
                          baselines["log_views_std"])

        # Depth: avg_engaged minutes vs. section baseline (recirc fallback)
        if use_recirc or post["avg_engaged"] == 0:
            depth = round(min(post["recirculation_rate"] / 0.10, 1.0) * 100, 1)
        else:
            depth = z_to_pct(post["avg_engaged"],
                              baselines["avg_min_mean"],
                              baselines["avg_min_std"])

        # Discovery: search % vs. section baseline
        search_pct = post["search_refs"] / views
        discovery  = z_to_pct(search_pct,
                               baselines["search_pct_mean"],
                               baselines["search_pct_std"])

        composite = round(reach * 0.30 + depth * 0.50 + discovery * 0.20, 1)

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
    print(f"  Scoring: Reach 30% | Depth 50% | Discovery 20%")
    print(f"  All scores are section-relative percentiles (0–100)")
    print(f"  Baselines: Dec 2024–Jul 2026  |  N=9,483 stories")
    print(f"{'='*80}\n")

    fmt = "{:>3}. {:<42} {:>7} {:>7} {:>7} {:>7} {:>8}  {}"
    print(fmt.format("#", "Title", "Views", "Reach", "Depth", "Discov", "SCORE", "Section"))
    print("-" * 105)

    for i, p in enumerate(scored[:20], 1):
        print(fmt.format(
            i, p["title"][:42],
            f"{p['views']:,}",
            f"{p['reach']:.0f}",
            f"{p['depth']:.0f}",
            f"{p['discovery']:.0f}",
            f"{p['composite']:.1f}",
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
    margin-left: auto;
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
  .score-high {{ background: rgba(39,174,96,0.2);  color: #2ecc71; }}
  .score-mid  {{ background: rgba(255,198,39,0.2); color: var(--gold); }}
  .score-low  {{ background: rgba(231,76,60,0.15); color: #e74c3c; }}

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
    <div class="meta">Stories from the week of {report_date} &nbsp;|&nbsp; scored after 7+ days &nbsp;|&nbsp; {n_posts} stories</div>
  </div>
  <span class="badge">Auto-generated</span>
</header>

<div class="layout">
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
          <th data-col="section_norm">Section</th>
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
      comparing this story against its section's Dec 2024–Jul 2026 historical baseline (N=9,483).<br><br>
      <strong style="color:#3498db">Reach</strong> — log(views) vs. section avg<br>
      <strong style="color:#9b59b6">Depth</strong> — {depth_label} vs. section avg<br>
      <strong style="color:#1abc9c">Discovery</strong> — % traffic from search vs. section avg<br><br>
      Composite = Depth 50% · Reach 30% · Discovery 20%.
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

const tbody = document.getElementById('tbody');
posts.forEach((p, i) => {{
  const tr = document.createElement('tr');
  tr.dataset.idx = i;
  tr.innerHTML = `
    <td style="color:var(--muted);font-size:0.75rem">${{i+1}}</td>
    <td><a href="${{p.url}}" target="_blank" style="color:#fff;text-decoration:none;font-size:0.83rem" onclick="event.stopPropagation()">${{p.title.length>55?p.title.slice(0,55)+'…':p.title}}</a></td>
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

const radarCtx = document.getElementById('radarChart').getContext('2d');
const radarChart = new Chart(radarCtx, {{
  type: 'radar',
  data: {{
    labels: ['Reach','Depth','Discovery'],
    datasets: [{{ label: 'Score', data: [0,0,0],
      backgroundColor: 'rgba(255,198,39,0.15)', borderColor: '#FFC627',
      pointBackgroundColor: '#FFC627', borderWidth: 2 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{ r: {{ min:0, max:100,
      ticks: {{ stepSize:25, color:'#888', font:{{size:10}} }},
      grid: {{ color:'rgba(255,255,255,0.08)' }},
      pointLabels: {{ color:'#e0e0e0', font:{{size:12}} }},
      angleLines: {{ color:'rgba(255,255,255,0.08)' }},
    }} }},
    plugins: {{ legend: {{ display:false }} }},
  }}
}});

const scatterCtx = document.getElementById('scatterChart').getContext('2d');
new Chart(scatterCtx, {{
  type: 'scatter',
  data: {{ datasets: [{{ label:'Stories',
    data: posts.map(p => ({{ x:p.reach, y:p.depth, post:p }})),
    backgroundColor: posts.map(p => p.composite>=65?'rgba(46,204,113,0.7)':p.composite>=40?'rgba(255,198,39,0.7)':'rgba(231,76,60,0.7)'),
    pointRadius: 5,
  }}] }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      x: {{ min:0, max:100, title:{{display:true,text:'Reach',color:'#3498db',font:{{size:11}}}}, grid:{{color:'rgba(255,255,255,0.05)'}}, ticks:{{color:'#888'}} }},
      y: {{ min:0, max:100, title:{{display:true,text:'Depth',color:'#9b59b6',font:{{size:11}}}}, grid:{{color:'rgba(255,255,255,0.05)'}}, ticks:{{color:'#888'}} }},
    }},
    plugins: {{ legend:{{display:false}}, tooltip:{{ callbacks:{{ label: ctx => ctx.raw.post.title.slice(0,40) }} }} }},
  }}
}});

let activeRow = null;
function selectPost(idx) {{
  if (activeRow !== null) document.querySelectorAll('#tbody tr')[activeRow].classList.remove('active');
  activeRow = idx;
  document.querySelectorAll('#tbody tr')[idx].classList.add('active');
  const p = posts[idx];
  document.getElementById('sel-title').textContent = p.title;
  document.getElementById('sel-meta').textContent = `${{p.section_norm}} · ${{p.views.toLocaleString()}} views · ${{p.author}}`;
  radarChart.data.datasets[0].data = [p.reach, p.depth, p.discovery];
  radarChart.update();
}}

if (posts.length > 0) selectPost(0);

let sortCol = 'composite', sortDir = -1;
document.querySelectorAll('th').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    sortDir = sortCol === col ? -sortDir : -1;
    sortCol = col;
    const sorted = [...posts].sort((a,b) => sortDir*((a[col]??0)<(b[col]??0)?-1:1));
    tbody.innerHTML = '';
    sorted.forEach((p,i) => {{
      const origIdx = posts.indexOf(p);
      const tr = document.querySelector(`tr[data-idx="${{origIdx}}"]`);
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
        report_date=today, n_posts=len(scored),
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

  Reach      {reach}/100  — how many readers found your story
  Depth      {depth}/100  — how long readers stayed engaged
  Discovery  {discovery}/100 — how much traffic came from search

A score of 50 means exactly average for {section_norm}. A 70 means you
outperformed 70% of {section_norm} stories published Dec 2024–Jul 2026.

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
    body  = EMAIL_TEMPLATE.format(first_name=first, **{k: post[k] for k in
            ["title","url","composite","section_norm","reach","depth","discovery"]})

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
