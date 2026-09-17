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

history = load_history(league)

teams = get_values("SELECT DISTINCT batting_team FROM deliveries WHERE league=? ORDER BY batting_team", (league,))
venues = get_values("SELECT DISTINCT venue FROM matches WHERE league=? AND venue IS NOT NULL AND venue<>'' ORDER BY venue", (league,))
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
        actual_future_runs = float(future.iloc[-1].cum_runs - state.cum_runs)
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
        fr=pd.DataFrame(future_rows, columns=["match_id","innings_no","future_runs","weight"])
        session_prob=100*float(np.average((fr.future_runs >= target_bt).astype(float), weights=fr.weight))
        # Actual event in the held-out match.
        actual_session = 1.0 if (float(future.iloc[-1].cum_runs) >= target_bt) else 0.0
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

with st.expander("🧪 VasuDev Historical Backtest", expanded=False):
    st.caption("This test uses past match states and excludes the same match from its comparison pool. It tests the current target over the current ball horizon; it is a directional backtest, not a guarantee of future accuracy.")
    if st.button("▶ Run Backtest", use_container_width=True):
        with st.spinner("Testing historical situations..."):
            bt = backtest_session_and_win(history, target_runs=target_runs, horizon_balls=remaining, sample_size=100, seed=42)
        if bt is None:
            st.warning("Not enough historical data for a backtest.")
        else:
            a,b,c,d=st.columns(4)
            if bt["session_directional_accuracy"] is not None:
                a.metric("Session direction accuracy", f"{bt['session_directional_accuracy']:.1f}%")
            if bt["win_directional_accuracy"] is not None:
                b.metric("WIN direction accuracy", f"{bt['win_directional_accuracy']:.1f}%")
            c.metric("Test states", bt["states"])
            if bt["session_avg_probability"] is not None:
                d.metric("Avg session probability", f"{bt['session_avg_probability']:.1f}%")
            if bt["win_avg_probability"] is not None:
                st.write(f"Average historical WIN probability across tested states: **{bt['win_avg_probability']:.1f}%**")
            st.info("Backtest accuracy is measured only on held-out historical states. It is a measurement of past performance, not a guarantee of future accuracy.")

            # Probability calibration: a 70% prediction should historically occur
            # close to 70% of the time. This checks the quality of the probabilities,
            # not just whether the final YES/NO direction was correct.
            if bt.get("session_probs") and bt.get("session_actuals"):
                probs = np.asarray(bt["session_probs"], dtype=float) / 100.0
                actuals = np.asarray(bt["session_actuals"], dtype=float)
                brier = float(np.mean((probs - actuals) ** 2))
                st.markdown("#### 🎯 Session Probability Calibration")
                st.write(f"Brier score: **{brier:.4f}** (0 is perfect)")
                bins=[]
                for lo,hi in [(0,20),(20,40),(40,60),(60,80),(80,100)]:
                    mask=(probs*100 >= lo) & (probs*100 < hi if hi < 100 else probs*100 <= hi)
                    if mask.any():
                        bins.append({"Predicted range":f"{lo}–{hi}%","Tests":int(mask.sum()),"Average predicted %":round(float(probs[mask].mean()*100),1),"Actual YES %":round(float(actuals[mask].mean()*100),1)})
                if bins:
                    st.dataframe(pd.DataFrame(bins), use_container_width=True, hide_index=True)
            if bt.get("win_probs") and bt.get("win_actuals"):
                probs = np.asarray(bt["win_probs"], dtype=float) / 100.0
                actuals = np.asarray(bt["win_actuals"], dtype=float)
                brier = float(np.mean((probs - actuals) ** 2))
                st.markdown("#### 🏆 WIN Probability Calibration")
                st.write(f"Brier score: **{brier:.4f}** (0 is perfect)")
                bins=[]
                for lo,hi in [(0,20),(20,40),(40,60),(60,80),(80,100)]:
                    mask=(probs*100 >= lo) & (probs*100 < hi if hi < 100 else probs*100 <= hi)
                    if mask.any():
                        bins.append({"Predicted range":f"{lo}–{hi}%","Tests":int(mask.sum()),"Average predicted %":round(float(probs[mask].mean()*100),1),"Actual WIN %":round(float(actuals[mask].mean()*100),1)})
                if bins:
                    st.dataframe(pd.DataFrame(bins), use_container_width=True, hide_index=True)

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
            st.caption(f"Similarity engine: {method}. Ground, team, score, wickets and ball position are weighted; broader selected-league data is used when exact situations are sparse.")
            if len(cand)<30:
                st.warning("Small historical sample: treat this result as low-data historical evidence.")
            elif len(cand)<100:
                st.info("Moderate historical sample: the result is based on similar situations, not exact duplicates.")
            else:
                st.success("Good historical sample size for this situation.")
    else:
        st.info("No exact match was required, but the database could not find a usable historical continuation for this future point. Try a later future point or another IPL situation.")

    st.markdown("### 🧩 How VasuDev handles rare situations")
    st.write("The system does not depend on one exact historical match from the selected league. It first uses close score/wicket/ball situations and gives extra weight to the selected ground and teams. If the exact combination is rare, it automatically broadens to similar IPL situations instead of simply showing Data Not Found.")
    st.caption("Player-level adjustment is reserved for the next data layer because the current cricket_history.db does not contain the current playing XI/player-at-ball fields. The present engine therefore does not invent player information.")
