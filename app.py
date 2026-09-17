import sqlite3
import math
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
    "Men's Big Bash League": BASE_DIR / "bbl_history.db",
    "Women's Big Bash League": BASE_DIR / "wbbl_history.db",
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
.result_win { background:#06351f; padding:22px; border-radius:16px; border:2px solid #20c77a; text-align:center; }
.result_avg {
        border: 2px solid #3b82f6;
        background: #0b1f3a;
        padding: 16px;
        border-radius: 12px;
        margin: 8px 0 14px 0;
    }
    .result_loss { background:#3d1010; padding:22px; border-radius:16px; border:2px solid #ef5350; text-align:center; }
.small { color:#94a3b8; font-size:13px; }
</style>
""", unsafe_allow_html=True)


def _json_match_to_sqlite(db_path, league, zip_path):
    tmp_db = db_path.with_suffix(db_path.suffix + ".tmp")
    if tmp_db.exists():
        tmp_db.unlink()
    out = sqlite3.connect(str(tmp_db))
    try:
        out.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT)")
        out.execute("""CREATE TABLE deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            innings_no INTEGER,
            batting_team TEXT,
            bowling_team TEXT,
            over_no INTEGER,
            ball_no TEXT,
            runs INTEGER,
            wickets INTEGER,
            league TEXT
        )""")
        match_rows, delivery_rows = [], []
        with zipfile.ZipFile(zip_path) as z:
            for name in (n for n in z.namelist() if n.endswith('.json')):
                try:
                    data = json.loads(z.read(name))
                    info = data.get("info", {})
                    teams = info.get("teams", [])
                    if len(teams) < 2:
                        continue
                    outcome = info.get("outcome", {}) or {}
                    winner = outcome.get("winner", "") or outcome.get("eliminator", "") or outcome.get("bowl_out", "")
                    match_id = Path(name).stem
                    venue = info.get("venue", "") or ""
                    match_rows.append((match_id, venue, winner, league))
                    for innings_no, innings in enumerate(data.get("innings", []), start=1):
                        if innings.get("super_over"):
                            continue
                        batting_team = innings.get("team", "")
                        bowling_team = next((t for t in teams if t != batting_team), "")
                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))
                            for d in over.get("deliveries", []):
                                actual = str(d.get("actual_delivery", f"{over_no}.0"))
                                try:
                                    _, ball_s = actual.split(".", 1)
                                    ball_no = f"{over_no}.{int(ball_s)}"
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

@st.cache_data(show_spinner=False, ttl=3600)
def load_history(selected_league, db_path_str):
    # Keep the large historical dataframe out of the initial page load.
    # Streamlit caches this per league/database, so Analyze reuses it.
    q = """
    SELECT d.match_id, d.innings_no, d.batting_team, d.bowling_team,
           d.over_no, d.ball_no, d.runs, d.wickets, d.id,
           m.venue, m.winner
    FROM deliveries d
    JOIN matches m ON m.match_id=d.match_id
    WHERE d.league=?
    ORDER BY d.match_id, d.innings_no, d.id
    """
    local_conn = sqlite3.connect(f"file:{Path(db_path_str).resolve()}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(q, local_conn, params=(selected_league,))
    finally:
        local_conn.close()
    if df.empty:
        return df
    # Historical files can contain illegal-delivery labels such as 4.7 or 4.10.
    # Those labels are valid as historical sequence markers even though they must
    # never be accepted from the user's live input. Keep strict validation for UI
    # input, but parse historical labels without crashing.
    def historical_ball_position(value):
        text = str(value).strip()
        try:
            whole_s, ball_s = text.split(".", 1)
            whole = int(whole_s)
            ball = int(ball_s)
            if whole < 0 or ball < 0:
                raise ValueError
            return whole * 6 + ball
        except (ValueError, TypeError):
            return np.nan

    df["ball_pos"] = df["ball_no"].apply(historical_ball_position)
    df = df.dropna(subset=["ball_pos"]).copy()
    df["ball_pos"] = df["ball_pos"].astype(int)
    df["runs"] = pd.to_numeric(df["runs"], errors="coerce").fillna(0).astype(int)
    df["wickets"] = pd.to_numeric(df["wickets"], errors="coerce").fillna(0).astype(int)
    df["cum_runs"] = df.groupby(["match_id","innings_no"], sort=False)["runs"].cumsum()
    df["cum_wk"] = df.groupby(["match_id","innings_no"], sort=False)["wickets"].cumsum()
    df["batting_team"] = df["batting_team"].astype(str)
    df["bowling_team"] = df["bowling_team"].astype(str)
    df["venue"] = df["venue"].fillna("").astype(str)
    df["winner"] = df["winner"].fillna("").astype(str)
    return df

# IMPORTANT: Do not load the full ball-by-ball dataframe here.
# That was the main reason password unlock/page opening felt slow.
# The large history is loaded lazily only when ANALYZE is pressed.
history = pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=3600)
def load_metadata(db_path_str, selected_league):
    local_conn = sqlite3.connect(f"file:{Path(db_path_str).resolve()}?mode=ro", uri=True)
    try:
        teams_df = pd.read_sql_query(
            "SELECT DISTINCT batting_team FROM deliveries WHERE league=? ORDER BY batting_team",
            local_conn, params=(selected_league,)
        )
        venues_df = pd.read_sql_query(
            "SELECT DISTINCT venue FROM matches WHERE league=? AND venue IS NOT NULL AND venue<>'' ORDER BY venue",
            local_conn, params=(selected_league,)
        )
        return (teams_df.iloc[:,0].dropna().astype(str).tolist(),
                venues_df.iloc[:,0].dropna().astype(str).tolist())
    finally:
        local_conn.close()

teams, venues = load_metadata(str(selected_db), league)
if not teams:
    st.error(f"No teams were found for {league}.")
    st.stop()
if not venues:
    venues = ["Unknown Ground"]




st.subheader("🏏 Current Match")
c1,c2,c3 = st.columns(3)
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
                used = "broad selected-league similarity"
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
    """Attach the score at/before target_ball without scanning each candidate row.

    The old version called groupby.get_group() once for every candidate. With a
    large historical database that created hundreds/thousands of repeated scans.
    This version builds one target snapshot per innings and merges it once.
    """
    if candidates.empty:
        return candidates

    target_rows = history[history.ball_pos <= target_ball]
    if target_rows.empty:
        return pd.DataFrame()

    target_rows = (
        target_rows.sort_values(["match_id", "innings_no", "ball_pos"])
        .groupby(["match_id", "innings_no"], sort=False)
        .tail(1)[["match_id", "innings_no", "cum_runs"]]
        .rename(columns={"cum_runs": "future_score"})
    )

    out = candidates.merge(target_rows, on=["match_id", "innings_no"], how="inner")
    if out.empty:
        return out
    out["future_score"] = out["future_score"].astype(float)
    out["future_runs"] = out["future_score"] - out["cum_runs"]
    return out

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


def backtest_session_and_win(history_df, target_runs=50, horizon_balls=24, sample_size=100, seed=42):
    """Time-safe historical backtest: each test state excludes its own match."""
    if history_df.empty:
        return None
    h = history_df.copy()
    # Keep states that have a meaningful future horizon. We test a fixed 24-ball session
    # because it is a common, simple benchmark and avoids cherry-picking a target.
    candidates = h[h.ball_pos <= 96].copy()
    if candidates.empty:
        return None
    rng = np.random.default_rng(seed)
    keys = candidates[["match_id", "innings_no"]].drop_duplicates()
    n = min(sample_size, len(keys))
    chosen = keys.iloc[rng.choice(len(keys), size=n, replace=False)]

    session_hits = []
    session_probs = []
    win_hits = []
    win_probs = []
    session_actuals = []
    win_actuals = []
    used_states = 0

    grouped = h.groupby(["match_id", "innings_no"], sort=False)
    for _, keyrow in chosen.iterrows():
        match_id = keyrow.match_id
        innings_no_bt = int(keyrow.innings_no)
        own = grouped.get_group((match_id, innings_no_bt))
        # Choose a real historical state, avoiding the very first few balls.
        usable = own[(own.ball_pos >= 12) & (own.ball_pos <= 96)].copy()
        if usable.empty:
            continue
        state = usable.iloc[int(rng.integers(0, len(usable)))]
        current_ball_bt = int(state.ball_pos)
        target_ball_bt = current_ball_bt + int(horizon_balls)

        # Actual session outcome at/before the same fixed horizon.
        future = own[own.ball_pos <= target_ball_bt]
        if future.empty:
            continue
        actual_future_score = float(future.iloc[-1].cum_runs)
        # Use the same target for every test state. This avoids the invalid
        # practice of defining the target from the already-known future outcome.
        target_bt = float(target_runs)

        # Exclude the current match entirely to prevent leakage.
        pool = h[(h.innings_no == innings_no_bt) & (h.match_id != match_id)].copy()
        if pool.empty:
            continue
        pool = pool[pool.ball_pos.between(max(1, current_ball_bt-1), current_ball_bt+1)]
        pool = pool[(pool.cum_runs-state.cum_runs).abs() <= 20]
        pool = pool[(pool.cum_wk-state.cum_wk).abs() <= 3]
        if pool.empty:
            continue

        pool["team_score"] = (pool.batting_team == state.batting_team).astype(float) + 0.8*(pool.bowling_team == state.bowling_team).astype(float)
        pool["ground_score"] = (pool.venue == state.venue).astype(float)
        pool["ball_score"] = np.exp(-((pool.ball_pos-current_ball_bt).abs())/2.5)
        pool["score_score"] = np.exp(-((pool.cum_runs-state.cum_runs).abs())/7.0)
        pool["wk_score"] = np.exp(-((pool.cum_wk-state.cum_wk).abs())/1.2)
        pool["similarity"] = (0.28*pool.score_score + 0.18*pool.wk_score + 0.18*pool.ball_score + 0.18*pool.ground_score + 0.18*(pool.team_score/1.8))
        pool["weight"] = pool.similarity.clip(lower=0.05)

        # Session probability: historical probability of reaching the fixed target
        # by the same horizon. The test match itself is excluded from the pool.
        future_rows=[]
        for (mid, inn), g in pool.groupby(["match_id","innings_no"], sort=False):
            f=g[g.ball_pos <= target_ball_bt]
            if f.empty:
                continue
            # g only contains states near current ball; retrieve the full innings.
            try:
                full = grouped.get_group((mid, inn))
            except KeyError:
                continue
            ff=full[full.ball_pos <= target_ball_bt]
            if ff.empty:
                continue
            first=g.iloc[0]
            # Use the closest current state from this historical innings.
            idx=(g.ball_pos-current_ball_bt).abs().idxmin()
            first=g.loc[idx]
            actual=float(ff.iloc[-1].cum_runs-first.cum_runs)
            future_rows.append((mid, inn, actual, float(first.weight)))
        if not future_rows:
            continue
        fr=pd.DataFrame(future_rows, columns=["match_id","innings_no","future_score","weight"])
        session_prob=100*float(np.average((fr.future_score >= target_bt).astype(float), weights=fr.weight))
        # Actual event in the held-out match.
        actual_session = 1.0 if actual_future_score >= target_bt else 0.0
        session_hits.append(1.0 if (session_prob >= 50) == bool(actual_session) else 0.0)
        session_probs.append(session_prob)
        session_actuals.append(actual_session)

        # Win probability: same-match outcome is held out from the candidate pool.
        pool["won_flag"]=(pool.winner==pool.batting_team).astype(float)
        valid=pool[pool.winner.str.strip() != ""]
        if not valid.empty and valid.weight.sum()>0:
            win_prob=100*float(np.average(valid.won_flag, weights=valid.weight))
            actual_win=1.0 if str(state.winner)==str(state.batting_team) else 0.0
            win_hits.append(1.0 if (win_prob >= 50)==bool(actual_win) else 0.0)
            win_probs.append(win_prob)
            win_actuals.append(actual_win)
        used_states += 1

    if used_states == 0:
        return None
    return {
        "states": used_states,
        "session_directional_accuracy": 100*float(np.mean(session_hits)) if session_hits else None,
        "session_avg_probability": float(np.mean(session_probs)) if session_probs else None,
        "win_directional_accuracy": 100*float(np.mean(win_hits)) if win_hits else None,
        "win_avg_probability": float(np.mean(win_probs)) if win_probs else None,
        "session_probs": session_probs,
        "session_actuals": session_actuals,
        "win_probs": win_probs,
        "win_actuals": win_actuals,
    }

with st.expander("🧪 VasuDev Historical Validation (advanced)", expanded=False):
    st.caption("Advanced validation runs only when requested. It uses held-out historical match states and never changes a result just to make the percentage look higher.")
    if st.button("▶ Run Historical Validation", use_container_width=True):
        if history.empty:
            with st.spinner("Loading historical cricket data..."):
                history = load_history(league, str(selected_db))
        with st.spinner("Validating VasuDev on historical situations..."):
            bt = backtest_session_and_win(history, target_runs=target_runs, horizon_balls=remaining, sample_size=100, seed=42)
        if bt is None:
            st.warning("Not enough historical data for validation.")
        else:
            a,b,c,d=st.columns(4)
            if bt["session_directional_accuracy"] is not None:
                a.metric("Session accuracy", f"{bt['session_directional_accuracy']:.1f}%")
            if bt["win_directional_accuracy"] is not None:
                b.metric("WIN accuracy", f"{bt['win_directional_accuracy']:.1f}%")
            c.metric("Test states", bt["states"])
            if bt["session_avg_probability"] is not None:
                d.metric("Avg session probability", f"{bt['session_avg_probability']:.1f}%")
            st.info("These are measured results on held-out historical states. They are not a guarantee of future accuracy and are not used to manufacture a preferred percentage.")
            if bt.get("session_probs") and bt.get("session_actuals"):
                probs=np.asarray(bt["session_probs"],dtype=float)/100.0
                actuals=np.asarray(bt["session_actuals"],dtype=float)
                st.write(f"Session Brier score: **{np.mean((probs-actuals)**2):.4f}** (lower is better)")
            if bt.get("win_probs") and bt.get("win_actuals"):
                probs=np.asarray(bt["win_probs"],dtype=float)/100.0
                actuals=np.asarray(bt["win_actuals"],dtype=float)
                st.write(f"WIN Brier score: **{np.mean((probs-actuals)**2):.4f}** (lower is better)")

if st.button("🔎 ANALYZE VASUDEV", use_container_width=True, disabled=(target_ball<=current_ball)):
    # Load the large historical dataframe only when the user actually analyzes.
    # This keeps password unlock and normal page interaction fast.
    if history.empty:
        with st.spinner("Loading historical cricket data..."):
            history = load_history(league, str(selected_db))
    if history.empty:
        st.error("Historical data could not be loaded for this league.")
        st.stop()

    # Final user-facing output is intentionally compact. Detailed calculations
    # remain available in the optional Details expander.
    win_df=historical_win_similarity(batting,bowling,venue,innings_no,current_ball,current_runs,wickets)
    win_pct=loss_pct=other_pct=0.0
    win_samples=0
    if win_df is not None and len(win_df):
        valid_result=win_df[win_df.winner.str.strip() != ""].copy()
        if len(valid_result):
            won=(valid_result.winner==valid_result.batting_team)
            lost=(valid_result.winner==valid_result.bowling_team)
            other=~(won|lost)
            ww=float(valid_result.loc[won,"weight"].sum())
            lw=float(valid_result.loc[lost,"weight"].sum())
            ow=float(valid_result.loc[other,"weight"].sum())
            total=ww+lw+ow
            if total>0:
                win_pct=100*ww/total
                loss_pct=100*lw/total
                other_pct=100*ow/total
            win_samples=len(valid_result)

    cand,method=similarity_candidates(batting,bowling,venue,innings_no,current_ball,current_runs,wickets,target_ball)
    session_yes=session_no=0.0
    session_samples=0
    session_target_yes=0
    session_target_no=0
    expected_score=None
    range_low=range_high=None
    if not cand.empty:
        cand=add_future_scores(cand,target_ball)
    if not cand.empty:
        cand["hit"]=(cand.future_score>=target_runs).astype(float)
        session_target_yes=int(cand["hit"].sum())
        session_target_no=int(len(cand)-session_target_yes)
        session_yes=weighted_pct(cand.hit.to_numpy(),cand.weight.to_numpy())
        session_no=100-session_yes
        session_samples=len(cand)
        expected_score=float(np.average(cand.future_score,weights=cand.weight))
        range_low=float(cand.future_score.quantile(.10))
        range_high=float(cand.future_score.quantile(.90))

    def reliability(n):
        if n>=500: return "High"
        if n>=100: return "Good"
        if n>=30: return "Medium"
        return "Limited"

    st.subheader("🧠 VasuDev Result")
    st.caption(f"{league} • {batting} vs {bowling} • {innings_label} • {venue}")

    st.markdown("### 🏆 WINNING")
    if win_samples:
        win_box = "result_win" if win_pct >= loss_pct else "result_loss"
        st.markdown(
            f"<div class=\"{win_box}\"><h2>{batting} WIN — {win_pct:.1f}%</h2>"
            f"<h3>LOSS — {loss_pct:.1f}%</h3>"
            f"<p class=\"small\">Historical probability • {win_samples:,} similar match states • Reliability: {reliability(win_samples)}</p></div>",
            unsafe_allow_html=True
        )
    else:
        st.info("Not enough historical match-result data for this situation.")

    st.markdown("### 🎯 SESSION")
    if session_samples:
        label="YES" if session_yes>=session_no else "NO"
        pct=max(session_yes,session_no)
        box="result_yes" if label=="YES" else "result_no"
        st.markdown(f"<div class=\"{box}\"><h1>{label} — {pct:.1f}%</h1><p>Target <b>{target_runs}</b> by <b>{over_ball_from_balls(target_ball)}</b> • {remaining} balls remaining</p><p class=\"small\">Historical probability • {session_samples:,} similar situations • Reliability: {reliability(session_samples)}</p></div>",unsafe_allow_html=True)
    else:
        st.info("Not enough historical continuation data for this session.")

    st.caption("Probabilities are calculated from historical data and validated methods. They are not guarantees; the final decision remains with the user.")

    # ---------- Historical average-run + scoring-trend results ----------
    # These are the only two additional historical result boxes. WINNING and
    # SESSION above are intentionally left unchanged.
    def historical_extra_results(candidates, current_ball, target_ball, current_runs):
        """Fast historical average/trend calculation for only the selected window.

        The expensive old version repeatedly scanned every innings for every ball.
        This version builds the relevant historical future rows in one merge, so
        the calculation stays limited to the selected current->future window.
        """
        if candidates is None or candidates.empty or target_ball <= current_ball:
            return None

        base = candidates.copy()
        base["distance"] = (base.ball_pos - current_ball).abs()
        base = base.sort_values(["distance", "weight"], ascending=[True, False])
        # One representative state per historical innings.
        base = base.drop_duplicates(["match_id", "innings_no"], keep="first")
        if base.empty:
            return None

        starts = base[["match_id", "innings_no", "ball_pos", "cum_runs", "weight"]].copy()
        starts = starts.rename(columns={
            "ball_pos": "start_ball",
            "cum_runs": "start_score",
            "weight": "start_weight",
        })
        starts["case_id"] = np.arange(len(starts), dtype=np.int32)

        # Only bring in historical deliveries from innings that actually matched.
        future_pool = history[["match_id", "innings_no", "ball_pos", "cum_runs", "runs"]].copy()
        future = starts.merge(future_pool, on=["match_id", "innings_no"], how="inner")
        future = future[
            (future.ball_pos > future.start_ball) &
            (future.ball_pos <= target_ball)
        ].copy()
        if future.empty:
            return None

        # Total runs added from the matched current state to the selected future point.
        end_scores = (
            future.sort_values(["case_id", "ball_pos"])
            .groupby("case_id", sort=False)
            .tail(1)[["case_id", "cum_runs"]]
            .rename(columns={"cum_runs": "future_score"})
        )
        case_table = starts.merge(end_scores, on="case_id", how="inner")
        if case_table.empty:
            return None

        case_table["future_runs"] = case_table["future_score"] - case_table["start_score"]
        totals = case_table["future_runs"].to_numpy(dtype=float)
        weights = case_table["start_weight"].to_numpy(dtype=float)
        avg_added = (
            float(np.average(totals, weights=weights))
            if weights.sum() > 0 else float(np.mean(totals))
        )
        projected_score = float(current_runs + avg_added)

        # User-facing sample breakdown around the rounded average.
        avg_threshold = safe_round(avg_added)
        reached = int((case_table["future_runs"] >= avg_threshold).sum())
        below = int((case_table["future_runs"] < avg_threshold).sum())
        total_cases = int(len(case_table))
        match_count = int(case_table[["match_id", "innings_no"]].drop_duplicates().shape[0])

        # Scoring trend: check every legal ball in the selected window.
        # For each checkpoint, average the most recent six legal-ball runs.
        trend_rows = []
        future = future.sort_values(["case_id", "ball_pos"])
        for cp in range(current_ball + 1, target_ball + 1):
            window = future[
                (future.ball_pos <= cp) &
                (future.ball_pos >= cp - 5)
            ]
            if window.empty:
                continue
            rates = window.groupby("case_id", sort=False)["runs"].sum()
            if len(rates):
                trend_rows.append({
                    "ball": cp,
                    "avg_6ball_runs": float(rates.mean()),
                })

        trend = pd.DataFrame(trend_rows)
        trend_summary = None
        if not trend.empty:
            trend["change"] = trend["avg_6ball_runs"].diff()
            if len(trend) > 1:
                biggest_up = trend.loc[trend["change"].idxmax()]
                biggest_down = trend.loc[trend["change"].idxmin()]
            else:
                biggest_up = biggest_down = trend.iloc[0]

            if len(trend) > 1:
                if abs(float(biggest_up["change"])) >= abs(float(biggest_down["change"])):
                    direction = "increase"
                    change_ball = int(biggest_up["ball"])
                    change_value = float(biggest_up["change"])
                else:
                    direction = "decrease"
                    change_ball = int(biggest_down["ball"])
                    change_value = float(biggest_down["change"])
            else:
                direction = "increase" if float(biggest_up["change"]) >= 0 else "decrease"
                change_ball = int(biggest_up["ball"])
                change_value = float(biggest_up["change"]) if pd.notna(biggest_up["change"]) else 0.0

            trend_summary = {
                "change_ball": change_ball,
                "change_value": change_value,
                "direction": direction,
            }

        return {
            "cases": total_cases,
            "match_count": match_count,
            "avg_added": avg_added,
            "projected_score": projected_score,
            "avg_threshold": avg_threshold,
            "reached": reached,
            "below": below,
            "trend": trend_summary,
        }

    extra = historical_extra_results(cand, current_ball, target_ball, current_runs)

    st.markdown("### 📊 HISTORICAL AVERAGE & SCORING CHANGE")
    if extra is None:
        st.info("Not enough historical data for the selected situation.")
    else:
        c3, c4 = st.columns(2)
        with c3:
            st.markdown(
                f'<div class="result_avg"><h3>📈 HISTORICAL AVERAGE</h3>'
                f'<h1>+{safe_round(extra["avg_added"])} runs</h1>'
                f'<p>Current <b>{current_runs}</b> → historical average future score <b>{safe_round(extra["projected_score"])}</b></p>'
                f'<p><b>{extra["reached"]:,}</b> of <b>{extra["cases"]:,}</b> similar innings reached <b>{extra["avg_threshold"]}+ runs</b>; '
                f'<b>{extra["below"]:,}</b> stayed below.</p>'
                f'<p class="small">{target_ball-current_ball} legal balls • {extra["cases"]:,} similar innings from {extra["match_count"]:,} matches</p></div>',
                unsafe_allow_html=True,
            )
        with c4:
            tr = extra["trend"]
            if tr is None:
                trend_text = "Not enough ball-by-ball data"
            else:
                change_ball = over_ball_from_balls(tr["change_ball"])
                change_value = safe_round(abs(tr["change_value"]))
                if tr["direction"] == "increase":
                    change_word = "increased"
                    sign = "+"
                else:
                    change_word = "decreased"
                    sign = "-"
                trend_text = (
                    f'<p><b>Biggest scoring change:</b> after <b>{change_ball}</b></p>'
                    f'<h2>{change_word.title()} by {sign}{change_value} runs / 6 balls</h2>'
                )
            st.markdown(
                f'<div class="result_avg"><h3>🔄 AVG SCORING CHANGE</h3>{trend_text}'
                f'<p class="small">Checked at every legal ball from {over_ball_from_balls(current_ball+1)} to {over_ball_from_balls(target_ball)}.</p></div>',
                unsafe_allow_html=True,
            )

    with st.expander("Details (optional)", expanded=False):
        st.write(f"**Current:** {current_runs}/{wickets} at {over_ball_from_balls(current_ball)} → **Future:** {over_ball_from_balls(target_ball)} → **Target:** {target_runs}")
        if session_samples:
            st.write(f"YES: **{session_yes:.1f}%** • NO: **{session_no:.1f}%**")
            st.write(f"Expected score at future point: **{safe_round(expected_score)}** • Historical 10–90% range: **{safe_round(range_low)}–{safe_round(range_high)}**")
            st.caption(f"Similarity: {method}. Team, ground, score, wickets and ball position are weighted; broader {league} data is used when exact situations are sparse.")

            st.markdown("### 🔎 WHY THIS RESULT?")
            st.write(
                f"• **{session_samples:,}** similar historical situations were used from **{extra['match_count']:,} matches**."
            )
            st.write(
                f"• The historical calculation gave **{session_yes:.1f}% YES** because the selected target was reached in **{session_target_yes:,} of {session_samples:,}** cases; **{session_target_no:,}** did not reach it."
            )
            st.write(
                f"• The result is **weighted**, so closer matches to the current team, ground, score, wickets and ball position have more influence than weaker matches."
            )
            st.write(
                f"• Historical average added **+{safe_round(extra['avg_added'])} runs**, giving a projected score of **{safe_round(extra['projected_score'])}** by {over_ball_from_balls(target_ball)}."
            )
            if extra.get("trend") is not None:
                tr = extra["trend"]
                direction_word = "increased" if tr["direction"] == "increase" else "decreased"
                st.write(
                    f"• Scoring trend {direction_word} by about **{safe_round(abs(tr['change_value']))} runs per 6 balls** around {over_ball_from_balls(tr['change_ball'])}."
                )

        if win_samples:
            st.write(f"WIN: **{win_pct:.1f}%** • LOSS: **{loss_pct:.1f}%** • Other/Tie: **{other_pct:.1f}%**")
            st.write(
                f"• WIN/LOSS is calculated separately from historical match outcomes using **{win_samples:,}** similar match states; the percentage is not manually increased."
            )
        st.write("VasuDev does not manually increase a probability to make it look better. Advanced validation/backtesting is kept separate from the live result.")
