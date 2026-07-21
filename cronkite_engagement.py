#!/usr/bin/env python3
"""Cronkite News Bureau — Weekly Engagement Scorer & Dashboard"""
import os, sys, csv, json, math, datetime, smtplib, requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── CREDENTIALS (via environment variables / GitHub Secrets) ──────────────────
PARSELY_KEY    = os.environ.get("PARSELY_KEY",    "cronkitenews.azpbs.org")
PARSELY_SECRET = os.environ.get("PARSELY_SECRET", "")
SMTP_EMAIL     = os.environ.get("SMTP_EMAIL",     "")
SMTP_PASSWORD  = os.environ.get("SMTP_PASSWORD",  "")

PARSELY_API  = "https://api.parsely.com/v2"
SCORES_FILE  = "scores.json"
EMAILS_FILE  = "emails.csv"

# ── MATH HELPERS ─────────────────────────────────────────────────────────────
def norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))

def to_pct(z):
    return round(min(100, max(0, norm_cdf(z) * 100)), 1)

# ── LOAD ARCHIVE ─────────────────────────────────────────────────────────────
def load_archive():
    if not os.path.exists(SCORES_FILE):
        return []
    with open(SCORES_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_archive(records):
    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, separators=(",", ":"))

# ── SECTION BASELINES from archive ───────────────────────────────────────────
def compute_baselines(archive):
    """Per-section mean/std for log_views, avg_engaged, returning_pct."""
    from collections import defaultdict
    buckets = defaultdict(lambda: {"lv": [], "ae": [], "rt": []})
    for r in archive:
        sec = r.get("section_norm", "Other")
        if r.get("views", 0) > 0:
            buckets[sec]["lv"].append(math.log(r["views"]))
        if r.get("depth") is not None:
            buckets[sec]["ae"].append(r["depth"])   # already 0-100 pct in archive
        ret = r.get("returning") if r.get("returning") is not None else r.get("discovery")
        if ret is not None:
            buckets[sec]["rt"].append(ret)

    def ms(vals):
        if len(vals) < 2:
            return (0, 1)
        m = sum(vals) / len(vals)
        s = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)) or 1
        return (m, s)

    baselines = {}
    for sec, d in buckets.items():
        baselines[sec] = {
            "lv": ms(d["lv"]),
            "ae": ms(d["ae"]),
            "rt": ms(d["rt"]),
        }
    return baselines

def section_baseline(baselines, section, key):
    if section in baselines and key in baselines[section]:
        return baselines[section][key]
    # fallback to Other or global defaults
    return baselines.get("Other", {}).get(key, (0, 1))

