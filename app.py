import os
import hmac
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="VasuDev Cricket AI", page_icon="🐎", layout="wide", initial_sidebar_state="expanded")

# No HTML header is used anywhere in this file.
st.markdown("""
<style>
.stApp{background:linear-gradient(180deg,#061426 0%,#081c35 100%);color:#f8fafc}
.block-container{max-width:1600px;padding-top:1.5rem!important}
.card,.session-box{background:rgba(15,34,60,.95);padding:18px;border-radius:16px;border:1px solid #2d4d72;box-shadow:0 8px 24px rgba(0,0,0,.18)}
.session-box{text-align:center;border:2px solid #4777a8;margin:14px 0}
.yes{background:#07552f;border:2px solid #20c77a;padding:20px;border-radius:16px;text-align:center}
.no{background:#651b1b;border:2px solid #ef5350;padding:20px;border-radius:16px;text-align:center}
.small{color:#bed0e5!important;font-size:13px}h1,h2,h3,h4,p,label{color:#f8fafc!important}
[data-testid="stSidebar"]{background:#071a2e}
[data-testid="stStatusWidget"],[data-testid="stDecoration"]{display:none!important}
div.stButton>button{min-height:42px;border-radius:11px;font-weight:700;background:#12365f;color:white;border:1px solid #3c6795}
</style>
""", unsafe_allow_html=True)

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()
if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

