"""
Cronkite News Bureau — Weekly Engagement Scoring
Web: Depth 50% + Reach 30% + Retention 20%
YouTube: Reach 40% + Engagement 40% + Conversation 20%
"""
import os, json, math, datetime, smtplib
from email.mime.text import MIMEText
from collections import Counter
import requests

# ── Credentials ────────────────────────────────────────────────────────────────
PARSELY_KEY      = os.getenv("PARSELY_KEY")      or "cronkitenews.azpbs.org"
PARSELY_SECRET   = os.getenv("PARSELY_SECRET")   or "tAytVAdJCyLdFHatqOOHLVXTrdHpUm5kQusX8ZWzHoA"
YOUTUBE_API_KEY  = os.getenv("YOUTUBE_API_KEY")  or "AIzaSyB-mfuXtUnlKcBuHlTbicuoF-WF25UaN3w"
YOUTUBE_CHANNEL  = "UCO8tHWm0LQy3QWFcnZeV4CQ"
SMTP_EMAIL       = os.getenv("SMTP_EMAIL")       or ""
SMTP_PASSWORD    = os.getenv("SMTP_PASSWORD")    or ""

SCORES_FILE         = "scores.json"
YT_SCORES_FILE      = "youtube_scores.json"
YT_BASELINES_FILE   = "youtube_baselines.json"

# ── Web section config ──────────────────────────────────────────────────────────
CANONICAL_SECTIONS = {
    "Borderlands","Health","Indigenous","Money","Noticias",
    "Politics & Policy","Social Justice","Sports","Sustainability","Tech"
}
SECTION_MAP = {
    "Sport":"Sports","Indian Country":"Indigenous","Politics":"Politics & Policy",
    "Government":"Politics & Policy","Consumer":"Money","Future":"Tech","Legal":"Social Justice",
    "Longform hero image slim":None,"New Long Form":None,"Newscast":None,
    "Next Gen":None,"Editor's Picks":None,"Education":None,"Uncategorized":None,
}
def normalize_section(raw):
    raw=(raw or "").strip()
    if raw in CANONICAL_SECTIONS: return raw
    return SECTION_MAP.get(raw)

# Baselines from Dec 2024–Jul 2026 CSV (N=9,990)
SECTION_BASELINES = {
    "Borderlands":      {"log_views_mean":3.671606,"log_views_std":1.436332,"avg_min_mean":0.697908,"avg_min_std":0.611949,"ret_pct_mean":0.079513,"ret_pct_std":0.074632},
    "Health":           {"log_views_mean":3.759307,"log_views_std":1.325098,"avg_min_mean":0.760348,"avg_min_std":0.622188,"ret_pct_mean":0.079375,"ret_pct_std":0.077731},
    "Indigenous":       {"log_views_mean":3.761935,"log_views_std":1.347123,"avg_min_mean":0.765000,"avg_min_std":0.606882,"ret_pct_mean":0.078320,"ret_pct_std":0.070238},
    "Money":            {"log_views_mean":3.280083,"log_views_std":1.092896,"avg_min_mean":0.599677,"avg_min_std":0.591380,"ret_pct_mean":0.057937,"ret_pct_std":0.063694},
    "Noticias":         {"log_views_mean":3.691104,"log_views_std":1.014322,"avg_min_mean":0.711699,"avg_min_std":0.469350,"ret_pct_mean":0.124843,"ret_pct_std":0.108055},
    "Politics & Policy":{"log_views_mean":3.970215,"log_views_std":1.639747,"avg_min_mean":0.647451,"avg_min_std":0.580876,"ret_pct_mean":0.077784,"ret_pct_std":0.074398},
    "Social Justice":   {"log_views_mean":3.635902,"log_views_std":1.212057,"avg_min_mean":0.705322,"avg_min_std":0.639510,"ret_pct_mean":0.070734,"ret_pct_std":0.068064},
    "Sports":           {"log_views_mean":4.229719,"log_views_std":1.389051,"avg_min_mean":0.729208,"avg_min_std":0.500631,"ret_pct_mean":0.105318,"ret_pct_std":0.084311},
    "Sustainability":   {"log_views_mean":3.611491,"log_views_std":1.214433,"avg_min_mean":0.696243,"avg_min_std":0.612033,"ret_pct_mean":0.063010,"ret_pct_std":0.063251},
    "Tech":             {"log_views_mean":3.103329,"log_views_std":0.879452,"avg_min_mean":0.537443,"avg_min_std":0.427121,"ret_pct_mean":0.053097,"ret_pct_std":0.077217},
}
BUREAU_WIDE = {"log_views_mean":3.868346,"log_views_std":1.378027,"avg_min_mean":0.697029,"avg_min_std":0.573032,"ret_pct_mean":0.084345,"ret_pct_std":0.079605}

AUTHOR_EMAILS = {
    # "First Last": "asurite@asu.edu",
}

