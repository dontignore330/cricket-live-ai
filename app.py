# VasuDev V3 - transition-based historical analyzer
# Complete app.py. Replace the current app.py with this file.
# V3 keeps the percentages historical/empirical; it does not manually inflate them.
# Paste this whole file over your current app.py.

import sqlite3
import os
import hmac
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

BASE_DIR = Path(".")
DB_PATHS = {
    "IPL": BASE_DIR / "cricket_history.db",
    "Men's Big Bash League": BASE_DIR / "bbl_history_v3.db",
    "Women's Big Bash League": BASE_DIR / "wbbl_history_v3.db",
}
DATA_URLS = {
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
}

st.set_page_config(page_title="VasuDev", page_icon="🏏", layout="wide")

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

# ---------------- DATA ----------------

def parse_delivery(value, over_no):
    try:
        a, b = str(value).strip().split(".", 1)
        over = int(a)
        ball = int(b)
        if over < 0 or ball <= 0:
            raise ValueError
        return over * 6 + ball, f"{over}.{ball}"
    except Exception:
        return None, None

def _json_match_to_sqlite(db_path, league, zip_path):
    tmp_db = db_path.with_suffix(db_path.suffix + ".tmp")
    if tmp_db.exists():
        tmp_db.unlink()
    out = sqlite3.connect(str(tmp_db))
    try:
        out.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT)")
        out.execute("""CREATE TABLE deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT, innings_no INTEGER, batting_team TEXT,
            bowling_team TEXT, over_no INTEGER, ball_no TEXT,
            runs INTEGER, wickets INTEGER, league TEXT)""")
        match_rows, delivery_rows = [], []
        with zipfile.ZipFile(zip_path) as z:
            for name in (n for n in z.namelist() if n.endswith(".json")):
                try:
                    data = json.loads(z.read(name))
                    info = data.get("info", {})
                    teams = info.get("teams", [])
                    if len(teams) < 2:
                        continue
                    outcome = info.get("outcome", {}) or {}
                    winner = outcome.get("winner", "") or outcome.get("eliminator", "") or outcome.get("bowl_out", "") or ""
                    match_id = Path(name).stem
                    venue = info.get("venue", "") or ""
                    match_rows.append((match_id, venue, str(winner), league))
                    for innings_no, innings in enumerate(data.get("innings", []), start=1):
                        if innings.get("super_over"):
                            continue
                        batting_team = innings.get("team", "")
                        bowling_team = next((t for t in teams if t != batting_team), "")
                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))
                            for d in over.get("deliveries", []):
                                pos, ball_no = parse_delivery(d.get("actual_delivery"), over_no)
                                if pos is None:
                                    try:
                                        ball = int(d.get("ball"))
                                        pos, ball_no = over_no * 6 + ball, f"{over_no}.{ball}"
                                    except Exception:
                                        continue
                                runs = int((d.get("runs") or {}).get("total", 0) or 0)
                                wickets = len(d.get("wickets") or [])
                                delivery_rows.append((match_id, innings_no, batting_team, bowling_team, over_no, ball_no, runs, wickets, league))
                except Exception:
                    continue
        out.executemany("INSERT OR REPLACE INTO matches VALUES (?,?,?,?)", match_rows)
        out.executemany("""INSERT INTO deliveries
            (match_id, innings_no, batting_team, bowling_team, over_no, ball_no, runs, wickets, league)
            VALUES (?,?,?,?,?,?,?,?,?)""", delivery_rows)
        out.execute("CREATE INDEX idx_deliveries_league ON deliveries(league)")
        out.execute("CREATE INDEX idx_deliveries_state ON deliveries(league, innings_no, ball_no)")
        out.execute("CREATE INDEX idx_deliveries_match_innings ON deliveries(match_id, innings_no, id)")
        out.commit()
    finally:
        out.close()
    tmp_db.replace(db_path)

