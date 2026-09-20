# VasuDev V2 - Final complete, corrected app.py
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


# ============================================================
# BASE CONFIG
# ============================================================

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

LEAGUES = [
    "IPL",
    "Men's Big Bash League",
    "Women's Big Bash League",
]

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not APP_PASSWORD:
    st.error(
        "🔒 VasuDev is locked. Set the VASUDEV_PASSWORD secret in Render."
    )
    st.stop()

if "vasudev_authenticated" not in st.session_state:
    st.session_state.vasudev_authenticated = False


# ============================================================
# BRAND / CSS
# ============================================================

def render_brand():
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top right, #17365d 0%, transparent 34%),
                linear-gradient(180deg, #061426 0%, #081c35 100%);
            color: #f8fafc;
        }

        .block-container {
            max-width: 1600px;
            padding-top: 2.4rem !important;
            padding-bottom: 2rem;
        }

        .vasudev-brand {
            display: flex;
            align-items: center;
            gap: 16px;
            margin: 12px 0 18px 0;
            padding: 16px 20px;
            border-radius: 18px;
            background: linear-gradient(135deg, #0d294a, #102f54);
            border: 1px solid #31577f;
            box-shadow: 0 8px 24px rgba(0,0,0,.28);
        }

        .horse-logo {
            width: 82px;
            height: 66px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #ffffff;
            border: 1px solid #dbeafe;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 8px 18px rgba(0,0,0,.2);
        }

        .horse-logo svg {
            width: 72px;
            height: 56px;
        }

        .vasudev-title {
            color: #ffffff !important;
            font-size: 2.35rem;
            font-weight: 900;
            letter-spacing: .5px;
            line-height: 1;
        }

        .vasudev-subtitle {
            color: #b9cfe9 !important;
            font-size: .92rem;
            margin-top: 8px;
        }

        .card {
            background: rgba(15, 34, 60, .94);
            padding: 18px;
            border-radius: 18px;
            border: 1px solid #2d4d72;
            box-shadow: 0 8px 26px rgba(0,0,0,.18);
        }

        .session-box {
            background: rgba(14, 31, 54, .95);
            padding: 20px;
            border-radius: 18px;
            border: 2px solid #4777a8;
            margin: 14px 0;
            text-align: center;
            box-shadow: 0 8px 26px rgba(0,0,0,.2);
        }

        .result_yes {
            background: linear-gradient(135deg, #06351f, #0b6040);
            color: #ffffff;
            border: 2px solid #20c77a;
            padding: 22px;
            border-radius: 16px;
            text-align: center;
        }

        .result_no {
            background: linear-gradient(135deg, #421010, #681b1b);
            color: #ffffff;
            border: 2px solid #ef5350;
            padding: 22px;
            border-radius: 16px;
            text-align: center;
        }

        .small {
            color: #bed0e5 !important;
            font-size: 13px;
        }

        h1, h2, h3, h4, p, label {
            color: #f8fafc !important;
        }

        [data-testid="stSidebar"] {
            background: #071a2e;
            border-right: 1px solid rgba(255,255,255,.1);
        }

        [data-testid="stStatusWidget"],
        [data-testid="stDecoration"] {
            display: none !important;
        }

        div.stButton > button {
            min-height: 42px;
            border-radius: 11px;
            font-weight: 700;
            border: 1px solid #3c6795;
            background: #12365f;
            color: #ffffff;
        }

        div.stButton > button:hover {
            background: #194a7e;
            border-color: #76a9df;
            color: #ffffff;
        }

        .sidebar-info {
            background: rgba(18, 35, 58, .9);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
            padding: 12px 14px;
            margin-bottom: 10px;
            color: #dfeaf8;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="vasudev-brand">
            <div class="horse-logo" aria-label="Running white horse">
                <svg viewBox="0 0 180 120" xmlns="http://www.w3.org/2000/svg">
                    <g fill="none"
                       stroke="#071d38"
                       stroke-width="8"
                       stroke-linecap="round"
                       stroke-linejoin="round">
                        <path d="M112 24 C126 13 145 15 157 25"/>
                        <path d="M116 25 C106 36 102 49 105 61"/>
                        <path d="M105 61 C112 70 126 73 139 68"/>
                        <path d="M126 20 L124 7 L135 18"/>
                        <path d="M139 20 L148 8 L150 25"/>
                        <path d="M110 31 C98 26 91 31 88 42"/>
                        <path d="M104 38 C94 39 90 48 91 57"/>
                        <path d="M105 61 C91 54 75 55 61 64"/>
                        <path d="M61 64 C48 72 46 86 58 91"/>
                        <path d="M58 91 C78 101 108 96 124 80"/>
                        <path d="M124 80 C133 72 137 65 139 58"/>
                        <path d="M123 77 C137 85 151 94 166 91"/>
                        <path d="M166 91 L174 86"/>
                        <path d="M116 78 C125 91 132 104 145 108"/>
                        <path d="M145 108 L154 106"/>
                        <path d="M67 82 C55 94 42 105 28 101"/>
                        <path d="M28 101 L19 96"/>
                        <path d="M75 87 C65 103 51 113 37 115"/>
                        <path d="M37 115 L27 112"/>
                        <path d="M61 67 C45 57 30 57 18 68"/>
                        <path d="M31 59 C19 54 12 45 14 35"/>
                        <circle cx="143" cy="31" r="3" fill="#071d38" stroke="none"/>
                        <path d="M8 78 H34" opacity=".45"/>
                        <path d="M3 89 H29" opacity=".45"/>
                    </g>
                </svg>
            </div>

            <div>
                <div class="vasudev-title">VasuDev</div>
                <div class="vasudev-subtitle">
                    Cricket Historical & Situation Analyzer
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


if not st.session_state.vasudev_authenticated:
    render_brand()

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

render_brand()


# ============================================================
# DATABASE BUILDERS
# ============================================================

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


def build_database(db_path, league, zip_path):
    tmp_db = db_path.with_suffix(db_path.suffix + ".tmp")
    if tmp_db.exists():
        try:
            tmp_db.unlink()
        except Exception:
            pass

    out = sqlite3.connect(str(tmp_db))

    try:
        out.execute(
            """
            CREATE TABLE matches (
                match_id TEXT PRIMARY KEY,
                venue TEXT,
                winner TEXT,
                league TEXT
            )
            """
        )

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

        with zipfile.ZipFile(zip_path) as archive:
            names = [n for n in archive.namelist() if n.endswith(".json")]

            for name in names:
                try:
                    data = json.loads(archive.read(name))
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
                        bowling_team = next((team for team in teams if team != batting_team), "")

                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))

                            for delivery in over.get("deliveries", []):
                                pos, ball_no = parse_delivery(delivery.get("actual_delivery"), over_no)

                                if pos is None:
                                    try:
                                        ball = int(delivery.get("ball"))
                                        pos = over_no * 6 + ball
                                        ball_no = f"{over_no}.{ball}"
                                    except Exception:
                                        continue

                                runs = int((delivery.get("runs") or {}).get("total", 0) or 0)
                                wickets = len(delivery.get("wickets") or [])

                                delivery_rows.append((
                                    match_id,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    over_no,
                                    ball_no,
                                    runs,
                                    wickets,
                                    league,
                                ))

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
        out.execute("CREATE INDEX idx_deliveries_match ON deliveries(match_id, innings_no, id)")
        out.commit()

    finally:
        out.close()

    tmp_db.replace(db_path)


def ensure_bigbash_db(league):
    db_path = DB_PATHS[league]
    if db_path.exists():
        return db_path, False

    building_db = db_path.with_suffix(db_path.suffix + ".building")

    try:
        if building_db.exists():
            try:
                building_db.unlink()
            except Exception:
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "matches.zip"
            urllib.request.urlretrieve(DATA_URLS[league], zip_path)
            build_database(building_db, league, zip_path)

        building_db.replace(db_path)
        return db_path, True

    except Exception as exc:
        if building_db.exists():
            try:
                building_db.unlink()
            except Exception:
                pass

        raise RuntimeError(f"Could not prepare {league} historical data: {exc}") from exc


@st.cache_resource(show_spinner=False)
def get_db_connection(db_path_string):
    db_path = Path(db_path_string)
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
def get_database_counts(db_path_string):
    db_path = Path(db_path_string)
    with closing(
        sqlite3.connect(
            f"file:{db_path.resolve()}?mode=ro",
            uri=True,
            check_same_thread=False,
            timeout=30,
        )
    ) as connection:
        match_count = connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        delivery_count = connection.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]

    return int(match_count), int(delivery_count)


@st.cache_data(show_spinner=False, max_entries=8)
def load_history(league, db_path_string):
    db_path = Path(db_path_string)

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
        FROM deliveries d
        JOIN matches m
          ON m.match_id = d.match_id
        WHERE d.league = ?
        ORDER BY d.match_id, d.innings_no, d.id
    """

    with closing(
        sqlite3.connect(
            f"file:{db_path.resolve()}?mode=ro",
            uri=True,
            check_same_thread=False,
            timeout=30,
        )
    ) as connection:
        dataframe = pd.read_sql_query(query, connection, params=(league,))

    if dataframe.empty:
        return dataframe

    def parse_ball_position(value):
        try:
            over_text, ball_text = str(value).split(".", 1)
            over = int(over_text)
            ball = int(ball_text)

            if over < 0 or ball < 0:
                raise ValueError
            return over * 6 + ball
        except Exception:
            return np.nan

    dataframe["ball_pos"] = dataframe["ball_no"].map(parse_ball_position)
    dataframe = dataframe.dropna(subset=["ball_pos"]).copy()
    if dataframe.empty:
        return dataframe

    dataframe["ball_pos"] = dataframe["ball_pos"].astype("int32")
    dataframe["runs"] = pd.to_numeric(dataframe["runs"], errors="coerce").fillna(0).astype("int16")
    dataframe["wickets"] = pd.to_numeric(dataframe["wickets"], errors="coerce").fillna(0).astype("int8")

    for column in ["batting_team", "bowling_team", "venue", "winner"]:
        dataframe[column] = dataframe[column].fillna("").astype(str)

    grouped = dataframe.groupby(["match_id", "innings_no"], sort=False)

    dataframe["cum_runs"] = grouped["runs"].cumsum().astype("int32")
    dataframe["cum_wk"] = grouped["wickets"].cumsum().astype("int16")
    dataframe["current_rr"] = np.where(
        dataframe["ball_pos"] > 0,
        dataframe["cum_runs"] / dataframe["ball_pos"] * 6.0,
        0.0,
    )

    last6 = []
    last12 = []
    last18 = []

    for _, group in grouped:
        positions = group["ball_pos"].to_numpy(dtype=np.int32)
        cumulative = group["cum_runs"].to_numpy(dtype=np.float64)

        g6 = []
        g12 = []
        g18 = []

        for position, total in zip(positions, cumulative):
            idx6 = np.searchsorted(positions, position - 6, side="right") - 1
            idx12 = np.searchsorted(positions, position - 12, side="right") - 1
            idx18 = np.searchsorted(positions, position - 18, side="right") - 1

            prev6 = cumulative[idx6] if idx6 >= 0 else 0.0
            prev12 = cumulative[idx12] if idx12 >= 0 else 0.0
            prev18 = cumulative[idx18] if idx18 >= 0 else 0.0

            g6.append(max(0.0, total - prev6))
            g12.append(max(0.0, total - prev12))
            g18.append(max(0.0, total - prev18))

        last6.extend(g6)
        last12.extend(g12)
        last18.extend(g18)

    dataframe["runs_last6"] = last6
    dataframe["runs_last12"] = last12
    dataframe["runs_last18"] = last18
    dataframe["rr_last12"] = dataframe["runs_last12"] / 2.0
    dataframe["momentum"] = dataframe["rr_last12"] - dataframe["current_rr"]

    return dataframe


def get_values(sql, params, connection):
    try:
        rows = connection.execute(sql, params).fetchall()
        return [row[0] for row in rows if row[0] not in (None, "")]
    except Exception:
        return []


# ============================================================
# HELPERS
# ============================================================

def balls_from_over_ball(value):
    value = str(value).strip()
    try:
        over_text, ball_text = value.split(".", 1)
        over = int(over_text)
        ball = int(ball_text)
    except Exception as exc:
        raise ValueError("Invalid over.ball value") from exc

    if over < 0 or over > 20:
        raise ValueError("Invalid over")
    if ball < 0 or ball > 6:
        raise ValueError("Invalid ball")
    if over == 20 and ball != 0:
        raise ValueError("20.0 is innings end")

    return over * 6 + ball


def over_ball_from_balls(balls):
    balls = int(balls)
    if balls <= 0:
        return "0.0"

    over = (balls - 1) // 6
    ball = ((balls - 1) % 6) + 1
    return f"{over}.{ball}"


def valid_over_ball_options(max_over=20):
    values = ["0.0"]
    for over in range(max_over):
        values.extend(f"{over}.{ball}" for ball in range(1, 7))
    return values


VALID_POINTS = valid_over_ball_options(20)


def safe_round(value):
    try:
        return int(round(float(value)))
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


# ============================================================
# LIVE STATE
# ============================================================

def initialize_live_state():
    defaults = {
        "live_runs": 0,
        "live_wickets": 0,
        "live_ball": 0,
        "live_initialized": False,
        "live_history": [],
        "live_last_action": "",
    }

    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def save_live_snapshot():
    st.session_state.live_history.append(
        {
            "runs": st.session_state.live_runs,
            "wickets": st.session_state.live_wickets,
            "ball": st.session_state.live_ball,
            "action": st.session_state.live_last_action,
        }
    )


def add_live_event(runs=0, wicket=False, legal_ball=True, label=""):
    save_live_snapshot()
    st.session_state.live_runs += int(runs)

    if wicket:
        st.session_state.live_wickets = min(10, st.session_state.live_wickets + 1)

    if legal_ball:
        st.session_state.live_ball += 1

    st.session_state.live_last_action = label
    st.session_state.live_initialized = True


def undo_live_event():
    if not st.session_state.live_history:
        return

    previous = st.session_state.live_history.pop()
    st.session_state.live_runs = previous["runs"]
    st.session_state.live_wickets = previous["wickets"]
    st.session_state.live_ball = previous["ball"]
    st.session_state.live_last_action = "Undo"


def reset_live_state():
    st.session_state.live_runs = 0
    st.session_state.live_wickets = 0
    st.session_state.live_ball = 0
    st.session_state.live_history = []
    st.session_state.live_last_action = ""
    st.session_state.live_initialized = False


# ============================================================
# SESSION ENGINE
# ============================================================

def match_phase(ball_position):
    if ball_position <= 36:
        return "powerplay"
    if ball_position <= 90:
        return "middle"
    return "death"


def calculate_live_trend(history_df, innings_no, current_ball, current_runs, wickets):
    if history_df is None or history_df.empty:
        return {
            "runs_last6": 0.0,
            "runs_last12": 0.0,
            "runs_last18": 0.0,
            "momentum": 0.0,
        }

    nearby = history_df[
        (history_df["innings_no"] == innings_no)
        & (history_df["ball_pos"].between(max(1, current_ball - 2), current_ball + 2))
    ].copy()

    if nearby.empty:
        return {
            "runs_last6": 0.0,
            "runs_last12": 0.0,
            "runs_last18": 0.0,
            "momentum": 0.0,
        }

    nearby["distance"] = (
        (nearby["cum_runs"] - current_runs).abs() / 8.0
        + (nearby["cum_wk"] - wickets).abs() / 1.5
        + (nearby["ball_pos"] - current_ball).abs() / 2.0
    )

    nearby = nearby.sort_values("distance").head(80)

    return {
        "runs_last6": float(nearby["runs_last6"].mean()),
        "runs_last12": float(nearby["runs_last12"].mean()),
        "runs_last18": float(nearby["runs_last18"].mean()),
        "momentum": float(nearby["momentum"].mean()),
    }


def historical_session_line(history_df, innings_no, current_ball, current_runs, wickets, session_over, batting_team, bowling_team, venue):
    session_ball = int(session_over) * 6

    if current_ball >= session_ball:
        return {
            "low": current_runs,
            "high": current_runs + 1,
            "expected": float(current_runs),
            "samples": 0,
            "confidence": "Session point reached",
        }

    if history_df is None or history_df.empty:
        return {
            "low": current_runs,
            "high": current_runs + 1,
            "expected": float(current_runs),
            "samples": 0,
            "confidence": "No historical data",
        }

    trend = calculate_live_trend(history_df, innings_no, current_ball, current_runs, wickets)

    phase = match_phase(current_ball)

    candidates = history_df[
        (history_df["innings_no"] == innings_no)
        & (history_df["ball_pos"].between(max(1, current_ball - 2), current_ball + 2))
    ].copy()

    if candidates.empty:
        return {
            "low": current_runs,
            "high": current_runs + 1,
            "expected": float(current_runs),
            "samples": 0,
            "confidence": "No similar states",
        }

    candidates = candidates[candidates["ball_pos"] <= session_ball]
    candidates = candidates[(candidates["cum_runs"] - current_runs).abs() <= 30]
    candidates = candidates[(candidates["cum_wk"] - wickets).abs() <= 3]

    if candidates.empty:
        return {
            "low": current_runs,
            "high": current_runs + 1,
            "expected": float(current_runs),
            "samples": 0,
            "confidence": "No similar states",
        }

    candidates["phase_match"] = (candidates["ball_pos"].map(match_phase) == phase).astype(float)

    current_rr_value = current_runs / max(1, current_ball) * 6.0

    candidates["score_similarity"] = np.exp(-((candidates["cum_runs"] - current_runs).abs()) / 11.0)
    candidates["wicket_similarity"] = np.exp(-((candidates["cum_wk"] - wickets).abs()) / 2.0)
    candidates["ball_similarity"] = np.exp(-((candidates["ball_pos"] - current_ball).abs()) / 2.5)
    candidates["rr_similarity"] = np.exp(-((candidates["current_rr"] - current_rr_value).abs()) / 1.8)
    candidates["trend_similarity"] = np.exp(-((candidates["runs_last12"] - trend["runs_last12"]).abs()) / 10.0)
    candidates["momentum_similarity"] = np.exp(-((candidates["momentum"] - trend["momentum"]).abs()) / 2.5)

    candidates["team_similarity"] = (
        (candidates["batting_team"] == batting_team).astype(float)
        + 0.85 * (candidates["bowling_team"] == bowling_team).astype(float)
    ) / 1.85

    candidates["ground_similarity"] = (candidates["venue"] == venue).astype(float)

    candidates["weight"] = (
        0.22 * candidates["score_similarity"]
        + 0.12 * candidates["wicket_similarity"]
        + 0.10 * candidates["ball_similarity"]
        + 0.16 * candidates["rr_similarity"]
        + 0.12 * candidates["trend_similarity"]
        + 0.08 * candidates["momentum_similarity"]
        + 0.08 * candidates["team_similarity"]
        + 0.05 * candidates["ground_similarity"]
        + 0.07 * candidates["phase_match"]
    ).clip(lower=0.03)

    candidates = candidates.sort_values("weight", ascending=False).head(1200)

    grouped = history_df.groupby(["match_id", "innings_no"], sort=False)
    future_rows = []

    for _, row in candidates.iterrows():
        key = (row["match_id"], int(row["innings_no"]))
        try:
            match_history = grouped.get_group(key)
        except KeyError:
            continue

        future = match_history[match_history["ball_pos"] <= session_ball]
        if future.empty:
            continue

        final_row = future.iloc[-1]
        future_rows.append({
            "future_score": float(final_row["cum_runs"]),
            "weight": float(row["weight"]),
        })

    if not future_rows:
        return {
            "low": current_runs,
            "high": current_runs + 1,
            "expected": float(current_runs),
            "samples": 0,
            "confidence": "No continuation data",
        }

    result = pd.DataFrame(future_rows)
    expected = float(np.average(result["future_score"], weights=result["weight"]))

    low = max(current_runs, int(round(expected)))
    high = low + 1

    samples = len(result)
    confidence = "Good historical sample" if samples >= 100 else "Medium historical sample" if samples >= 40 else "Limited sample"

    return {
        "low": low,
        "high": high,
        "expected": float(expected),
        "samples": samples,
        "confidence": confidence,
    }


def initialize_session_state():
    defaults = {
        "session_over": 6,
        "session_low": 0,
        "session_high": 0,
        "session_expected": 0.0,
        "session_note": "Auto generated",
        "manual_session_mode": False,
        "manual_session_low": 0,
        "manual_session_high": 0,
        "manual_session_note": "",
    }

    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def refresh_session_line_for_current_state(current_score, current_wickets, current_ball_pos, betting_team_name, bowling_team_name, venue_name, innings_index, session_over_value):
    result = historical_session_line(
        history_df=history,
        innings_no=innings_index,
        current_ball=current_ball_pos,
        current_runs=current_score,
        wickets=current_wickets,
        session_over=session_over_value,
        batting_team=betting_team_name,
        bowling_team=bowling_team_name,
        venue=venue_name,
    )

    st.session_state.session_low = int(result["low"])
    st.session_state.session_high = int(result["high"])
    st.session_state.session_expected = float(result["expected"])
    st.session_state.session_note = result["confidence"]


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
    refresh_session_line_for_current_state(
        current_score=int(st.session_state.live_runs),
        current_wickets=int(st.session_state.live_wickets),
        current_ball_pos=int(st.session_state.live_ball),
        betting_team_name=batting,
        bowling_team_name=bowling,
        venue_name=venue,
        innings_index=innings_no,
        session_over_value=int(st.session_state.session_over),
    )


# ============================================================
# APP
# ============================================================

initialize_live_state()
initialize_session_state()

with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-info">
            <strong>Quick Setup</strong><br>
            Base details set karne ke baad ball-by-ball update easy hota hai.
        </div>
        """,
        unsafe_allow_html=True,
    )

    league = st.selectbox("🏆 League", LEAGUES, index=0)

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

    conn = get_db_connection(str(selected_db))
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
        conn,
    )

    if not teams:
        st.error(f"No teams were found for {league}.")
        st.stop()

    venues = get_values(
        "SELECT DISTINCT venue FROM matches WHERE league=? AND venue IS NOT NULL AND venue<>'' ORDER BY venue",
        (league,),
        conn,
    )

    if not venues:
        venues = ["Unknown Ground"]

    batting = st.selectbox("Batting Team", teams, index=min(len(teams)-1, 0))
    bowling_options = [team for team in teams if team != batting]
    bowling = st.selectbox("Bowling Team", bowling_options, index=min(len(bowling_options)-1, 0))
    venue = st.selectbox("Ground", venues, index=0)
    innings_label = st.selectbox("Innings", ["1st Innings", "2nd Innings"])

    st.session_state.session_over = st.number_input(
        "Session Over",
        min_value=1,
        max_value=20,
        value=6,
        step=1,
    )

    setup_current_over = st.selectbox("Start Over / Ball", VALID_POINTS, index=VALID_POINTS.index("3.1"))
    setup_current_runs = st.number_input("Start Runs", min_value=0, max_value=400, value=16, step=1)
    setup_wickets = st.number_input("Start Wickets", min_value=0, max_value=10, value=1, step=1)

    if st.button("✅ Set Current Match Situation", use_container_width=True):
        st.session_state.live_initialized = True
        st.session_state.live_runs = int(setup_current_runs)
        st.session_state.live_wickets = int(setup_wickets)
        st.session_state.live_ball = balls_from_over_ball(setup_current_over)
        st.session_state.live_history = []
        st.session_state.live_last_action = "Starting situation set"

    if st.button("🔄 Reset Live Situation", use_container_width=True):
        reset_live_state()
        st.rerun()