# ── Helpers ─────────────────────────────────────────────────────────────────────
def norm_cdf(z): return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))
def z_to_pct(value,mean,std):
    if std<=0: return 50.0
    z=max(-3.0,min(3.0,(value-mean)/std))
    return round(norm_cdf(z)*100.0,1)
def mean_std(vals):
    if len(vals)<2: return 0.0,1.0
    m=sum(vals)/len(vals)
    s=math.sqrt(sum((v-m)**2 for v in vals)/len(vals))
    return m,max(s,0.001)
def this_monday():
    today=datetime.date.today()
    return today-datetime.timedelta(days=today.weekday())

# ── Parse.ly ────────────────────────────────────────────────────────────────────
def parsely_get(endpoint,params):
    r=requests.get(f"https://api.parsely.com/v2{endpoint}",
                   params={"apikey":PARSELY_KEY,"secret":PARSELY_SECRET,"limit":50,**params})
    r.raise_for_status()
    return r.json().get("data",[])

def get_posts():
    now=datetime.datetime.utcnow()
    week_ago=now-datetime.timedelta(days=7)
    two_weeks=now-datetime.timedelta(days=14)
    dp={"pub_date_start":two_weeks.strftime("%Y-%m-%d"),"pub_date_end":week_ago.strftime("%Y-%m-%d"),
        "period_start":two_weeks.strftime("%Y-%m-%d"),"period_end":now.strftime("%Y-%m-%d")}
    combined={}
    for sort in ["views","avg_engaged","returning_visitors","mobile_views","desktop_views"]:
        for post in parsely_get("/analytics/posts",{**dp,"sort":sort}):
            url=post.get("url","")
            if not url: continue
            if url not in combined: combined[url]=post
            else:
                e=combined[url].get("metrics",{})
                for k,v in post.get("metrics",{}).items():
                    if isinstance(v,(int,float)) and v>e.get(k,0): e[k]=v
                combined[url]["metrics"]=e
    return list(combined.values())

def score_articles(posts):
    week_scored=this_monday().strftime("%Y-%m-%d")
    scored=[]
    for post in posts:
        try:
            m=post.get("metrics",{})
            views=m.get("views",0); avg_min=m.get("avg_engaged",0.0)
            visitors=m.get("visitors",0); ret_vis=m.get("returning_visitors",0)
            mob=m.get("mobile_views",0); desk=m.get("desktop_views",0)
            if views<5: continue
            meta=post.get("metadata",{})
            sec_raw=(meta.get("section") or [""])[0]
            section=normalize_section(sec_raw)
            b=SECTION_BASELINES.get(section,BUREAU_WIDE)
            display_sec=section if section else "Other"
            reach=z_to_pct(math.log(views+1),b["log_views_mean"],b["log_views_std"])
            depth=z_to_pct(avg_min,b["avg_min_mean"],b["avg_min_std"])
            ret_pct=ret_vis/visitors if visitors>0 else 0.0
            retention=z_to_pct(ret_pct,b["ret_pct_mean"],b["ret_pct_std"])
            composite=round(reach*0.30+depth*0.50+retention*0.20,1)
            mob_pct=round(mob/views*100,1) if views else 0.0
            desk_pct=round(desk/views*100,1) if views else 0.0
            tab_pct=round(max(0.0,100-mob_pct-desk_pct),1)
            pub_raw=(meta.get("pub_date") or "")[:10]
            try: pub_disp=datetime.datetime.strptime(pub_raw,"%Y-%m-%d").strftime("%b %-d, %Y")
            except: pub_disp=pub_raw
            scored.append({"url":post.get("url",""),"title":meta.get("title","(no title)"),
                "author":", ".join(meta.get("authors",["Unknown"])),"section_norm":display_sec,
                "pub_date":pub_raw,"pub_date_display":pub_disp,"week_scored":week_scored,
                "views":views,"reach":reach,"depth":depth,"returning":retention,"composite":composite,
                "mob_pct":mob_pct,"desk_pct":desk_pct,"tab_pct":tab_pct})
        except Exception as e: print(f"  Skip {post.get('url','?')}: {e}")
    scored.sort(key=lambda x:x["composite"],reverse=True)
    return scored

def load_scores():
    if not os.path.exists(SCORES_FILE): return {}
    with open(SCORES_FILE,encoding="utf-8") as f: data=json.load(f)
    return {e["url"]:e for e in data}

def save_scores(scores_by_url):
    entries=sorted(scores_by_url.values(),key=lambda x:x.get("week_scored",""),reverse=True)
    with open(SCORES_FILE,"w",encoding="utf-8") as f: json.dump(entries,f,indent=2)

# ── YouTube ─────────────────────────────────────────────────────────────────────
def yt_get(endpoint,params):
    r=requests.get(f"https://www.googleapis.com/youtube/v3/{endpoint}",
                   params={"key":YOUTUBE_API_KEY,**params})
    r.raise_for_status()
    return r.json()

def get_yt_uploads_playlist():
    data=yt_get("channels",{"part":"contentDetails","id":YOUTUBE_CHANNEL})
    return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