def ensure_bigbash_db(league):
    db_path = DB_PATHS[league]
    if db_path.exists():
        return db_path, False
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "matches.zip"
        try:
            urllib.request.urlretrieve(DATA_URLS[league], zip_path)
            _json_match_to_sqlite(db_path, league, zip_path)
        except Exception as exc:
            if db_path.exists():
                db_path.unlink()
            raise RuntimeError(f"Could not prepare {league} historical data: {exc}") from exc
    return db_path, True

def get_db_connection(db_path):
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

st.title("🏏 VasuDev")
st.caption("Cricket Historical & Situation Analyzer")
league = st.selectbox("🏆 League", ["IPL", "Men's Big Bash League", "Women's Big Bash League"], index=0)

try:
    selected_db, built_now = ensure_bigbash_db(league) if league != "IPL" else (DB_PATHS["IPL"], False)
except Exception as exc:
    st.error(str(exc))
    st.info("IPL remains available. Reload after the hosting service has internet access to prepare Big Bash data.")
    st.stop()

conn = get_db_connection(selected_db)
if conn is None:
    st.error(f"Historical database for {league} not found.")
    st.stop()

try:
    match_count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    delivery_count = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
except Exception as e:
    st.error(f"Database could not be read: {e}")
    st.stop()

st.success(f"{league} historical database connected • {match_count:,} matches • {delivery_count:,} deliveries")
if built_now:
    st.caption(f"{league} data prepared automatically and opened read-only for analysis.")
else:
    st.write(f"Compare the live cricket situation with similar historical {league} situations.")

def get_values(sql, params=()):
    try:
        rows = conn.execute(sql, params).fetchall()
        return [r[0] for r in rows if r[0] not in (None, "")]
    except Exception:
        return []

def balls_from_over_ball(value):
    text = str(value).strip()
    try:
        whole_s, ball_s = text.split(".", 1)
        whole, ball = int(whole_s), int(ball_s)
    except (ValueError, TypeError):
        raise ValueError("Invalid cricket over.ball")
    if whole < 0 or whole > 20 or ball < 0 or ball > 6:
        raise ValueError("Invalid cricket over.ball")
    if whole == 20 and ball != 0:
        raise ValueError("20.0 is the end of a T20 innings")
    return whole * 6 + ball

def over_ball_from_balls(balls):
    balls = int(balls)
    if balls <= 0:
        return "0.0"
    if balls >= 120:
        return "20.0"
    over = (balls - 1) // 6
    ball = ((balls - 1) % 6) + 1
    return f"{over}.{ball}"

def valid_over_ball_options(max_over=20):
    options = ["0.0"]
    for over in range(max_over):
        options.extend(f"{over}.{ball}" for ball in range(1, 7))
    options.append("20.0")
    return options

VALID_CURRENT_POINTS = valid_over_ball_options(20)
VALID_FUTURE_POINTS = valid_over_ball_options(20)

def safe_round(x):
    try:
        return int(round(float(x)))
    except Exception:
        return 0

