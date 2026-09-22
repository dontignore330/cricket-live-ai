import os
import hmac
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide",
)

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #061426, #081c35);
        color: #f8fafc;
    }

    .block-container {
        max-width: 1500px;
        padding-top: 1rem !important;
    }

    .card {
        background: #0f223c;
        border: 1px solid #2d4d72;
        border-radius: 16px;
        padding: 16px 18px;
        min-height: 120px;
        box-shadow: 0 12px 24px rgba(0,0,0,0.15);
    }

    .box {
        background: #0f223c;
        border: 1px solid #2d4d72;
        border-radius: 16px;
        padding: 14px 16px;
        min-height: 120px;
        text-align: center;
    }

    .session-box {
        background: #0f223c;
        border: 2px solid #4777a8;
        border-radius: 16px;
        padding: 18px 14px;
        text-align: center;
        margin-top: 6px;
    }

    .winning-box {
        background: #0f223c;
        border: 2px solid #b78d26;
        border-radius: 16px;
        padding: 18px 14px;
        text-align: center;
        margin-top: 6px;
    }

    .yes {
        background: #0a5d34;
        border: 2px solid #22c55e;
        border-radius: 12px;
        padding: 14px 12px;
        text-align: center;
    }

    .no {
        background: #5b1a1a;
        border: 2px solid #ef4444;
        border-radius: 12px;
        padding: 14px 12px;
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

    div.stButton > button {
        min-height: 40px;
        border-radius: 10px;
        font-weight: 700;
        background: #12365f;
        color: #fff;
        border: 1px solid #3c6795;
    }

    .stRadio [data-baseweb="radio"] > div {
        background: #0d233d;
        border-radius: 10px;
        padding: 6px 10px;
    }

    /* Remove unnecessary gaps between ball buttons */
    div[data-testid="stHorizontalBlock"] {
        gap: 0.25rem !important;
    }

    div[data-testid="column"] {
        padding-left: 2px !important;
        padding-right: 2px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# AUTH
# ============================================================

if not st.session_state.authenticated:
    st.title("VasuDev Cricket AI")

    password = st.text_input(
        "Password",
        type="password",
        key="auth_password",
    )

    if st.button(
        "Unlock",
        use_container_width=True,
        key="unlock",
    ):
        if hmac.compare_digest(password, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("auth_password", None)
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()


# ============================================================
# DATABASE SETTINGS
# ============================================================

BASE = Path(".")

DBS = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db",
}

URLS = {
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
}

LEAGUES = list(DBS)


# ============================================================
# BALL PARSING
# ============================================================

def parse_ball(value):
    try:
        over, ball = str(value).split(".", 1)
        over = int(over)
        ball = int(ball)

        if over < 0 or ball <= 0:
            raise ValueError

        return over * 6 + ball

    except Exception:
        return None


def display_over(balls):
    balls = int(balls)

    if balls <= 0:
        return "0.0"

    return f"{(balls - 1) // 6}.{((balls - 1) % 6) + 1}"


# ============================================================
# DATABASE HELPERS
# ============================================================

def table_columns(connection, table):
    return {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table})"
        )
    }


