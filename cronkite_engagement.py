"""
Cronkite Sports Bureau — Engagement Scoring Script
====================================================
Pulls the past 7 days of articles from the Parse.ly API,
scores each one using a weighted engagement formula,
prints a ranked weekly report, generates an HTML dashboard,
and emails authors their 48-hour performance report.

Run:
    python3 cronkite_engagement.py

Email setup (one-time):
    export SMTP_EMAIL="yourbureau@gmail.com"
    export SMTP_PASSWORD="your-app-password"

Requirements:
    pip3 install requests
"""

import os
import math
import json
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ── Credentials ────────────────────────────────────────────────────────────────
PARSELY_KEY    = os.getenv("PARSELY_KEY",    "cronkitenews.azpbs.org")
PARSELY_SECRET = os.getenv("PARSELY_SECRET", "tAytVAdJCyLdFHatqOOHLVXTrdHpUm5kQusX8ZWzHoA")
BASE_URL = "https://api.parsely.com/v2"

# ── Email config ───────────────────────────────────────────────────────────────
SMTP_EMAIL    = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_SERVER   = "smtp.gmail.com"
SMTP_PORT     = 587

# ── Author email directory — fill in with bureau staff ────────────────────────
# Format: "Name as it appears in Parse.ly": "email@cronkite.asu.edu"
AUTHOR_EMAILS = {
    # "Jane Smith": "jane.smith@cronkitebureau.com",
    # "John Doe":   "john.doe@cronkitebureau.com",
}

# ── Scoring weights ────────────────────────────────────────────────────────────
# Parse.ly returns views + recirculation_rate for the posts endpoint.
# Recirculation rate = % of readers who clicked to a second story.
WEIGHTS = {
    "reach":       0.40,   # log-normalized page views
    "depth":       0.45,   # recirculation rate
    "search_pull": 0.15,   # % traffic from search
}

# ── Section benchmarks: avg recirculation rate ─────────────────────────────────
# Update these once you pull a longer historical window from the API.
SECTION_BENCHMARKS = {
    "Sports":            0.018,
    "Politics & Policy": 0.016,
    "Politics":          0.015,
    "Sustainability":    0.020,
    "Health":            0.019,
    "Consumer":          0.022,
    "Borderlands":       0.017,
    "Government":        0.016,
    "Social Justice":    0.021,
    "National Security": 0.018,
    "Indigenous":        0.016,
    "Immigration":       0.014,
    "default":           0.017,
}


# ── API helpers ────────────────────────────────────────────────────────────────