@st.cache_data(show_spinner=False)
def load_history(selected_league):
    q = """
    SELECT d.match_id, d.innings_no, d.batting_team, d.bowling_team,
           d.over_no, d.ball_no, d.runs, d.wickets, d.id,
           m.venue, m.winner
    FROM deliveries d
    JOIN matches m ON m.match_id=d.match_id
    WHERE d.league=?
    ORDER BY d.match_id, d.innings_no, d.id
    """
    df = pd.read_sql_query(q, conn, params=(selected_league,))
    if df.empty:
        return df

    def pos(v):
        try:
            a, b = str(v).split(".", 1)
            a, b = int(a), int(b)
            if a < 0 or b < 0:
                raise ValueError
            return a * 6 + b
        except Exception:
            return np.nan

    df["ball_pos"] = df["ball_no"].apply(pos)
    df = df.dropna(subset=["ball_pos"]).copy()
    df["ball_pos"] = df["ball_pos"].astype(int)
    df["runs"] = pd.to_numeric(df["runs"], errors="coerce").fillna(0).astype(int)
    df["wickets"] = pd.to_numeric(df["wickets"], errors="coerce").fillna(0).astype(int)
    for c in ["batting_team", "bowling_team", "venue", "winner"]:
        df[c] = df[c].fillna("").astype(str)

    groups = ["match_id", "innings_no"]
    df["cum_runs"] = df.groupby(groups, sort=False)["runs"].cumsum()
    df["cum_wk"] = df.groupby(groups, sort=False)["wickets"].cumsum()
    df["current_rr"] = np.where(df.ball_pos > 0, df.cum_runs / df.ball_pos * 6.0, 0.0)

    r6, r12, r18 = [], [], []
    for _, g in df.groupby(groups, sort=False):
        p = g.ball_pos.to_numpy(dtype=int)
        cr = g.cum_runs.to_numpy(dtype=float)
        a6, a12, a18 = [], [], []
        for position, total in zip(p, cr):
            i6 = np.searchsorted(p, position - 6, side="right") - 1
            i12 = np.searchsorted(p, position - 12, side="right") - 1
            i18 = np.searchsorted(p, position - 18, side="right") - 1
            b6 = cr[i6] if i6 >= 0 else 0.0
            b12 = cr[i12] if i12 >= 0 else 0.0
            b18 = cr[i18] if i18 >= 0 else 0.0
            a6.append(max(0.0, total - b6))
            a12.append(max(0.0, total - b12))
            a18.append(max(0.0, total - b18))
        r6.extend(a6); r12.extend(a12); r18.extend(a18)

    df["runs_last6"] = r6
    df["runs_last12"] = r12
    df["runs_last18"] = r18
    df["rr_last12"] = df.runs_last12 / 2.0
    df["momentum"] = df.rr_last12 - df.current_rr
    return df

history = load_history(league)

teams = get_values("SELECT DISTINCT batting_team FROM deliveries WHERE league=? ORDER BY batting_team", (league,))
venues = get_values("SELECT DISTINCT venue FROM matches WHERE league=? AND venue IS NOT NULL AND venue<>'' ORDER BY venue", (league,))
if not teams:
    st.error(f"No teams were found for {league}.")
    st.stop()
if not venues:
    venues = ["Unknown Ground"]

st.subheader("🏏 Current Match")
c1, c2, c3 = st.columns(3)
with c1:
    preferred_bat = {"IPL": "Sunrisers Hyderabad", "Men's Big Bash League": "Melbourne Stars", "Women's Big Bash League": "Sydney Sixers"}.get(league)
    default_bat = preferred_bat if preferred_bat in teams else teams[0]
    batting = st.selectbox("Batting Team", teams, index=teams.index(default_bat))
with c2:
    bowling_options = [x for x in teams if x != batting]
    preferred_bowl = {"IPL": "Rajasthan Royals", "Men's Big Bash League": "Sydney Sixers", "Women's Big Bash League": "Sydney Thunder"}.get(league)
    default_bowl = preferred_bowl if preferred_bowl in bowling_options else bowling_options[0]
    bowling = st.selectbox("Bowling Team", bowling_options, index=bowling_options.index(default_bowl))
with c3:
    venue = st.selectbox("Ground", venues, index=0)

c4, c5, c6, c7 = st.columns(4)
with c4:
    innings_label = st.selectbox("Innings", ["1st Innings", "2nd Innings"])
with c5:
    current_over = st.selectbox("Current Over / Ball", VALID_CURRENT_POINTS, index=VALID_CURRENT_POINTS.index("3.1"))
with c6:
    current_runs = st.number_input("Current Runs", min_value=0, max_value=400, value=16, step=1)
with c7:
    wickets = st.number_input("Wickets", min_value=0, max_value=10, value=1, step=1)