def migrate_database(path):
    if not path.exists():
        return

    connection = sqlite3.connect(str(path), timeout=60)

    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        if "deliveries" not in tables:
            return

        columns = table_columns(connection, "deliveries")

        if "ball_pos" not in columns:
            connection.execute(
                "ALTER TABLE deliveries ADD COLUMN ball_pos INTEGER"
            )

            rows = connection.execute(
                "SELECT id, ball_no FROM deliveries WHERE ball_pos IS NULL"
            ).fetchall()

            updates = [
                (parse_ball(ball_no), row_id)
                for row_id, ball_no in rows
            ]

            connection.executemany(
                "UPDATE deliveries SET ball_pos=? WHERE id=?",
                updates,
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deliveries_state
            ON deliveries(league, innings_no, ball_pos)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deliveries_match
            ON deliveries(match_id, innings_no, ball_pos)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_matches_league
            ON matches(league)
            """
        )

        connection.commit()

    finally:
        connection.close()


def readonly(path):
    migrate_database(path)

    connection = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=60,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-8000")

    return connection


# ============================================================
# DATABASE BUILDER
# ============================================================

def build_database(path, league, archive):
    temporary = path.with_suffix(".tmp")

    if temporary.exists():
        temporary.unlink()

    connection = sqlite3.connect(str(temporary))

    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")

        connection.execute(
            """
            CREATE TABLE matches(
                match_id TEXT PRIMARY KEY,
                venue TEXT,
                winner TEXT,
                league TEXT
            )
            """
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
                ball_pos INTEGER,
                runs INTEGER,
                wickets INTEGER,
                league TEXT
            )
            """
        )

        matches = []
        deliveries = []

        with zipfile.ZipFile(archive) as source:
            for filename in source.namelist():
                if not filename.endswith(".json"):
                    continue

                try:
                    data = json.loads(source.read(filename))
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

                    match_id = Path(filename).stem

                    matches.append(
                        (
                            match_id,
                            str(info.get("venue", "") or ""),
                            str(winner),
                            league,
                        )
                    )

                    for innings_no, innings in enumerate(
                        data.get("innings", []),
                        1,
                    ):
                        if innings.get("super_over"):
                            continue

                        batting = innings.get("team", "")
                        bowling = next(
                            (team for team in teams if team != batting),
                            "",
                        )

                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))

                            for delivery in over.get("deliveries", []):
                                value = delivery.get("actual_delivery")

                                if not value:
                                    try:
                                        value = f"{over_no}.{int(delivery.get('ball'))}"
                                    except Exception:
                                        continue

                                position = parse_ball(value)
                                if position is None:
                                    continue

                                runs = int(
                                    (delivery.get("runs") or {}).get("total", 0) or 0
                                )
                                wickets = len(delivery.get("wickets") or [])

                                deliveries.append(
                                    (
                                        match_id,
                                        innings_no,
                                        batting,
                                        bowling,
                                        over_no,
                                        str(value),
                                        position,
                                        runs,
                                        wickets,
                                        league,
                                    )
                                )

                    if len(matches) >= 100:
                        connection.executemany(
                            """
                            INSERT OR REPLACE INTO matches
                            VALUES(?,?,?,?)
                            """,
                            matches,
                        )
                        matches.clear()

                    if len(deliveries) >= 5000:
                        connection.executemany(
                            """
                            INSERT INTO deliveries(
                                match_id, innings_no, batting_team, bowling_team,
                                over_no, ball_no, ball_pos, runs, wickets, league
                            )
                            VALUES(?,?,?,?,?,?,?,?,?,?)
                            """,
                            deliveries,
                        )
                        deliveries.clear()

                except Exception:
                    continue

        if matches:
            connection.executemany(
                """
                INSERT OR REPLACE INTO matches
                VALUES(?,?,?,?)
                """,
                matches,
            )

        if deliveries:
            connection.executemany(
                """
                INSERT INTO deliveries(
                    match_id, innings_no, batting_team, bowling_team,
                    over_no, ball_no, ball_pos, runs, wickets, league
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                deliveries,
            )

        connection.execute(
            """
            CREATE INDEX idx_deliveries_state
            ON deliveries(league, innings_no, ball_pos)
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_deliveries_match
            ON deliveries(match_id, innings_no, ball_pos)
            """
        )

        connection.commit()

    finally:
        connection.close()

    temporary.replace(path)


# ============================================================
# ENSURE DATABASE
# ============================================================

def ensure_database(league):
    path = DBS[league]

    if path.exists():
        migrate_database(path)
        return path

    if league == "IPL":
        return path

    building = path.with_suffix(".building")

    try:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "matches.zip"
            urllib.request.urlretrieve(URLS[league], archive)
            build_database(building, league, archive)

        building.replace(path)
        return path

    except Exception:
        if building.exists():
            building.unlink()
        raise


# ============================================================
# VALUES HELPER
# ============================================================

def values(connection, sql, league):
    return [
        row[0]
        for row in connection.execute(sql, (league,)).fetchall()
        if row[0]
    ]


# ============================================================
# SCORE
# ============================================================

def score_at(connection, match_id, innings_no, end_ball):
    row = connection.execute(
        """
        SELECT
            COALESCE(SUM(runs), 0),
            COALESCE(SUM(wickets), 0)
        FROM deliveries
        WHERE match_id=?
        AND innings_no=?
        AND ball_pos<=?
        """,
        (match_id, innings_no, end_ball),
    ).fetchone()

    return (
        int(row[0] or 0),
        int(row[1] or 0),
    )


# ============================================================
# SIMILAR HISTORICAL MATCHES
# ============================================================

def similar_matches(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    end_ball,
):
    rows = connection.execute(
        """
        SELECT DISTINCT
            match_id,
            innings_no,
            ball_pos
        FROM deliveries
        WHERE league=?
        AND innings_no=?
        AND ball_pos BETWEEN ? AND ?
        AND ball_pos<=?
        LIMIT 2500
        """,
        (
            league,
            innings_no,
            max(1, current_ball - 2),
            current_ball + 2,
            end_ball,
        ),
    ).fetchall()

    result = []

    for row in rows:
        score, wickets = score_at(
            connection,
            row["match_id"],
            row["innings_no"],
            row["ball_pos"],
        )

        if (
            abs(score - current_runs) <= 30
            and abs(wickets - current_wickets) <= 3
        ):
            weight = (
                1
                / (1 + abs(score - current_runs))
                / (1 + abs(wickets - current_wickets))
                / (1 + abs(row["ball_pos"] - current_ball))
            )

            result.append((row["match_id"], int(row["innings_no"]), weight))

    result.sort(key=lambda item: item[2], reverse=True)
    return result[:800]


# ============================================================
# SESSION CALCULATION
# ============================================================

def calculate_line(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
):
    end_ball = int(session_over) * 6

    if current_ball >= end_ball:
        return (
            current_runs,
            current_runs + 1,
            float(current_runs),
            0,
        )

    matches = similar_matches(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        end_ball,
    )

    if not matches:
        return (
            current_runs,
            current_runs + 1,
            float(current_runs),
            0,
        )

    scores = []
    weights = []

    for match_id, inn, weight in matches:
        scores.append(score_at(connection, match_id, inn, end_ball)[0])
        weights.append(weight)

    expected = (
        sum(score * weight for score, weight in zip(scores, weights))
        / sum(weights)
    )

    low = max(current_runs, int(round(expected)))

    return (
        low,
        low + 1,
        expected,
        len(scores),
    )


# ============================================================
# RESULT CALCULATION
# ============================================================

def calculate_result(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    threshold,
):
    end_ball = int(session_over) * 6

    matches = similar_matches(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        end_ball,
    )

    if not matches:
        return None

    scores = [
        score_at(connection, match_id, inn, end_ball)[0]
        for match_id, inn, _ in matches
    ]

    if not scores:
        return None

    yes = (
        sum(score >= threshold for score in scores) / len(scores) * 100
    )

    ordered = sorted(scores)

    return {
        "yes": yes,
        "no": 100 - yes,
        "samples": len(scores),
        "expected": sum(scores) / len(scores),
        "low": ordered[max(0, int(len(ordered) * 0.1) - 1)],
        "high": ordered[max(0, int(len(ordered) * 0.9) - 1)],
    }


# ============================================================
# SESSION STATE DEFAULTS
# ============================================================

for key, value in {
    "runs": 16,
    "wickets": 1,
    "balls": 19,
    "last": "Starting situation",
    "undo": [],
    "session_over": 6,
    "target": 0,
    "low": 0,
    "high": 1,
    "expected": 0.0,
    "manual": False,
    "analysis": None,
    "session_mode": "Auto",
}.items():
    st.session_state.setdefault(key, value)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    league = st.selectbox(
        "League",
        LEAGUES,
        key="league_choice",
    )

    try:
        database_path = ensure_database(league)
        connection = readonly(database_path)
    except Exception as error:
        st.error(f"Historical database could not be prepared: {error}")
        st.stop()

    teams = values(
        connection,
        """
        SELECT DISTINCT batting_team
        FROM deliveries
        WHERE league=?
        ORDER BY batting_team
        """,
        league,
    )

    venues = values(
        connection,
        """
        SELECT DISTINCT venue
        FROM matches
        WHERE league=?
        AND venue<>''
        ORDER BY venue
        """,
        league,
    ) or ["Unknown"]

    if not teams:
        st.error("No teams found in database.")
        st.stop()

    batting = st.selectbox(
        "Batting Team",
        teams,
        key="batting_team",
    )

    bowling_options = [team for team in teams if team != batting]

    bowling = st.selectbox(
        "Bowling Team",
        bowling_options,
        key="bowling_team",
    )

    venue = st.selectbox(
        "Ground",
        venues,
        key="ground",
    )

    innings_label = st.selectbox(
        "Innings",
        ["1st Innings", "2nd Innings"],
        key="innings",
    )

    innings_no = 1 if innings_label.startswith("1") else 2

    session_over = st.number_input(
        "Session Over",
        1,
        20,
        int(st.session_state.session_over),
        1,
        key="session_over_input",
    )

    target = st.number_input(
        "Target Runs",
        0,
        400,
        int(st.session_state.target),
        1,
        key="target_input",
    )

    st.session_state.session_over = int(session_over)
    st.session_state.target = int(target)

    points = ["0.0"] + [f"{over}.{ball}" for over in range(20) for ball in range(1, 7)]

    start_over = st.selectbox(
        "Start Over / Ball",
        points,
        index=19,
        key="start_over",
    )

    start_runs = st.number_input(
        "Start Runs",
        0,
        400,
        16,
        1,
        key="start_runs",
    )

    start_wickets = st.number_input(
        "Start Wickets",
        0,
        10,
        1,
        1,
        key="start_wickets",
    )

    if st.button("Set Current Match Situation", use_container_width=True, key="set_situation"):
        st.session_state.runs = int(start_runs)
        st.session_state.wickets = int(start_wickets)
        st.session_state.balls = parse_ball(start_over) or 0
        st.session_state.undo = []
        st.session_state.last = "Starting situation set"
        st.session_state.analysis = None
        st.rerun()

    if st.button("Reset Live Situation", use_container_width=True, key="reset_live"):
        st.session_state.runs = 0
        st.session_state.wickets = 0
        st.session_state.balls = 0
        st.session_state.undo = []
        st.session_state.last = ""
        st.session_state.analysis = None
        st.rerun()


# ============================================================
# CURRENT STATE
# ============================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

low, high, expected, samples = calculate_line(
    connection,
    league,
    innings_no,
    balls,
    runs,
    wickets,
    session_over,
)

if not st.session_state.manual:
    st.session_state.low = low
    st.session_state.high = high
    st.session_state.expected = expected

# ============================================================
# AUTO SESSION + MANUAL SESSION
# ============================================================

mode = st.radio(
    "Session Mode",
    ["Auto", "Manual"],
    index=0 if st.session_state.session_mode == "Auto" else 1,
    horizontal=True,
    key="session_mode",
)

st.session_state.session_mode = mode

if mode == "Manual":
    st.session_state.manual = True
else:
    st.session_state.manual = False

# ============================================================
# AUTO RESULT CALCULATION
# ============================================================

session_analysis = calculate_result(
    connection,
    league,
    innings_no,
    balls,
    runs,
    wickets,
    session_over,
    int(st.session_state.high),
)

st.session_state.analysis = session_analysis


# ============================================================
# TOP LIVE BOX + BALL BUTTONS
# ============================================================

top_left, top_right = st.columns([1, 3], gap="small")

with top_left:
    st.markdown(
        f"""
        <div class="card">
            <div style="font-size:14px; color:#bed0e5; margin-bottom:6px;">Live Score</div>
            <div style="font-size:32px; font-weight:800; line-height:1.2;">{batting}</div>
            <div style="font-size:28px; font-weight:700; margin-top:8px;">{runs}/{wickets}</div>
            <div style="font-size:14px; color:#bed0e5; margin-top:8px;">{display_over(balls)} ov</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top_right:
    ball_buttons = [
        ("Dot", 0, False),
        ("1", 1, False),
        ("2", 2, False),
        ("4", 4, False),
        ("6", 6, False),
        ("Wicket", 0, True),
        ("Wide", 1, False),
        ("No Ball", 1, False),
    ]

    btn_cols = st.columns(8, gap="small")

    for i, (label, run_value, wicket) in enumerate(ball_buttons):
        with btn_cols[i]:
            if st.button(label, use_container_width=True, key=f"ball_{i}"):
                if label == "Wide" or label == "No Ball":
                    st.session_state.undo.append((runs, wickets, balls, st.session_state.last))
                    st.session_state.runs += int(run_value)
                    st.session_state.last = label
                    st.session_state.analysis = None
                    st.rerun()

                elif label == "Wicket":
                    st.session_state.undo.append((runs, wickets, balls, st.session_state.last))
                    st.session_state.wickets = min(10, wickets + 1)
                    st.session_state.balls += 1
                    st.session_state.last = "Wicket"
                    st.session_state.analysis = None
                    st.rerun()

                else:
                    st.session_state.undo.append((runs, wickets, balls, st.session_state.last))
                    st.session_state.runs += int(run_value)
                    st.session_state.balls += 1
                    st.session_state.last = label
                    st.session_state.analysis = None
                    st.rerun()

    if st.button("Undo", use_container_width=True, key="btn_undo"):
        if st.session_state.undo:
            st.session_state.runs, st.session_state.wickets, st.session_state.balls, st.session_state.last = st.session_state.undo.pop()
            st.session_state.analysis = None
            st.rerun()


# ============================================================
# SESSION RESULT CARD
# ============================================================

if session_analysis:
    yes = float(session_analysis["yes"])
    no = float(session_analysis["no"])

    if yes >= no:
        result_label = "YES"
        result_value = yes
        result_css = "yes"
    else:
        result_label = "NO"
        result_value = no
        result_css = "no"

    st.markdown(
        f"""
        <div class="session-box">
            <div style="font-size:15px; color:#bed0e5; margin-bottom:6px;">Session Result</div>
            <div class="{result_css}" style="width:100%; margin:0 auto;">
                <div style="font-size:18px; font-weight:800; letter-spacing:0.5px;">{result_label}</div>
                <div style="font-size:32px; font-weight:800; margin-top:6px;">{result_value:.1f}%</div>
            </div>

            <div style="margin-top:12px; font-size:14px; color:#bed0e5;">
                <div><b>Session</b>: {int(st.session_state.low)} - {int(st.session_state.high)}</div>
                <div><b>Avg Score</b>: {session_analysis['expected']:.1f}</div>
                <div><b>Similar Matches</b>: {session_analysis['samples']}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <div class="session-box">
            <div style="font-size:15px; color:#bed0e5; margin-bottom:6px;">Session Result</div>
            <div style="font-size:28px; font-weight:700;">Calculating...</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# TEAM WINNING CARD
# ============================================================

winning_data = None

if target > 0:
    winning_data = calculate_result(
        connection,
        league,
        innings_no,
        balls,
        runs,
        wickets,
        session_over,
        int(target),
    )

if winning_data is None:
    if session_analysis:
        winning_data = session_analysis

if winning_data:
    win_yes = float(winning_data["yes"])
    win_no = float(winning_data["no"])

    if win_yes >= win_no:
        winning_label = batting
        winning_pct = win_yes
        winning_css = "yes"
    else:
        winning_label = bowling
        winning_pct = win_no
        winning_css = "no"

    st.markdown(
        f"""
        <div class="winning-box">
            <div style="font-size:15px; color:#bed0e5; margin-bottom:6px;">Team Winning</div>
            <div class="{winning_css}" style="width:100%; margin:0 auto;">
                <div style="font-size:18px; font-weight:800; letter-spacing:0.5px;">{winning_label}</div>
                <div style="font-size:32px; font-weight:800; margin-top:6px;">{winning_pct:.1f}%</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <div class="winning-box">
            <div style="font-size:15px; color:#bed0e5; margin-bottom:6px;">Team Winning</div>
            <div style="font-size:28px; font-weight:700;">Calculating...</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# MATCH DETAIL
# ============================================================

st.subheader("Match Detail")

detail = st.columns(4)
detail[0].metric("Batting", batting)
detail[1].metric("Bowling", bowling)
detail[2].metric("Ground", venue)
detail[3].metric("Innings", innings_label)


# ============================================================
# MANUAL SESSION
# ============================================================

st.subheader("Session Settings")

manual = st.columns(2)

with manual[0]:
    manual_low = st.number_input(
        "Session Low",
        0,
        400,
        int(st.session_state.low),
        1,
        key="manual_low",
    )

with manual[1]:
    manual_high = st.number_input(
        "Session High",
        0,
        400,
        int(st.session_state.high),
        1,
        key="manual_high",
    )

a, b = st.columns(2)

with a:
    if st.button("Apply Manual Session", use_container_width=True, key="apply_manual"):
        st.session_state.manual = True
        st.session_state.low = int(manual_low)
        st.session_state.high = max(int(manual_low) + 1, int(manual_high))
        st.session_state.analysis = None
        st.rerun()

with b:
    if st.button("Use Auto Session", use_container_width=True, key="auto_session"):
        st.session_state.manual = False
        st.session_state.analysis = None
        st.rerun()


# ============================================================
# FINAL RESULT SUMMARY
# ============================================================

if session_analysis:
    yes = float(session_analysis["yes"])
    no = float(session_analysis["no"])
    result_label = "YES" if yes >= no else "NO"
    result_css = "yes" if result_label == "YES" else "no"

    st.subheader("VasuDev Result")

    st.markdown(
        f"""
        <div class="{result_css}" style="padding:16px; border-radius:16px; text-align:center;">
            <h1>{result_label} — {max(yes, no):.1f}%</h1>
            <p>Session: <b>{int(st.session_state.low)} - {int(st.session_state.high)}</b></p>
            <p>Avg Score: <b>{session_analysis['expected']:.1f}</b></p>
            <p>Similar Matches: <b>{session_analysis['samples']}</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("Historical estimate only; it is not a guarantee.")

    with st.expander("Details"):
        st.write(f"Expected score: **{session_analysis['expected']:.1f}**")
        st.write(f"Historical range: **{int(session_analysis['low'])}–{int(session_analysis['high'])}**")
        st.write(f"YES: **{yes:.1f}%** • NO: **{no:.1f}%**")