# If no live state yet, set default values
if not st.session_state.live_initialized:
    st.session_state.live_runs = 16
    st.session_state.live_wickets = 1
    st.session_state.live_ball = balls_from_over_ball("3.1")
    st.session_state.live_initialized = True

current_runs = int(st.session_state.live_runs)
wickets = int(st.session_state.live_wickets)
current_ball = int(st.session_state.live_ball)
current_over = over_ball_from_balls(current_ball)
innings_no = 1 if innings_label == "1st Innings" else 2

# Keep session line auto generated when not manual
if not st.session_state.manual_session_mode:
    refresh_session_line_for_current_state(
        current_score=current_runs,
        current_wickets=wickets,
        current_ball_pos=current_ball,
        betting_team_name=batting,
        bowling_team_name=bowling,
        venue_name=venue,
        innings_index=innings_no,
        session_over_value=int(st.session_state.session_over),
    )

# Current live score card
st.markdown(
    f"""
    <div class="card">
        <h3>Current Live Score</h3>
        <h2>{current_runs}/{wickets}</h2>
        <p class="small">
            Over/Ball: {current_over}
            • Session over: {st.session_state.session_over}
            • Last action: {st.session_state.live_last_action or "—"}
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Quick ball buttons
st.markdown("### ⚡ Ball-by-Ball Update")

button_row1, button_row2, button_row3, button_row4 = st.columns(4)

with button_row1:
    if st.button("• Dot", use_container_width=True):
        add_live_event(runs=0, wicket=False, legal_ball=True, label="Dot ball")
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

with button_row2:
    if st.button("1 Run", use_container_width=True):
        add_live_event(runs=1, wicket=False, legal_ball=True, label="1 run")
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

with button_row3:
    if st.button("2 Runs", use_container_width=True):
        add_live_event(runs=2, wicket=False, legal_ball=True, label="2 runs")
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

with button_row4:
    if st.button("3 Runs", use_container_width=True):
        add_live_event(runs=3, wicket=False, legal_ball=True, label="3 runs")
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

button_row5, button_row6, button_row7, button_row8 = st.columns(4)

with button_row5:
    if st.button("4 Runs", use_container_width=True):
        add_live_event(runs=4, wicket=False, legal_ball=True, label="4 runs")
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

with button_row6:
    if st.button("6 Runs", use_container_width=True):
        add_live_event(runs=6, wicket=False, legal_ball=True, label="6 runs")
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

with button_row7:
    if st.button("🔴 Wicket", use_container_width=True):
        add_live_event(runs=0, wicket=True, legal_ball=True, label="Wicket")
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

with button_row8:
    if st.button("↩ Undo", use_container_width=True):
        undo_live_event()
        refresh_session_line_for_current_state(
            current_score=int(st.session_state.live_runs),
            current_wickets=int(st.session_state.live_wickets),
            current_ball_pos=int(st.session_state.live_ball),
            betting_team_name=batting,
            bowling_team_name=bowling,
            venue_name=venue,
            innings_index=innings_no,
            session_over_value=int(st.session_state.session_over),
        )
        st.rerun()

# Match details row
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

# Session display
session_low = int(st.session_state.get("session_low", 0))
session_high = int(st.session_state.get("session_high", 0))
session_expected = float(st.session_state.get("session_expected", 0.0))

st.markdown(
    f"""
    <div class="session-box">
        <h3>📈 Session Engine</h3>
        <h2>{session_low}-{session_high}</h2>
        <p class="small">
            Expected score: {session_expected:.1f}
            • Session over: {st.session_state.session_over}
            • Mode: {('Manual' if st.session_state.manual_session_mode else 'Auto')}
            • Note: {st.session_state.session_note}
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Manual override block
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
        key="manual_note_input",
    )