# Streamlit session_state survives normal widget reruns. Nothing in this file resets it.
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("VasuDev Cricket AI")
    st.caption("Private access")
    entered = st.text_input("Password", type="password", key="auth_input")
    if st.button("Unlock", key="unlock"):
        if hmac.compare_digest(entered, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("auth_input", None)
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

BASE = Path(".")
DBS = {"IPL": BASE/"cricket_history.db", "Men's Big Bash League": BASE/"bbl_history.db", "Women's Big Bash League": BASE/"wbbl_history.db"}
URLS = {"Men's Big Bash League":"https://cricsheet.org/downloads/bbl_json.zip", "Women's Big Bash League":"https://cricsheet.org/downloads/wbb_json.zip"}
LEAGUES = list(DBS)


def ball_position(value):
    try:
        a,b = str(value).split(".",1); return int(a)*6+int(b)
    except Exception: return np.nan


def make_db(path, league, archive_path):
    tmp = path.with_suffix(".tmp")
    if tmp.exists(): tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.execute("CREATE TABLE matches(match_id TEXT PRIMARY KEY,venue TEXT,winner TEXT,league TEXT)")
        con.execute("CREATE TABLE deliveries(id INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT,innings_no INTEGER,batting_team TEXT,bowling_team TEXT,over_no INTEGER,ball_no TEXT,runs INTEGER,wickets INTEGER,league TEXT)")
        matches, deliveries = [], []
        with zipfile.ZipFile(archive_path) as z:
            for name in (n for n in z.namelist() if n.endswith(".json")):
                try:
                    data=json.loads(z.read(name)); info=data.get("info",{}); teams=info.get("teams",[])
                    if len(teams)<2: continue
                    out=info.get("outcome",{}) or {}; winner=out.get("winner","") or out.get("eliminator","") or ""
                    mid=Path(name).stem; matches.append((mid,info.get("venue","") or "",str(winner),league))
                    for inn_no,inn in enumerate(data.get("innings",[]),1):
                        if inn.get("super_over"): continue
                        bat=inn.get("team",""); bowl=next((x for x in teams if x!=bat),"")
                        for over in inn.get("overs",[]):
                            over_no=int(over.get("over",0))
                            for d in over.get("deliveries",[]):
                                raw=d.get("actual_delivery")
                                try: pos,ball=ball_position(raw),str(raw)
                                except Exception: pos=np.nan; ball=""
                                if pd.isna(pos):
                                    try: ball=f"{over_no}.{int(d.get('ball'))}"
                                    except Exception: continue
                                deliveries.append((mid,inn_no,bat,bowl,over_no,ball,int((d.get("runs") or {}).get("total",0) or 0),len(d.get("wickets") or []),league))
                except Exception: continue
        con.executemany("INSERT OR REPLACE INTO matches VALUES(?,?,?,?)",matches)
        con.executemany("INSERT INTO deliveries(match_id,innings_no,batting_team,bowling_team,over_no,ball_no,runs,wickets,league) VALUES(?,?,?,?,?,?,?,?,?)",deliveries)
        con.execute("CREATE INDEX dl ON deliveries(league,innings_no,ball_no)"); con.commit()
    finally: con.close()
    tmp.replace(path)


def ensure_db(league):
    path=DBS[league]
    if path.exists(): return path
    tmp=path.with_suffix(".building")
    with tempfile.TemporaryDirectory() as td:
        archive=Path(td)/"data.zip"; urllib.request.urlretrieve(URLS[league],archive); make_db(tmp,league,archive)
    tmp.replace(path); return path


@st.cache_resource(show_spinner=False)
def readonly(path):
    p=Path(path)
    if not p.exists(): return None
    c=sqlite3.connect(f"file:{p.resolve()}?mode=ro",uri=True,check_same_thread=False,timeout=30); c.row_factory=sqlite3.Row; return c


@st.cache_data(show_spinner=False,max_entries=6)
def history_data(league,path):
    q="""SELECT d.match_id,d.innings_no,d.batting_team,d.bowling_team,d.ball_no,d.runs,d.wickets,m.venue,m.winner FROM deliveries d JOIN matches m ON m.match_id=d.match_id WHERE d.league=? ORDER BY d.match_id,d.innings_no,d.id"""
    with closing(sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro",uri=True,check_same_thread=False,timeout=30)) as c: df=pd.read_sql_query(q,c,params=(league,))
    if df.empty:return df
    df["ball_pos"]=df.ball_no.map(ball_position); df=df.dropna(subset=["ball_pos"]).copy(); df["ball_pos"]=df.ball_pos.astype(int)
    df["runs"]=pd.to_numeric(df.runs,errors="coerce").fillna(0); df["wickets"]=pd.to_numeric(df.wickets,errors="coerce").fillna(0)
    for col in ["batting_team","bowling_team","venue","winner"]: df[col]=df[col].fillna("").astype(str)
    g=df.groupby(["match_id","innings_no"],sort=False); df["score"]=g.runs.cumsum(); df["wk"]=g.wickets.cumsum(); df["rr"]=np.where(df.ball_pos>0,df.score/df.ball_pos*6,0)
    df["last6"]=g.runs.rolling(6,min_periods=1).sum().reset_index(level=[0,1],drop=True).to_numpy()
    df["last12"]=g.runs.rolling(12,min_periods=1).sum().reset_index(level=[0,1],drop=True).to_numpy()
    return df


def over_ball(b):
    b=int(b); return "0.0" if b<=0 else f"{(b-1)//6}.{((b-1)%6)+1}"


def to_balls(v):
    a,b=str(v).split("."); return int(a)*6+int(b)


def init_state():
    defaults={"runs":0,"wickets":0,"balls":0,"started":False,"undo":[],"last":"","session_over":6,"target":0,"session_low":0,"session_high":1,"session_expected":0.0,"manual":False}
    for k,v in defaults.items(): st.session_state.setdefault(k,v)


def snapshot(): st.session_state.undo.append((st.session_state.runs,st.session_state.wickets,st.session_state.balls,st.session_state.last))


def event(runs=0,wicket=False,legal=True,label=""):
    snapshot(); st.session_state.runs+=runs; st.session_state.wickets=min(10,st.session_state.wickets+int(wicket)); st.session_state.balls+=int(legal); st.session_state.last=label; st.session_state.started=True


def undo():
    if st.session_state.undo:
        r,w,b,l=st.session_state.undo.pop(); st.session_state.runs=r; st.session_state.wickets=w; st.session_state.balls=b; st.session_state.last="Undo"


def auto_line(df,inn,balls,runs,wickets,session_over,bat,bowl,venue):
    end=int(session_over)*6
    if balls>=end or df.empty:return runs,runs+1,float(runs),0
    x=df[(df.innings_no==inn)&(df.ball_pos.between(max(1,balls-2),balls+2))&(df.ball_pos<=end)].copy()
    x=x[(x.score-runs).abs()<=30&(x.wk-wickets).abs()<=3] if not x.empty else x
    if x.empty:return runs,runs+1,float(runs),0
    x["weight"]=np.exp(-(x.score-runs).abs()/10)*np.exp(-(x.wk-wickets).abs()/1.7)*np.exp(-(x.ball_pos-balls).abs()/2.5)
    x=x.sort_values("weight",ascending=False).head(1000); grouped=df.groupby(["match_id","innings_no"],sort=False); vals=[]; weights=[]
    for _,row in x.iterrows():
        try: m=grouped.get_group((row.match_id,int(row.innings_no))); f=m[m.ball_pos<=end]
        except KeyError: continue
        if not f.empty: vals.append(float(f.iloc[-1].score)); weights.append(float(row.weight))
    if not vals:return runs,runs+1,float(runs),0
    expected=float(np.average(vals,weights=weights)); low=max(runs,int(round(expected))); return low,low+1,expected,len(vals)


init_state()
with st.sidebar:
    league=st.selectbox("League",LEAGUES,key="league_choice")
    try: db=ensure_db(league)
    except Exception as e: st.error(str(e)); st.stop()
    con=readonly(str(db)); df=history_data(league,str(db))
    teams=sorted(set(df.batting_team.dropna())|set(df.bowling_team.dropna())) if not df.empty else []
    venues=sorted([x for x in df.venue.unique() if x]) if not df.empty else ["Unknown"]
    if not teams: st.error("No historical teams found."); st.stop()
    batting=st.selectbox("Batting Team",teams,key="batting_choice")
    bowling=st.selectbox("Bowling Team",[x for x in teams if x!=batting],key="bowling_choice")
    venue=st.selectbox("Ground",venues,key="venue_choice")
    innings_label=st.selectbox("Innings",["1st Innings","2nd Innings"],key="innings_choice")
    session_over=st.number_input("Session Over",1,20,int(st.session_state.session_over),1,key="session_over_widget")
    target=st.number_input("Target Runs",0,400,int(st.session_state.target),1,key="target_widget")
    start_over=st.selectbox("Start Over / Ball",["0.0"]+[f"{o}.{b}" for o in range(20) for b in range(1,7)],index=19,key="start_over_widget")
    start_runs=st.number_input("Start Runs",0,400,16,1,key="start_runs_widget")
    start_wk=st.number_input("Start Wickets",0,10,1,1,key="start_wk_widget")
    st.session_state.session_over=int(session_over); st.session_state.target=int(target)
    if st.button("Set Current Match Situation",use_container_width=True,key="set_situation"):
        st.session_state.runs=int(start_runs); st.session_state.wickets=int(start_wk); st.session_state.balls=to_balls(start_over); st.session_state.undo=[]; st.session_state.last="Starting situation set"; st.session_state.started=True; st.rerun()
    if st.button("Reset Live Situation",use_container_width=True,key="reset_live"):
        st.session_state.runs=0; st.session_state.wickets=0; st.session_state.balls=0; st.session_state.undo=[]; st.session_state.last=""; st.session_state.started=False; st.rerun()

if not st.session_state.started:
    st.session_state.runs=16; st.session_state.wickets=1; st.session_state.balls=to_balls("3.1"); st.session_state.started=True

runs=int(st.session_state.runs); wickets=int(st.session_state.wickets); balls=int(st.session_state.balls); inn=1 if innings_label.startswith("1") else 2
low,high,expected,samples=auto_line(df,inn,balls,runs,wickets,int(session_over),batting,bowling,venue)
if not st.session_state.manual: st.session_state.session_low=low; st.session_state.session_high=high; st.session_state.session_expected=expected

st.markdown(f"<div class='card'><h3>Current Live Score</h3><h2>{runs}/{wickets}</h2><p class='small'>Over/Ball: {over_ball(balls)} • Target: {target or 'Not set'} • Session over: {session_over} • Last: {st.session_state.last or '—'}</p></div>",unsafe_allow_html=True)
st.subheader("Ball-by-Ball Update")
buttons=[("Dot",0,False,True),("1 Run",1,False,True),("2 Runs",2,False,True),("3 Runs",3,False,True),("4 Runs",4,False,True),("6 Runs",6,False,True),("Wicket",0,True,True),("Undo",0,False,False)]
cols=st.columns(4)
for i,(label,rr,ww,legal) in enumerate(buttons):
    with cols[i%4]:
        if st.button(label,use_container_width=True,key=f"ball_{label}"):
            if label=="Undo": undo()
            else: event(rr,ww,legal,label)
            st.rerun()

st.subheader("Match Detail")
a,b,c,d=st.columns(4)
a.metric("Batting",batting); b.metric("Bowling",bowling); c.metric("Ground",venue); d.metric("Innings",innings_label)

st.markdown(f"<div class='session-box'><h3>Session</h3><h2>{int(st.session_state.session_low)}-{int(st.session_state.session_high)}</h2><p class='small'>Expected: {float(st.session_state.session_expected):.1f} • Over: {session_over} • Mode: {'Manual' if st.session_state.manual else 'Auto'} • Samples: {samples}</p></div>",unsafe_allow_html=True)

mc1,mc2,mc3=st.columns(3)
with mc1: manual_low=st.number_input("Manual Session Low",0,400,int(st.session_state.session_low),1,key="manual_low")
with mc2: manual_high=st.number_input("Manual Session High",0,400,int(st.session_state.session_high),1,key="manual_high")
with mc3: manual_note=st.text_input("Manual note",key="manual_note")
ma,mb=st.columns(2)
with ma:
    if st.button("Apply Manual Session",use_container_width=True,key="apply_manual"):
        st.session_state.manual=True; st.session_state.session_low=int(manual_low); st.session_state.session_high=max(int(manual_low)+1,int(manual_high)); st.rerun()
with mb:
    if st.button("Use Auto Session",use_container_width=True,key="use_auto"):
        st.session_state.manual=False; st.rerun()

if st.button("Analyze Current Situation",use_container_width=True,key="analyze"):
    end=int(session_over)*6; target_line=int(st.session_state.session_high)
    grouped=df.groupby(["match_id","innings_no"],sort=False); results=[]
    for (mid,ii),m in grouped:
        near=m[(m.ball_pos.between(max(1,balls-2),balls+2))&(m.innings_no==inn)]
        if near.empty: continue
        row=near.iloc[(near.score-runs).abs().argmin()]
        if abs(float(row.score)-runs)>30 or abs(float(row.wk)-wickets)>3: continue
        future=m[m.ball_pos<=end]
        if not future.empty: results.append(float(future.iloc[-1].score))
    st.subheader("VasuDev Result")
    if results:
        arr=np.array(results); yes=float((arr>=target_line).mean()*100); no=100-yes
        cls="yes" if yes>=no else "no"; label="YES" if yes>=no else "NO"
        st.markdown(f"<div class='{cls}'><h1>{label} — {max(yes,no):.1f}%</h1><p>Session line: {int(st.session_state.session_low)}-{int(st.session_state.session_high)} • {len(results)} similar states</p></div>",unsafe_allow_html=True)
        st.caption("Historical estimate only; not a guarantee.")
    else: st.warning("No similar historical situations found.")