st.subheader("🎯 Target & Future Point")
st.caption("Future Point = kis over/ball tak dekhna hai. Target Runs = us point tak total score kitna pahunchna hai.")
c8, c9, c10 = st.columns(3)
with c8:
    future_over = st.selectbox("Future Ball / Over", VALID_FUTURE_POINTS, index=VALID_FUTURE_POINTS.index("7.1"))
with c9:
    target_runs = st.number_input("Target Runs", min_value=0, max_value=400, value=50, step=1)
with c10:
    match_format = st.selectbox("Match Format", ["T20"])

current_ball = balls_from_over_ball(current_over)
target_ball = balls_from_over_ball(future_over)
innings_no = 1 if innings_label == "1st Innings" else 2
remaining = max(0, target_ball - current_ball)
current_rr_live = current_runs / current_ball * 6 if current_ball > 0 else 0.0
required_runs_live = max(0, target_runs - current_runs)
required_rr_live = required_runs_live / remaining * 6 if remaining > 0 else 999.0

st.info(
    f"**Live situation:** {current_runs}/{wickets} at {over_ball_from_balls(current_ball)} • "
    f"**Current RR:** {current_rr_live:.2f} • "
    f"**Future point:** {over_ball_from_balls(target_ball)} • "
    f"**Balls remaining:** {remaining} • **Target:** {target_runs} • "
    f"**Runs required:** {required_runs_live} • **Required RR:** {required_rr_live:.2f}"
)

# ---------------- V2 LIVE TREND ----------------

def estimate_live_trend():
    if history.empty:
        return {"runs_last6": 0.0, "runs_last12": 0.0, "runs_last18": 0.0, "momentum": 0.0}
    x = history[
        (history.innings_no == innings_no) &
        (history.ball_pos.between(max(1, current_ball - 1), current_ball + 1))
    ].copy()
    if x.empty:
        return {"runs_last6": 0.0, "runs_last12": 0.0, "runs_last18": 0.0, "momentum": 0.0}
    x["d"] = ((x.cum_runs - current_runs).abs() / 8.0) + ((x.cum_wk - wickets).abs() / 1.5) + ((x.ball_pos - current_ball).abs() / 2.0)
    x = x.sort_values("d").head(80)
    return {
        "runs_last6": float(x.runs_last6.mean()),
        "runs_last12": float(x.runs_last12.mean()),
        "runs_last18": float(x.runs_last18.mean()),
        "momentum": float(x.momentum.mean()),
    }

live = estimate_live_trend()

# ---------------- V3 TRANSITION ENGINE ----------------
# Core idea:
# Do not ask only "what happened in similar states?".
# Ask "from similar historical states, how often did the innings actually
# reach THIS future target at THIS future point?".
# This directly models transitions such as 15/1 at 3.0 -> 35 at 6.0.

def _historical_state_at(g, ball_target):
    """Return the last recorded delivery at or before ball_target."""
    f = g[g.ball_pos <= int(ball_target)]
    if f.empty:
        return None
    return f.iloc[-1]


