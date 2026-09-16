import sqlite3
import math
import os
import hmac
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

DB_PATH = Path("cricket_history.db")
st.set_page_config(page_title="VasuDev", page_icon="🏏", layout="wide")

# ---------- private app lock ----------
# Set VASUDEV_PASSWORD as a secret/environment variable on the hosting service.
APP_PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()
if not APP_PASSWORD:
    st.error("🔒 VasuDev is locked. Hosting setup is incomplete: set the VASUDEV_PASSWORD secret.")
    st.stop()

if "vasudev_authenticated" not in st.session_state:
    st.session_state.vasudev_authenticated = False

if not st.session_state.vasudev_authenticated:
    st.title("🔒 VasuDev Private Access")
    st.caption("Enter the private password to open the cricket analysis app.")
    password = st.text_input("Password", type="password")
    if st.button("🔓 Unlock", use_container_width=True):
        if hmac.compare_digest(password, APP_PASSWORD):
            st.session_state.vasudev_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

st.markdown("""
<style>
.main { background:#07111f; }
.block-container { padding-top:1.4rem; }
.card { background:#0f1b2d; padding:18px; border-radius:14px; border:1px solid #26364d; }
.result_yes { background:#06351f; padding:22px; border-radius:16px; border:2px solid #20c77a; text-align:center; }
.result_no { background:#3d1010; padding:22px; border-radius:16px; border:2px solid #ef5350; text-align:center; }
.small { color:#94a3b8; font-size:13px; }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_conn():
    if not DB_PATH.exists():
        return None
    # Open the historical database in SQLite read-only mode. The deployed app
    # therefore cannot insert, update, or delete historical data through this connection.
    conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = get_conn()
st.title("🏏 VasuDev")
st.caption("Cricket Historical & Situation Analyzer")
st.write("Compare the live cricket situation with similar historical IPL situations.")

if conn is None:
    st.error("Historical database not found.")
    st.info("The app is running, but the historical cricket database has not been connected yet.")
    st.stop()

try:
    match_count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    delivery_count = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
except Exception as e:
    st.error(f"Database could not be read: {e}")
    st.stop()

st.success(f"Historical database connected • {match_count:,} matches • {delivery_count:,} deliveries")

def get_values(sql, params=()):
    try:
        rows = conn.execute(sql, params).fetchall()
        return [r[0] for r in rows if r[0] not in (None, "")]
    except Exception:
        return []

def balls_from_over_ball(value):
    # Cricket over.ball is NOT decimal math: each over has exactly 6 legal balls.
    # We accept whole-over states (e.g. 3.0) and legal balls 1-6 only.
    text = str(value).strip()
    try:
        whole_s, ball_s = text.split(".", 1)
        whole = int(whole_s)
        ball = int(ball_s)
    except (ValueError, TypeError):
        raise ValueError("Invalid cricket over.ball")
    if whole < 0 or whole > 20 or ball < 0 or ball > 6:
        raise ValueError("Invalid cricket over.ball")
    if whole == 20 and ball != 0:
        raise ValueError("20.0 is the end of a T20 innings")
    return whole * 6 + ball

def over_ball_from_balls(balls):
    # Internal ball count is one-based within each over: 4.6 is ball 30,
    # and the next legal delivery is 5.1 (ball 31).
    balls = int(balls)
    if balls <= 0:
        return "0.0"
    over = (balls - 1) // 6
    ball = ((balls - 1) % 6) + 1
    return f"{over}.{ball}"

def valid_over_ball_options(max_over=20):
    # Offer only legal delivery positions. 0.0 means before the first ball.
    # After 4.6 the next option is 5.1 — never 4.7, 4.8, etc.
    options = ["0.0"]
    for over in range(max_over):
        options.extend(f"{over}.{ball}" for ball in range(1, 7))
    return options

VALID_CURRENT_POINTS = valid_over_ball_options(20)
VALID_FUTURE_POINTS = valid_over_ball_options(20)

def safe_round(x):
    try:
        return int(round(float(x)))
    except Exception:
        return 0

@st.cache_data(show_spinner=False)
def load_history():
    q = """
    SELECT d.match_id, d.innings_no, d.batting_team, d.bowling_team,
           d.over_no, d.ball_no, d.runs, d.wickets, d.id,
           m.venue, m.winner
    FROM deliveries d
    JOIN matches m ON m.match_id=d.match_id
    WHERE d.league='IPL'
    ORDER BY d.match_id, d.innings_no, d.id
    """
    df = pd.read_sql_query(q, conn)
    if df.empty:
        return df
    df["ball_pos"] = df["ball_no"].apply(balls_from_over_ball).astype(int)
    df["runs"] = pd.to_numeric(df["runs"], errors="coerce").fillna(0).astype(int)
    df["wickets"] = pd.to_numeric(df["wickets"], errors="coerce").fillna(0).astype(int)
    df["cum_runs"] = df.groupby(["match_id","innings_no"], sort=False)["runs"].cumsum()
    df["cum_wk"] = df.groupby(["match_id","innings_no"], sort=False)["wickets"].cumsum()
    df["batting_team"] = df["batting_team"].astype(str)
    df["bowling_team"] = df["bowling_team"].astype(str)
    df["venue"] = df["venue"].fillna("").astype(str)
    df["winner"] = df["winner"].fillna("").astype(str)
    return df

history = load_history()

teams = get_values("SELECT DISTINCT batting_team FROM deliveries WHERE league='IPL' ORDER BY batting_team")
venues = get_values("SELECT DISTINCT venue FROM matches WHERE league='IPL' AND venue IS NOT NULL AND venue<>'' ORDER BY venue")
if not teams:
    teams = ["Chennai Super Kings","Delhi Capitals","Gujarat Titans","Kolkata Knight Riders","Lucknow Super Giants","Mumbai Indians","Punjab Kings","Rajasthan Royals","Royal Challengers Bengaluru","Sunrisers Hyderabad"]
if not venues:
    venues = ["Rajiv Gandhi International Stadium, Uppal, Hyderabad"]

st.subheader("🏏 Current Match")
c1,c2,c3 = st.columns(3)
with c1:
    default_bat = "Sunrisers Hyderabad" if "Sunrisers Hyderabad" in teams else teams[0]
    batting = st.selectbox("Batting Team", teams, index=teams.index(default_bat))
with c2:
    bowling_options = [x for x in teams if x != batting]
    default_bowl = "Rajasthan Royals" if "Rajasthan Royals" in bowling_options else bowling_options[0]
    bowling = st.selectbox("Bowling Team", bowling_options, index=bowling_options.index(default_bowl))
with c3:
    default_venue = "Rajiv Gandhi International Stadium, Uppal, Hyderabad" if "Rajiv Gandhi International Stadium, Uppal, Hyderabad" in venues else venues[0]
    venue = st.selectbox("Ground", venues, index=venues.index(default_venue))

c4,c5,c6,c7 = st.columns(4)
with c4:
    innings_label = st.selectbox("Innings", ["1st Innings","2nd Innings"])
with c5:
    current_over = st.selectbox("Current Over / Ball", VALID_CURRENT_POINTS, index=VALID_CURRENT_POINTS.index("3.1"))
with c6:
    current_runs = st.number_input("Current Runs", min_value=0, max_value=400, value=16, step=1)
with c7:
    wickets = st.number_input("Wickets", min_value=0, max_value=10, value=1, step=1)

st.subheader("🎯 Target & Future Point")
st.caption("Future Point = kis over/ball tak dekhna hai. Target Runs = us point tak total score kitna pahunchna hai.")
c8,c9,c10 = st.columns(3)
with c8:
    future_over = st.selectbox("Future Ball / Over", VALID_FUTURE_POINTS, index=VALID_FUTURE_POINTS.index("7.1"))
with c9:
    target_runs = st.number_input("Target Runs", min_value=0, max_value=400, value=50, step=1)
with c10:
    match_format = st.selectbox("Match Format", ["T20"])

current_ball = balls_from_over_ball(current_over)
target_ball = balls_from_over_ball(future_over)
innings_no = 1 if innings_label == "1st Innings" else 2
remaining = max(0, target_ball-current_ball)

st.info(f"**Live situation:** {current_runs}/{wickets} at {over_ball_from_balls(current_ball)} • **Future point:** {over_ball_from_balls(target_ball)} • **Balls remaining:** {remaining} • **Target:** {target_runs} runs")

# ---------- similarity engine ----------
def similarity_candidates(batting, bowling, venue, innings_no, current_ball, current_runs, wickets, target_ball):
    if history.empty or target_ball <= current_ball:
        return pd.DataFrame(), "No usable historical data"

    # Only compare situations that have enough future deliveries to reach the requested point.
    cur = history[(history.innings_no == innings_no) & (history.ball_pos == current_ball)].copy()
    if cur.empty:
        # A small ball-position window prevents sparse exact-ball positions from killing the result.
        cur = history[(history.innings_no == innings_no) & (history.ball_pos.between(max(1,current_ball-1), current_ball+1))].copy()
    if cur.empty:
        return pd.DataFrame(), "No historical state near this ball"

    # Never use a state from after the target point.
    cur = cur[cur.ball_pos < target_ball]
    if cur.empty:
        return pd.DataFrame(), "No historical state before target point"

    # Score/wicket neighborhood first; then progressively broaden.
    tolerances = [(2,0),(4,1),(7,1),(12,2),(20,3),(999,10)]
    selected = pd.DataFrame()
    used = ""
    for score_tol, wk_tol in tolerances:
        x = cur[(cur["cum_runs"]-current_runs).abs() <= score_tol]
        x = x[(x["cum_wk"]-wickets).abs() <= wk_tol]
        if not x.empty:
            selected = x.copy()
            if score_tol == 999:
                used = "broad IPL similarity"
            else:
                used = f"similar score ±{score_tol}, wickets ±{wk_tol}"
            if len(selected) >= 40 or score_tol >= 12:
                break
    if selected.empty:
        return pd.DataFrame(), "No similar historical states"

    # Team/ground match strength. This is intentionally a weighting, not an all-or-nothing filter.
    selected["team_score"] = (selected.batting_team == batting).astype(float) * 1.0 + (selected.bowling_team == bowling).astype(float) * 0.8
    selected["ground_score"] = (selected.venue == venue).astype(float) * 1.0
    selected["ball_score"] = np.exp(-((selected.ball_pos-current_ball).abs())/2.5)
    selected["score_score"] = np.exp(-((selected.cum_runs-current_runs).abs())/7.0)
    selected["wk_score"] = np.exp(-((selected.cum_wk-wickets).abs())/1.2)
    selected["similarity"] = (0.28*selected["score_score"] + 0.18*selected["wk_score"] + 0.18*selected["ball_score"] + 0.18*selected["ground_score"] + 0.18*(selected["team_score"]/1.8))

    # Stronger exact team/ground states get more influence, but broad IPL states remain available.
    selected["weight"] = selected["similarity"].clip(lower=0.05)
    return selected, used

def add_future_scores(candidates, target_ball):
    if candidates.empty:
        return candidates
    future_rows=[]
    # Candidate rows are only a few thousand at most; find first delivery at/after target in each innings.
    grouped = history.groupby(["match_id","innings_no"], sort=False)
    for idx,row in candidates.iterrows():
        key=(row.match_id,row.innings_no)
        try:
            g=grouped.get_group(key)
        except KeyError:
            continue
        f=g[g.ball_pos <= target_ball]
        if f.empty:
            continue
        # Prefer the state exactly at target; if no legal delivery exists, use the last score at/before it.
        fr=f.iloc[-1]
        r=row.to_dict()
        r["future_score"]=float(fr.cum_runs)
        r["future_runs"]=float(fr.cum_runs-row.cum_runs)
        future_rows.append(r)
    return pd.DataFrame(future_rows)

def weighted_pct(values, weights):
    if len(values)==0 or weights.sum()<=0:
        return 0.0
    return float(np.average(values, weights=weights))*100

def historical_win_similarity(batting, bowling, venue, innings_no, current_ball, current_runs, wickets):
    if history.empty:
        return None
    x=history[(history.innings_no==innings_no) & (history.ball_pos.between(max(1,current_ball-1),current_ball+1))].copy()
    if x.empty:
        return None
    x=x[(x.cum_runs-current_runs).abs()<=20]
    x=x[(x.cum_wk-wickets).abs()<=3]
    if x.empty:
        return None
    x["weight"]=(np.exp(-((x.cum_runs-current_runs).abs())/8.0)*0.45 + np.exp(-((x.cum_wk-wickets).abs())/1.5)*0.25 + (x.venue==venue).astype(float)*0.15 + ((x.batting_team==batting)&(x.bowling_team==bowling)).astype(float)*0.15)
    x=x[x.weight>0]
    if x.empty:
        return None
    x["won_flag"]=(x.winner==x.batting_team).astype(float)
    return x

if st.button("🔎 ANALYZE VASUDEV", use_container_width=True, disabled=(target_ball<=current_ball)):
    st.subheader("🧠 VasuDev Analysis")
    st.markdown(f"**{batting}** vs **{bowling}**  •  **{venue}**  •  **{innings_label}**  •  **{match_format}**")
    st.write(f"Current: **{current_runs}/{wickets} at {over_ball_from_balls(current_ball)}** → Future: **{over_ball_from_balls(target_ball)}** → Target: **{target_runs}**")

    # Existing eventual-match-result style, now similarity based.
    win_df=historical_win_similarity(batting,bowling,venue,innings_no,current_ball,current_runs,wickets)
    st.markdown("### 🏆 Historical Team Winning / Loss Result")
    if win_df is not None and len(win_df):
        valid_result = win_df[win_df.winner.str.strip() != ""].copy()
        if len(valid_result):
            won = (valid_result.winner == valid_result.batting_team)
            lost = (valid_result.winner == valid_result.bowling_team)
            other = ~(won | lost)
            win_weight = valid_result.loc[won, "weight"].sum()
            loss_weight = valid_result.loc[lost, "weight"].sum()
            other_weight = valid_result.loc[other, "weight"].sum()
            total_weight = win_weight + loss_weight + other_weight
            win_pct = 100 * win_weight / total_weight if total_weight else 0.0
            loss_pct = 100 * loss_weight / total_weight if total_weight else 0.0
            other_pct = 100 * other_weight / total_weight if total_weight else 0.0
            a,b,c,d=st.columns(4)
            a.metric("Batting Team WIN",f"{win_pct:.1f}%")
            b.metric("Batting Team LOSS",f"{loss_pct:.1f}%")
            c.metric("Other / Tie",f"{other_pct:.1f}%")
            d.metric("Similar States",len(valid_result))
            st.write(f"**{batting}:** {win_pct:.1f}% historical win frequency  •  **Loss:** {loss_pct:.1f}%  •  **Other:** {other_pct:.1f}%")
            st.caption("This is based on historical match states similar to the current score, wickets, ball position, teams and ground. It is historical frequency, not a guarantee.")
        else:
            st.info("Similar states were found, but they do not contain a usable final match result.")
    else:
        st.info("No usable historical match-result sample was found.")

    # Target analysis.
    st.markdown("### 🎯 Historical Target Analysis")
    cand, method=similarity_candidates(batting,bowling,venue,innings_no,current_ball,current_runs,wickets,target_ball)
    if not cand.empty:
        cand=add_future_scores(cand,target_ball)
        if cand.empty:
            st.info("Historical states were found, but not enough of them continued to the selected future point.")
        else:
            cand["hit"]=(cand.future_score>=target_runs).astype(float)
            yes_pct=weighted_pct(cand.hit.to_numpy(),cand.weight.to_numpy())
            no_pct=100-yes_pct
            avg_future=np.average(cand.future_runs,weights=cand.weight)
            avg_score=np.average(cand.future_score,weights=cand.weight)
            q10=float(cand.future_score.quantile(.10)); q90=float(cand.future_score.quantile(.90))
            box="result_yes" if yes_pct>=no_pct else "result_no"
            label="YES" if yes_pct>=no_pct else "NO"
            pct=max(yes_pct,no_pct)
            st.write(f"**Question:** Similar historical situations — did the batting team reach **{target_runs} runs by {over_ball_from_balls(target_ball)}**?")
            st.markdown(f'<div class="{box}"><h1>{label}</h1><h2>{pct:.1f}% historical frequency</h2><p>Target: <b>{target_runs}</b> by <b>{over_ball_from_balls(target_ball)}</b> • {remaining} balls remaining</p></div>',unsafe_allow_html=True)
            m1,m2,m3,m4=st.columns(4)
            m1.metric("Historical YES",int(round(cand.hit.sum())))
            m2.metric("Historical NO",int(len(cand)-round(cand.hit.sum())))
            m3.metric("Similar Samples",len(cand))
            m4.metric("Avg Future Runs",safe_round(avg_future))
            st.write(f"**YES:** {yes_pct:.1f}%  •  **NO:** {no_pct:.1f}%")
            st.write(f"Expected score at {over_ball_from_balls(target_ball)}: **{safe_round(avg_score)} runs**  •  Historical 10–90% range: **{safe_round(q10)}–{safe_round(q90)}**")
            st.caption(f"Similarity engine: {method}. Ground, team, score, wickets and ball position are weighted; broader IPL data is used when exact situations are sparse.")
            if len(cand)<30:
                st.warning("Small historical sample: treat this result as low-data historical evidence.")
            elif len(cand)<100:
                st.info("Moderate historical sample: the result is based on similar situations, not exact duplicates.")
            else:
                st.success("Good historical sample size for this situation.")
    else:
        st.info("No exact match was required, but the database could not find a usable historical continuation for this future point. Try a later future point or another IPL situation.")

    st.markdown("### 🧩 How VasuDev handles rare situations")
    st.write("The system does not depend on one exact historical match. It first uses close score/wicket/ball situations and gives extra weight to the selected ground and teams. If the exact combination is rare, it automatically broadens to similar IPL situations instead of simply showing Data Not Found.")
    st.caption("Player-level adjustment is reserved for the next data layer because the current cricket_history.db does not contain the current playing XI/player-at-ball fields. The present engine therefore does not invent player information.")
