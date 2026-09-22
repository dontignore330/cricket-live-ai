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

    .live-card,
    .session-box,
    .winning-box {
        background: #0f223c;
        border-radius: 16px;
        padding: 16px;
        border: 1px solid #2d4d72;
        text-align: center;
    }

    .live-card {
        min-height: 150px;
    }

    .session-box,
    .winning-box {
        min-height: 245px;
    }

    .yes {
        background: #07552f;
        border: 2px solid #20c77a;
        border-radius: 12px;
        padding: 14px;
        text-align: center;
    }

    .no {
        background: #651b1b;
        border: 2px solid #ef5350;
        border-radius: 12px;
        padding: 14px;
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
        min-height: 42px;
        border-radius: 10px;
        font-weight: 700;
        background: #12365f;
        color: #fff;
        border: 1px solid #3c6795;
    }

    div[data-testid="stHorizontalBlock"] {
        gap: 0.35rem !important;
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
# SESSION MODE
# ============================================================

mode = st.radio(
    "Session Mode",
    ["Auto", "Manual"],
    index=0 if st.session_state.session_mode == "Auto" else 1,
    horizontal=True,
    key="session_mode",
)

st.session_state.manual = mode == "Manual"

# ============================================================
# AUTOMATIC RESULT
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
# TOP LIVE SCORE + BALL BUTTONS
# ============================================================

top_score, top_buttons = st.columns([1, 4], gap="small")

with top_score:
    st.markdown(
        f"""
        <div class="live-card">
            <div class="small">Live Score</div>
            <h2 style="margin:8px 0 4px 0;">{batting}</h2>
            <h1 style="margin:0;">{runs}/{wickets}</h1>
            <p class="small" style="margin-top:8px;">{display_over(balls)} ov</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top_buttons:
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    ball_buttons = [
        ("Dot", 0, False, True),
        ("1", 1, False, True),
        ("2", 2, False, True),
        ("4", 4, False, True),
        ("6", 6, False, True),
        ("Wkt", 0, True, True),
        ("Wide", 1, False, False),
        ("No Ball", 1, False, False),
    ]

    button_columns = st.columns(8, gap="small")

    for index, (label, run_value, wicket, legal_ball) in enumerate(ball_buttons):
        with button_columns[index]:
            if st.button(
                label,
                use_container_width=True,
                key=f"live_ball_{index}",
            ):
                st.session_state.undo.append(
                    (
                        runs,
                        wickets,
                        balls,
                        st.session_state.last,
                    )
                )

                st.session_state.runs += int(run_value)

                if wicket:
                    st.session_state.wickets = min(
                        10,
                        wickets + 1,
                    )

                if legal_ball:
                    st.session_state.balls += 1

                st.session_state.last = label
                st.session_state.analysis = None
                st.rerun()

    if st.button(
        "Undo",
        use_container_width=True,
        key="live_undo",
    ):
        if st.session_state.undo:
            (
                st.session_state.runs,
                st.session_state.wickets,
                st.session_state.balls,
                st.session_state.last,
            ) = st.session_state.undo.pop()

            st.session_state.analysis = None
            st.rerun()

# ============================================================
# SESSION + TEAM WINNING
# ============================================================

session_column, winning_column = st.columns(2, gap="small")

with session_column:
    if session_analysis:
        session_yes = float(session_analysis["yes"])
        session_no = float(session_analysis["no"])

        if session_yes >= session_no:
            session_label = "YES"
            session_percent = session_yes
            session_class = "yes"
        else:
            session_label = "NO"
            session_percent = session_no
            session_class = "no"

        st.markdown(
            f"""
            <div class="session-box">
                <h3>Session Result</h3>

                <div class="{session_class}">
                    <h2 style="margin:0;">{session_label} — {session_percent:.1f}%</h2>
                </div>

                <p class="small">
                    Session:
                    <b>{int(st.session_state.low)} - {int(st.session_state.high)}</b>
                </p>

                <p class="small">
                    Avg Score:
                    <b>{session_analysis["expected"]:.1f}</b>
                </p>

                <p class="small">
                    Similar Matches:
                    <b>{session_analysis["samples"]}</b>
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="session-box">
                <h3>Session Result</h3>
                <h2>Calculating...</h2>
            </div>
            """,
            unsafe_allow_html=True,
        )

with winning_column:
    if innings_no == 1 and target <= 0:
        st.markdown(
            """
            <div class="winning-box">
                <h3>Team Winning</h3>
                <p class="small">1st innings me target available nahi hai.</p>
                <p class="small">2nd innings start hone par target set karein.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        winning_target = int(target)

        if innings_no == 2 and winning_target <= 0:
            st.markdown(
                """
                <div class="winning-box">
                    <h3>Team Winning</h3>
                    <p class="small">Winning result ke liye target runs set karein.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            winning_analysis = calculate_result(
                connection,
                league,
                innings_no,
                balls,
                runs,
                wickets,
                session_over,
                winning_target,
            )

            if winning_analysis:
                batting_probability = float(winning_analysis["yes"])
                bowling_probability = float(winning_analysis["no"])

                if batting_probability >= bowling_probability:
                    winning_team = batting
                    winning_percent = batting_probability
                    winning_class = "yes"
                else:
                    winning_team = bowling
                    winning_percent = bowling_probability
                    winning_class = "no"

                st.markdown(
                    f"""
                    <div class="winning-box">
                        <h3>Team Winning</h3>

                        <div class="{winning_class}">
                            <h2 style="margin:0;">{winning_team}</h2>
                            <h2 style="margin:8px 0 0 0;">{winning_percent:.1f}%</h2>
                        </div>

                        <p class="small">
                            Target: <b>{winning_target}</b>
                        </p>

                        <p class="small">
                            Similar Matches: <b>{winning_analysis["samples"]}</b>
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div class="winning-box">
                        <h3>Team Winning</h3>
                        <h2>Calculating...</h2>
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
# MANUAL SESSION SETTINGS
# ============================================================

if st.session_state.manual:
    st.subheader("Manual Session Settings")

    manual_low_col, manual_high_col = st.columns(2)

    with manual_low_col:
        manual_low = st.number_input(
            "Session Low",
            0,
            400,
            int(st.session_state.low),
            1,
            key="manual_low_value",
        )

    with manual_high_col:
        manual_high = st.number_input(
            "Session High",
            0,
            400,
            int(st.session_state.high),
            1,
            key="manual_high_value",
        )

    if st.button(
        "Apply Manual Session",
        use_container_width=True,
        key="apply_manual_session",
    ):
        st.session_state.low = int(manual_low)
        st.session_state.high = max(
            int(manual_low) + 1,
            int(manual_high),
        )
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