def transition_candidates():
    if history.empty or target_ball <= current_ball:
        return pd.DataFrame(), "No usable historical transition data"

    # Start with states very close to the live point.
    x = history[
        (history.innings_no == innings_no) &
        (history.ball_pos.between(max(1, current_ball - 1), current_ball + 1))
    ].copy()
    if x.empty:
        return pd.DataFrame(), "No historical state near this ball"

    x = x[(x.cum_runs - current_runs).abs() <= 22]
    x = x[(x.cum_wk - wickets).abs() <= 3]
    if x.empty:
        return pd.DataFrame(), "No similar historical states"

    # One candidate per historical match/innings. This prevents a single match
    # from being counted dozens of times and dominating the probability.
    x = x.sort_values(["match_id", "innings_no", "ball_pos"])
    x = x.assign(state_distance=(x.ball_pos-current_ball).abs() +
                  (x.cum_runs-current_runs).abs()*0.20 +
                  (x.cum_wk-wickets).abs()*1.5)
    x = x.sort_values("state_distance").groupby(["match_id", "innings_no"], sort=False).head(1).copy()

    # Live required scoring for the requested transition.
    live_required_rr = required_runs_live / max(1, target_ball-current_ball) * 6

    x["required_runs"] = (target_runs - x.cum_runs).clip(lower=0)
    x["remaining_balls"] = (target_ball - x.ball_pos).clip(lower=1)
    x["required_rr"] = x.required_runs / x.remaining_balls * 6

    # Similarity is deliberately interpretable. The final YES/NO is then based
    # on the actual historical future state, not on a hand-written prediction.
    x["s1"] = np.exp(-((x.cum_runs-current_runs).abs()) / 7.0)
    x["s2"] = np.exp(-((x.cum_wk-wickets).abs()) / 1.15)
    x["s3"] = np.exp(-((x.ball_pos-current_ball).abs()) / 1.5)
    x["s4"] = np.exp(-((x.current_rr-current_rr_live).abs()) / 1.15)
    x["s5"] = np.exp(-((x.runs_last12-live["runs_last12"]).abs()) / 8.0)
    x["s6"] = np.exp(-((x.runs_last6-live["runs_last6"]).abs()) / 6.0)
    x["s7"] = np.exp(-((x.momentum-live["momentum"]).abs()) / 2.0)
    x["s8"] = np.exp(-((x.required_rr-live_required_rr).abs()) / 1.7)
    x["team"] = ((x.batting_team == batting).astype(float) + 0.85*(x.bowling_team == bowling).astype(float))
    x["ground"] = (x.venue == venue).astype(float)

    x["similarity"] = (
        0.17*x.s1 + 0.11*x.s2 + 0.08*x.s3 + 0.13*x.s4 +
        0.12*x.s5 + 0.08*x.s6 + 0.07*x.s7 + 0.12*x.s8 +
        0.05*x.ground + 0.07*(x.team/1.85)
    )
    x["weight"] = x.similarity.clip(lower=0.02)

    grouped = history.groupby(["match_id", "innings_no"], sort=False)
    rows = []
    for _, row in x.iterrows():
        try:
            g = grouped.get_group((row.match_id, int(row.innings_no)))
        except KeyError:
            continue
        future = _historical_state_at(g, target_ball)
        if future is None:
            continue
        r = row.to_dict()
        r["future_score"] = float(future.cum_runs)
        r["future_wickets"] = float(future.cum_wk)
        r["future_runs"] = float(future.cum_runs - row.cum_runs)
        r["transition_hit"] = 1.0 if float(future.cum_runs) >= target_runs else 0.0
        rows.append(r)

    if not rows:
        return pd.DataFrame(), "No historical future transitions available"

    out = pd.DataFrame(rows)
    out = out.sort_values("weight", ascending=False).head(500)
    return out, "V3: historical state → actual future transition + score/wicket/RR/trend/required-RR/team/ground"


def calibrate_probability(successes, weights, prior_strength=12.0):
    """Conservative empirical probability with a small 50% prior.
    This prevents tiny samples from producing fake-looking extreme confidence.
    The prior is fixed and transparent; it is not tuned to a desired outcome.
    """
    weights = np.asarray(weights, dtype=float)
    successes = np.asarray(successes, dtype=float)
    total_w = float(weights.sum())
    if total_w <= 0:
        return 50.0
    raw = float(np.sum(successes*weights) / total_w)
    # Effective sample size for weighted observations.
    ess = float((weights.sum()**2) / max(1e-9, np.sum(weights**2)))
    alpha = prior_strength / max(1.0, ess + prior_strength)
    return 100.0 * ((1.0-alpha)*raw + alpha*0.5)

# ---------------- WIN V3 ----------------