manual_action1, manual_action2 = st.columns(2)

with manual_action1:
    if st.button("✅ Apply Manual Session Line", use_container_width=True):
        apply_manual_session_line(
            st.session_state.manual_session_low,
            st.session_state.manual_session_high,
            st.session_state.manual_session_note or "User override",
        )
        st.rerun()

with manual_action2:
    if st.button("🔁 Auto Session", use_container_width=True):
        reset_manual_session()
        st.rerun()


# ============================================================
# ANALYSIS MODEL
# ============================================================

current_rr_live = current_runs / current_ball * 6 if current_ball > 0 else 0.0
target_runs = int(st.session_state.session_high)

# For the session engine, we do not need separate future point or target.
# Session over itself acts as target window.

trend_data = calculate_live_trend(
    history_df=history,
    innings_no=innings_no,
    current_ball=current_ball,
    current_runs=current_runs,
    wickets=wickets,
)

def match_phase(ball_position):
    if ball_position <= 36:
        return "powerplay"
    if ball_position <= 90:
        return "middle"
    return "death"


def session_candidates():
    if history.empty:
        return pd.DataFrame(), "No usable historical data"

    current_phase = match_phase(current_ball)

    x = history[
        (history["innings_no"] == innings_no)
        & (history["ball_pos"].between(max(1, current_ball - 2), current_ball + 2))
    ].copy()

    if x.empty:
        return pd.DataFrame(), "No historical state near this ball"

    x["phase"] = x["ball_pos"].map(match_phase)
    x["phase_match"] = (x["phase"] == current_phase).astype(float)

    x = x[x["ball_pos"] < (int(st.session_state.session_over) * 6)]
    x = x[(x["cum_runs"] - current_runs).abs() <= 30]
    x = x[(x["cum_wk"] - wickets).abs() <= 3]

    if x.empty:
        return pd.DataFrame(), "No similar historical states"

    target_turn = int(st.session_state.session_high)
    target_runs_local = max(target_turn, current_runs)

    live_required_rr = (
        max(0, target_runs_local - current_runs)
        / max(1, (int(st.session_state.session_over) * 6) - current_ball)
        * 6.0
    )

    x["required_runs"] = (target_runs_local - x["cum_runs"]).clip(lower=0)
    x["remaining_balls"] = ((int(st.session_state.session_over) * 6) - x["ball_pos"]).clip(lower=1)
    x["required_rr"] = x["required_runs"] / x["remaining_balls"] * 6.0

    x["s_score"] = np.exp(-((x["cum_runs"] - current_runs).abs()) / 10.0)
    x["s_wickets"] = np.exp(-((x["cum_wk"] - wickets).abs()) / 1.5)
    x["s_ball"] = np.exp(-((x["ball_pos"] - current_ball).abs()) / 2.5)
    x["s_rr"] = np.exp(-((x["current_rr"] - current_rr_live).abs()) / 1.8)
    x["s_required_rr"] = np.exp(-((x["required_rr"] - live_required_rr).abs()) / 2.2)
    x["s_last6"] = np.exp(-((x["runs_last6"] - trend_data["runs_last6"]).abs()) / 7.0)
    x["s_last12"] = np.exp(-((x["runs_last12"] - trend_data["runs_last12"]).abs()) / 10.0)
    x["s_momentum"] = np.exp(-((x["momentum"] - trend_data["momentum"]).abs()) / 2.5)

    x["team_match"] = (
        (x["batting_team"] == batting).astype(float)
        + 0.85 * (x["bowling_team"] == bowling).astype(float)
    ) / 1.85

    x["ground_match"] = (x["venue"] == venue).astype(float)

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

    return x, "Phase-aware session model"


