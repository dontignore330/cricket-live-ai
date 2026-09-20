# VasuDev V2 - complete app.py
# Paste this whole file over your current app.py.

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

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()
if not APP_PASSWORD:
    st.error("🔒 VasuDev is locked. Hosting setup is incomplete: set the VASUDEV_PASSWORD secret.")
    st.stop()

if "vasudev_authenticated" not in st.session_state:
    st.session_state.vasudev_authenticated = False

if not st.session_state.vasudev_authenticated:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top right, #17365d 0%, transparent 35%),
                linear-gradient(180deg, #061426 0%, #081c35 100%);
            color: #f8fafc;
        }
        .block-container {
            max-width: 1400px;
            padding-top: 1.1rem;
            padding-bottom: 2rem;
        }
        h1, h2, h3, h4, p, label {
            color: #f8fafc !important;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
            margin-bottom: 3px;
        }
        .horse-logo {
            width: 58px;
            height: 58px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 16px;
            background: #102d50;
            border: 1px solid #365b86;
            box-shadow: 0 8px 22px rgba(0, 0, 0, .28);
            font-size: 36px;
        }
        .brand-name {
            font-size: 2.35rem;
            line-height: 1;
            font-weight: 800;
            letter-spacing: .4px;
            color: #ffffff;
        }
        .brand-subtitle {
            color: #a9bed8;
            font-size: .92rem;
            margin-top: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="brand">
            <div class="horse-logo">🐎</div>
            <div>
                <div class="brand-name">VasuDev</div>
                <div class="brand-subtitle">
                    Cricket Historical & Situation Analyzer
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at top right, #17365d 0%, transparent 35%),
            linear-gradient(180deg, #061426 0%, #081c35 100%);
        color: #f8fafc;
    }

    .block-container {
        max-width: 1400px;
        padding-top: 1.1rem;
        padding-bottom: 2rem;
    }

    h1, h2, h3, h4, p, label {
        color: #f8fafc !important;
    }

    .brand {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 3px;
    }

    .horse-logo {
        width: 58px;
        height: 58px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 16px;
        background: #102d50;
        border: 1px solid #365b86;
        box-shadow: 0 8px 22px rgba(0, 0, 0, .28);
        font-size: 36px;
    }

    .brand-name {
        font-size: 2.35rem;
        line-height: 1;
        font-weight: 800;
        letter-spacing: .4px;
        color: #ffffff;
    }

    .brand-subtitle {
        color: #a9bed8;
        font-size: .92rem;
        margin-top: 6px;
    }

    .card {
        background: rgba(15, 34, 60, .94);
        padding: 18px;
        border-radius: 16px;
        border: 1px solid #284a72;
        box-shadow: 0 8px 26px rgba(0, 0, 0, .18);
    }

    .result_yes {
        background: linear-gradient(135deg, #06351f, #0b6040);
        padding: 22px;
        border-radius: 16px;
        border: 2px solid #20c77a;
        text-align: center;
        box-shadow: 0 8px 26px rgba(0, 0, 0, .2);
    }

    .result_no {
        background: linear-gradient(135deg, #421010, #681b1b);
        padding: 22px;
        border-radius: 16px;
        border: 2px solid #ef5350;
        text-align: center;
        box-shadow: 0 8px 26px rgba(0, 0, 0, .2);
    }

    .small {
        color: #b6c7da !important;
        font-size: 13px;
    }

    div[data-testid="stSelectbox"] label,
    div[data-testid="stNumberInput"] label {
        color: #d9e7f7 !important;
    }

    div.stButton > button {
        border-radius: 11px;
        min-height: 42px;
        font-weight: 700;
        border: 1px solid #3c6795;
        background: #12365f;
        color: white;
    }

    div.stButton > button:hover {
        border-color: #76a9df;
        background: #194a7e;
        color: white;
    }

    [data-testid="stMetricValue"] {
        color: #ffffff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="brand">
        <div class="horse-logo">🐎</div>
        <div>
            <div class="brand-name">VasuDev</div>
            <div class="brand-subtitle">
                Cricket Historical & Situation Analyzer
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------- UTILS ----------------

def parse_delivery(value, over_no):
    try:
        left, right = str(value).strip().split(".", 1)
        over = int(left)
        ball = int(right)
        if over < 0 or ball <= 0:
            raise ValueError
        return over * 6 + ball, f"{over}.{ball}"
    except Exception:
        return None, None


def _json_match_to_sqlite(db_path, league, zip_path):
    tmp_db = db_path.with_suffix(db_path.suffix + ".tmp")
    if tmp_db.exists():
        try:
            tmp_db.unlink()
        except Exception:
            pass

    out = sqlite3.connect(str(tmp_db))
    try:
        out.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT)")
        out.execute(
            """
            CREATE TABLE deliveries (
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
            )
            """
        )

        match_rows = []
        delivery_rows = []

        with zipfile.ZipFile(zip_path) as zf:
            json_files = [n for n in zf.namelist() if n.endswith(".json")]
            for name in json_files:
                try:
                    data = json.loads(zf.read(name))
                    info = data.get("info", {})
                    teams = info.get("teams", [])
                    if len(teams) < 2:
                        continue

                    outcome = info.get("outcome", {}) or {}
                    winner = (
                        outcome.get("winner", "")
                        or outcome.get("eliminator", "")
                        or outcome.get("bowl_out", "")
                        or ""
                    )

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
                                delivery_rows.append(
                                    (
                                        match_id,
                                        innings_no,
                                        batting_team,
                                        bowling_team,
                                        over_no,
                                        ball_no,
                                        runs,
                                        wickets,
                                        league,
                                    )
                                )

                except Exception:
                    continue

        if match_rows:
            out.executemany(
                "INSERT OR REPLACE INTO matches VALUES (?,?,?,?)",
                match_rows,
            )

        if delivery_rows:
            out.executemany(
                """
                INSERT INTO deliveries
                (match_id, innings_no, batting_team, bowling_team, over_no, ball_no, runs, wickets, league)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                delivery_rows,
            )

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

    tmp_db = db_path.with_suffix(db_path.suffix + ".building")

    try:
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except Exception:
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "matches.zip"
            urllib.request.urlretrieve(DATA_URLS[league], zip_path)
            _json_match_to_sqlite(tmp_db, league, zip_path)

        tmp_db.replace(db_path)
        return db_path, True

    except Exception as exc:
        if tmp_db.exists():
            try:
                tmp_db.unlink()
            except Exception:
                pass
        if db_path.exists():
            try:
                db_path.unlink()
            except Exception:
                pass
        raise RuntimeError(f"Could not prepare {league} historical data: {exc}") from exc


@st.cache_resource(show_spinner=False)
def get_cached_db_connection(db_path_str):
    db_path = Path(db_path_str)

    if not db_path.exists():
        return None

    conn = sqlite3.connect(
        f"file:{db_path.resolve()}?mode=ro",
        uri=True,
        check_same_thread=False,
        cached_statements=512,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-64000")
    return conn


@st.cache_data(show_spinner=False)
def get_database_counts(db_path_str):
    db_path = Path(db_path_str)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with closing(
        sqlite3.connect(
            f"file:{db_path.resolve()}?mode=ro",
            uri=True,
            check_same_thread=False,
            cached_statements=128,
            timeout=30,
        )
    ) as count_conn:
        match_count = count_conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        delivery_count = count_conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]

    return int(match_count), int(delivery_count)


@st.cache_data(show_spinner=False, max_entries=8)
def load_history(selected_league, db_path_str):
    db_path = Path(db_path_str)

    if not db_path.exists():
        return pd.DataFrame()

    query = """
        SELECT
            d.match_id,
            d.innings_no,
            d.batting_team,
            d.bowling_team,
            d.over_no,
            d.ball_no,
            d.runs,
            d.wickets,
            d.id,
            m.venue,
            m.winner
        FROM deliveries AS d
        INNER JOIN matches AS m
            ON m.match_id = d.match_id
        WHERE d.league = ?
        ORDER BY d.match_id, d.innings_no, d.id
    """

    with closing(
        sqlite3.connect(
            f"file:{db_path.resolve()}?mode=ro",
            uri=True,
            check_same_thread=False,
            cached_statements=512,
            timeout=30,
        )
    ) as history_conn:
        df = pd.read_sql_query(query, history_conn, params=(selected_league,))

    if df.empty:
        return df

    def parse_ball_position(value):
        try:
            whole, ball = str(value).split(".", 1)
            whole = int(whole)
            ball = int(ball)
            if whole < 0 or ball < 0:
                raise ValueError
            return whole * 6 + ball
        except Exception:
            return np.nan

    df["ball_pos"] = df["ball_no"].map(parse_ball_position)
    df = df.dropna(subset=["ball_pos"]).copy()

    if df.empty:
        return df

    df["ball_pos"] = df["ball_pos"].astype("int32")
    df["runs"] = pd.to_numeric(df["runs"], errors="coerce").fillna(0).astype("int16")
    df["wickets"] = pd.to_numeric(df["wickets"], errors="coerce").fillna(0).astype("int8")

    for col in ["batting_team", "bowling_team", "venue", "winner"]:
        df[col] = df[col].fillna("").astype(str)

    groups = ["match_id", "innings_no"]
    grouped = df.groupby(groups, sort=False)

    df["cum_runs"] = grouped["runs"].cumsum().astype("int32")
    df["cum_wk"] = grouped["wickets"].cumsum().astype("int16")
    df["current_rr"] = np.where(df["ball_pos"] > 0, df["cum_runs"] / df["ball_pos"] * 6.0, 0.0)

    runs_last6 = []
    runs_last12 = []
    runs_last18 = []

    for _, group in grouped:
        positions = group["ball_pos"].to_numpy(dtype=np.int32)
        cumulative_runs = group["cum_runs"].to_numpy(dtype=np.float64)

        last6 = []
        last12 = []
        last18 = []

        for position, total_runs in zip(positions, cumulative_runs):
            idx6 = np.searchsorted(positions, position - 6, side="right") - 1
            idx12 = np.searchsorted(positions, position - 12, side="right") - 1
            idx18 = np.searchsorted(positions, position - 18, side="right") - 1

            prev6 = cumulative_runs[idx6] if idx6 >= 0 else 0.0
            prev12 = cumulative_runs[idx12] if idx12 >= 0 else 0.0
            prev18 = cumulative_runs[idx18] if idx18 >= 0 else 0.0

            last6.append(max(0.0, total_runs - prev6))
            last12.append(max(0.0, total_runs - prev12))
            last18.append(max(0.0, total_runs - prev18))

        runs_last6.extend(last6)
        runs_last12.extend(last12)
        runs_last18.extend(last18)

    df["runs_last6"] = runs_last6
    df["runs_last12"] = runs_last12
    df["runs_last18"] = runs_last18
    df["rr_last12"] = df["runs_last12"] / 2.0
    df["momentum"] = df["rr_last12"] - df["current_rr"]

    return df


def get_values(sql, params=(), conn=None):
    if conn is None:
        return []
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
    over = (balls - 1) // 6
    ball = ((balls - 1) % 6) + 1
    return f"{over}.{ball}"


def valid_over_ball_options(max_over=20):
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


# ---------------- APP ----------------

league = st.selectbox("🏆 League", ["IPL", "Men's Big Bash League", "Women's Big Bash League"], index=0)

if league != "IPL":
    try:
        selected_db, built_now = ensure_bigbash_db(league)
    except Exception as exc:
        st.error(str(exc))
        st.info("IPL remains available. Reload after the hosting service has internet access to prepare Big Bash data.")
        st.stop()
else:
    selected_db = DB_PATHS["IPL"]
    built_now = False

conn = get_cached_db_connection(str(selected_db))
if conn is None:
    st.error(f"Historical database for {league} not found.")
    st.stop()

try:
    match_count, delivery_count = get_database_counts(str(selected_db))
except Exception as e:
    st.error(f"Database could not be read: {e}")
    st.stop()

st.success(f"{league} historical database connected • {match_count:,} matches • {delivery_count:,} deliveries")
if built_now:
    st.caption(f"{league} data prepared automatically and opened read-only for analysis.")
else:
    st.write(f"Compare the live cricket situation with similar historical {league} situations.")

history = load_history(league, str(selected_db))

teams = get_values(
    "SELECT DISTINCT batting_team FROM deliveries WHERE league=? ORDER BY batting_team",
    (league,),
    conn=conn,
)
venues = get_values(
    "SELECT DISTINCT venue FROM matches WHERE league=? AND venue IS NOT NULL AND venue<>'' ORDER BY venue",
    (league,),
    conn=conn,
)

if not teams:
    st.error(f"No teams were found for {league}.")
    st.stop()

if not venues:
    venues = ["Unknown Ground"]

# ---------------- UI ----------------

st.subheader("🏏 Current Match")
c1, c2, c3 = st.columns(3)

with c1:
    preferred_bat = {
        "IPL": "Sunrisers Hyderabad",
        "Men's Big Bash League": "Melbourne Stars",
        "Women's Big Bash League": "Sydney Sixers",
    }.get(league)
    default_bat = preferred_bat if preferred_bat in teams else teams[0]
    batting = st.selectbox("Batting Team", teams, index=teams.index(default_bat))

with c2:
    bowling_options = [x for x in teams if x != batting]
    preferred_bowl = {
        "IPL": "Rajasthan Royals",
        "Men's Big Bash League": "Sydney Sixers",
        "Women's Big Bash League": "Sydney Thunder",
    }.get(league)
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

# ---------------- LIVE TREND ----------------

def estimate_live_trend():
    if history.empty:
        return {"runs_last6": 0.0, "runs_last12": 0.0, "runs_last18": 0.0, "momentum": 0.0}

    x = history[
        (history.innings_no == innings_no)
        & (history.ball_pos.between(max(1, current_ball - 1), current_ball + 1))
    ].copy()

    if x.empty:
        return {"runs_last6": 0.0, "runs_last12": 0.0, "runs_last18": 0.0, "momentum": 0.0}

    x["d"] = (
        ((x.cum_runs - current_runs).abs() / 8.0)
        + ((x.cum_wk - wickets).abs() / 1.5)
        + ((x.ball_pos - current_ball).abs() / 2.0)
    )

    x = x.sort_values("d").head(80)

    return {
        "runs_last6": float(x.runs_last6.mean()),
        "runs_last12": float(x.runs_last12.mean()),
        "runs_last18": float(x.runs_last18.mean()),
        "momentum": float(x.momentum.mean()),
    }


live = estimate_live_trend()

# ---------------- PHASE AWARE ----------------

def match_phase(ball_pos):
    ball_pos = int(ball_pos)

    if ball_pos <= 36:
        return "powerplay"
    if ball_pos <= 90:
        return "middle"
    return "death"


# ---------------- HISTORY SIMILARITY ----------------

def session_candidates():
    if history.empty or target_ball <= current_ball:
        return pd.DataFrame(), "No usable historical data"

    current_phase = match_phase(current_ball)

    x = history[
        (history.innings_no == innings_no)
        & (
            history.ball_pos.between(
                max(1, current_ball - 2),
                current_ball + 2,
            )
        )
    ].copy()

    if x.empty:
        return pd.DataFrame(), "No historical state near this ball"

    x["phase"] = x["ball_pos"].map(match_phase)
    x["phase_match"] = (x["phase"] == current_phase).astype(float)

    x = x[x.ball_pos < target_ball]
    x = x[(x.cum_runs - current_runs).abs() <= 30]
    x = x[(x.cum_wk - wickets).abs() <= 3]

    if x.empty:
        return pd.DataFrame(), "No similar historical states"

    live_required_rr = required_runs_live / max(1, target_ball - current_ball) * 6.0

    x["required_runs"] = (target_runs - x.cum_runs).clip(lower=0)
    x["remaining_balls"] = (target_ball - x.ball_pos).clip(lower=1)
    x["required_rr"] = x.required_runs / x.remaining_balls * 6.0

    x["s_score"] = np.exp(-((x.cum_runs - current_runs).abs()) / 10.0)
    x["s_wickets"] = np.exp(-((x.cum_wk - wickets).abs()) / 1.5)
    x["s_ball"] = np.exp(-((x.ball_pos - current_ball).abs()) / 2.5)
    x["s_rr"] = np.exp(-((x.current_rr - current_rr_live).abs()) / 1.8)
    x["s_required_rr"] = np.exp(-((x.required_rr - live_required_rr).abs()) / 2.2)
    x["s_last6"] = np.exp(-((x.runs_last6 - live["runs_last6"]).abs()) / 7.0)
    x["s_last12"] = np.exp(-((x.runs_last12 - live["runs_last12"]).abs()) / 10.0)
    x["s_momentum"] = np.exp(-((x.momentum - live["momentum"]).abs()) / 2.5)

    x["team_match"] = (
        (x.batting_team == batting).astype(float)
        + 0.85 * (x.bowling_team == bowling).astype(float)
    ) / 1.85

    x["ground_match"] = (x.venue == venue).astype(float)

    x["similarity"] = (
        0.18 * x["s_score"]
        + 0.10 * x["s_wickets"]
        + 0.08 * x["s_ball"]
        + 0.13 * x["s_rr"]
        + 0.17 * x["s_required_rr"]
        + 0.09 * x["s_last6"]
        + 0.09 * x["s_last12"]
        + 0.07 * x["s_momentum"]
        + 0.05 * x["team_match"]
        + 0.02 * x["ground_match"]
        + 0.02 * x["phase_match"]
    )

    x["weight"] = x["similarity"].clip(lower=0.03)

    return (
        x.sort_values("weight", ascending=False).head(1500),
        "Phase-aware V2: score + wickets + RR + required RR + recent trend + momentum + teams + ground",
    )


def add_future_scores(candidates):
    if candidates.empty:
        return candidates

    future_scores = (
        history.loc[
            history["ball_pos"] <= target_ball,
            ["match_id", "innings_no", "ball_pos", "cum_runs"],
        ]
        .sort_values(["match_id", "innings_no", "ball_pos"])
        .groupby(["match_id", "innings_no"], as_index=False, sort=False)
        .tail(1)
        .rename(columns={"cum_runs": "future_score"})
        [["match_id", "innings_no", "future_score"]]
    )

    if future_scores.empty:
        return pd.DataFrame()

    result = candidates.merge(
        future_scores,
        on=["match_id", "innings_no"],
        how="inner",
        sort=False,
    )

    if result.empty:
        return result

    result["future_score"] = result["future_score"].astype(float)
    result["future_runs"] = result["future_score"] - result["cum_runs"].astype(float)
    return result


def win_candidates():
    if history.empty:
        return None

    current_phase = match_phase(current_ball)

    x = history[
        (history.innings_no == innings_no)
        & (
            history.ball_pos.between(
                max(1, current_ball - 2),
                current_ball + 2,
            )
        )
    ].copy()

    if x.empty:
        return None

    x["phase"] = x["ball_pos"].map(match_phase)
    x["phase_match"] = (x["phase"] == current_phase).astype(float)

    x = x[(x.cum_runs - current_runs).abs() <= 35]
    x = x[(x.cum_wk - wickets).abs() <= 3]
    x = x[x.winner.str.strip() != ""]

    if x.empty:
        return None

    x["s_score"] = np.exp(-((x.cum_runs - current_runs).abs()) / 11.0)
    x["s_wickets"] = np.exp(-((x.cum_wk - wickets).abs()) / 1.7)
    x["s_ball"] = np.exp(-((x.ball_pos - current_ball).abs()) / 2.5)
    x["s_rr"] = np.exp(-((x.current_rr - current_rr_live).abs()) / 2.0)
    x["s_last6"] = np.exp(-((x.runs_last6 - live["runs_last6"]).abs()) / 8.0)
    x["s_last12"] = np.exp(-((x.runs_last12 - live["runs_last12"]).abs()) / 11.0)
    x["s_momentum"] = np.exp(-((x.momentum - live["momentum"]).abs()) / 2.8)

    x["team_match"] = (
        (x.batting_team == batting).astype(float)
        + 0.85 * (x.bowling_team == bowling).astype(float)
    ) / 1.85

    x["ground_match"] = (x.venue == venue).astype(float)

    x["similarity"] = (
        0.21 * x["s_score"]
        + 0.13 * x["s_wickets"]
        + 0.09 * x["s_ball"]
        + 0.16 * x["s_rr"]
        + 0.12 * x["s_last6"]
        + 0.11 * x["s_last12"]
        + 0.08 * x["s_momentum"]
        + 0.06 * x["team_match"]
        + 0.02 * x["ground_match"]
        + 0.02 * x["phase_match"]
    )

    x["weight"] = x["similarity"].clip(lower=0.03)
    x["won_flag"] = (x.winner == x.batting_team).astype(float)

    return x.sort_values("weight", ascending=False).head(1500)


def reliability(n):
    if n >= 500:
        return "High"
    if n >= 150:
        return "Good"
    if n >= 50:
        return "Medium"
    if n >= 20:
        return "Limited"
    return "Very limited"


# ---------------- VALIDATION ----------------

def backtest_v2(history_df, target_delta_runs=20, horizon_balls=24, sample_size=150, seed=42):
    if history_df.empty:
        return None

    h = history_df[history_df.ball_pos <= 96].copy()
    if h.empty:
        return None

    rng = np.random.default_rng(seed)
    keys = h[["match_id", "innings_no"]].drop_duplicates().reset_index(drop=True)
    n = min(sample_size, len(keys))
    chosen = keys.iloc[rng.choice(len(keys), size=n, replace=False)]
    grouped = h.groupby(["match_id", "innings_no"], sort=False)

    session_hits, win_hits = [], []
    used = 0

    for _, k in chosen.iterrows():
        try:
            own = grouped.get_group((k.match_id, int(k.innings_no)))
        except KeyError:
            continue

        usable = own[own.ball_pos.between(12, 72)]
        if usable.empty:
            continue

        state = usable.iloc[int(rng.integers(0, len(usable)))]
        cur = int(state.ball_pos)

        future = own[own.ball_pos <= cur + horizon_balls]
        if future.empty:
            continue

        actual_future_runs = float(future.iloc[-1].cum_runs - state.cum_runs)

        pool = h[(h.innings_no == int(k.innings_no)) & (h.match_id != k.match_id)].copy()
        pool = pool[pool.ball_pos.between(max(1, cur - 1), cur + 1)]
        pool = pool[(pool.cum_runs - state.cum_runs).abs() <= 25]
        pool = pool[(pool.cum_wk - state.cum_wk).abs() <= 3]

        if pool.empty:
            continue

        pool["s"] = (
            0.20 * np.exp(-((pool.cum_runs - state.cum_runs).abs()) / 8.0)
            + 0.12 * np.exp(-((pool.cum_wk - state.cum_wk).abs()) / 1.35)
            + 0.10 * np.exp(-((pool.ball_pos - cur).abs()) / 2.0)
            + 0.14 * np.exp(-((pool.current_rr - state.current_rr).abs()) / 1.4)
            + 0.14 * np.exp(-((pool.runs_last12 - state.runs_last12).abs()) / 10.0)
            + 0.10 * np.exp(-((pool.runs_last6 - state.runs_last6).abs()) / 7.0)
            + 0.08 * np.exp(-((pool.momentum - state.momentum).abs()) / 2.5)
            + 0.07 * (pool.venue == state.venue).astype(float)
            + 0.05 * ((pool.batting_team == state.batting_team).astype(float))
        )

        pool["weight"] = pool.s.clip(lower=0.03)

        future_rows = []
        for (mid, inn), g in pool.groupby(["match_id", "innings_no"], sort=False):
            try:
                full = grouped.get_group((mid, inn))
            except KeyError:
                continue

            ff = full[full.ball_pos <= cur + horizon_balls]
            if ff.empty:
                continue

            first = g.loc[(g.ball_pos - cur).abs().idxmin()]
            future_rows.append((mid, float(ff.iloc[-1].cum_runs - first.cum_runs), float(first.weight)))

        if future_rows:
            fr = pd.DataFrame(future_rows, columns=["mid", "future_runs", "weight"])
            session_prob = 100 * float(np.average((fr.future_runs >= target_delta_runs).astype(float), weights=fr.weight))
            pred = 1 if session_prob >= 50 else 0
            actual = 1 if actual_future_runs >= target_delta_runs else 0
            session_hits.append(1.0 if pred == actual else 0.0)

        valid = pool[pool.winner.str.strip() != ""]
        if not valid.empty and valid.weight.sum() > 0:
            wp = 100 * float(np.average(valid.winner.eq(valid.batting_team).astype(float), weights=valid.weight))
            actual_w = 1 if str(state.winner) == str(state.batting_team) else 0
            win_hits.append(1.0 if (wp >= 50) == bool(actual_w) else 0.0)

        used += 1

    if used == 0:
        return None

    return {
        "states": used,
        "session_accuracy": 100 * float(np.mean(session_hits)) if session_hits else None,
        "win_accuracy": 100 * float(np.mean(win_hits)) if win_hits else None,
    }


@st.cache_data(show_spinner=False, max_entries=32)
def cached_backtest(history_df, target_delta_runs, horizon_balls, sample_size=150, seed=42):
    return backtest_v2(
        history_df,
        target_delta_runs=target_delta_runs,
        horizon_balls=horizon_balls,
        sample_size=sample_size,
        seed=seed,
    )


with st.expander("🧪 VasuDev Historical Validation (advanced)", expanded=False):
    st.caption("V2 validation uses held-out historical match states. The test match is excluded from its own comparison pool.")
    if st.button("▶ Run Historical Validation", use_container_width=True):
        with st.spinner("Validating VasuDev V2..."):
            bt = cached_backtest(
                history,
                target_delta_runs=max(1, int(required_runs_live)),
                horizon_balls=max(6, int(remaining)),
                sample_size=300,
                seed=42,
            )

        if bt is None:
            st.warning("Not enough historical data for validation.")
        else:
            a, b, c = st.columns(3)
            if bt["session_accuracy"] is not None:
                a.metric("Session accuracy", f"{bt['session_accuracy']:.1f}%")
            if bt["win_accuracy"] is not None:
                b.metric("WIN accuracy", f"{bt['win_accuracy']:.1f}%")
            c.metric("Test states", bt["states"])

            st.info("Validation is measurement only. It does not force the model toward 80% or any other number.")


# ---------------- FINAL ANALYZE ----------------

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
            win_pct = 100 * ww / total
            loss_pct = 100 * lw / total
            other_pct = 100 * ow / total
        win_samples = len(win_df)

    cand, method = session_candidates()
    session_yes = session_no = 0.0
    session_samples = 0
    expected_score = range_low = range_high = None

    if not cand.empty:
        cand = add_future_scores(cand)

    if not cand.empty:
        cand["hit"] = (cand.future_score >= target_runs).astype(float)
        session_yes = 100 * float(np.average(cand.hit.to_numpy(), weights=cand.weight.to_numpy()))
        session_no = 100 - session_yes
        session_samples = len(cand)
        expected_score = float(np.average(cand.future_score, weights=cand.weight))
        range_low = float(cand.future_score.quantile(0.10))
        range_high = float(cand.future_score.quantile(0.90))

    st.subheader("🧠 VasuDev Result")
    st.caption(f"{league} • {batting} vs {bowling} • {innings_label} • {venue}")

    st.markdown("### 🏆 WIN")
    if win_samples:
        st.markdown(
            f'<div class="card"><h2>{batting} WIN — {win_pct:.1f}%</h2>'
            f'<h3>LOSS — {loss_pct:.1f}%</h3>'
            f'<p class="small">Historical probability • {win_samples:,} similar match states • Reliability: {reliability(win_samples)}</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("Not enough historical match-result data for this situation.")

    st.markdown("### 🎯 SESSION")
    if session_samples:
        label = "YES" if session_yes >= session_no else "NO"
        pct = max(session_yes, session_no)

        if session_samples < 20:
            confidence_note = "Very limited sample"
        elif session_samples < 50:
            confidence_note = "Limited sample"
        elif pct < 55:
            confidence_note = "Close call"
        elif pct < 65:
            confidence_note = "Moderate confidence"
        else:
            confidence_note = "Strong historical signal"

        box = "result_yes" if label == "YES" else "result_no"

        st.markdown(
            f'<div class="{box}"><h1>{label} — {pct:.1f}%</h1>'
            f'<p>Target <b>{target_runs}</b> by <b>{over_ball_from_balls(target_ball)}</b> • {remaining} balls remaining</p>'
            f'<p class="small">Historical probability • {session_samples:,} similar situations • Reliability: {reliability(session_samples)} • {confidence_note}</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("Not enough historical continuation data for this session.")

    st.caption("Probabilities are calculated from historical data. They are not guarantees.")

    with st.expander("Details (optional)", expanded=False):
        st.write(
            f"**Current:** {current_runs}/{wickets} at {over_ball_from_balls(current_ball)} → "
            f"**Future:** {over_ball_from_balls(target_ball)} → **Target:** {target_runs}"
        )
        st.write(
            f"**Current RR:** {current_rr_live:.2f} • **Runs required:** {required_runs_live} • "
            f"**Required RR:** {required_rr_live:.2f}"
        )
        st.write(
            f"**Recent trend estimate:** last 6 = {live['runs_last6']:.1f}, "
            f"last 12 = {live['runs_last12']:.1f}, last 18 = {live['runs_last18']:.1f}"
        )

        if session_samples:
            st.write(f"YES: **{session_yes:.1f}%** • NO: **{session_no:.1f}%**")
            st.write(
                f"Expected score at future point: **{safe_round(expected_score)}** • "
                f"Historical 10–90% range: **{safe_round(range_low)}–{safe_round(range_high)}**"
            )
            st.caption(method)

        if win_samples:
            st.write(f"WIN: **{win_pct:.1f}%** • LOSS: **{loss_pct:.1f}%** • Other/Tie: **{other_pct:.1f}%**")

        st.write("V2 does not manually increase percentages. It changes the historical similarity features.")