def win_candidates():
    if history.empty:
        return None
    x = history[
        (history.innings_no == innings_no) &
        (history.ball_pos.between(max(1, current_ball - 1), current_ball + 1))
    ].copy()
    if x.empty:
        return None
    x = x[(x.cum_runs-current_runs).abs() <= 28]
    x = x[(x.cum_wk-wickets).abs() <= 3]
    x = x[x.winner.str.strip() != ""]
    if x.empty:
        return None

    x["state_distance"] = (x.ball_pos-current_ball).abs() + (x.cum_runs-current_runs).abs()*0.18 + (x.cum_wk-wickets).abs()*1.4
    x = x.sort_values("state_distance").groupby(["match_id","innings_no"], sort=False).head(1).copy()

    x["s1"] = np.exp(-((x.cum_runs-current_runs).abs())/8.0)
    x["s2"] = np.exp(-((x.cum_wk-wickets).abs())/1.2)
    x["s3"] = np.exp(-((x.ball_pos-current_ball).abs())/1.5)
    x["s4"] = np.exp(-((x.current_rr-current_rr_live).abs())/1.3)
    x["s5"] = np.exp(-((x.runs_last12-live["runs_last12"]).abs())/9.0)
    x["s6"] = np.exp(-((x.runs_last6-live["runs_last6"]).abs())/6.5)
    x["s7"] = np.exp(-((x.momentum-live["momentum"]).abs())/2.2)
    x["team"] = ((x.batting_team==batting).astype(float) + 0.85*(x.bowling_team==bowling).astype(float))
    x["ground"] = (x.venue==venue).astype(float)
    x["similarity"] = (
        0.20*x.s1 + 0.12*x.s2 + 0.09*x.s3 + 0.14*x.s4 +
        0.12*x.s5 + 0.09*x.s6 + 0.07*x.s7 +
        0.07*x.ground + 0.10*(x.team/1.85)
    )
    x["weight"] = x.similarity.clip(lower=0.02)
    x["won_flag"] = (x.winner == x.batting_team).astype(float)
    return x.sort_values("weight", ascending=False).head(500)

def reliability(n):
    if n >= 500: return "High"
    if n >= 150: return "Good"
    if n >= 50: return "Medium"
    if n >= 20: return "Limited"
    return "Very limited"

# ---------------- VALIDATION ----------------