def fetch_yt_video_ids(playlist_id,max_results=200):
    ids=[]; page_token=None
    while len(ids)<max_results:
        params={"part":"snippet","playlistId":playlist_id,"maxResults":50}
        if page_token: params["pageToken"]=page_token
        data=yt_get("playlistItems",params)
        for item in data.get("items",[]):
            ids.append(item["snippet"]["resourceId"]["videoId"])
        page_token=data.get("nextPageToken")
        if not page_token: break
    return ids

def fetch_yt_details(video_ids):
    items=[]
    for i in range(0,len(video_ids),50):
        batch=video_ids[i:i+50]
        data=yt_get("videos",{"part":"snippet,statistics,contentDetails","id":",".join(batch)})
        items.extend(data.get("items",[]))
    return items

def compute_yt_baselines(items):
    log_views,like_rates,comment_rates=[],[],[]
    for v in items:
        stats=v.get("statistics",{})
        views=int(stats.get("viewCount",0))
        likes=int(stats.get("likeCount",0))
        comments=int(stats.get("commentCount",0))
        if views<10: continue
        log_views.append(math.log(views+1))
        like_rates.append(likes/views)
        comment_rates.append(comments/views)
    lm,ls=mean_std(log_views)
    rim,ris=mean_std(like_rates)
    cm,cs=mean_std(comment_rates)
    b={"log_views_mean":round(lm,6),"log_views_std":round(ls,6),
       "like_rate_mean":round(rim,6),"like_rate_std":round(ris,6),
       "comment_rate_mean":round(cm,6),"comment_rate_std":round(cs,6),
       "n":len(log_views)}
    print(f"  YouTube baselines (N={b['n']}): log_views {lm:.3f}±{ls:.3f} | like_rate {rim:.4f}±{ris:.4f} | comment_rate {cm:.4f}±{cs:.4f}")
    return b

def load_yt_baselines():
    """Load cached baselines or bootstrap from channel history."""
    if os.path.exists(YT_BASELINES_FILE):
        with open(YT_BASELINES_FILE) as f: return json.load(f)
    print("  No YouTube baselines found — bootstrapping from channel history…")
    playlist_id=get_yt_uploads_playlist()
    ids=fetch_yt_video_ids(playlist_id,200)
    items=fetch_yt_details(ids)
    baselines=compute_yt_baselines(items)
    with open(YT_BASELINES_FILE,"w") as f: json.dump(baselines,f,indent=2)
    print(f"  Baselines saved to {YT_BASELINES_FILE}")
    return baselines

def score_yt_videos(items,baselines):
    week_scored=this_monday().strftime("%Y-%m-%d")
    scored=[]
    for v in items:
        try:
            stats=v.get("statistics",{})
            snippet=v.get("snippet",{})
            views=int(stats.get("viewCount",0))
            likes=int(stats.get("likeCount",0))
            comments=int(stats.get("commentCount",0))
            if views<10: continue
            like_rate=likes/views
            comment_rate=comments/views
            reach=z_to_pct(math.log(views+1),baselines["log_views_mean"],baselines["log_views_std"])
            engagement=z_to_pct(like_rate,baselines["like_rate_mean"],baselines["like_rate_std"])
            conversation=z_to_pct(comment_rate,baselines["comment_rate_mean"],baselines["comment_rate_std"])
            composite=round(reach*0.40+engagement*0.40+conversation*0.20,1)
            pub_raw=snippet.get("publishedAt","")[:10]
            try: pub_disp=datetime.datetime.strptime(pub_raw,"%Y-%m-%d").strftime("%b %-d, %Y")
            except: pub_disp=pub_raw
            scored.append({
                "video_id":v["id"],
                "url":f"https://www.youtube.com/watch?v={v['id']}",
                "thumbnail":f"https://img.youtube.com/vi/{v['id']}/mqdefault.jpg",
                "title":snippet.get("title","(no title)"),
                "pub_date":pub_raw,"pub_date_display":pub_disp,"week_scored":week_scored,
                "views":views,"likes":likes,"comments":comments,
                "like_rate":round(like_rate*100,2),"comment_rate":round(comment_rate*100,2),
                "reach":reach,"engagement":engagement,"conversation":conversation,
                "composite":composite,
            })
        except Exception as e: print(f"  YT skip {v.get('id','?')}: {e}")
    scored.sort(key=lambda x:x["composite"],reverse=True)
    return scored

def load_yt_scores():
    if not os.path.exists(YT_SCORES_FILE): return {}
    with open(YT_SCORES_FILE,encoding="utf-8") as f: data=json.load(f)
    return {e["video_id"]:e for e in data}

def save_yt_scores(scores_by_id):
    entries=sorted(scores_by_id.values(),key=lambda x:x.get("week_scored",""),reverse=True)
    with open(YT_SCORES_FILE,"w",encoding="utf-8") as f: json.dump(entries,f,indent=2)

