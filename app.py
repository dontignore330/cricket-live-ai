# VasuDev V2 - final complete app.py
# Paste this whole file over your current app.py

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
    initial_sidebar_state="expanded",
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
        }
        .block-container {
            max-width: 1500px;
            padding-top: 1rem;
            padding-bottom: 2rem;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
            margin: 12px 0 18px 0;
            padding: 14px 18px;
            border-radius: 16px;
            background: linear-gradient(135deg, #0d294a, #102f54);
            border: 1px solid #31577f;
            box-shadow: 0 8px 24px rgba(0,0,0,.25);
        }
        .horse-logo {
            width: 74px;
            height: 62px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 16px;
            background: #ffffff;
            border: 1px solid #dbeafe;
            overflow: hidden;
            box-shadow: 0 8px 18px rgba(0,0,0,.2);
        }
        .horse-logo svg {
            width: 64px;
            height: 52px;
            display: block;
        }
        .brand-name {
            font-size: 2.25rem;
            font-weight: 800;
            color: #fff !important;
            letter-spacing: .3px;
            line-height: 1;
        }
        .brand-subtitle {
            margin-top: 6px;
            color: #b9cfe9 !important;
            font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="brand">
            <div class="horse-logo" aria-label="White running horse logo">
                <svg viewBox="0 0 180 120" xmlns="http://www.w3.org/2000/svg" role="img">
                    <g fill="none" stroke="#071d38" stroke-width="8" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M112 24 C126 13 145 15 157 25" />
                        <path d="M116 25 C106 36 102 49 105 61" />
                        <path d="M105 61 C112 70 126 73 139 68" />
                        <path d="M126 20 L124 7 L135 18" />
                        <path d="M139 20 L148 8 L150 25" />
                        <path d="M110 31 C98 26 91 31 88 42" />
                        <path d="M104 38 C94 39 90 48 91 57" />
                        <path d="M105 61 C91 54 75 55 61 64" />
                        <path d="M61 64 C48 72 46 86 58 91" />
                        <path d="M58 91 C78 101 108 96 124 80" />
                        <path d="M124 80 C133 72 137 65 139 58" />
                        <path d="M123 77 C137 85 151 94 166 91" />
                        <path d="M166 91 L174 86" />
                        <path d="M116 78 C125 91 132 104 145 108" />
                        <path d="M145 108 L154 106" />
                        <path d="M67 82 C55 94 42 105 28 101" />
                        <path d="M28 101 L19 96" />
                        <path d="M75 87 C65 103 51 113 37 115" />
                        <path d="M37 115 L27 112" />
                        <path d="M61 67 C45 57 30 57 18 68" />
                        <path d="M31 59 C19 54 12 45 14 35" />
                        <circle cx="143" cy="31" r="2.8" fill="#071d38" stroke="none" />
                        <path d="M8 78 H34" opacity=".45" />
                        <path d="M3 89 H29" opacity=".45" />
                    </g>
                </svg>
            </div>
            <div>
                <div class="brand-name">VasuDev</div>
                <div class="brand-subtitle">Cricket Historical & Situation Analyzer</div>
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

# ---------------- MAIN PAGE CSS ----------------

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
        max-width: 1600px;
        padding-top: 1.4rem;
        padding-bottom: 2rem;
    }

    .card {
        background: rgba(15, 34, 60, .94);
        padding: 18px;
        border-radius: 18px;
        border: 1px solid #2d4d72;
        box-shadow: 0 8px 26px rgba(0,0,0,.18);
    }

    .result_yes {
        background: linear-gradient(135deg, #06351f, #0b6040);
        color: #fff;
        border: 2px solid #20c77a;
        padding: 22px;
        border-radius: 16px;
        text-align: center;
        box-shadow: 0 8px 26px rgba(0,0,0,.2);
    }

    .result_no {
        background: linear-gradient(135deg, #421010, #681b1b);
        color: #fff;
        border: 2px solid #ef5350;
        padding: 22px;
        border-radius: 16px;
        text-align: center;
        box-shadow: 0 8px 26px rgba(0,0,0,.2);
    }

    .small {
        color: #bed0e5 !important;
        font-size: 13px;
    }

    div[data-testid="stSelectbox"] label,
    div[data-testid="stNumberInput"] label {
        color: #e2edf9 !important;
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

    [data-testid="stSidebar"] {
        background: #071a2e;
        border-right: 1px solid rgba(255,255,255,.08);
    }

    .sidebar-info {
        background: rgba(18, 35, 58, .9);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 10px;
        color: #dfeaf8;
    }

    [data-testid="stStatusWidget"] {
        display: none !important;
    }

    [data-testid="stDecoration"] {
        display: none !important;
    }

    .session-box {
        background: rgba(14, 31, 54, 0.92);
        border: 1px solid rgba(148, 163, 184, 0.3);
        border-radius: 14px;
        padding: 18px;
        margin-top: 12px;
        box-shadow: 0 8px 22px rgba(0,0,0,.18);
    }
    </style>
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
                                delivery_rows.append((
                                    match_id, innings_no, batting_team, bowling_team,
                                    over_no, ball_no, runs, wickets, league
                                ))

                except Exception:
                    continue

        if match_rows:
            out.executemany("INSERT OR REPLACE INTO matches VALUES (?,?,?,?)", match_rows)
        if delivery_rows:
            out.executemany(
                """
                INSERT INTO deliveries
                (match_id, innings_no, batting_team, bowling_team, over_no, ball_no, runs, wickets, league)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                delivery_rows
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


def calibrate_probability(probability, sample_count):
    probability = float(np.clip(probability, 0.0, 100.0))
    if sample_count < 20:
        strength = 0.25
    elif sample_count < 50:
        strength = 0.45
    elif sample_count < 100:
        strength = 0.70
    else:
        strength = 1.0

    calibrated = 50.0 + (probability - 50.0) * strength
    return float(np.clip(calibrated, 1.0, 99.0))


# ---------------- QUICK LIVE UPDATE STATE ----------------

def initialize_live_state():
    defaults = {
        "live_initialized": False,
        "live_runs": 0,
        "live_wickets": 0,
        "live_ball": 0,
        "live_target": 0,
        "live_history": [],
        "live_last_action": "",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def save_live_state():
    st.session_state.live_history.append({
        "runs": st.session_state.live_runs,
        "wickets": st.session_state.live_wickets,
        "ball": st.session_state.live_ball,
        "action": st.session_state.live_last_action,
    })


def add_live_ball(runs=0, wicket=False, label=""):
    if st.session_state.live_ball >= 120:
        return

    save_live_state()
    st.session_state.live_runs += int(runs)

    if wicket:
        st.session_state.live_wickets = min(10, st.session_state.live_wickets + 1)

    st.session_state.live_ball += 1
    st.session_state.live_last_action = label


def undo_live_ball():
    history = st.session_state.live_history
    if not history:
        return

    previous = history.pop()
    st.session_state.live_runs = previous["runs"]
    st.session_state.live_wickets = previous["wickets"]
    st.session_state.live_ball = previous["ball"]
    st.session_state.live_last_action = "Last ball undone"


def reset_live_state():
    st.session_state.live_initialized = False
    st.session_state.live_runs = 0
    st.session_state.live_wickets = 0
    st.session_state.live_ball = 0
    st.session_state.live_target = 0
    st.session_state.live_history = []
    st.session_state.live_last_action = ""


# ---------------- SESSION ENGINE ----------------

def generate_session_line(current_score, current_wickets, current_ball_pos, session_over, target_runs):
    if history.empty:
        return (0, 0, 0.0, 0.0)

    session_target_balls = int(session_over) * 6
    if current_ball_pos >= session_target_balls:
        return (0, 0, float(current_score), 0.0)

    mask = (
        (history["innings_no"] == innings_no)
        & (history["ball_pos"].between(max(1, current_ball_pos - 2), current_ball_pos + 2))
    )

    x = history[mask].copy()
    if x.empty:
        return (0, 0, float(current_score), 0.0)

    x = x[x["ball_pos"] <= session_target_balls]
    x = x[(x["cum_runs"] - current_score).abs() <= 30]
    x = x[(x["cum_wk"] - current_wickets).abs() <= 3]

    if x.empty:
        return (0, 0, float(current_score), 0.0)

    x["required_runs"] = (target_runs - x["cum_runs"]).clip(lower=0)
    x["remaining_balls"] = (session_target_balls - x["ball_pos"]).clip(lower=1)
    x["required_rr"] = x["required_runs"] / x["remaining_balls"] * 6.0

    x["s_score"] = np.exp(-((x["cum_runs"] - current_score).abs()) / 11.0)
    x["s_wk"] = np.exp(-((x["cum_wk"] - current_wickets).abs()) / 2.0)
    x["s_rr"] = np.exp(-((x["current_rr"] - current_rr_live).abs()) / 1.8)
    x["s_last6"] = np.exp(-((x["runs_last6"] - live["runs_last6"]).abs()) / 7.0)
    x["s_last12"] = np.exp(-((x["runs_last12"] - live["runs_last12"]).abs()) / 10.0)
    x["s_momentum"] = np.exp(-((x["momentum"] - live["momentum"]).abs()) / 2.5)

    x["team_match"] = (
        (x["batting_team"] == batting).astype(float)
        + 0.85 * (x["bowling_team"] == bowling).astype(float)
    ) / 1.85

    x["ground_match"] = (x["venue"] == venue).astype(float)

    x["similarity"] = (
        0.22 * x["s_score"]
        + 0.12 * x["s_wk"]
        + 0.14 * x["s_rr"]
        + 0.13 * x["s_last6"]
        + 0.11 * x["s_last12"]
        + 0.08 * x["s_momentum"]
        + 0.08 * x["team_match"]
        + 0.04 * x["ground_match"]
    )

    x["weight"] = x["similarity"].clip(lower=0.02)
    x = x.sort_values("weight", ascending=False).head(2500)

    if x.empty:
        return (0, 0, float(current_score), 0.0)

    future_scores = (
        x[["match_id", "innings_no", "cum_runs", "ball_pos"]]
        .sort_values(["match_id", "innings_no", "ball_pos"])
        .groupby(["match_id", "innings_no"], as_index=False, sort=False)
        .tail(1)
        .rename(columns={"cum_runs": "future_total"})
    )

    if future_scores.empty:
        return (0, 0, float(current_score), 0.0)

    expected_score = float(np.average(future_scores["future_total"], weights=x["weight"][:len(future_scores)]))
    values = future_scores["future_total"].to_numpy()

    low_line = int(np.percentile(values, 10))
    high_line = int(np.percentile(values, 90))
    low_line = max(0, low_line)
    high_line = max(low_line + 1, high_line)

    return (low_line, high_line, float(expected_score), float(np.mean(x["weight"])))


def initialize_session_state():
    defaults = {
        "session_over": 6,
        "session_low": 0,
        "session_high": 0,
        "session_expected": 0.0,
        "manual_session_mode": False,
        "manual_session_low": 0,
        "manual_session_high": 0,
        "manual_session_note": "",
        "session_memory": [],
        "session_note": "Auto generated",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def refresh_session_line():
    session_over = int(st.session_state.get("session_over", 6))
    session_low, session_high, session_expected, session_conf = generate_session_line(
        current_runs,
        wickets,
        current_ball,
        session_over,
        target_runs
    )

    st.session_state.session_low = int(session_low)
    st.session_state.session_high = int(session_high)
    st.session_state.session_expected = float(session_expected)
    st.session_state.session_note = "Auto generated"

    if "session_memory" not in st.session_state:
        st.session_state.session_memory = []
    st.session_state.session_memory.append({
        "low": session_low,
        "high": session_high,
        "score": current_runs,
        "wickets": wickets,
        "ball": current_ball,
        "over": session_over,
    })
    if len(st.session_state.session_memory) > 10:
        st.session_state.session_memory = st.session_state.session_memory[-10:]


def apply_manual_session_line(low_line, high_line, note):
    st.session_state.manual_session_mode = True
    st.session_state.manual_session_low = int(low_line)
    st.session_state.manual_session_high = int(high_line)
    st.session_state.manual_session_note = note
    st.session_state.session_low = int(low_line)
    st.session_state.session_high = int(high_line)
    st.session_state.session_note = f"Manual: {low_line}-{high_line}"


def reset_manual_session():
    st.session_state.manual_session_mode = False
    st.session_state.manual_session_low = 0
    st.session_state.manual_session_high = 0
    st.session_state.manual_session_note = ""
    refresh_session_line()


# ---------------- APP ----------------

initialize_session_state()

# Sidebar
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-info">
            <strong>Quick Setup</strong><br>
            Keep base details fixed, then update ball-by-ball.
        </div>
        """,
        unsafe_allow_html=True,
    )

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

    st.markdown(
        f"""
        <div class="sidebar-info">
            <strong>{league}</strong><br>
            {match_count:,} matches<br>
            {delivery_count:,} deliveries
        </div>
        """,
        unsafe_allow_html=True,
    )

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

    batting = st.selectbox("Batting Team", teams, index=min(len(teams)-1, 0))
    bowling_options = [x for x in teams if x != batting]
    bowling = st.selectbox("Bowling Team", bowling_options, index=min(len(bowling_options)-1, 0))
    venue = st.selectbox("Ground", venues, index=0)
    innings_label = st.selectbox("Innings", ["1st Innings", "2nd Innings"])
    target_runs = st.number_input("Target Runs", min_value=0, max_value=400, value=50, step=1)
    future_over = st.selectbox("Future Point", VALID_FUTURE_POINTS, index=VALID_FUTURE_POINTS.index("7.1"))

    setup_current_over = st.selectbox("Start Over / Ball", VALID_CURRENT_POINTS, index=VALID_CURRENT_POINTS.index("3.1"))
    setup_current_runs = st.number_input("Start Runs", min_value=0, max_value=400, value=16, step=1)
    setup_wickets = st.number_input("Start Wickets", min_value=0, max_value=10, value=1, step=1)

    if st.button("✅ Set Current Match Situation", use_container_width=True):
        st.session_state.live_initialized = True
        st.session_state.live_runs = int(setup_current_runs)
        st.session_state.live_wickets = int(setup_wickets)
        st.session_state.live_ball = balls_from_over_ball(setup_current_over)
        st.session_state.live_history = []
        st.session_state.live_last_action = "Starting situation set"

    st.markdown("### Session Setup")
    st.session_state.session_over = st.number_input("Session Over", min_value=1, max_value=20, value=6, step=1)

    if st.button("🔄 Reset Live Situation", use_container_width=True):
        reset_live_state()

    st.caption("Ball update ke baad session line auto re-calculate hoti rahegi.")

# Initialize live state if not set
if "live_initialized" not in st.session_state:
    st.session_state.live_initialized = True
    st.session_state.live_runs = 16
    st.session_state.live_wickets = 1
    st.session_state.live_ball = balls_from_over_ball("3.1")
    st.session_state.live_history = []
    st.session_state.live_last_action = "Start"

if not st.session_state.live_initialized:
    st.session_state.live_runs = int(setup_current_runs)
    st.session_state.live_wickets = int(setup_wickets)
    st.session_state.live_ball = balls_from_over_ball(setup_current_over)
    st.session_state.live_initialized = True

# Use live stored values
current_runs = st.session_state.live_runs
wickets = st.session_state.live_wickets
current_ball = st.session_state.live_ball
current_over = over_ball_from_balls(current_ball)
innings_no = 1 if innings_label == "1st Innings" else 2
target_ball = balls_from_over_ball(future_over)
remaining = max(0, target_ball - current_ball)
current_rr_live = current_runs / current_ball * 6 if current_ball > 0 else 0.0
required_runs_live = max(0, target_runs - current_runs)
required_rr_live = required_runs_live / remaining * 6 if remaining > 0 else 999.0

# Live score card
st.markdown(
    f"""
    <div class="card">
        <h3>Current Live Score</h3>
        <h2>{current_runs}/{wickets}</h2>
        <p class="small">
            Over/Ball: {current_over}
            • Target: {target_runs}
            • Required RR: {required_rr_live:.2f}
            • Last action: {st.session_state.live_last_action or "—"}
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Quick update buttons
st.markdown("### ⚡ Ball-by-Ball Update")

button_row1, button_row2, button_row3, button_row4 = st.columns(4)
with button_row1:
    if st.button("• Dot", use_container_width=True):
        add_live_ball(0, False, "Dot ball")
        refresh_session_line()
        st.rerun()

with button_row2:
    if st.button("1 Run", use_container_width=True):
        add_live_ball(1, False, "1 run")
        refresh_session_line()
        st.rerun()

with button_row3:
    if st.button("2 Runs", use_container_width=True):
        add_live_ball(2, False, "2 runs")
        refresh_session_line()
        st.rerun()

with button_row4:
    if st.button("3 Runs", use_container_width=True):
        add_live_ball(3, False, "3 runs")
        refresh_session_line()
        st.rerun()

button_row5, button_row6, button_row7, button_row8 = st.columns(4)
with button_row5:
    if st.button("4 Runs", use_container_width=True):
        add_live_ball(4, False, "4 runs")
        refresh_session_line()
        st.rerun()

with button_row6:
    if st.button("6 Runs", use_container_width=True):
        add_live_ball(6, False, "6 runs")
        refresh_session_line()
        st.rerun()

with button_row7:
    if st.button("🔴 Wicket", use_container_width=True):
        add_live_ball(0, True, "Wicket")
        refresh_session_line()
        st.rerun()

with button_row8:
    if st.button("↩ Undo", use_container_width=True):
        undo_live_ball()
        refresh_session_line()
        st.rerun()

# Match details
st.subheader("📊 Match Detail")

detail1, detail2, detail3, detail4 = st.columns(4)
with detail1:
    st.markdown(f"<div class='card'><strong>Batting</strong><br>{batting}</div>", unsafe_allow_html=True)
with detail2:
    st.markdown(f"<div class='card'><strong>Bowling</strong><br>{bowling}</div>", unsafe_allow_html=True)
with detail3:
    st.markdown(f"<div class='card'><strong>Ground</strong><br>{venue}</div>", unsafe_allow_html=True)
with detail4:
    st.markdown(f"<div class='card'><strong>Innings</strong><br>{innings_label}</div>", unsafe_allow_html=True)

# Session engine display
if not st.session_state.manual_session_mode:
    refresh_session_line()

session_low = int(st.session_state.session_low)
session_high = int(st.session_state.session_high)

st.markdown(
    f"""
    <div class="session-box">
        <h3>📈 Session Engine</h3>
        <h2>{session_low}-{session_high}</h2>
        <p class="small">
            Expected score: {st.session_state.session_expected:.1f}
            • Session over: {st.session_state.session_over}
            • Mode: {('Manual' if st.session_state.manual_session_mode else 'Auto')}
            • Note: {st.session_state.session_note}
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

manual_col1, manual_col2, manual_col3 = st.columns(3)
with manual_col1:
    st.session_state.manual_session_low = st.number_input(
        "Manual Session Low",
        min_value=0,
        max_value=200,
        value=int(st.session_state.session_low or 0),
        step=1,
        key="manual_low_input",
    )

with manual_col2:
    st.session_state.manual_session_high = st.number_input(
        "Manual Session High",
        min_value=0,
        max_value=200,
        value=int(st.session_state.session_high or 0),
        step=1,
        key="manual_high_input",
    )

with manual_col3:
    st.session_state.manual_session_note = st.text_input(
        "Manual session note",
        value=st.session_state.manual_session_note or "",
        key="manual_session_note",
    )

manual_action1, manual_action2 = st.columns(2)
with manual_action1:
    if st.button("✅ Apply Manual Session Line", use_container_width=True):
        apply_manual_session_line(
            st.session_state.manual_session_low,
            st.session_state.manual_session_high,
            st.session_state.manual_session_note or "User override"
        )
        st.rerun()

with manual_action2:
    if st.button("🔁 Auto Session", use_container_width=True):
        reset_manual_session()
        st.rerun()

# ---------------- LIVE TREND ----------------

def match_phase(ball_pos):
    ball_pos = int(ball_pos)
    if ball_pos <= 36:
        return "powerplay"
    if ball_pos <= 90:
        return "middle"
    return "death"

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

# ---------------- HISTORY SIMILARITY ----------------

def session_candidates():
    if history.empty or target_ball <= current_ball:
        return pd.DataFrame(), "No usable historical data"

    current_phase = match_phase(current_ball)
    x = history[
        (history.innings_no == innings_no)
        & (history.ball_pos.between(max(1, current_ball - 2), current_ball + 2))
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
    x = x.sort_values("weight", ascending=False).head(1500)

    return x, "Phase-aware V2: score + wickets + RR + required RR + recent trend + momentum + teams + ground"


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
        & (history.ball_pos.between(max(1, current_ball - 2), current_ball + 2))
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


# ---------------- FINAL ANALYZE ----------------

if st.button("🔎 ANALYZE CURRENT SITUATION", use_container_width=True, disabled=(target_ball <= current_ball)):
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
            raw_win = 100 * ww / total
            raw_loss = 100 * lw / total
            raw_other = 100 * ow / total

            win_pct = calibrate_probability(raw_win, len(win_df))
            loss_pct = calibrate_probability(raw_loss, len(win_df))
            other_pct = calibrate_probability(raw_other, len(win_df))
        win_samples = len(win_df)

    cand, method = session_candidates()
    session_yes = session_no = 0.0
    session_samples = 0
    expected_score = range_low = range_high = None

    if not cand.empty:
        cand = add_future_scores(cand)

    if not cand.empty:
        cand["hit"] = (cand.future_score >= target_runs).astype(float)
        raw_yes = 100 * float(np.average(cand.hit.to_numpy(), weights=cand.weight.to_numpy()))
        session_samples = len(cand)
        session_yes = calibrate_probability(raw_yes, session_samples)
        session_no = 100.0 - session_yes
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
