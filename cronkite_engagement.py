"""
Cronkite Sports Bureau — Weekly Engagement Scoring
Weights: Depth 50%, Reach 30%, Discovery 20%
Scores stories published 7–14 days ago (all have had ≥1 week to accumulate traffic).
week_scored is snapped to the Monday of the week the script runs.
"""

import os, json, math, datetime, smtplib
from email.mime.text import MIMEText
import requests

# ── Credentials (set as GitHub Actions secrets) ──────────────────────────────
PARSELY_KEY    = os.getenv("PARSELY_KEY")    or "cronkitenews.azpbs.org"
PARSELY_SECRET = os.getenv("PARSELY_SECRET") or "tAytVAdJCyLdFHatqOOHLVXTrdHpUm5kQusX8ZWzHoA"
SMTP_EMAIL     = os.getenv("SMTP_EMAIL")     or ""
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD")  or ""

SCORES_FILE = "scores.json"

# ── Official Cronkite News sections ──────────────────────────────────────────
CANONICAL_SECTIONS = {
    "Borderlands", "Health", "Indigenous", "Money", "Noticias",
    "Politics & Policy", "Social Justice", "Sports", "Sustainability", "Tech"
}

# Map legacy/messy Parse.ly section names → canonical
SECTION_MAP = {
    # Direct renames
    "Sport":          "Sports",
    "Indian Country": "Indigenous",
    "Politics":       "Politics & Policy",
    # Same-beat merges
    "Government":     "Politics & Policy",
    "Consumer":       "Money",
    "Future":         "Tech",
    "Legal":          "Social Justice",
    # Layout/format types → None (fall back to BUREAU_WIDE)
    "Longform hero image slim": None,
    "New Long Form":  None,
    "Newscast":       None,
    "Next Gen":       None,
    "Editor's Picks": None,
    "Education":      None,
    "Uncategorized":  None,
}

def normalize_section(raw):
    raw = (raw or "").strip()
    if raw in CANONICAL_SECTIONS:
        return raw
    return SECTION_MAP.get(raw)  # None → BUREAU_WIDE fallback

# ── Per-section baselines (Dec 2024–Jul 2026, canonical sections, N=9 483) ───
SECTION_BASELINES = {
    "Borderlands":      {"log_views_mean": 3.671606, "log_views_std": 1.436332, "avg_min_mean": 0.697908, "avg_min_std": 0.611949, "search_pct_mean": 0.460599, "search_pct_std": 0.210653},
    "Health":           {"log_views_mean": 3.759307, "log_views_std": 1.325098, "avg_min_mean": 0.760348, "avg_min_std": 0.622188, "search_pct_mean": 0.430614, "search_pct_std": 0.219331},
    "Indigenous":       {"log_views_mean": 3.761935, "log_views_std": 1.347123, "avg_min_mean": 0.765000, "avg_min_std": 0.606882, "search_pct_mean": 0.434136, "search_pct_std": 0.202614},
    "Money":            {"log_views_mean": 3.280083, "log_views_std": 1.092896, "avg_min_mean": 0.599677, "avg_min_std": 0.591380, "search_pct_mean": 0.463257, "search_pct_std": 0.216778},
    "Noticias":         {"log_views_mean": 3.691104, "log_views_std": 1.014322, "avg_min_mean": 0.711699, "avg_min_std": 0.469350, "search_pct_mean": 0.512309, "search_pct_std": 0.258930},
    "Politics & Policy":{"log_views_mean": 3.970215, "log_views_std": 1.639747, "avg_min_mean": 0.647451, "avg_min_std": 0.580876, "search_pct_mean": 0.429302, "search_pct_std": 0.209634},
    "Social Justice":   {"log_views_mean": 3.635902, "log_views_std": 1.212057, "avg_min_mean": 0.705322, "avg_min_std": 0.639510, "search_pct_mean": 0.456853, "search_pct_std": 0.208976},
    "Sports":           {"log_views_mean": 4.229719, "log_views_std": 1.389051, "avg_min_mean": 0.729208, "avg_min_std": 0.500631, "search_pct_mean": 0.490636, "search_pct_std": 0.211517},
    "Sustainability":   {"log_views_mean": 3.611491, "log_views_std": 1.214433, "avg_min_mean": 0.696243, "avg_min_std": 0.612033, "search_pct_mean": 0.438929, "search_pct_std": 0.214009},
    "Tech":             {"log_views_mean": 3.103329, "log_views_std": 0.879452, "avg_min_mean": 0.537443, "avg_min_std": 0.427121, "search_pct_mean": 0.522230, "search_pct_std": 0.215371},
}
BUREAU_WIDE = {
    "log_views_mean": 3.868346, "log_views_std": 1.378027,
    "avg_min_mean":   0.697029, "avg_min_std":   0.573032,
    "search_pct_mean":0.462767, "search_pct_std":0.215110,
}