# ── Dashboard ───────────────────────────────────────────────────────────────────
def generate_dashboard(all_scores,all_yt_scores):
    # Web config
    weeks=sorted(set(s["week_scored"] for s in all_scores),reverse=True)
    sections=sorted(set(s["section_norm"] for s in all_scores))
    counts=Counter(s["week_scored"] for s in all_scores)
    default_week=next((w for w in weeks if counts[w]>=10),weeks[0] if weeks else "all")
    week_opts="".join(f'<option value="{w}">Week of {w}</option>' for w in weeks)
    sec_opts='<option value="all">All sections</option>'+"".join(f'<option value="{s}">{s}</option>' for s in sections)
    # YouTube config
    yt_weeks=sorted(set(s["week_scored"] for s in all_yt_scores),reverse=True)
    yt_counts=Counter(s["week_scored"] for s in all_yt_scores)
    yt_default=next((w for w in yt_weeks if yt_counts[w]>=3),yt_weeks[0] if yt_weeks else "all")
    yt_week_opts="".join(f'<option value="{w}">Week of {w}</option>' for w in yt_weeks)

    rows_json=json.dumps(all_scores)
    default_json=json.dumps(default_week)
    yt_rows_json=json.dumps(all_yt_scores)
    yt_default_json=json.dumps(yt_default)
    total=f"{len(all_scores):,}"
    yt_total=f"{len(all_yt_scores):,}"

    JS = """
const ROWS    = """ + rows_json + """;
const DEFAULT = """ + default_json + """;
const YT_ROWS    = """ + yt_rows_json + """;
const YT_DEFAULT = """ + yt_default_json + """;

let filtered=[], selectedUrl=null, radarChart=null, scatterChart=null;
let ytFiltered=[], ytSelectedId=null, ytRadarChart=null;
let activeTab='web';

function switchTab(tab) {
  activeTab=tab;
  document.getElementById('webTab').classList.toggle('tab-active',tab==='web');
  document.getElementById('ytTab').classList.toggle('tab-active',tab==='youtube');
  document.getElementById('webContent').style.display=tab==='web'?'contents':'none';
  document.getElementById('ytContent').style.display=tab==='youtube'?'contents':'none';
  if(tab==='youtube'&&!ytFiltered.length) ytRender();
}

// ── WEB helpers ────────────────────────────────────────────────────────────────
function cls(v)     { return v>=65?'high':v>=40?'mid':'low'; }
function pillCls(v) { return v>=65?'score-high':v>=40?'score-mid':'score-low'; }
function bar(val,c) {
  return '<div class="bar-wrap"><div class="bar"><div class="bar-fill '+c+'" style="width:'+val+'%"></div></div><span class="bar-val">'+Math.round(val)+'</span></div>';
}
function getThird(r) { return r.returning??r.discovery??50; }

function buildScatter(rows) {
  if(scatterChart){scatterChart.destroy();scatterChart=null;}
  const ctx=document.getElementById('sc'); if(!ctx) return;
  scatterChart=new Chart(ctx.getContext('2d'),{type:'scatter',
    data:{datasets:[{data:rows.map((r,i)=>({x:r.reach,y:r.depth,idx:i})),
      backgroundColor:rows.map(r=>r.composite>=65?'rgba(39,174,96,.7)':r.composite>=40?'rgba(230,126,34,.7)':'rgba(192,57,43,.7)'),
      pointRadius:5,pointHoverRadius:7}]},
    options:{responsive:true,maintainAspectRatio:false,
      onClick(e,els){if(els.length)showDetail(filtered[els[0].index]);},
      scales:{x:{min:0,max:100,title:{display:true,text:'Reach',color:'#3498db',font:{size:10}},grid:{color:'#f0f1f5'},ticks:{color:'#58595b',font:{size:10}}},
              y:{min:0,max:100,title:{display:true,text:'Depth',color:'#9b59b6',font:{size:10}},grid:{color:'#f0f1f5'},ticks:{color:'#58595b',font:{size:10}}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>filtered[ctx.dataIndex]?.title?.slice(0,38)||''}}}}});
}

function showDetail(r) {
  selectedUrl=r.url;
  document.querySelectorAll('#webBody tr').forEach(t=>t.classList.remove('selected'));
  const row=document.querySelector('#webBody tr[data-url="'+CSS.escape(r.url)+'"]');
  if(row) row.classList.add('selected');
  const c=cls(r.composite);
  const mob=r.mob_pct||0,desk=r.desk_pct||0,tab=r.tab_pct||0;
  const third=getThird(r);
  document.getElementById('webRight').innerHTML=
    '<div class="card">'+
      '<div class="story-section">'+r.section_norm+' &middot; '+(r.pub_date_display||r.pub_date)+'</div>'+
      '<div class="story-title"><a href="'+r.url+'" target="_blank">'+r.title+'</a></div>'+
      '<div class="story-meta">'+(r.author||'')+' &middot; '+(r.views||0).toLocaleString()+' views &middot; Week: '+r.week_scored+'</div>'+
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
      'Section-relative percentile (0-100) vs. Dec 2024–present baseline (N=9,990).<br><br>'+
      '<b style="color:#3498db">Reach</b> — log(views) vs. section avg<br>'+
      '<b style="color:#9b59b6">Depth</b> — Avg. Engaged Minutes vs. section avg<br>'+
      '<b style="color:#1abc9c">Retention</b> — % returning visitors vs. section avg<br><br>'+
      'Composite = Depth 50% + Reach 30% + Retention 20%'+
    '</p></div>';
  if(radarChart){radarChart.destroy();radarChart=null;}
  radarChart=new Chart(document.getElementById('rc').getContext('2d'),{type:'radar',
    data:{labels:['Reach (30%)','Depth (50%)','Retention (20%)'],datasets:[{
      data:[r.reach,r.depth,third],backgroundColor:'rgba(0,81,149,0.1)',
      borderColor:'#005195',pointBackgroundColor:'#005195',pointBorderColor:'#fff',pointBorderWidth:1.5,borderWidth:2,pointRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{r:{min:0,max:100,ticks:{display:false},grid:{color:'#e2e3ea'},angleLines:{color:'#e2e3ea'},pointLabels:{color:'#58595b',font:{size:11}}}}}});
  buildScatter(filtered);
}

function render() {
  const q=document.getElementById('webSearch').value.toLowerCase();
  const wk=document.getElementById('weekSel').value;
  const sec=document.getElementById('secSel').value;
  const srt=document.getElementById('sortSel').value;
  filtered=ROWS.filter(r=>(wk==='all'||r.week_scored===wk)&&(sec==='all'||r.section_norm===sec)&&
    (!q||r.title.toLowerCase().includes(q)||(r.author||'').toLowerCase().includes(q)||r.url.toLowerCase().includes(q)));
  filtered.sort((a,b)=>{
    if(srt==='pub_date') return b.pub_date>a.pub_date?1:-1;
    if(srt==='returning') return (getThird(b)??0)-(getThird(a)??0);
    return (b[srt]??0)-(a[srt]??0);
  });
  document.getElementById('shownCount').textContent=filtered.length.toLocaleString();
  const body=document.getElementById('webBody');
  if(!filtered.length){
    body.innerHTML='<tr><td colspan="8" style="text-align:center;padding:40px;color:#aaa">No stories match.</td></tr>';
    document.getElementById('webRight').innerHTML='<div class="detail-empty">No stories to show.</div>';
    return;
  }
  body.innerHTML=filtered.map((r,i)=>
    '<tr data-url="'+r.url+'" onclick="showDetail(filtered['+i+'])" class="'+(r.url===selectedUrl?'selected':'')+'">'+
    '<td class="rk">'+(i+1)+'</td><td class="ttl">'+r.title+'</td><td class="sec">'+r.section_norm+'</td>'+
    '<td class="vw">'+(r.views||0).toLocaleString()+'</td>'+
    '<td class="bar-cell">'+bar(r.reach,'bar-reach')+'</td>'+
    '<td class="bar-cell">'+bar(r.depth,'bar-depth')+'</td>'+
    '<td class="bar-cell">'+bar(getThird(r),'bar-discovery')+'</td>'+
    '<td class="sc"><span class="score-pill '+pillCls(r.composite)+'">'+r.composite+'</span></td></tr>'
  ).join('');
  if(!selectedUrl||!filtered.find(r=>r.url===selectedUrl)) showDetail(filtered[0]);
  else buildScatter(filtered);
}

['webSearch','weekSel','secSel','sortSel'].forEach(id=>document.getElementById(id).addEventListener('input',render));
document.querySelectorAll('th[data-col]').forEach(th=>th.addEventListener('click',()=>{document.getElementById('sortSel').value=th.dataset.col;render();}));
document.getElementById('weekSel').value=DEFAULT||'all';
render();

// ── YOUTUBE ─────────────────────────────────────────────────────────────────────
function ytShowDetail(r) {
  ytSelectedId=r.video_id;
  document.querySelectorAll('#ytBody tr').forEach(t=>t.classList.remove('selected'));
  const row=document.querySelector('#ytBody tr[data-id="'+r.video_id+'"]');
  if(row) row.classList.add('selected');
  const c=cls(r.composite);
  document.getElementById('ytRight').innerHTML=
    '<div class="card">'+
      '<img src="'+r.thumbnail+'" style="width:100%;border-radius:6px;margin-bottom:10px;object-fit:cover">'+
      '<div class="story-section">YouTube &middot; '+(r.pub_date_display||r.pub_date)+'</div>'+
      '<div class="story-title"><a href="'+r.url+'" target="_blank">'+r.title+'</a></div>'+
      '<div class="story-meta">'+(r.views||0).toLocaleString()+' views &middot; '+
        (r.likes||0).toLocaleString()+' likes &middot; Week: '+r.week_scored+'</div>'+
      '<div class="score-row">'+
        '<div class="score-circle '+c+'"><div class="sc-num">'+r.composite+'</div><div class="sc-lbl">Score</div></div>'+
        '<div class="score-breakdown">'+
          '<div class="sb-row"><span class="sb-label" style="color:#FF0000">Reach (40%)</span><div class="sb-bar"><div class="bar-fill bar-yt-reach" style="width:'+r.reach+'%"></div></div><span class="sb-val">'+r.reach+'</span></div>'+
          '<div class="sb-row"><span class="sb-label" style="color:#FF6B35">Engagement (40%)</span><div class="sb-bar"><div class="bar-fill bar-yt-eng" style="width:'+r.engagement+'%"></div></div><span class="sb-val">'+r.engagement+'</span></div>'+
          '<div class="sb-row"><span class="sb-label" style="color:#FF9E1B">Conversation (20%)</span><div class="sb-bar"><div class="bar-fill bar-yt-conv" style="width:'+r.conversation+'%"></div></div><span class="sb-val">'+r.conversation+'</span></div>'+
        '</div>'+
      '</div>'+
    '</div>'+
    '<div class="card">'+
      '<h2>Video Stats</h2>'+
      '<div class="metric-row"><span class="metric-lbl">Views</span><span class="metric-val">'+(r.views||0).toLocaleString()+'</span></div>'+
      '<div class="metric-row"><span class="metric-lbl">Likes</span><span class="metric-val">'+(r.likes||0).toLocaleString()+'</span></div>'+
      '<div class="metric-row"><span class="metric-lbl">Comments</span><span class="metric-val">'+(r.comments||0).toLocaleString()+'</span></div>'+
      '<div class="metric-row"><span class="metric-lbl">Like Rate</span><span class="metric-val">'+r.like_rate+'%</span></div>'+
      '<div class="metric-row"><span class="metric-lbl">Comment Rate</span><span class="metric-val">'+r.comment_rate+'%</span></div>'+
    '</div>'+
    '<div class="card"><h2>Pillar Breakdown</h2><div class="chart-wrap"><canvas id="ytrc"></canvas></div></div>'+
    '<div class="card"><h2>Methodology</h2><p class="method-text">'+
      'Channel-relative percentile (0-100) vs. channel historical baseline.<br><br>'+
      '<b style="color:#FF0000">Reach</b> — log(views) vs. channel avg<br>'+
      '<b style="color:#FF6B35">Engagement</b> — like rate (likes/views) vs. channel avg<br>'+
      '<b style="color:#FF9E1B">Conversation</b> — comment rate (comments/views) vs. channel avg<br><br>'+
      'Composite = Reach 40% + Engagement 40% + Conversation 20%'+
    '</p></div>';
  if(ytRadarChart){ytRadarChart.destroy();ytRadarChart=null;}
  ytRadarChart=new Chart(document.getElementById('ytrc').getContext('2d'),{type:'radar',
    data:{labels:['Reach (40%)','Engagement (40%)','Conversation (20%)'],datasets:[{
      data:[r.reach,r.engagement,r.conversation],backgroundColor:'rgba(255,0,0,0.08)',
      borderColor:'#FF0000',pointBackgroundColor:'#FF0000',pointBorderColor:'#fff',pointBorderWidth:1.5,borderWidth:2,pointRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{r:{min:0,max:100,ticks:{display:false},grid:{color:'#e2e3ea'},angleLines:{color:'#e2e3ea'},pointLabels:{color:'#58595b',font:{size:11}}}}}});
}

function ytRender() {
  const q=document.getElementById('ytSearch').value.toLowerCase();
  const wk=document.getElementById('ytWeekSel').value;
  const srt=document.getElementById('ytSortSel').value;
  ytFiltered=YT_ROWS.filter(r=>(wk==='all'||r.week_scored===wk)&&
    (!q||r.title.toLowerCase().includes(q)));
  ytFiltered.sort((a,b)=>{
    if(srt==='pub_date') return b.pub_date>a.pub_date?1:-1;
    return (b[srt]??0)-(a[srt]??0);
  });
  document.getElementById('ytShownCount').textContent=ytFiltered.length.toLocaleString();
  const body=document.getElementById('ytBody');
  if(!ytFiltered.length){
    body.innerHTML='<tr><td colspan="6" style="text-align:center;padding:40px;color:#aaa">No videos match.</td></tr>';
    document.getElementById('ytRight').innerHTML='<div class="detail-empty">No videos to show.</div>';
    return;
  }
  body.innerHTML=ytFiltered.map((r,i)=>
    '<tr data-id="'+r.video_id+'" onclick="ytShowDetail(ytFiltered['+i+'])" class="'+(r.video_id===ytSelectedId?'selected':'')+'">'+
    '<td class="rk">'+(i+1)+'</td><td class="ttl">'+r.title+'</td>'+
    '<td class="vw">'+(r.views||0).toLocaleString()+'</td>'+
    '<td class="bar-cell">'+bar(r.engagement,'bar-yt-eng')+'</td>'+
    '<td class="bar-cell">'+bar(r.conversation,'bar-yt-conv')+'</td>'+
    '<td class="sc"><span class="score-pill '+pillCls(r.composite)+'">'+r.composite+'</span></td></tr>'
  ).join('');
  if(!ytSelectedId||!ytFiltered.find(r=>r.video_id===ytSelectedId)) ytShowDetail(ytFiltered[0]);
}

['ytSearch','ytWeekSel','ytSortSel'].forEach(id=>document.getElementById(id).addEventListener('input',ytRender));
document.getElementById('ytWeekSel').value=YT_DEFAULT||'all';
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Cronkite News Bureau — Engagement Dashboard</title>
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
.tab-yt.tab-active{{color:#FF0000;border-bottom-color:#FF0000}}
.controls{{background:#fff;border-bottom:1px solid #e2e3ea;padding:9px 16px;display:flex;gap:10px;flex-wrap:wrap;flex-shrink:0}}
.controls input,.controls select{{background:#f5f6fa;border:1px solid #e2e3ea;color:#414141;padding:6px 10px;border-radius:6px;font-size:12px;outline:none}}
.controls input{{flex:1;min-width:180px}}
.controls input:focus,.controls select:focus{{border-color:#005195;background:#fff}}
.layout{{display:grid;grid-template-columns:1fr 400px;flex:1;overflow:hidden}}
.table-panel{{overflow-y:auto;border-right:1px solid #e2e3ea;background:#fff}}
.table-header{{padding:10px 14px 7px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#005195;border-bottom:1px solid #e2e3ea;display:flex;justify-content:space-between;align-items:center}}
.table-header.yt-header{{color:#FF0000}}
.pill-legend{{display:flex;gap:7px}}
.pill-legend span{{font-size:.68rem;padding:2px 7px;border-radius:99px;font-weight:600}}
.leg-reach{{background:rgba(52,152,219,.15);color:#3498db}}
.leg-depth{{background:rgba(155,89,182,.15);color:#9b59b6}}
.leg-retention{{background:rgba(26,188,156,.15);color:#1abc9c}}
.leg-yt-eng{{background:rgba(255,107,53,.15);color:#FF6B35}}
.leg-yt-conv{{background:rgba(255,158,27,.15);color:#FF9E1B}}
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
.bar-yt-reach{{background:#FF0000}}.bar-yt-eng{{background:#FF6B35}}.bar-yt-conv{{background:#FF9E1B}}
.bar-val{{font-size:10px;color:#58595b;width:22px;text-align:right}}
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
.metric-row{{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f0f1f5;font-size:12px}}
.metric-row:last-child{{border-bottom:none}}
.metric-lbl{{color:#58595b}}.metric-val{{font-weight:600;color:#414141}}
.chart-wrap{{position:relative;height:220px}}
.chart-wrap-sm{{position:relative;height:190px}}
.detail-empty{{text-align:center;padding:50px 20px;color:#aaa;font-size:12px}}
.method-text{{font-size:11px;color:#58595b;line-height:1.7}}
.method-text b{{color:#414141}}
</style>
</head>
<body>
<header>
  <div>
    <div class="bureau">Cronkite News Bureau</div>
    <div class="report-title">Audience Engagement Dashboard</div>
    <div class="daterange">Section-relative scoring &middot; Score at Day 7 &middot; Auto-generated weekly</div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <div class="totals">
      <div class="total"><div class="total-label">Web Archive</div><div class="total-value">{total}</div></div>
      <div class="total"><div class="total-label">Shown</div><div class="total-value" id="shownCount">—</div></div>
    </div>
    <span class="badge">Auto-generated</span>
  </div>
</header>
<div class="tab-bar">
  <button id="webTab" class="tab tab-active" onclick="switchTab('web')">📰 Web Stories</button>
  <button id="ytTab" class="tab tab-yt" onclick="switchTab('youtube')">▶ YouTube ({yt_total} videos)</button>
</div>
<!-- WEB CONTENT -->
<div id="webContent" style="display:contents">
  <div class="controls">
    <input id="webSearch" type="text" placeholder="Search title, author, URL…">
    <select id="weekSel"><option value="all">All weeks</option>{week_opts}</select>
    <select id="secSel">{sec_opts}</select>
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
          <th class="rk">#</th><th class="ttl">Story</th><th class="sec">Section</th>
          <th class="vw" data-col="views">Views</th>
          <th class="bar-cell">Reach</th><th class="bar-cell">Depth</th><th class="bar-cell">Retention</th>
          <th class="sc" data-col="composite">Score</th>
        </tr></thead>
        <tbody id="webBody"></tbody>
      </table>
    </div>
    <div class="right-panel" id="webRight">
      <div class="detail-empty">&#8592; Select a story to see details</div>
    </div>
  </div>
</div>
<!-- YOUTUBE CONTENT -->
<div id="ytContent" style="display:none">
  <div class="controls">
    <input id="ytSearch" type="text" placeholder="Search video title…">
    <select id="ytWeekSel"><option value="all">All weeks</option>{yt_week_opts}</select>
    <select id="ytSortSel">
      <option value="composite">Sort: Score</option>
      <option value="reach">Sort: Reach</option>
      <option value="engagement">Sort: Engagement</option>
      <option value="conversation">Sort: Conversation</option>
      <option value="views">Sort: Views</option>
      <option value="pub_date">Sort: Newest</option>
    </select>
  </div>
  <div class="layout">
    <div class="table-panel">
      <div class="table-header yt-header">Video Rankings
        <div class="pill-legend">
          <span class="leg-yt-eng">Engagement</span>
          <span class="leg-yt-conv">Conversation</span>
        </div>
      </div>
      <table>
        <thead><tr>
          <th class="rk">#</th><th class="ttl">Video</th>
          <th class="vw" data-col="views">Views</th>
          <th class="bar-cell">Engagement</th>
          <th class="bar-cell">Conversation</th>
          <th class="sc" data-col="composite">Score</th>
        </tr></thead>
        <tbody id="ytBody"></tbody>
      </table>
    </div>
    <div class="right-panel" id="ytRight">
      <div class="detail-empty">&#8592; Select a video to see details</div>
    </div>
  </div>
</div>
<script>{JS}</script>
</body>
</html>"""

    filename=f"cronkite_report_{datetime.date.today().strftime('%Y-%m-%d')}.html"
    with open(filename,"w",encoding="utf-8") as f: f.write(html)
    print(f"Dashboard → {filename}")
    return filename