def backtest_v3(history_df, sample_size=250, seed=42):
    """Match-level holdout test of the same transition idea used live.
    The selected match is never allowed into its own historical comparison pool.
    """
    if history_df.empty:
        return None
    h = history_df.copy()
    keys = h[["match_id","innings_no"]].drop_duplicates().reset_index(drop=True)
    if len(keys) < 10:
        return None
    rng = np.random.default_rng(seed)
    n = min(sample_size, len(keys))
    chosen = keys.iloc[rng.choice(len(keys), size=n, replace=False)]
    grouped = h.groupby(["match_id","innings_no"], sort=False)
    session_hits=[]; win_hits=[]; brier=[]; states=0

    for _, k in chosen.iterrows():
        try:
            own=grouped.get_group((k.match_id,int(k.innings_no)))
        except KeyError:
            continue
        # Test many different match phases; this keeps 1-6 overs and later phases represented.
        usable=own[own.ball_pos.between(6,108)]
        if usable.empty:
            continue
        state=usable.iloc[int(rng.integers(0,len(usable)))]
        cur=int(state.ball_pos)
        # Random horizon between 12 and 30 balls, clipped to innings.
        horizon=int(rng.choice([12,18,24,30]))
        future=_historical_state_at(own,cur+horizon)
        if future is None:
            continue
        actual_delta=float(future.cum_runs-state.cum_runs)
        # Target is the actual future score plus a random small requirement. This tests the
        # transition question rather than a fixed arbitrary target.
        req=int(rng.integers(8, min(25, int(actual_delta)+12)+1))
        target=int(state.cum_runs)+req
        pool=h[(h.innings_no==int(k.innings_no)) & (h.match_id!=k.match_id)].copy()
        pool=pool[pool.ball_pos.between(max(1,cur-1),cur+1)]
        pool=pool[(pool.cum_runs-state.cum_runs).abs()<=22]
        pool=pool[(pool.cum_wk-state.cum_wk).abs()<=3]
        if pool.empty:
            continue
        pool["s"]=(
            0.22*np.exp(-((pool.cum_runs-state.cum_runs).abs())/7.0)+
            0.12*np.exp(-((pool.cum_wk-state.cum_wk).abs())/1.2)+
            0.10*np.exp(-((pool.ball_pos-cur).abs())/1.5)+
            0.15*np.exp(-((pool.current_rr-state.current_rr).abs())/1.2)+
            0.13*np.exp(-((pool.runs_last12-state.runs_last12).abs())/8.0)+
            0.08*np.exp(-((pool.runs_last6-state.runs_last6).abs())/6.0)+
            0.08*np.exp(-((pool.momentum-state.momentum).abs())/2.0)+
            0.07*(pool.venue==state.venue).astype(float)+
            0.05*(pool.batting_team==state.batting_team).astype(float)
        )
        pool["weight"]=pool.s.clip(lower=0.02)
        rows=[]
        for (mid,inn),g in pool.groupby(["match_id","innings_no"],sort=False):
            full=grouped.get_group((mid,inn))
            fs=_historical_state_at(full,cur+horizon)
            if fs is None: continue
            # nearest state from this match is the starting state.
            idx=(g.ball_pos-cur).abs().idxmin(); first=g.loc[idx]
            rows.append((mid,float(fs.cum_runs-first.cum_runs),float(first.weight)))
        if not rows: continue
        fr=pd.DataFrame(rows,columns=["mid","future_runs","weight"])
        p=calibrate_probability((fr.future_runs>=req).astype(float),fr.weight)
        actual=1 if actual_delta>=req else 0
        session_hits.append(float((p>=50)==bool(actual)))
        brier.append(((p/100.0)-actual)**2)
        valid=pool[pool.winner.str.strip()!=""]
        if not valid.empty:
            wp=calibrate_probability(valid.won_flag.to_numpy(),valid.weight.to_numpy())
            actual_w=int(str(state.winner)==str(state.batting_team))
            win_hits.append(float((wp>=50)==bool(actual_w)))
        states+=1

    if states==0: return None
    return {
        "states":states,
        "session_accuracy":100*float(np.mean(session_hits)) if session_hits else None,
        "win_accuracy":100*float(np.mean(win_hits)) if win_hits else None,
        "session_brier":float(np.mean(brier)) if brier else None,
    }

with st.expander("🧪 VasuDev Historical Validation (advanced)", expanded=False):
    st.caption("Match-level holdout test. The test match is excluded from its own comparison pool. This is measurement only; it never changes the live percentage.")
    if st.button("▶ Run Historical Validation", use_container_width=True):
        with st.spinner("Validating VasuDev V3..."):
            bt=backtest_v3(history,sample_size=250,seed=42)
        if bt is None:
            st.warning("Not enough historical data for validation.")
        else:
            a,b,c,d=st.columns(4)
            if bt["session_accuracy"] is not None: a.metric("Session accuracy",f"{bt['session_accuracy']:.1f}%")
            if bt["win_accuracy"] is not None: b.metric("WIN accuracy",f"{bt['win_accuracy']:.1f}%")
            if bt["session_brier"] is not None: c.metric("Session Brier",f"{bt['session_brier']:.3f}")
            d.metric("Test states",bt["states"])
            st.info("No 75%, 80% or 90% target is forced. The test reports what the historical sample actually produced.")

# ---------------- FINAL RESULT ----------------