# ── Author email map (add bureau staff here) ──────────────────────────────────
AUTHOR_EMAILS = {
    # "First Last": "asurite@asu.edu",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def z_to_pct(value, mean, std):
    if std <= 0:
        return 50.0
    z = max(-3.0, min(3.0, (value - mean) / std))
    return round(norm_cdf(z) * 100.0, 1)

def this_monday():
    """Return the Monday of the current week (date object)."""
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())

# ── Parse.ly API ──────────────────────────────────────────────────────────────
def parsely_get(endpoint, params):
    url = f"https://api.parsely.com/v2{endpoint}"
    r = requests.get(url, params={"apikey": PARSELY_KEY, "secret": PARSELY_SECRET,
                                   "limit": 50, **params})
    r.raise_for_status()
    return r.json().get("data", [])

def get_posts():
    now       = datetime.datetime.utcnow()
    week_ago  = now - datetime.timedelta(days=7)
    two_weeks = now - datetime.timedelta(days=14)
    date_params = {
        "pub_date_start": two_weeks.strftime("%Y-%m-%d"),
        "pub_date_end":   week_ago.strftime("%Y-%m-%d"),
        "period_start":   two_weeks.strftime("%Y-%m-%d"),
        "period_end":     now.strftime("%Y-%m-%d"),
    }

    combined = {}
    for sort_key in ["views", "avg_engaged", "search_refs", "mobile_views", "desktop_views"]:
        for post in parsely_get("/analytics/posts", {**date_params, "sort": sort_key}):
            url = post.get("url", "")
            if url and url not in combined:
                combined[url] = post
            elif url:
                # Merge: keep the higher value for each numeric field
                for field in ["metrics"]:
                    existing = combined[url].get("metrics", {})
                    incoming = post.get("metrics", {})
                    for k, v in incoming.items():
                        if isinstance(v, (int, float)) and v > existing.get(k, 0):
                            existing[k] = v
                    combined[url]["metrics"] = existing

    return list(combined.values())

