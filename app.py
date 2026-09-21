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
# CONFIG
# ============================================================

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide",
    initial_sidebar_state="expanded",
)

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #061426 0%, #081c35 100%);
        color: #f8fafc;
    }
    .block-container {
        max-width: 1600px;
        padding-top: 1.5rem !important;
        padding-bottom: 2rem;
    }
    .card, .session-box {
        background: rgba(15, 34, 60, .95);
        padding: 18px;
        border-radius: 16px;
        border: 1px solid #2d4d72;
        box-shadow: 0 8px 24px rgba(0, 0, 0, .18);
    }
    .session-box {
        text-align: center;
        border: 2px solid #4777a8;
        margin: 14px 0;
    }
    .yes {
        background: #07552f;
        border: 2px solid #20c77a;
        padding: 20px;
        border-radius: 16px;
        text-align: center;
    }
    .no {
        background: #651b1b;
        border: 2px solid #ef5350;
        padding: 20px;
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
    }
    [data-testid="stStatusWidget"], [data-testid="stDecoration"] {
        display: none !important;
    }
    div.stButton > button {
        min-height: 42px;
        border-radius: 11px;
        font-weight: 700;
        background: #12365f;
        color: white;
        border: 1px solid #3c6795;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# AUTH
# ============================================================

if not st.session_state["authenticated"]:
    st.title("VasuDev Cricket AI")
    st.caption("Private access")
    entered_password = st.text_input(
        "Password",
        type="password",
        key="auth_input",
    )

    if st.button("Unlock", key="unlock_button", use_container_width=True):
        if hmac.compare_digest(entered_password, PASSWORD):
            st.session_state["authenticated"] = True
            st.session_state.pop("auth_input", None)
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()

# ============================================================
# DATABASE
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
LEAGUES = list(DB_PATHS.keys())


def parse_ball_position(value):
    try:
        over_text, ball_text = str(value).split(".", 1)
        return int(over_text) * 6 + int(ball_text)
    except Exception:
        return np.nan


def build_database(path, league, archive_path):
    temp_path = path.with_suffix(".tmp")
    if temp_path.exists():
        temp_path.unlink()

    connection = sqlite3.connect(str(temp_path))
    try:
        connection.execute(
            "CREATE TABLE matches(match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT)"
        )
        connection.execute(
            """
            CREATE TABLE deliveries(
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

        with zipfile.ZipFile(archive_path) as archive:
            for name in (item for item in archive.namelist() if item.endswith(".json")):
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
                        or ""
                    )
                    match_id = Path(name).stem
                    match_rows.append(
                        (match_id, info.get("venue", "") or "", str(winner), league)
                    )

                    for innings_no, innings in enumerate(data.get("innings", []), start=1):
                        if innings.get("super_over"):
                            continue

                        batting_team = innings.get("team", "")
                        bowling_team = next(
                            (team for team in teams if team != batting_team),
                            "",
                        )

                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))
                            for delivery in over.get("deliveries", []):
                                ball_no = delivery.get("actual_delivery")
                                if not ball_no:
                                    try:
                                        ball_no = f"{over_no}.{int(delivery.get('ball'))}"
                                    except Exception:
                                        continue

                                runs = int(
                                    (delivery.get("runs") or {}).get("total", 0) or 0
                                )
                                wickets = len(delivery.get("wickets") or [])
                                delivery_rows.append(
                                    (
                                        match_id,
                                        innings_no,
                                        batting_team,
                                        bowling_team,
                                        over_no,
                                        str(ball_no),
                                        runs,
                                        wickets,
                                        league,
                                    )
                                )
                except Exception:
                    continue

        connection.executemany(
            "INSERT OR REPLACE INTO matches VALUES (?,?,?,?)",
            match_rows,
        )
        connection.executemany(
            """
            INSERT INTO deliveries(
                match_id, innings_no, batting_team, bowling_team,
                over_no, ball_no, runs, wickets, league
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            delivery_rows,
        )
        connection.execute(
            "CREATE INDEX deliveries_lookup ON deliveries(league, innings_no, ball_no)"
        )
        connection.commit()
    finally:
        connection.close()

    temp_path.replace(path)


def ensure_database(league):
    path = DB_PATHS[league]
    if path.exists():
        return path

    building_path = path.with_suffix(".building")
    with tempfile.TemporaryDirectory() as temp_dir:
        archive_path = Path(temp_dir) / "data.zip"
        urllib.request.urlretrieve(DATA_URLS[league], archive_path)
        build_database(building_path, league, archive_path)

    building_path.replace(path)
    return path


@st.cache_data(show_spinner=False, max_entries=6)
def load_history(league, path_string):
    path = Path(path_string)
    query = """
        SELECT
            d.match_id,
            d.innings_no,
            d.batting_team,
            d.bowling_team,
            d.ball_no,
            d.runs,
            d.wickets,
            m.venue,
            m.winner
        FROM deliveries d
        JOIN matches m ON m.match_id = d.match_id
        WHERE d.league = ?
        ORDER BY d.match_id, d.innings_no, d.id
    """

    with closing(
        sqlite3.connect(
            f"file:{path.resolve()}?mode=ro",
            uri=True,
            check_same_thread=False,
            timeout=30,
        )
    ) as connection:
        dataframe = pd.read_sql_query(query, connection, params=(league,))

    if dataframe.empty:
        return dataframe

    dataframe["ball_pos"] = dataframe["ball_no"].map(parse_ball_position)
    dataframe = dataframe.dropna(subset=["ball_pos"]).copy()
    if dataframe.empty:
        return dataframe

    dataframe["ball_pos"] = dataframe["ball_pos"].astype(int)
    dataframe["runs"] = pd.to_numeric(dataframe["runs"], errors="coerce").fillna(0)
    dataframe["wickets"] = pd.to_numeric(dataframe["wickets"], errors="coerce").fillna(0)

    for column in ["batting_team", "bowling_team", "venue", "winner"]:
        dataframe[column] = dataframe[column].fillna("").astype(str)

    grouped = dataframe.groupby(["match_id", "innings_no"], sort=False)
    dataframe["score"] = grouped["runs"].cumsum()
    dataframe["wk"] = grouped["wickets"].cumsum()
    dataframe["rr"] = np.where(
        dataframe["ball_pos"] > 0,
        dataframe["score"] / dataframe["ball_pos"] * 6.0,
        0.0,
    )

    dataframe["last6"] = grouped["runs"].transform(
        lambda values: values.rolling(6, min_periods=1).sum()
    )
    dataframe["last12"] = grouped["runs"].transform(
        lambda values: values.rolling(12, min_periods=1).sum()
    )

    return dataframe


# ============================================================
# LIVE STATE AND HELPERS
# ============================================================

def initialise_state():
    defaults = {
        "runs": 16,
        "wickets": 1,
        "balls": 19,
        "started": True,
        "undo": [],
        "last_action": "Starting situation",
        "session_over": 6,
        "target": 0,
        "session_low": 0,
        "session_high": 1,
        "session_expected": 0.0,
        "manual_session": False,
        "analysis": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def over_ball(balls):
    balls = int(balls)
    if balls <= 0:
        return "0.0"
    return f"{(balls - 1) // 6}.{((balls - 1) % 6) + 1}"


def to_balls(value):
    over_text, ball_text = str(value).split(".", 1)
    return int(over_text) * 6 + int(ball_text)


def save_snapshot():
    st.session_state.undo.append(
        (
            st.session_state.runs,
            st.session_state.wickets,
            st.session_state.balls,
            st.session_state.last_action,
        )
    )


def add_event(runs=0, wicket=False, legal_ball=True, label=""):
    save_snapshot()
    st.session_state.runs += int(runs)
    if wicket:
        st.session_state.wickets = min(10, st.session_state.wickets + 1)
    if legal_ball:
        st.session_state.balls += 1
    st.session_state.last_action = label
    st.session_state.analysis = None


def undo_event():
    if not st.session_state.undo:
        return
    runs, wickets, balls, last_action = st.session_state.undo.pop()
    st.session_state.runs = runs
    st.session_state.wickets = wickets
    st.session_state.balls = balls
    st.session_state.last_action = "Undo"
    st.session_state.analysis = None


def reset_live():
    st.session_state.runs = 0
    st.session_state.wickets = 0
    st.session_state.balls = 0
    st.session_state.undo = []
    st.session_state.last_action = ""
    st.session_state.started = False
    st.session_state.analysis = None


def auto_line(dataframe, innings_no, current_balls, current_runs, current_wickets, session_over):
    session_end = int(session_over) * 6

    if dataframe.empty or current_balls >= session_end:
        return current_runs, current_runs + 1, float(current_runs), 0

    candidates = dataframe[
        (dataframe["innings_no"] == innings_no)
        & dataframe["ball_pos"].between(
            max(1, current_balls - 2),
            current_balls + 2,
        )
        & (dataframe["ball_pos"] <= session_end)
    ].copy()

    if candidates.empty:
        return current_runs, current_runs + 1, float(current_runs), 0

    candidates = candidates[
        ((candidates["score"] - current_runs).abs() <= 30)
        & ((candidates["wk"] - current_wickets).abs() <= 3)
    ].copy()

    if candidates.empty:
        return current_runs, current_runs + 1, float(current_runs), 0

    candidates["weight"] = (
        np.exp(-((candidates["score"] - current_runs).abs()) / 10.0)
        * np.exp(-((candidates["wk"] - current_wickets).abs()) / 1.7)
        * np.exp(-((candidates["ball_pos"] - current_balls).abs()) / 2.5)
    )
    candidates = candidates.sort_values("weight", ascending=False).head(1000)

    grouped = dataframe.groupby(["match_id", "innings_no"], sort=False)
    future_scores = []
    weights = []

    for _, row in candidates.iterrows():
        try:
            match_data = grouped.get_group(
                (row["match_id"], int(row["innings_no"]))
            )
        except KeyError:
            continue

        future = match_data[match_data["ball_pos"] <= session_end]
        if future.empty:
            continue

        future_scores.append(float(future.iloc[-1]["score"]))
        weights.append(float(row["weight"]))

    if not future_scores:
        return current_runs, current_runs + 1, float(current_runs), 0

    expected = float(np.average(future_scores, weights=weights))
    low = max(current_runs, int(round(expected)))
    return low, low + 1, expected, len(future_scores)


def calculate_analysis(dataframe, innings_no, current_balls, current_runs, current_wickets, session_end, threshold):
    if dataframe.empty:
        return None

    future_scores = []

    for match_id, match_data in dataframe.groupby(["match_id"], sort=False):
        innings_data = match_data[
            (match_data["innings_no"] == innings_no)
            & match_data["ball_pos"].between(
                max(1, current_balls - 2),
                current_balls + 2
            )
        ].copy()

        if innings_data.empty:
            continue

        innings_data = innings_data[
            ((innings_data["score"] - current_runs).abs() <= 30)
            & ((innings_data["wk"] - current_wickets).abs() <= 3)
        ]
        if innings_data.empty:
            continue

        future = match_data[match_data["ball_pos"] <= session_end]
        if not future.empty:
            future_scores.append(float(future.iloc[-1]["score"]))

    if not future_scores:
        return None

    values = np.asarray(future_scores, dtype=float)
    yes = float((values >= threshold).mean() * 100.0)
    no = 100.0 - yes

    return {
        "yes": yes,
        "no": no,
        "samples": len(values),
        "expected": float(values.mean()),
        "low": float(np.quantile(values, 0.10)),
        "high": float(np.quantile(values, 0.90)),
    }


initialise_state()


# ============================================================
# SIDEBAR INPUTS
# ============================================================

with st.sidebar:
    league = st.selectbox("League", LEAGUES, key="league_choice")

    try:
        database_path = ensure_database(league)
    except Exception as error:
        st.error(f"Historical data could not be prepared: {error}")
        st.stop()

    history = load_history(league, str(database_path))

    if history.empty:
        st.error("No historical data found for this league.")
        st.stop()

    teams = sorted(
        set(history["batting_team"].dropna()) |
        set(history["bowling_team"].dropna())
    )
    venues = sorted(
        venue for venue in history["venue"].dropna().unique() if venue
    ) or ["Unknown"]

    batting_team = st.selectbox("Batting Team", teams, key="batting_choice")
    bowling_team = st.selectbox(
        "Bowling Team",
        [team for team in teams if team != batting_team],
        key="bowling_choice",
    )
    venue = st.selectbox("Ground", venues, key="venue_choice")
    innings_label = st.selectbox(
        "Innings",
        ["1st Innings", "2nd Innings"],
        key="innings_choice",
    )

    session_over = st.number_input(
        "Session Over",
        min_value=1,
        max_value=20,
        value=int(st.session_state.session_over),
        step=1,
        key="session_over_input",
    )
    target_runs = st.number_input(
        "Target Runs",
        min_value=0,
        max_value=400,
        value=int(st.session_state.target),
        step=1,
        key="target_input",
    )

    start_over = st.selectbox(
        "Start Over / Ball",
        ["0.0"] + [f"{over}.{ball}" for over in range(20) for ball in range(1, 7)],
        index=19,
        key="start_over_input",
    )
    start_runs = st.number_input(
        "Start Runs",
        min_value=0,
        max_value=400,
        value=16,
        step=1,
        key="start_runs_input",
    )
    start_wickets = st.number_input(
        "Start Wickets",
        min_value=0,
        max_value=10,
        value=1,
        step=1,
        key="start_wickets_input",
    )

    st.session_state.session_over = int(session_over)
    st.session_state.target = int(target_runs)

    if st.button("Set Current Match Situation", use_container_width=True, key="set_situation"):
        st.session_state.runs = int(start_runs)
        st.session_state.wickets = int(start_wickets)
        st.session_state.balls = to_balls(start_over)
        st.session_state.undo = []
        st.session_state.last_action = "Starting situation set"
        st.session_state.started = True
        st.session_state.analysis = None
        st.rerun()

    if st.button("Reset Live Situation", use_container_width=True, key="reset_live"):
        reset_live()
        st.rerun()


# ============================================================
# CURRENT STATE AND AUTO SESSION
# ============================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)
innings_no = 1 if innings_label.startswith("1") else 2

low, high, expected, sample_count = auto_line(
    history,
    innings_no,
    balls,
    runs,
    wickets,
    int(session_over),
)

if not st.session_state.manual_session:
    st.session_state.session_low = int(low)
    st.session_state.session_high = int(high)
    st.session_state.session_expected = float(expected)


# ============================================================
# LIVE UI
# ============================================================

st.markdown(
    f"""
    <div class="card">
        <h3>Current Live Score</h3>
        <h2>{runs}/{wickets}</h2>
        <p class="small">
            Over/Ball: {over_ball(balls)} •
            Target: {target_runs or 'Not set'} •
            Session over: {session_over} •
            Last: {st.session_state.last_action or '—'}
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.subheader("Ball-by-Ball Update")
button_definitions = [
    ("Dot", 0, False, True),
    ("1 Run", 1, False, True),
    ("2 Runs", 2, False, True),
    ("3 Runs", 3, False, True),
    ("4 Runs", 4, False, True),
    ("6 Runs", 6, False, True),
    ("Wicket", 0, True, True),
    ("Undo", 0, False, False),
]

button_columns = st.columns(4)
for index, (label, run_value, wicket, legal_ball) in enumerate(button_definitions):
    with button_columns[index % 4]:
        if st.button(label, use_container_width=True, key=f"ball_button_{index}"):
            if label == "Undo":
                undo_event()
            else:
                add_event(run_value, wicket, legal_ball, label)
            st.rerun()

st.subheader("Match Detail")
detail_columns = st.columns(4)
detail_columns[0].metric("Batting", batting_team)
detail_columns[1].metric("Bowling", bowling_team)
detail_columns[2].metric("Ground", venue)
detail_columns[3].metric("Innings", innings_label)

st.markdown(
    f"""
    <div class="session-box">
        <h3>Session</h3>
        <h2>{int(st.session_state.session_low)}-{int(st.session_state.session_high)}</h2>
        <p class="small">
            Expected: {float(st.session_state.session_expected):.1f} •
            Over: {session_over} •
            Target: {target_runs or 'Not set'} •
            Mode: {'Manual' if st.session_state.manual_session else 'Auto'} •
            Samples: {sample_count}
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

manual_columns = st.columns(3)
with manual_columns[0]:
    manual_low = st.number_input(
        "Manual Session Low",
        min_value=0,
        max_value=400,
        value=int(st.session_state.session_low),
        step=1,
        key="manual_low_input",
    )
with manual_columns[1]:
    manual_high = st.number_input(
        "Manual Session High",
        min_value=0,
        max_value=400,
        value=int(st.session_state.session_high),
        step=1,
        key="manual_high_input",
    )
with manual_columns[2]:
    st.text_input("Manual Note", key="manual_note_input")

manual_buttons = st.columns(2)
with manual_buttons[0]:
    if st.button("Apply Manual Session", use_container_width=True, key="apply_manual"):
        st.session_state.manual_session = True
        st.session_state.session_low = int(manual_low)
        st.session_state.session_high = max(int(manual_low) + 1, int(manual_high))
        st.session_state.analysis = None
        st.rerun()
with manual_buttons[1]:
    if st.button("Use Auto Session", use_container_width=True, key="use_auto"):
        st.session_state.manual_session = False
        st.session_state.analysis = None
        st.rerun()


# ============================================================
# ANALYSIS
# ============================================================

if st.button("Analyze Current Situation", use_container_width=True, key="analyze"):
    threshold = int(st.session_state.session_high)
    st.session_state.analysis = calculate_analysis(
        history,
        innings_no,
        balls,
        runs,
        wickets,
        int(session_over) * 6,
        threshold,
    )
    st.rerun()

analysis = st.session_state.get("analysis")

if analysis is not None:
    yes = float(analysis["yes"])
    no = float(analysis["no"])
    label = "YES" if yes >= no else "NO"
    percentage = max(yes, no)
    css_class = "yes" if label == "YES" else "no"

    st.subheader("VasuDev Result")
    st.markdown(
        f"""
        <div class="{css_class}">
            <h1>{label} — {percentage:.1f}%</h1>
            <p>
                Session line: <b>{int(st.session_state.session_low)}-{int(st.session_state.session_high)}</b>
                • {analysis['samples']} similar historical states
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Historical estimate only; it is not a guarantee.")

    with st.expander("Details", expanded=False):
        st.write(f"Expected score: **{analysis['expected']:.1f}**")
        st.write(
            f"Historical 10–90% range: **{int(round(analysis['low']))}–{int(round(analysis['high']))}**"
        )
        st.write(f"YES: **{yes:.1f}%** • NO: **{no:.1f}%**")
else:
    st.info("Enter the match situation and press Analyze Current Situation.")