if st.button("🔎 ANALYZE VASUDEV", use_container_width=True, disabled=(target_ball <= current_ball)):

    win_df = win_candidates()
    win_pct = loss_pct = other_pct = 0.0
    win_samples = 0

    if win_df is not None and len(win_df):
        won = win_df.winner == win_df.batting_team
        lost = win_df.winner == win_df.bowling_team
        other = ~(won | lost)
        ww = float(win_df.loc[won, "weight"].sum())
        lw = float(win_df.loc[lost, "weight"].sum())
        ow = float(win_df.loc[other, "weight"].sum())
        total = ww + lw + ow
        if total > 0:
            win_pct = 100*ww/total
            loss_pct = 100*lw/total
            other_pct = 100*ow/total
        win_samples = len(win_df)

    cand, method = transition_candidates()
    session_yes = session_no = 0.0
    session_samples = 0
    expected_score = range_low = range_high = None

    if not cand.empty:
        cand = add_future_scores(cand)

    if not cand.empty:
        cand["hit"] = cand.transition_hit.astype(float)
        session_yes = calibrate_probability(cand.hit.to_numpy(), cand.weight.to_numpy())
        session_no = 100-session_yes
        session_samples = len(cand)
        expected_score = float(np.average(cand.future_score, weights=cand.weight))
        range_low = float(cand.future_score.quantile(.10))
        range_high = float(cand.future_score.quantile(.90))

    st.subheader("🧠 VasuDev Result")
    st.caption(f"{league} • {batting} vs {bowling} • {innings_label} • {venue}")

    st.markdown("### 🏆 WIN")
    if win_samples:
        st.markdown(
            f'<div class="card"><h2>{batting} WIN — {win_pct:.1f}%</h2>'
            f'<h3>LOSS — {loss_pct:.1f}%</h3>'
            f'<p class="small">Historical probability • {win_samples:,} similar match states • Reliability: {reliability(win_samples)}</p></div>',
            unsafe_allow_html=True
        )
    else:
        st.info("Not enough historical match-result data for this situation.")

    st.markdown("### 🎯 SESSION")
    if session_samples:
        label = "YES" if session_yes >= session_no else "NO"
        pct = max(session_yes, session_no)
        box = "result_yes" if label == "YES" else "result_no"
        st.markdown(
            f'<div class="{box}"><h1>{label} — {pct:.1f}%</h1>'
            f'<p>Target <b>{target_runs}</b> by <b>{over_ball_from_balls(target_ball)}</b> • {remaining} balls remaining</p>'
            f'<p class="small">Historical probability • {session_samples:,} similar situations • Reliability: {reliability(session_samples)}</p></div>',
            unsafe_allow_html=True
        )
    else:
        st.info("Not enough historical continuation data for this session.")

    st.caption("Probabilities are calculated from historical data. They are not guarantees.")

    with st.expander("Details (optional)", expanded=False):
        st.write(f"**Current:** {current_runs}/{wickets} at {over_ball_from_balls(current_ball)} → **Future:** {over_ball_from_balls(target_ball)} → **Target:** {target_runs}")
        st.write(f"**Current RR:** {current_rr_live:.2f} • **Runs required:** {required_runs_live} • **Required RR:** {required_rr_live:.2f}")
        st.write(f"**Recent trend estimate:** last 6 = {live['runs_last6']:.1f}, last 12 = {live['runs_last12']:.1f}, last 18 = {live['runs_last18']:.1f}")
        if session_samples:
            st.write(f"YES: **{session_yes:.1f}%** • NO: **{session_no:.1f}%**")
            st.write(f"Expected score at future point: **{safe_round(expected_score)}** • Historical 10–90% range: **{safe_round(range_low)}–{safe_round(range_high)}**")
            st.caption(method)
        if win_samples:
            st.write(f"WIN: **{win_pct:.1f}%** • LOSS: **{loss_pct:.1f}%** • Other/Tie: **{other_pct:.1f}%**")
        st.write("V2 does not manually increase percentages. It changes the historical similarity features.")