# ── Scoring ───────────────────────────────────────────────────────────────────
def score_articles(posts):
    monday = this_monday()
    week_scored = monday.strftime("%Y-%m-%d")

    scored = []
    for post in posts:
        try:
            metrics = post.get("metrics", {})
            views      = metrics.get("views", 0)
            avg_min    = metrics.get("avg_engaged", 0.0)
            search_ref = metrics.get("search_refs", 0)
            mob        = metrics.get("mobile_views", 0)
            desk       = metrics.get("desktop_views", 0)

            if views < 5:
                continue

            meta       = post.get("metadata", {})
            sec_raw    = (meta.get("section") or [""])[0]
            section    = normalize_section(sec_raw)      # canonical name or None
            b          = SECTION_BASELINES.get(section, BUREAU_WIDE)
            display_sec = section if section else "Other"

            reach     = z_to_pct(math.log(views + 1), b["log_views_mean"], b["log_views_std"])
            depth     = z_to_pct(avg_min,              b["avg_min_mean"],   b["avg_min_std"])
            discovery = z_to_pct(search_ref / views,   b["search_pct_mean"],b["search_pct_std"])
            composite = round(reach * 0.30 + depth * 0.50 + discovery * 0.20, 1)

            mob_pct   = round(mob  / views * 100, 1) if views else 0.0
            desk_pct  = round(desk / views * 100, 1) if views else 0.0
            tab_pct   = round(max(0.0, 100 - mob_pct - desk_pct), 1)

            pub_raw   = (meta.get("pub_date") or "")[:10]
            try:
                pub_disp = datetime.datetime.strptime(pub_raw, "%Y-%m-%d").strftime("%b %-d, %Y")
            except Exception:
                pub_disp = pub_raw

            scored.append({
                "url":              post.get("url", ""),
                "title":            meta.get("title", "(no title)"),
                "author":           ", ".join(meta.get("authors", ["Unknown"])),
                "section_norm":     display_sec,
                "pub_date":         pub_raw,
                "pub_date_display": pub_disp,
                "week_scored":      week_scored,
                "views":            views,
                "reach":            reach,
                "depth":            depth,
                "discovery":        discovery,
                "composite":        composite,
                "depth_label":      "Avg. Engaged Minutes",
                "mob_pct":          mob_pct,
                "desk_pct":         desk_pct,
                "tab_pct":          tab_pct,
            })
        except Exception as e:
            print(f"  Skipping {post.get('url','?')}: {e}")

    scored.sort(key=lambda x: x["composite"], reverse=True)
    return scored

# ── Archive ───────────────────────────────────────────────────────────────────
def load_scores():
    if not os.path.exists(SCORES_FILE):
        return {}
    with open(SCORES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {entry["url"]: entry for entry in data}

def save_scores(scores_by_url):
    entries = sorted(scores_by_url.values(), key=lambda x: x.get("week_scored", ""), reverse=True)
    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)