def add_future_scores(candidates):
    if candidates.empty:
        return candidates

    session_total = int(st.session_state.session_over) * 6
    future_scores = (
        history.loc[
            history["ball_pos"] <= session_total,
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

    result = candidates.merge(future_scores, on=["match_id", "innings_no"], how="inner", sort=False)
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
        (history["innings_no"] == innings_no)
        & (history["ball_pos"].between(max(1, current_ball - 2), current_ball + 2))
    ].copy()

    if x.empty:
        return None

    x["phase"] = x["ball_pos"].map(match_phase)
    x["phase_match"] = (x["phase"] == current_phase).astype(float)

    x = x[(x["cum_runs"] - current_runs).abs() <= 35]
    x = x[(x["cum_wk"] - wickets).abs() <= 3]
    x = x[x["winner"].str.strip() != ""]

    if x.empty:
        return None

    current_rr_value = current_runs / max(1, current_ball) * 6.0
    trend = calculate_live_trend(history, innings_no, current_ball, current_runs, wickets)

    x["s_score"] = np.exp(-((x["cum_runs"] - current_runs).abs()) / 11.0)
    x["s_wickets"] = np.exp(-((x["cum_wk"] - wickets).abs()) / 1.7)
    x["s_ball"] = np.exp(-((x["ball_pos"] - current_ball).abs()) / 2.5)
    x["s_rr"] = np.exp(-((x["current_rr"] - current_rr_value).abs()) / 2.0)
    x["s_last6"] = np.exp(-((x["runs_last6"] - trend["runs_last6"]).abs()) / 8.0)
    x["s_last12"] = np.exp(-((x["runs_last12"] - trend["runs_last12"]).abs()) / 11.0)
    x["s_momentum"] = np.exp(-((x["momentum"] - trend["momentum"]).abs()) / 2.8)

    x["team_match"] = (
        (x["batting_team"] == batting).astype(float)
        + 0.85 * (x["bowling_team"] == bowling).astype(float)
    ) / 1.85

    x["ground_match"] = (x["venue"] == venue).astype(float)

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
    x["won_flag"] = (x["winner"] == x["batting_team"]).astype(float)

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


# ============================================================
# FINAL ANALYSIS
# ============================================================

if st.button("🔎 ANALYZE CURRENT SITUATION", use_container_width=True):
    win_df = win_candidates()
    win_pct = loss_pct = other_pct = 0.0
    win_samples = 0

    if win_df is not None and len(win_df):
        won = win_df["winner"] == win_df["batting_team"]
        lost = win_df["winner"] == win_df["bowling_team"]
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
        cand["hit"] = (cand["future_score"] >= int(st.session_state.session_high)).astype(float)
        raw_yes = 100 * float(np.average(cand["hit"].to_numpy(), weights=cand["weight"].to_numpy()))
        session_samples = len(cand)
        session_yes = calibrate_probability(raw_yes, session_samples)
        session_no = 100.0 - session_yes
        expected_score = float(np.average(cand["future_score"], weights=cand["weight"]))
        range_low = float(cand["future_score"].quantile(0.10))
        range_high = float(cand["future_score"].quantile(0.90))

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
            f'<p>Session line: <b>{st.session_state.session_low}-{st.session_state.session_high}</b> • Over: {st.session_state.session_over}</p>'
            f'<p class="small">Historical probability • {session_samples:,} similar situations • Reliability: {reliability(session_samples)} • {confidence_note}</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("Not enough historical continuation data for this session.")

    st.caption("Probabilities are calculated from historical data. They are not guarantees.")

    with st.expander("Details", expanded=False):
        st.write(
            f"**Current:** {current_runs}/{wickets} at {current_over} → "
            f"**Session line:** {st.session_state.session_low}-{st.session_state.session_high}"
        )

        st.write(
            f"**Session expected:** {st.session_state.session_expected:.1f}"
        )

        if session_samples:
            st.write(f"YES: **{session_yes:.1f}%** • NO: **{session_no:.1f}%**")
            st.write(
                f"Expected score at session point: **{safe_round(expected_score)}** • "
                f"Historical range: **{safe_round(range_low)}–{safe_round(range_high)}**"
            )
            st.caption(method)

        if win_samples:
            st.write(f"WIN: **{win_pct:.1f}%** • LOSS: **{loss_pct:.1f}%** • Other/Tie: **{other_pct:.1f}%**")

        st.write("This version keeps signal honest and does not claim bookmaker-grade certainty.")