# ── PARSE.LY API ─────────────────────────────────────────────────────────────
def parsely_get(endpoint, params):
    params.update({"apikey": PARSELY_KEY, "secret": PARSELY_SECRET, "limit": 100})
    r = requests.get(f"{PARSELY_API}{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def fetch_week_stories(pub_start, pub_end):
    """Fetch stories published in [pub_start, pub_end] via 5 Parse.ly calls."""
    period_start = pub_start.strftime("%Y-%m-%d")
    period_end   = pub_end.strftime("%Y-%m-%d")
    base = {"period_start": period_start, "period_end": period_end,
            "pub_date_start": period_start, "pub_date_end": period_end}

    seen = {}
    for sort in ["views", "avg_engaged", "returning_visitors", "mobile_views", "desktop_views"]:
        try:
            data = parsely_get("/analytics/posts", {**base, "sort": sort, "_fields":
                "url,title,author,section,pub_date,metrics"})
            for item in data:
                url = item.get("url", "")
                if url and url not in seen:
                    seen[url] = item
        except Exception as e:
            print(f"  Parse.ly error ({sort}): {e}")
    return list(seen.values())

# ── NORMALIZE SECTION ─────────────────────────────────────────────────────────
SECTION_MAP = {
    "sports": "Sports", "politics": "Politics & Policy", "policy": "Politics & Policy",
    "health": "Health", "indigenous": "Indigenous", "money": "Money",
    "noticias": "Noticias", "borderlands": "Borderlands", "tech": "Tech",
    "social justice": "Social Justice", "sustainability": "Sustainability",
}

def norm_section(raw):
    if not raw:
        return "Other"
    low = raw.lower().strip()
    for k, v in SECTION_MAP.items():
        if k in low:
            return v
    return raw.strip().title() or "Other"

# ── SCORING ───────────────────────────────────────────────────────────────────
def score_story(item, baselines):
    url     = item.get("url", "")
    title   = item.get("title", "")
    author  = item.get("author", "")
    section = norm_section(item.get("section", ""))
    pub_raw = item.get("pub_date", "")
    pub_date = pub_raw[:10] if pub_raw else ""

    m = item.get("metrics", {})
    views    = int(m.get("views", 0))
    avg_eng  = float(m.get("avg_engaged", 0) or 0)
    ret_pct  = float(m.get("visitors", {}).get("returning", 0) or 0) if isinstance(m.get("visitors"), dict) \
               else float(m.get("returning_visitor_pct", 0) or 0)
    mob_v    = float(m.get("mobile_views", 0) or 0)
    desk_v   = float(m.get("desktop_views", 0) or 0)
    tab_v    = float(m.get("tablet_views", 0) or 0)

    total_d  = mob_v + desk_v + tab_v
    mob_pct  = round(mob_v  / total_d * 100, 1) if total_d else 0
    desk_pct = round(desk_v / total_d * 100, 1) if total_d else 0
    tab_pct  = round(tab_v  / total_d * 100, 1) if total_d else 0

    lv = math.log(views) if views > 0 else 0
    lv_mu, lv_sd  = section_baseline(baselines, section, "lv")
    ae_mu, ae_sd  = section_baseline(baselines, section, "ae")
    rt_mu, rt_sd  = section_baseline(baselines, section, "rt")

    reach     = to_pct((lv - lv_mu)       / lv_sd)
    depth     = to_pct((avg_eng - ae_mu)  / ae_sd)
    retention = to_pct((ret_pct - rt_mu)  / rt_sd)

    composite = round(depth * 0.50 + reach * 0.30 + retention * 0.20, 1)

    # snap pub_date to Monday for week_scored
    try:
        d = datetime.date.fromisoformat(pub_date)
        week_scored = (d - datetime.timedelta(days=d.weekday())).isoformat()
    except Exception:
        week_scored = datetime.date.today().isoformat()

    try:
        pub_display = datetime.date.fromisoformat(pub_date).strftime("%b %-d, %Y")
    except Exception:
        pub_display = pub_date

    return {
        "url": url, "title": title, "author": author,
        "section_norm": section, "pub_date": pub_date,
        "pub_date_display": pub_display, "week_scored": week_scored,
        "views": views, "reach": reach, "depth": depth,
        "returning": retention, "composite": composite,
        "mob_pct": mob_pct, "desk_pct": desk_pct, "tab_pct": tab_pct,
    }

# ── AUTHOR EMAILS ─────────────────────────────────────────────────────────────
def load_author_emails():
    emails = {}
    if not os.path.exists(EMAILS_FILE):
        print(f"  No {EMAILS_FILE} found — skipping author emails")
        return emails
    with open(EMAILS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name  = (row.get("Name")  or "").strip()
            email = (row.get("Email") or "").strip()
            if name and email:
                emails[name] = email
    print(f"  Loaded {len(emails)} author emails from {EMAILS_FILE}")
    return emails

# ── EMAIL SENDING ─────────────────────────────────────────────────────────────
def send_email(to_addr, subject, html_body, dry_run=False):
    if dry_run:
        print(f"  [DRY RUN] Would send to {to_addr}: {subject}")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = to_addr
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(SMTP_EMAIL, SMTP_PASSWORD)
        s.sendmail(SMTP_EMAIL, to_addr, msg.as_string())
    print(f"  Sent to {to_addr}")

def build_story_html(story):
    score = story["composite"]
    color = "#27ae60" if score >= 65 else "#e67e22" if score >= 40 else "#c0392b"
    label = "Strong" if score >= 65 else "Average" if score >= 40 else "Needs work"
    return f"""
<div style="border:1px solid #e2e3ea;border-radius:8px;padding:14px;margin-bottom:12px;background:#fff">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#58595b;margin-bottom:3px">{story['section_norm']}</div>
  <div style="font-size:14px;font-weight:600;margin-bottom:6px">
    <a href="{story['url']}" style="color:#005195;text-decoration:none">{story['title']}</a>
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
    <span style="font-size:22px;font-weight:800;color:{color}">{score}</span>
    <span style="font-size:11px;color:{color};font-weight:600">{label}</span>
    <span style="font-size:11px;color:#58595b">{story['views']:,} views</span>
  </div>
  <div style="font-size:11px;color:#58595b">
    Reach: <b>{story['reach']}</b> &nbsp;|&nbsp;
    Depth: <b>{story['depth']}</b> &nbsp;|&nbsp;
    Retention: <b>{story['returning']}</b>
  </div>
</div>"""

def send_all_author_emails(scored, author_emails, dry_run=False):
    by_author = {}
    for story in scored:
        author = story.get("author", "")
        email  = author_emails.get(author)
        if not email:
            continue
        by_author.setdefault(author, {"email": email, "stories": []})["stories"].append(story)

    if not by_author:
        print("  No matching authors in emails.csv — no emails sent")
        return

    for author, data in by_author.items():
        stories_html = "".join(build_story_html(s) for s in data["stories"])
        week = data["stories"][0].get("week_scored", "this week")
        subject = f"Your Cronkite engagement score — week of {week}"
        html = f"""
<div style="font-family:Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;background:#f5f6fa;padding:20px">
  <div style="background:#005195;padding:16px 20px;border-radius:8px 8px 0 0;margin-bottom:2px">
    <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,.6)">Cronkite News Bureau</div>
    <div style="font-size:18px;font-weight:700;color:#fff;margin-top:4px">Audience Engagement Report</div>
    <div style="font-size:11px;color:rgba(255,255,255,.55);margin-top:2px">Week of {week}</div>
  </div>
  <div style="background:#fff;padding:16px 20px;border-radius:0 0 8px 8px;border:1px solid #e2e3ea">
    <p style="font-size:13px;color:#414141;margin-bottom:14px">Hi {author.split()[0]},<br><br>
    Here are your engagement scores for stories published this week. Scores are section-relative —
    a 50 means you hit your section's average; above 65 is strong.</p>
    {stories_html}
    <p style="font-size:11px;color:#58595b;margin-top:14px">
      <a href="https://hopecfrost.github.io/cronkite-engagement/" style="color:#005195">View full dashboard</a>
      &nbsp;&middot;&nbsp; Questions? Contact the audience engagement team.
    </p>
  </div>
</div>"""
        send_email(data["email"], subject, html, dry_run=dry_run)

# ── HTML DASHBOARD ────────────────────────────────────────────────────────────
def build_dashboard(all_scores, week_options, section_options):
    last_updated = datetime.date.today().strftime("%B %-d, %Y")
    total = len(all_scores)
    rows_json = json.dumps(all_scores, separators=(",", ":"))

    week_opts = "\n".join(
        f'<option value="{w}">Week of {w}</option>' for w in week_options
    )
    sec_opts = "\n".join(
        f'<option value="{s}">{s}</option>' for s in section_options
    )

    # Default week: most recent week with ≥10 stories
    from collections import Counter
    week_counts = Counter(r["week_scored"] for r in all_scores)
    default_week = next(
        (w for w in week_options if week_counts.get(w, 0) >= 10),
        week_options[0] if week_options else "all"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cronkite Audience Engagement Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;background:#f5f6fa;color:#414141;height:100vh;overflow:hidden;display:flex;flex-direction:column}}
header{{background:#005195;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;border-bottom:3px solid #58595b}}
.bureau{{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.6)}}
.report-title{{font-size:19px;font-weight:700;color:#fff;margin:2px 0}}
.daterange{{font-size:11px;color:rgba(255,255,255,0.55)}}
.totals{{display:flex;gap:24px}}
.total{{text-align:right}}
.total-label{{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.55)}}
.total-value{{font-size:20px;font-weight:800;color:#fff}}
.badge{{background:#fff;color:#005195;font-size:.68rem;font-weight:700;padding:3px 9px;border-radius:99px;text-transform:uppercase;letter-spacing:.05em}}
.tab-bar{{background:#fff;border-bottom:1px solid #e2e3ea;display:flex;gap:0;flex-shrink:0}}
.tab{{background:none;border:none;border-bottom:3px solid transparent;padding:10px 24px;font-size:13px;font-weight:600;color:#58595b;cursor:pointer;transition:all .15s}}
.tab:hover{{color:#005195}}
.tab-active{{color:#005195;border-bottom-color:#005195}}
.controls{{background:#fff;border-bottom:1px solid #e2e3ea;padding:9px 16px;display:flex;gap:10px;flex-wrap:wrap;flex-shrink:0}}
.controls input,.controls select{{background:#f5f6fa;border:1px solid #e2e3ea;color:#414141;padding:6px 10px;border-radius:6px;font-size:12px;outline:none}}
.controls input{{flex:1;min-width:180px}}
.controls input:focus,.controls select:focus{{border-color:#005195;background:#fff}}
.layout{{display:grid;grid-template-columns:1fr 400px;flex:1;overflow:hidden}}
.table-panel{{overflow-y:auto;border-right:1px solid #e2e3ea;background:#fff}}
.table-header{{padding:10px 14px 7px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#005195;border-bottom:1px solid #e2e3ea;display:flex;justify-content:space-between;align-items:center}}
.pill-legend{{display:flex;gap:7px}}
.pill-legend span{{font-size:.68rem;padding:2px 7px;border-radius:99px;font-weight:600}}
.leg-reach{{background:rgba(52,152,219,.15);color:#3498db}}
.leg-depth{{background:rgba(155,89,182,.15);color:#9b59b6}}
.leg-retention{{background:rgba(26,188,156,.15);color:#1abc9c}}
table{{width:100%;border-collapse:separate;border-spacing:0;border:none}}
thead th{{position:sticky;top:0;background:#f5f6fa;padding:7px 10px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#58595b;border:none;border-bottom:2px solid #e2e3ea;z-index:1;white-space:nowrap;cursor:pointer;user-select:none}}
thead th:hover{{color:#005195}}
tbody tr{{cursor:pointer;transition:background .1s}}
tbody tr:hover td{{background:#eef4fb}}
tbody tr.selected td{{background:#ddeaf7}}
tbody tr.selected td:first-child{{border-left:3px solid #005195}}
td{{padding:7px 10px;font-size:12px;color:#414141;border:none;border-bottom:1px solid #f0f1f5}}
td.rk{{color:#58595b;font-size:11px;width:28px;padding-right:4px}}
td.ttl{{max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
td.sec{{color:#58595b;font-size:11px;width:100px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100px}}
td.vw{{font-size:11px;color:#58595b;width:62px;text-align:right}}
td.bar-cell{{width:80px}}
td.sc{{width:50px}}
.bar-wrap{{display:flex;align-items:center;gap:4px}}
.bar{{height:5px;border-radius:3px;background:#e8eaf0;flex:1;overflow:hidden}}
.bar-fill{{height:100%;border-radius:3px}}
.bar-reach{{background:#3498db}}.bar-depth{{background:#9b59b6}}.bar-discovery{{background:#1abc9c}}
.score-pill{{display:inline-block;padding:3px 9px;border-radius:99px;font-weight:700;font-size:.78rem}}
.score-high{{background:rgba(39,174,96,.15);color:#27ae60}}
.score-mid{{background:rgba(230,126,34,.15);color:#e67e22}}
.score-low{{background:rgba(192,57,43,.12);color:#c0392b}}
.right-panel{{overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:10px;background:#f5f6fa}}
.card{{background:#fff;border:1px solid #e2e3ea;border-radius:8px;padding:14px}}
.card h2{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#005195;font-weight:700;margin-bottom:10px}}
.story-section{{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#58595b;margin-bottom:3px}}
.story-title{{font-size:13px;font-weight:600;color:#414141;line-height:1.4;margin-bottom:4px}}
.story-title a{{color:#005195;text-decoration:none}}
.story-title a:hover{{text-decoration:underline}}
.story-meta{{font-size:11px;color:#58595b;margin-bottom:10px}}
.score-row{{display:flex;align-items:center;gap:12px}}
.score-circle{{width:62px;height:62px;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;border:3px solid;flex-shrink:0}}
.score-circle.high{{border-color:#27ae60;color:#27ae60}}
.score-circle.mid{{border-color:#e67e22;color:#e67e22}}
.score-circle.low{{border-color:#c0392b;color:#c0392b}}
.sc-num{{font-size:20px;font-weight:800;line-height:1}}
.sc-lbl{{font-size:8px;text-transform:uppercase;letter-spacing:1px;opacity:.65}}
.score-breakdown{{flex:1;display:flex;flex-direction:column;gap:6px}}
.sb-row{{display:flex;align-items:center;gap:6px;font-size:11px;color:#58595b}}
.sb-label{{width:100px;font-size:10px}}
.sb-bar{{flex:1;height:6px;background:#eef;border-radius:3px;overflow:hidden}}
.sb-val{{width:24px;text-align:right;font-weight:600;color:#414141;font-size:11px}}
.dev-bar-full{{display:flex;height:12px;border-radius:6px;overflow:hidden;margin-bottom:10px}}
.dev-seg{{height:100%;transition:width .3s}}
.dev-legend{{display:flex;gap:14px;font-size:11px;color:#58595b}}
.dev-dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;vertical-align:middle}}
.chart-wrap{{position:relative;height:220px}}
.chart-wrap-sm{{position:relative;height:190px}}
.detail-empty{{text-align:center;padding:50px 20px;color:#aaa;font-size:12px}}
.method-text{{font-size:11px;color:#58595b;line-height:1.7}}
.method-text b{{color:#414141}}
.ai-btn{{background:#005195;color:#fff;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600;width:100%}}
.ai-btn:hover{{background:#003f75}}
.ai-box{{margin-top:10px;padding:12px;background:#f5f6fa;border-left:3px solid #005195;border-radius:3px;font-size:12px;color:#414141;line-height:1.7;display:none}}
</style>
</head>
<body>
<header>
  <div>
    <div class="bureau">Cronkite News Bureau</div>
    <div class="report-title">Audience Engagement Dashboard</div>
    <div class="daterange">cronkitenews.azpbs.org &middot; Last updated: {last_updated}</div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <div class="totals">
      <div class="total"><div class="total-label">Web Archive</div><div class="total-value">{total:,}</div></div>
      <div class="total"><div class="total-label">Shown</div><div class="total-value" id="shownCount">&mdash;</div></div>
    </div>
    <span class="badge">Auto-generated</span>
  </div>
</header>
<div class="tab-bar">
  <button id="webTab" class="tab tab-active" onclick="switchTab('web')">&#128240; Web Stories</button>
</div>
<div id="webContent" style="display:contents">
  <div class="controls">
    <input id="webSearch" type="text" placeholder="Search title, author, URL&hellip;">
    <select id="weekSel">
      <option value="all">All weeks</option>
      {week_opts}
    </select>
    <select id="secSel">
      <option value="all">All sections</option>
      {sec_opts}
    </select>
    <select id="sortSel">
      <option value="composite">Sort: Score</option>
      <option value="reach">Sort: Reach</option>
      <option value="depth">Sort: Depth</option>
      <option value="returning">Sort: Retention</option>
      <option value="views">Sort: Views</option>
      <option value="pub_date">Sort: Newest</option>
    </select>
  </div>
  <div class="layout">
    <div class="table-panel">
      <div class="table-header">Story Rankings
        <div class="pill-legend">
          <span class="leg-reach">Reach</span>
          <span class="leg-depth">Depth</span>
          <span class="leg-retention">Retention</span>
        </div>
      </div>
      <table>
        <thead><tr>
          <th class="rk">#</th>
          <th class="ttl">Story</th>
          <th class="sec">Section</th>
          <th class="sc" data-col="composite">Score</th>
          <th class="vw" data-col="views">Views</th>
          <th class="bar-cell">Reach</th>
          <th class="bar-cell">Depth</th>
          <th class="bar-cell">Retention</th>
        </tr></thead>
        <tbody id="webBody"></tbody>
      </table>
    </div>
    <div class="right-panel" id="webRight">
      <div class="detail-empty">&#8592; Select a story to see details</div>
    </div>
  </div>
</div>
<script>
const ROWS={rows_json};
const DEFAULT="{default_week}";
let filtered=[],selectedUrl=null,currentStory=null,radarChart=null,scatterChart=null;

function switchTab(tab){{}}

function cls(v)     {{ return v>=65?'high':v>=40?'mid':'low'; }}
function pillCls(v) {{ return v>=65?'score-high':v>=40?'score-mid':'score-low'; }}
function bar(val,c) {{
  return '<div class="bar-wrap"><div class="bar"><div class="bar-fill '+c+'" style="width:'+val+'%"></div></div><span class="bar-val">'+Math.round(val)+'</span></div>';
}}
function getThird(r) {{ return r.returning??r.discovery??50; }}

function buildScatter(rows) {{
  if(scatterChart){{scatterChart.destroy();scatterChart=null;}}
  const ctx=document.getElementById('sc'); if(!ctx) return;
  scatterChart=new Chart(ctx.getContext('2d'),{{type:'scatter',
    data:{{datasets:[{{data:rows.map((r,i)=>{{return {{x:r.reach,y:r.depth,idx:i}}};}}).filter(Boolean),
      backgroundColor:rows.map(r=>r.composite>=65?'rgba(39,174,96,.7)':r.composite>=40?'rgba(230,126,34,.7)':'rgba(192,57,43,.7)'),
      pointRadius:5,pointHoverRadius:7}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      onClick(e,els){{if(els.length)showDetail(filtered[els[0].index]);}},
      scales:{{x:{{min:0,max:100,title:{{display:true,text:'Reach',color:'#3498db',font:{{size:10}}}},grid:{{color:'#f0f1f5'}},ticks:{{color:'#58595b',font:{{size:10}}}}}},
              y:{{min:0,max:100,title:{{display:true,text:'Depth',color:'#9b59b6',font:{{size:10}}}},grid:{{color:'#f0f1f5'}},ticks:{{color:'#58595b',font:{{size:10}}}}}}}},
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>filtered[ctx.dataIndex]?.title?.slice(0,38)||''}}}}}}}}}});
}}

function getSmartFeedback(r) {{
  const third=getThird(r);
  const score=r.composite, reach=r.reach, depth=r.depth, retention=third;
  const section=r.section_norm||'your section';
  const pillars=[{{name:'reach',val:reach}},{{name:'depth',val:depth}},{{name:'retention',val:retention}}];
  pillars.sort((a,b)=>a.val-b.val);
  const weak=pillars[0], strong=pillars[2];

  if(score>=65) {{
    if(weak.val<45) {{
      const strengthNote=strong.name==='depth'?'time-on-page is excellent':strong.name==='reach'?'reach is strong':'reader loyalty is impressive';
      const weakNote=weak.name==='reach'?`reach (${{{reach}}}) has room to grow — a more specific headline and earlier social distribution could pull in more first-time readers.`:
                     weak.name==='depth'?`depth (${{{depth}}}) could improve — consider adding more context, multimedia, or a longer narrative arc to keep readers engaged longer.`:
                     `retention (${{{retention}}}) suggests readers aren't coming back — link to related ${{section}} coverage to build a returning audience.`;
      return `Strong score (${{score}}) — your ${{strengthNote}}. Your weakest area is ${{weakNote}}`;
    }}
    return `Excellent story — ${{score}} with balanced pillars (Reach ${{reach}}, Depth ${{depth}}, Retention ${{retention}}). This is what strong ${{section}} content looks like.`;
  }} else if(score>=40) {{
    if(weak.name==='reach') return `Readers who find this story stay and come back — depth (${{depth}}) and retention (${{retention}}) are solid. The challenge is reach (${{reach}}): try a more curiosity-driven headline and distributing earlier in the news cycle.`;
    if(weak.name==='depth') return `Readers are finding the story but leaving quickly — depth is ${{depth}}, below the ${{section}} section average. A stronger narrative arc, more context, or added multimedia can help increase engaged time.`;
    return `Reach and depth are solid, but retention (${{retention}}) suggests one-time visitors. Linking to related ${{section}} coverage and following up with a second story can build loyal readership.`;
  }} else {{
    if(weak.name==='reach') return `Reach (${{reach}}) is the biggest opportunity — this story didn't find its audience. Revisit the headline for searchability, and consider if earlier social distribution or a stronger news hook would help.`;
    if(weak.name==='depth') return `With depth at ${{depth}}, readers are leaving quickly. Stronger ledes, a clearer narrative, and added multimedia can help. Ask: does the story fully answer the reader's core question?`;
    return `Retention (${{retention}}) is low — readers aren't returning after this story. A follow-up angle or links to related ${{section}} coverage could help build audience loyalty over time.`;
  }}
}}

function showDetail(r) {{
  currentStory=r;
  selectedUrl=r.url;
  document.querySelectorAll('#webBody tr').forEach(t=>t.classList.remove('selected'));
  const row=document.querySelector('#webBody tr[data-url="'+CSS.escape(r.url)+'"]');
  if(row) row.classList.add('selected');
  const c=cls(r.composite);
  const mob=r.mob_pct||0,desk=r.desk_pct||0,tab=r.tab_pct||0;
  const third=getThird(r);
  document.getElementById('webRight').innerHTML=
    '<div class="card">'+
      '<div class="story-section">'+r.section_norm+'&middot;'+(r.pub_date_display||r.pub_date)+'</div>'+
      '<div class="story-title"><a href="'+r.url+'" target="_blank">'+r.title+'</a></div>'+
      '<div class="story-meta">'+(r.author||'')+'&middot;'+(r.views||0).toLocaleString()+' views &middot; Week: '+r.week_scored+'</div>'+
      '<div class="score-row">'+
        '<div class="score-circle '+c+'"><div class="sc-num">'+r.composite+'</div><div class="sc-lbl">Score</div></div>'+
        '<div class="score-breakdown">'+
          '<div class="sb-row"><span class="sb-label" style="color:#3498db">Reach (30%)</span><div class="sb-bar"><div class="bar-fill bar-reach" style="width:'+r.reach+'%"></div></div><span class="sb-val">'+r.reach+'</span></div>'+
          '<div class="sb-row"><span class="sb-label" style="color:#9b59b6">Depth (50%)</span><div class="sb-bar"><div class="bar-fill bar-depth" style="width:'+r.depth+'%"></div></div><span class="sb-val">'+r.depth+'</span></div>'+
          '<div class="sb-row"><span class="sb-label" style="color:#1abc9c">Retention (20%)</span><div class="sb-bar"><div class="bar-fill bar-discovery" style="width:'+third+'%"></div></div><span class="sb-val">'+third+'</span></div>'+
        '</div>'+
      '</div>'+
    '</div>'+
    '<div class="card"><h2>How It Was Accessed</h2>'+
      '<div class="dev-bar-full">'+
        '<div class="dev-seg" style="width:'+mob+'%;background:#005195"></div>'+
        '<div class="dev-seg" style="width:'+desk+'%;background:#3498db"></div>'+
        '<div class="dev-seg" style="width:'+tab+'%;background:#c8d0d8"></div>'+
      '</div>'+
      '<div class="dev-legend">'+
        '<span><span class="dev-dot" style="background:#005195"></span>Mobile '+mob+'%</span>'+
        '<span><span class="dev-dot" style="background:#3498db"></span>Desktop '+desk+'%</span>'+
        '<span><span class="dev-dot" style="background:#c8d0d8"></span>Tablet '+tab+'%</span>'+
      '</div>'+
    '</div>'+
    '<div class="card"><h2>Pillar Breakdown</h2><div class="chart-wrap"><canvas id="rc"></canvas></div></div>'+
    '<div class="card"><h2>Score Distribution</h2><div class="chart-wrap-sm"><canvas id="sc"></canvas></div></div>'+
    '<div class="card"><h2>Methodology</h2><p class="method-text">'+
      'Section-relative percentile (0–100) vs. Dec 2024–present baseline (N=9,990).<br><br>'+
      '<b style="color:#3498db">Reach</b> — log(views) vs. section avg<br>'+
      '<b style="color:#9b59b6">Depth</b> — Avg. Engaged Minutes vs. section avg<br>'+
      '<b style="color:#1abc9c">Retention</b> — % returning visitors vs. section avg<br><br>'+
      'Composite = Depth 50% + Reach 30% + Retention 20%'+
    '</p></div>'+
    '<div class="card"><h2>&#10024; AI Feedback</h2>'+
      '<button class="ai-btn" onclick="showFeedback()">Get Engagement Feedback</button>'+
      '<div class="ai-box" id="ai-feedback-box"></div>'+
    '</div>';
  if(radarChart){{radarChart.destroy();radarChart=null;}}
  radarChart=new Chart(document.getElementById('rc').getContext('2d'),{{type:'radar',
    data:{{labels:['Reach (30%)','Depth (50%)','Retention (20%)'],datasets:[{{
      data:[r.reach,r.depth,third],backgroundColor:'rgba(0,81,149,0.1)',
      borderColor:'#005195',pointBackgroundColor:'#005195',pointBorderColor:'#fff',pointBorderWidth:1.5,borderWidth:2,pointRadius:4}}]}},
    options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},
      scales:{{r:{{min:0,max:100,ticks:{{display:false}},grid:{{color:'#e2e3ea'}},angleLines:{{color:'#e2e3ea'}},pointLabels:{{color:'#58595b',font:{{size:11}}}}}}}}}}});
  buildScatter(filtered);
}}

function showFeedback() {{
  const r=currentStory;
  if(!r) return;
  const box=document.getElementById('ai-feedback-box');
  if(!box) return;
  box.style.display='block';
  box.textContent=getSmartFeedback(r);
  const btn=box.previousElementSibling;
  if(btn) btn.textContent='Refresh Feedback';
}}

function render() {{
  const q=document.getElementById('webSearch').value.toLowerCase();
  const wk=document.getElementById('weekSel').value;
  const sec=document.getElementById('secSel').value;
  const srt=document.getElementById('sortSel').value;
  filtered=ROWS.filter(r=>(wk==='all'||r.week_scored===wk)&&(sec==='all'||r.section_norm===sec)&&
    (!q||r.title.toLowerCase().includes(q)||(r.author||'').toLowerCase().includes(q)||r.url.toLowerCase().includes(q)));
  filtered.sort((a,b)=>{{
    if(srt==='pub_date') return b.pub_date>a.pub_date?1:-1;
    if(srt==='returning') return (getThird(b)??0)-(getThird(a)??0);
    return (b[srt]??0)-(a[srt]??0);
  }});
  document.getElementById('shownCount').textContent=filtered.length.toLocaleString();
  const body=document.getElementById('webBody');
  if(!filtered.length){{
    body.innerHTML='<tr><td colspan="8" style="text-align:center;padding:40px;color:#aaa">No stories match.</td></tr>';
    document.getElementById('webRight').innerHTML='<div class="detail-empty">No stories to show.</div>';
    return;
  }}
  body.innerHTML=filtered.map((r,i)=>
    '<tr data-url="'+r.url+'" onclick="showDetail(filtered['+i+'])" class="'+(r.url===selectedUrl?'selected':'')+'">'+
    '<td class="rk">'+(i+1)+'</td>'+
    '<td class="ttl">'+r.title+'</td>'+
    '<td class="sec">'+r.section_norm+'</td>'+
    '<td class="sc"><span class="score-pill '+pillCls(r.composite)+'">'+r.composite+'</span></td>'+
    '<td class="vw">'+(r.views||0).toLocaleString()+'</td>'+
    '<td class="bar-cell">'+bar(r.reach,'bar-reach')+'</td>'+
    '<td class="bar-cell">'+bar(r.depth,'bar-depth')+'</td>'+
    '<td class="bar-cell">'+bar(getThird(r),'bar-discovery')+'</td>'+
    '</tr>'
  ).join('');
  if(!selectedUrl||!filtered.find(r=>r.url===selectedUrl)) showDetail(filtered[0]);
  else buildScatter(filtered);
}}

['webSearch','weekSel','secSel','sortSel'].forEach(id=>document.getElementById(id).addEventListener('input',render));
document.querySelectorAll('th[data-col]').forEach(th=>th.addEventListener('click',()=>{{document.getElementById('sortSel').value=th.dataset.col;render();}}));
document.getElementById('weekSel').value=DEFAULT||'all';
render();
</script>
</body>
</html>"""

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    dry_run = "--dry-run" in sys.argv
    print(f"Starting Cronkite engagement scorer (dry_run={dry_run})")

    # Load archive
    archive = load_archive()
    print(f"  Loaded {len(archive)} archived scores")

    # Compute baselines from archive
    baselines = compute_baselines(archive)
    print(f"  Computed baselines for {len(baselines)} sections")

    # Determine scoring window: stories published 7–14 days ago
    today = datetime.date.today()
    pub_end   = today - datetime.timedelta(days=7)
    pub_start = today - datetime.timedelta(days=14)
    print(f"  Scoring window: {pub_start} to {pub_end}")

    # Fetch stories from Parse.ly
    raw = fetch_week_stories(pub_start, pub_end)
    print(f"  Fetched {len(raw)} stories from Parse.ly")

    # Already-scored URLs
    scored_urls = {r["url"] for r in archive}

    # Score new stories
    new_scored = []
    for item in raw:
        url = item.get("url", "")
        if url and url not in scored_urls:
            rec = score_story(item, baselines)
            new_scored.append(rec)

    print(f"  Scored {len(new_scored)} new stories")

    # Update archive
    if new_scored:
        archive.extend(new_scored)
        save_archive(archive)
        print(f"  Saved {len(archive)} total to {SCORES_FILE}")

    # Collect week and section options (sorted, newest first)
    from collections import Counter
    all_weeks = sorted({r["week_scored"] for r in archive}, reverse=True)
    all_sections = sorted({r["section_norm"] for r in archive})

    # Generate dashboard
    html = build_dashboard(archive, all_weeks, all_sections)
    today_str = today.strftime("%Y-%m-%d")
    fname = f"cronkite_report_{today_str}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Generated {fname}")

    # Send author emails
    author_emails = load_author_emails()
    send_all_author_emails(new_scored, author_emails, dry_run=dry_run)

    print("Done.")

if __name__ == "__main__":
    main()