# ── Dashboard ─────────────────────────────────────────────────────────────────
def generate_dashboard(all_scores):
    weeks = sorted(set(s["week_scored"] for s in all_scores), reverse=True)
    sections = sorted(set(s["section_norm"] for s in all_scores))

    week_opts = '<option value="all">All weeks</option>' + "".join(
        f'<option value="{w}">Week of {w}</option>' for w in weeks
    )
    sec_opts = '<option value="all">All sections</option>' + "".join(
        f'<option value="{s}">{s}</option>' for s in sections
    )

    rows_json = json.dumps(all_scores)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cronkite Engagement Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f5f5f5; color: #222; }}
  header {{ background: #8C1D40; color: #fff; padding: 18px 28px; display: flex; align-items: center; gap: 16px; }}
  header h1 {{ font-size: 1.4rem; font-weight: 700; }}
  header .sub {{ font-size: 0.85rem; opacity: 0.8; margin-top: 2px; }}
  .controls {{ background: #fff; padding: 14px 28px; display: flex; flex-wrap: wrap; gap: 10px; border-bottom: 1px solid #ddd; }}
  .controls input, .controls select {{
    padding: 7px 12px; border: 1px solid #ccc; border-radius: 6px;
    font-size: 0.9rem; outline: none;
  }}
  .controls input {{ flex: 1; min-width: 200px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 0.88rem; }}
  th {{ background: #8C1D40; color: #fff; padding: 10px 14px; text-align: left; position: sticky; top: 0; cursor: pointer; user-select: none; white-space: nowrap; }}
  th:hover {{ background: #a0234d; }}
  td {{ padding: 9px 14px; border-bottom: 1px solid #eee; vertical-align: top; }}
  tr:hover td {{ background: #fdf5f7; }}
  .score-chip {{
    display: inline-block; padding: 3px 10px; border-radius: 20px;
    font-weight: 700; font-size: 0.82rem; color: #fff;
  }}
  .score-high   {{ background: #2e7d32; }}
  .score-mid    {{ background: #f57c00; }}
  .score-low    {{ background: #c62828; }}
  .pill {{ display: inline-block; background: #f0f0f0; border-radius: 4px; padding: 1px 7px; font-size: 0.78rem; margin-top: 2px; }}
  .device-bar {{ display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin-top: 4px; }}
  .device-bar .mob  {{ background: #8C1D40; }}
  .device-bar .desk {{ background: #FFC627; }}
  .device-bar .tab  {{ background: #bbb; }}
  .device-labels {{ font-size: 0.72rem; color: #666; margin-top: 2px; }}
  .title-link {{ color: #8C1D40; text-decoration: none; font-weight: 600; }}
  .title-link:hover {{ text-decoration: underline; }}
  #count {{ padding: 10px 28px; color: #666; font-size: 0.85rem; background: #f5f5f5; }}
  .no-results {{ text-align: center; padding: 40px; color: #888; }}
</style>
</head>
<body>
<header>
  <div>
    <div class="sub">Cronkite News Bureau</div>
    <h1>Audience Engagement Dashboard</h1>
  </div>
</header>
<div class="controls">
  <input  id="search"   type="text"   placeholder="Search title, author, URL…">
  <select id="weekSel">{week_opts}</select>
  <select id="secSel">{sec_opts}</select>
  <select id="sortSel">
    <option value="composite">Sort: Composite</option>
    <option value="reach">Sort: Reach</option>
    <option value="depth">Sort: Depth</option>
    <option value="discovery">Sort: Discovery</option>
    <option value="views">Sort: Views</option>
    <option value="pub_date">Sort: Publish Date</option>
  </select>
</div>
<div id="count"></div>
<table id="tbl">
  <thead>
    <tr>
      <th>Story</th>
      <th data-col="composite">Score ▾</th>
      <th data-col="reach">Reach</th>
      <th data-col="depth">Depth</th>
      <th data-col="discovery">Discovery</th>
      <th>Views</th>
      <th>Device Split</th>
      <th>Published</th>
      <th>Week Scored</th>
    </tr>
  </thead>
  <tbody id="body"></tbody>
</table>

<script>
const ROWS = {rows_json};

function chip(val) {{
  const cls = val >= 70 ? 'score-high' : val >= 40 ? 'score-mid' : 'score-low';
  return `<span class="score-chip ${{cls}}">${{val}}</span>`;
}}

function render() {{
  const q   = document.getElementById('search').value.toLowerCase();
  const wk  = document.getElementById('weekSel').value;
  const sec = document.getElementById('secSel').value;
  const srt = document.getElementById('sortSel').value;

  let rows = ROWS.filter(r =>
    (wk  === 'all' || r.week_scored    === wk)  &&
    (sec === 'all' || r.section_norm   === sec) &&
    (!q  || r.title.toLowerCase().includes(q)  ||
            (r.author||'').toLowerCase().includes(q) ||
            r.url.toLowerCase().includes(q))
  );

  rows.sort((a, b) => (b[srt] ?? 0) > (a[srt] ?? 0) ? 1 : -1);

  document.getElementById('count').textContent =
    `${{rows.length}} stor${{rows.length === 1 ? 'y' : 'ies'}} shown`;

  const body = document.getElementById('body');
  if (!rows.length) {{
    body.innerHTML = '<tr><td colspan="9" class="no-results">No stories match your filters.</td></tr>';
    return;
  }}

  body.innerHTML = rows.map(r => {{
    const mobW  = r.mob_pct  || 0;
    const deskW = r.desk_pct || 0;
    const tabW  = r.tab_pct  || 0;
    return `<tr>
      <td>
        <a class="title-link" href="${{r.url}}" target="_blank">${{r.title}}</a><br>
        <span class="pill">${{r.section_norm}}</span>
        ${{r.author ? `<span class="pill">${{r.author}}</span>` : ''}}
      </td>
      <td>${{chip(r.composite)}}</td>
      <td>${{chip(r.reach)}}</td>
      <td>${{chip(r.depth)}}</td>
      <td>${{chip(r.discovery)}}</td>
      <td>${{(r.views||0).toLocaleString()}}</td>
      <td>
        <div class="device-bar">
          <div class="mob"  style="width:${{mobW}}%"></div>
          <div class="desk" style="width:${{deskW}}%"></div>
          <div class="tab"  style="width:${{tabW}}%"></div>
        </div>
        <div class="device-labels">
          📱${{mobW}}% 🖥${{deskW}}% 📋${{tabW}}%
        </div>
      </td>
      <td>${{r.pub_date_display || r.pub_date}}</td>
      <td>${{r.week_scored}}</td>
    </tr>`;
  }}).join('');
}}

['search','weekSel','secSel','sortSel'].forEach(id =>
  document.getElementById(id).addEventListener('input', render)
);

// Column-header sort
document.querySelectorAll('th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    document.getElementById('sortSel').value = th.dataset.col;
    render();
  }});
}});

render();
</script>
</body>
</html>"""

    filename = f"cronkite_report_{datetime.date.today().strftime('%Y-%m-%d')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard written → {filename}")
    return filename

# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(to_addr, subject, body_html):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"  (SMTP not configured — skipping email to {to_addr})")
        return
    msg = MIMEText(body_html, "html")
    msg["Subject"] = subject
    msg["From"]    = SMTP_EMAIL
    msg["To"]      = to_addr
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_EMAIL, SMTP_PASSWORD)
            s.sendmail(SMTP_EMAIL, to_addr, msg.as_string())
        print(f"  Email sent → {to_addr}")
    except Exception as e:
        print(f"  Email failed ({to_addr}): {e}")

def send_all_author_emails(scored):
    for story in scored:
        author = story.get("author", "")
        email  = AUTHOR_EMAILS.get(author)
        if not email:
            continue
        subject = f"Your story engagement score this week — {story['composite']}/100"
        body = f"""
<p>Hi {author.split()[0] if author else 'there'},</p>
<p>Here's how your recent story performed on Cronkite News:</p>
<table style="border-collapse:collapse;font-family:sans-serif">
  <tr><td style="padding:4px 12px 4px 0"><b>Story</b></td><td><a href="{story['url']}">{story['title']}</a></td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Published</b></td><td>{story['pub_date_display']}</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Composite Score</b></td><td><b>{story['composite']}/100</b></td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Reach (30%)</b></td><td>{story['reach']}/100</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Depth (50%)</b></td><td>{story['depth']}/100</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Discovery (20%)</b></td><td>{story['discovery']}/100</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Views</b></td><td>{story['views']:,}</td></tr>
</table>
<p style="margin-top:12px;color:#666;font-size:0.9em">
  Scores are section-relative — your story is compared to others in <em>{story['section_norm']}</em>.
</p>
"""
        send_email(email, subject, body)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Fetching posts from Parse.ly…")
    posts = get_posts()
    print(f"  {len(posts)} unique posts retrieved")

    print("Scoring…")
    new_scored = score_articles(posts)
    print(f"  {len(new_scored)} stories scored")
    for s in new_scored[:5]:
        print(f"    [{s['composite']}] {s['title'][:60]}")

    print("Updating archive…")
    archive = load_scores()
    added = 0
    for story in new_scored:
        if story["url"] not in archive:
            archive[story["url"]] = story
            added += 1
    save_scores(archive)
    print(f"  {added} new stories added ({len(archive)} total in archive)")

    print("Generating dashboard…")
    all_scores = list(archive.values())
    generate_dashboard(all_scores)

    print("Sending author emails…")
    send_all_author_emails(new_scored)

    print("Done.")

if __name__ == "__main__":
    main()