def get_posts(days=7, limit=50):
    params = {
        "apikey": PARSELY_KEY, "secret": PARSELY_SECRET,
        "days": days, "limit": limit, "sort": "views",
    }
    r = requests.get(f"{BASE_URL}/analytics/posts", params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Parse.ly error: {data}")
    return data["data"]


def get_search_views(url, days=7):
    params = {
        "apikey": PARSELY_KEY, "secret": PARSELY_SECRET,
        "url": url, "days": days, "limit": 5,
    }
    r = requests.get(f"{BASE_URL}/referrers/post/detail", params=params, timeout=15)
    if r.status_code != 200:
        return 0
    data = r.json()
    if not data.get("success"):
        return 0
    for item in data.get("data", []):
        if item.get("type") == "search":
            return item.get("metrics", {}).get("views", 0)
    return 0


# ── Scoring ────────────────────────────────────────────────────────────────────

def normalize_log(value, max_value):
    if value <= 0 or max_value <= 0:
        return 0.0
    return math.log(value) / math.log(max_value)


def score_article(article, max_views):
    m      = article.get("metrics", {})
    views  = m.get("views", 0)
    recirc = m.get("recirculation_rate", 0.0) or 0.0
    search = article.get("_search_views", 0)

    reach_score  = normalize_log(views, max_views)
    depth_score  = min(recirc / 0.10, 1.0)
    search_score = min(search / views, 1.0) if views > 0 else 0

    composite = (
        reach_score  * WEIGHTS["reach"] +
        depth_score  * WEIGHTS["depth"] +
        search_score * WEIGHTS["search_pull"]
    )
    return round(composite * 100)


def vs_benchmark(article):
    section = article.get("section") or "default"
    bench   = SECTION_BENCHMARKS.get(section, SECTION_BENCHMARKS["default"])
    recirc  = article.get("metrics", {}).get("recirculation_rate", 0.0) or 0.0
    if bench == 0:
        return 0
    return round((recirc - bench) / bench * 100)


# ── Terminal report ────────────────────────────────────────────────────────────

def print_report(scored_articles, days=7):
    week_end   = datetime.now().strftime("%b %d, %Y")
    week_start = (datetime.now() - timedelta(days=days)).strftime("%b %d")

    print("=" * 72)
    print("  CRONKITE SPORTS BUREAU -- WEEKLY ENGAGEMENT REPORT")
    print(f"  {week_start} - {week_end}")
    print("=" * 72)

    if not scored_articles:
        print("  No articles found.")
        return

    standout   = scored_articles[0]
    bench_diff = vs_benchmark(standout)
    bench_str  = (f"+{bench_diff}% vs section avg" if bench_diff >= 0
                  else f"{bench_diff}% vs section avg")
    recirc     = standout.get("metrics", {}).get("recirculation_rate", 0.0) or 0.0

    print(f"\n  * STANDOUT STORY  (score: {standout['_score']}/100)")
    print(f"     {standout['title']}")
    print(f"     {standout.get('metrics',{}).get('views',0):,} views  *  "
          f"{recirc:.1%} recirc  *  {bench_str}")
    print()

    print(f"  {'#':<3} {'Score':>5}  {'Views':>7}  {'Recirc':>6}  {'Section':<22}  Title")
    print(f"  {'-'*3}  {'-'*5}  {'-'*7}  {'-'*6}  {'-'*22}  {'-'*35}")

    for i, a in enumerate(scored_articles, 1):
        m       = a.get("metrics", {})
        views   = m.get("views", 0)
        recirc  = m.get("recirculation_rate", 0.0) or 0.0
        section = (a.get("section") or "-")[:22]
        title   = (a.get("title") or "")[:38]
        flag    = "*" if i == 1 else " "
        print(f"  {flag}{i:<2} {a['_score']:>5}  {views:>7,}  {recirc:>5.1%}  {section:<22}  {title}")

    print()
    avg_score   = sum(a["_score"] for a in scored_articles) / len(scored_articles)
    avg_recirc  = sum((a.get("metrics",{}).get("recirculation_rate",0) or 0) for a in scored_articles) / len(scored_articles)
    total_views = sum(a.get("metrics",{}).get("views",0) for a in scored_articles)

    print(f"  Bureau totals:  {total_views:,} views  *  "
          f"{avg_recirc:.1%} avg recirc  *  avg score {avg_score:.1f}/100")
    print("=" * 72)


# ── HTML Dashboard ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cronkite Sports Bureau &mdash; Engagement Report</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;background:#0d1117;color:#c9d1d9;height:100vh;overflow:hidden;display:flex;flex-direction:column}
header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 28px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.bureau{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#8b949e}
.report-title{font-size:20px;font-weight:700;color:#f0f6fc;margin:3px 0}
.daterange{font-size:12px;color:#8b949e}
.totals{display:flex;gap:28px}
.total{text-align:right}
.total-label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8b949e}
.total-value{font-size:22px;font-weight:800;color:#58a6ff}
.layout{display:grid;grid-template-columns:1fr 400px;flex:1;overflow:hidden}
.table-panel{overflow-y:auto;border-right:1px solid #30363d}
table{width:100%;border-collapse:collapse}
thead th{position:sticky;top:0;background:#161b22;padding:9px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8b949e;border-bottom:1px solid #30363d;z-index:1;white-space:nowrap}
tbody tr{cursor:pointer;border-bottom:1px solid #21262d;transition:background .12s}
tbody tr:hover{background:#1c2128}
tbody tr.selected{background:#1a3354 !important;border-left:3px solid #58a6ff}
td{padding:9px 12px;font-size:13px}
td.rk{color:#8b949e;font-size:11px;width:30px;padding-right:4px}
td.sc{font-weight:800;width:44px}
td.vw{color:#c9d1d9;width:62px;text-align:right}
td.rc{width:56px;text-align:right}
td.sec{color:#8b949e;font-size:11px;width:110px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:110px}
td.ttl{color:#c9d1d9;max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.right-panel{overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;background:#0d1117}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.card-label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8b949e;margin-bottom:10px}
.story-section{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8b949e;margin-bottom:5px}
.story-title{font-size:14px;font-weight:600;color:#f0f6fc;line-height:1.4;margin-bottom:12px}
.score-row{display:flex;align-items:center;gap:14px}
.score-circle{width:68px;height:68px;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;border:3px solid;flex-shrink:0}
.score-num{font-size:22px;font-weight:800;line-height:1}
.score-lbl{font-size:9px;text-transform:uppercase;letter-spacing:1px;opacity:.7}
.score-meta{flex:1}
.bench{display:inline-block;padding:3px 9px;border-radius:4px;font-size:12px;font-weight:700;margin-bottom:5px}
.bench.pos{background:#1a3f2a;color:#3fb950}
.bench.neg{background:#3d1212;color:#f85149}
.rank-text{font-size:12px;color:#8b949e}
.metric-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.metric-box{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;text-align:center}
.metric-box .lbl{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8b949e;margin-bottom:3px}
.metric-box .val{font-size:20px;font-weight:800}
.metric-box .sub{font-size:10px;color:#8b949e;margin-top:2px}
.empty{text-align:center;padding:48px 20px;color:#8b949e}
.empty h3{font-size:15px;color:#c9d1d9;margin-bottom:8px}
.empty p{font-size:12px}
</style>
</head>
<body>
<header>
  <div>
    <div class="bureau">Cronkite Sports Bureau</div>
    <div class="report-title">Weekly Engagement Report</div>
    <div class="daterange">__WEEK_START__ &ndash; __WEEK_END__</div>
  </div>
  <div class="totals">
    <div class="total"><div class="total-label">Total Views</div><div class="total-value">__TOTAL_VIEWS__</div></div>
    <div class="total"><div class="total-label">Avg Recirc</div><div class="total-value">__AVG_RECIRC__</div></div>
    <div class="total"><div class="total-label">Avg Score</div><div class="total-value">__AVG_SCORE__</div></div>
  </div>
</header>
<div class="layout">
  <div class="table-panel">
    <table>
      <thead><tr>
        <th>#</th><th>Score</th><th style="text-align:right">Views</th>
        <th style="text-align:right">Recirc</th><th>Section</th><th>Title</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <div class="right-panel" id="right">
    <div class="empty"><h3>Select a story</h3><p>Click any row to see its engagement profile and charts.</p></div>
  </div>
</div>
<script>
const DATA = __ARTICLES_JSON__;
let radar = null, scatter = null;

function col(score){return score>=60?'#3fb950':score>=40?'#d29922':'#8b949e'}
function rcol(r){return r>=8?'#3fb950':r>=4?'#d29922':'#8b949e'}

function buildTable(){
  const tb = document.getElementById('tbody');
  DATA.forEach((a,i)=>{
    const tr = document.createElement('tr');
    const c = col(a.score), rc = rcol(a.recirc);
    tr.innerHTML =
      `<td class="rk">${a.rank}</td>`+
      `<td class="sc" style="color:${c}">${a.score}</td>`+
      `<td class="vw">${a.views.toLocaleString()}</td>`+
      `<td class="rc" style="color:${rc}">${a.recirc.toFixed(1)}%</td>`+
      `<td class="sec" title="${a.section}">${a.section}</td>`+
      `<td class="ttl" title="${a.title}">${i===0?'&#9733; ':''}${a.title}</td>`;
    tr.onclick = ()=>select(i);
    tb.appendChild(tr);
  });
}

function select(idx){
  document.querySelectorAll('tbody tr').forEach((r,i)=>r.classList.toggle('selected',i===idx));
  const a = DATA[idx];
  const c = col(a.score);
  const bs = a.bench_diff>=0?'+'+a.bench_diff+'%':a.bench_diff+'%';
  const bcls = a.bench_diff>=0?'pos':'neg';

  document.getElementById('right').innerHTML =
    `<div class="card">
      <div class="story-section">${a.section}</div>
      <div class="story-title">${a.title}</div>
      <div class="score-row">
        <div class="score-circle" style="border-color:${c};color:${c}">
          <div class="score-num">${a.score}</div>
          <div class="score-lbl">score</div>
        </div>
        <div class="score-meta">
          <div class="bench ${bcls}">${bs} vs ${a.section} avg</div>
          <div class="rank-text">Rank #${a.rank} of ${DATA.length} this week</div>
        </div>
      </div>
    </div>
    <div class="metric-grid">
      <div class="metric-box">
        <div class="lbl">Reach</div>
        <div class="val" style="color:#58a6ff">${a.reach}</div>
        <div class="sub">${a.views.toLocaleString()} views</div>
      </div>
      <div class="metric-box">
        <div class="lbl">Depth</div>
        <div class="val" style="color:#3fb950">${a.depth}</div>
        <div class="sub">${a.recirc.toFixed(1)}% recirc</div>
      </div>
      <div class="metric-box">
        <div class="lbl">Search</div>
        <div class="val" style="color:#d29922">${a.search}</div>
        <div class="sub">${a.search_views} search views</div>
      </div>
    </div>
    <div class="card">
      <div class="card-label">Engagement Profile</div>
      <canvas id="radarChart" height="210"></canvas>
    </div>
    <div class="card">
      <div class="card-label">Views vs. Recirculation &mdash; All Stories This Week</div>
      <canvas id="scatterChart" height="190"></canvas>
    </div>`;

  buildRadar(a);
  buildScatter(idx);
}

function buildRadar(a){
  if(radar){radar.destroy();radar=null;}
  const ctx = document.getElementById('radarChart').getContext('2d');
  radar = new Chart(ctx,{
    type:'radar',
    data:{
      labels:['Reach','Depth','Search Pull'],
      datasets:[{
        label:'This Story',
        data:[a.reach,a.depth,a.search],
        backgroundColor:'rgba(88,166,255,0.12)',
        borderColor:'#58a6ff',
        pointBackgroundColor:'#58a6ff',
        pointBorderColor:'#0d1117',
        borderWidth:2,pointRadius:5
      }]
    },
    options:{
      responsive:true,
      plugins:{legend:{display:false}},
      scales:{r:{
        min:0,max:100,
        ticks:{display:false},
        grid:{color:'#30363d'},
        angleLines:{color:'#30363d'},
        pointLabels:{color:'#c9d1d9',font:{size:12,weight:'600'}}
      }}
    }
  });
}

function buildScatter(selIdx){
  if(scatter){scatter.destroy();scatter=null;}
  const ctx = document.getElementById('scatterChart').getContext('2d');
  const pts = DATA.map((a,i)=>({
    x: Math.log10(Math.max(a.views,1)),
    y: a.recirc,
    title: a.title,
    isSel: i===selIdx
  }));
  const medV = [...DATA].sort((a,b)=>a.views-b.views)[Math.floor(DATA.length/2)].views;
  const medR = [...DATA].sort((a,b)=>a.recirc-b.recirc)[Math.floor(DATA.length/2)].recirc;
  scatter = new Chart(ctx,{
    type:'scatter',
    data:{datasets:[{
      data:pts,
      pointRadius: pts.map(p=>p.isSel?9:5),
      pointBackgroundColor: pts.map(p=>p.isSel?'#f0f6fc':'rgba(88,166,255,0.55)'),
      pointBorderColor: pts.map(p=>p.isSel?'#58a6ff':'transparent'),
      pointBorderWidth:2
    }]},
    options:{
      responsive:true,
      plugins:{
        legend:{display:false},
        tooltip:{callbacks:{label:ctx=>{
          const p=pts[ctx.dataIndex];
          return `${p.title.substring(0,36)}: ${Math.round(Math.pow(10,p.x)).toLocaleString()} views, ${p.y.toFixed(1)}% recirc`;
        }}}
      },
      scales:{
        x:{
          title:{display:true,text:'Views (log scale)',color:'#8b949e',font:{size:11}},
          ticks:{color:'#8b949e',callback:v=>Math.round(Math.pow(10,v)).toLocaleString()},
          grid:{color:'#21262d'}
        },
        y:{
          title:{display:true,text:'Recirculation %',color:'#8b949e',font:{size:11}},
          ticks:{color:'#8b949e',callback:v=>v+'%'},
          grid:{color:'#21262d'}
        }
      }
    },
    plugins:[{
      id:'quadrants',
      afterDraw(chart){
        const{ctx,chartArea:{left,right,top,bottom},scales:{x,y}}=chart;
        const mx=x.getPixelForValue(Math.log10(medV));
        const my=y.getPixelForValue(medR);
        ctx.save();
        ctx.strokeStyle='rgba(88,166,255,0.2)';
        ctx.lineWidth=1;
        ctx.setLineDash([4,4]);
        ctx.beginPath();ctx.moveTo(mx,top);ctx.lineTo(mx,bottom);ctx.stroke();
        ctx.beginPath();ctx.moveTo(left,my);ctx.lineTo(right,my);ctx.stroke();
        ctx.setLineDash([]);
        const labels=[
          {x:right-4,y:top+12,text:'High Reach + High Depth',align:'right'},
          {x:left+4, y:top+12,text:'Low Reach + High Depth',align:'left'},
          {x:right-4,y:bottom-6,text:'High Reach + Low Depth',align:'right'},
          {x:left+4, y:bottom-6,text:'Low Reach + Low Depth',align:'left'},
        ];
        ctx.font='9px Helvetica';ctx.fillStyle='rgba(139,148,158,0.6)';
        labels.forEach(l=>{ctx.textAlign=l.align;ctx.fillText(l.text,l.x,l.y);});
        ctx.restore();
      }
    }]
  });
}

buildTable();
select(0);
</script>
</body>
</html>"""


def generate_dashboard(scored_articles, days=7):
    """Generate a self-contained HTML dashboard and save it to disk."""
    if not scored_articles:
        return None

    max_views = max(a.get("metrics",{}).get("views",0) for a in scored_articles) or 1

    articles_data = []
    for i, a in enumerate(scored_articles, 1):
        m      = a.get("metrics", {})
        views  = m.get("views", 0)
        recirc = m.get("recirculation_rate", 0.0) or 0.0
        sv     = a.get("_search_views", 0)

        reach_score  = round(normalize_log(views, max_views) * 100)
        depth_score  = round(min(recirc / 0.10, 1.0) * 100)
        search_score = round(min(sv / views, 1.0) * 100 if views > 0 else 0)

        articles_data.append({
            "rank":       i,
            "title":      (a.get("title") or "")[:80],
            "section":    a.get("section") or "--",
            "views":      views,
            "recirc":     round(recirc * 100, 2),
            "score":      a["_score"],
            "bench_diff": vs_benchmark(a),
            "reach":      reach_score,
            "depth":      depth_score,
            "search":     search_score,
            "search_views": sv,
            "url":        a.get("url", ""),
        })

    now        = datetime.now()
    week_end   = now.strftime("%b %d, %Y")
    week_start = (now - timedelta(days=days)).strftime("%b %d")
    total_views = sum(d["views"] for d in articles_data)
    avg_recirc  = sum(d["recirc"] for d in articles_data) / len(articles_data)
    avg_score   = sum(d["score"] for d in articles_data) / len(articles_data)

    html = HTML_TEMPLATE
    html = html.replace("__ARTICLES_JSON__", json.dumps(articles_data))
    html = html.replace("__WEEK_START__",    week_start)
    html = html.replace("__WEEK_END__",      week_end)
    html = html.replace("__TOTAL_VIEWS__",   f"{total_views:,}")
    html = html.replace("__AVG_RECIRC__",    f"{avg_recirc:.1f}%")
    html = html.replace("__AVG_SCORE__",     f"{avg_score:.0f}")

    filename = f"cronkite_report_{now.strftime('%Y%m%d')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  Dashboard saved: {filename}  (open in any browser)")
    return filename


# ── Author Emails ──────────────────────────────────────────────────────────────

def send_author_email(post, rank, total):
    """Send a 48-hour performance email to the article author."""
    # Get author name from Parse.ly
    author = post.get("author", "")
    if not author and post.get("authors"):
        author = post["authors"][0].get("name", "") if isinstance(post["authors"], list) else ""
    if not author:
        return False

    email_addr = AUTHOR_EMAILS.get(author)
    if not email_addr:
        return False

    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"  [email] Skipping {author} -- SMTP credentials not set")
        return False

    m          = post.get("metrics", {})
    views      = m.get("views", 0)
    recirc     = m.get("recirculation_rate", 0.0) or 0.0
    score      = post.get("_score", 0)
    bench_diff = vs_benchmark(post)
    bench_sign = "+" if bench_diff >= 0 else ""
    title      = post.get("title", "Untitled")
    section    = post.get("section") or ""
    url        = post.get("url", "#")
    first_name = author.split()[0]

    score_color = "#3fb950" if score >= 60 else "#d29922" if score >= 40 else "#8b949e"
    bench_color = "#3fb950" if bench_diff >= 0 else "#f85149"

    if recirc >= 0.08:
        context_note = "Strong depth score -- readers who found your story engaged enough to keep exploring the site."
    elif recirc >= 0.04:
        context_note = "Recirculation measures readers who clicked to a second story. Above 4% is solid."
    else:
        context_note = "Tip: stories with strong headlines and related-content links tend to drive higher recirculation."

    body = f"""
<html><body style="font-family:'Helvetica Neue',Arial,sans-serif;background:#f6f8fa;padding:24px;">
<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #e1e4e8;">

  <div style="background:#1f2937;padding:18px 24px;">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:2px;color:#9ca3af;">Cronkite Sports Bureau</div>
    <div style="font-size:17px;font-weight:700;color:#fff;margin-top:4px;">48-Hour Story Report</div>
  </div>

  <div style="padding:22px 24px;">
    <p style="color:#374151;font-size:14px;margin-bottom:6px;">Hi {first_name},</p>
    <p style="color:#374151;font-size:14px;margin-bottom:18px;">Here's how your story performed in its first 48 hours:</p>

    <div style="background:#f6f8fa;border-radius:6px;padding:14px;margin-bottom:18px;">
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;margin-bottom:4px;">{section}</div>
      <a href="{url}" style="font-size:14px;font-weight:600;color:#1f2937;text-decoration:none;">{title}</a>
    </div>

    <div style="text-align:center;margin-bottom:20px;">
      <div style="display:inline-flex;align-items:center;justify-content:center;width:76px;height:76px;border-radius:50%;border:3px solid {score_color};">
        <span style="font-size:26px;font-weight:800;color:{score_color};">{score}</span>
      </div>
      <div style="font-size:11px;color:#6b7280;margin-top:4px;">Engagement Score / 100</div>
      <div style="font-size:13px;font-weight:700;color:{bench_color};margin-top:4px;">{bench_sign}{bench_diff}% vs {section} average</div>
    </div>

    <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
      <tr style="border-bottom:1px solid #e1e4e8;">
        <td style="padding:10px 0;font-size:13px;color:#374151;">Page Views</td>
        <td style="padding:10px 0;font-size:13px;font-weight:700;color:#1f2937;text-align:right;">{views:,}</td>
      </tr>
      <tr style="border-bottom:1px solid #e1e4e8;">
        <td style="padding:10px 0;font-size:13px;color:#374151;">Recirculation Rate</td>
        <td style="padding:10px 0;font-size:13px;font-weight:700;color:#1f2937;text-align:right;">{recirc:.1%}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;font-size:13px;color:#374151;">Rank This Week</td>
        <td style="padding:10px 0;font-size:13px;font-weight:700;color:#1f2937;text-align:right;">#{rank} of {total}</td>
      </tr>
    </table>

    <div style="background:#eff6ff;border-left:3px solid #3b82f6;padding:11px 14px;border-radius:0 4px 4px 0;font-size:12px;color:#1e40af;line-height:1.5;">
      {context_note}
    </div>
  </div>

  <div style="padding:14px 24px;border-top:1px solid #e1e4e8;font-size:10px;color:#9ca3af;">
    Sent automatically by the Cronkite Sports Bureau Engagement System.
  </div>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f'Your story "{title[:50]}{"..." if len(title)>50 else ""}" -- 48hr Engagement Report'
    msg["From"]    = f"Cronkite Sports Bureau <{SMTP_EMAIL}>"
    msg["To"]      = email_addr
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, email_addr, msg.as_string())
        print(f"  Email sent: {author} <{email_addr}>")
        return True
    except Exception as e:
        print(f"  Email failed for {author}: {e}")
        return False


def send_all_author_emails(scored_articles):
    """Email authors whose stories are 24-72 hours old."""
    if not AUTHOR_EMAILS:
        print("\n  [email] Add author entries to AUTHOR_EMAILS to enable this feature.")
        return

    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print("\n  [email] Set SMTP_EMAIL and SMTP_PASSWORD env vars to send emails.")
        return

    now   = datetime.now()
    total = len(scored_articles)
    sent  = 0

    print("\nSending author emails...")
    for rank, post in enumerate(scored_articles, 1):
        pub_str = post.get("pub_date", "")
        if pub_str:
            try:
                pub = datetime.fromisoformat(pub_str.replace("Z", "")).replace(tzinfo=None)
                hours_old = (now - pub).total_seconds() / 3600
                if not (24 <= hours_old <= 72):
                    continue
            except Exception:
                pass  # Date parse failed; send anyway

        if send_author_email(post, rank, total):
            sent += 1

    print(f"  {sent} email(s) sent.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    days = 7
    print(f"Fetching last {days} days from Parse.ly...")
    posts = get_posts(days=days, limit=50)

    if not posts:
        print("No posts returned.")
        return

    print(f"  Found {len(posts)} posts.\n")
    print("Fetching referrer data (this may take a moment)...")
    for post in posts:
        post["_search_views"] = get_search_views(post.get("url", ""), days=days)

    max_views = max(p.get("metrics", {}).get("views", 0) for p in posts) or 1
    for post in posts:
        post["_score"] = score_article(post, max_views)

    scored = sorted(posts, key=lambda x: x["_score"], reverse=True)

    print_report(scored, days=days)
    generate_dashboard(scored, days=days)
    send_all_author_emails(scored)


if __name__ == "__main__":
    main()