# ── Email ───────────────────────────────────────────────────────────────────────
def send_email(to_addr,subject,body_html):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"  (SMTP not configured — skipping {to_addr})"); return
    msg=MIMEText(body_html,"html"); msg["Subject"]=subject; msg["From"]=SMTP_EMAIL; msg["To"]=to_addr
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(SMTP_EMAIL,SMTP_PASSWORD); s.sendmail(SMTP_EMAIL,to_addr,msg.as_string())
        print(f"  Email sent → {to_addr}")
    except Exception as e: print(f"  Email failed ({to_addr}): {e}")

def send_all_author_emails(scored):
    for story in scored:
        author=story.get("author",""); email=AUTHOR_EMAILS.get(author)
        if not email: continue
        subject=f"Your story engagement score — {story['composite']}/100"
        body=f"""<p>Hi {author.split()[0] if author else 'there'},</p>
<p>Here's how your recent story performed:</p>
<table style="border-collapse:collapse;font-family:sans-serif">
  <tr><td style="padding:4px 12px 4px 0"><b>Story</b></td><td><a href="{story['url']}">{story['title']}</a></td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Score</b></td><td><b>{story['composite']}/100</b></td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Reach (30%)</b></td><td>{story['reach']}/100</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Depth (50%)</b></td><td>{story['depth']}/100</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Retention (20%)</b></td><td>{story['returning']}/100</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Views</b></td><td>{story['views']:,}</td></tr>
  <tr><td style="padding:4px 12px 4px 0"><b>Mobile / Desktop</b></td><td>{story['mob_pct']}% / {story['desk_pct']}%</td></tr>
</table>
<p style="margin-top:12px;color:#666;font-size:.9em">Scores are section-relative vs. <em>{story['section_norm']}</em> historical average.</p>"""
        send_email(email,subject,body)

# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    # --- Web ---
    print("Fetching from Parse.ly…")
    posts=get_posts(); print(f"  {len(posts)} posts")
    print("Scoring web stories…")
    new_scored=score_articles(posts); print(f"  {len(new_scored)} scored")
    for s in new_scored[:3]: print(f"    [{s['composite']}] {s['title'][:60]}")
    print("Updating web archive…")
    archive=load_scores()
    added=sum(1 for s in new_scored if s["url"] not in archive)
    for s in new_scored:
        if s["url"] not in archive: archive[s["url"]]=s
    save_scores(archive); print(f"  +{added} new ({len(archive)} total)")
    # --- YouTube ---
    print("Loading YouTube baselines…")
    yt_baselines=load_yt_baselines()
    print("Fetching recent YouTube videos…")
    playlist_id=get_yt_uploads_playlist()
    yt_ids=fetch_yt_video_ids(playlist_id,50)
    yt_items=fetch_yt_details(yt_ids)
    print(f"  {len(yt_items)} videos fetched")
    print("Scoring YouTube videos…")
    new_yt=score_yt_videos(yt_items,yt_baselines); print(f"  {len(new_yt)} scored")
    for v in new_yt[:3]: print(f"    [{v['composite']}] {v['title'][:60]}")
    print("Updating YouTube archive…")
    yt_archive=load_yt_scores()
    yt_added=sum(1 for v in new_yt if v["video_id"] not in yt_archive)
    for v in new_yt:
        yt_archive[v["video_id"]]=v  # always update (stats change over time)
    save_yt_scores(yt_archive); print(f"  +{yt_added} new ({len(yt_archive)} total)")
    # --- Dashboard ---
    print("Generating dashboard…")
    generate_dashboard(list(archive.values()),list(yt_archive.values()))
    # --- Emails ---
    print("Sending emails…")
    send_all_author_emails(new_scored)
    print("Done.")

if __name__=="__main__":
    main()
