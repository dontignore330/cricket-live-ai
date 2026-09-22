import os
import hmac
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide",
)


# ============================================================
# PASSWORD
# ============================================================

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False


# ============================================================
# CSS
# ============================================================

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

    [data-testid="stSidebar"] {
        background: #071a2e;
    }

    h1, h2, h3, h4, p, label {
        color: #f8fafc !important;
    }

    div.stButton > button {
        min-height: 42px;
        border-radius: 10px;
        font-weight: 700;
        background: #12365f;
        color: white;
        border: 1px solid #3c6795;
    }

    div.stButton > button:hover {
        border-color: #6ea8df;
    }

    div[data-testid="stHorizontalBlock"] {
        gap: 0.30rem !important;
    }

    div[data-testid="column"] {
        padding-left: 2px !important;
        padding-right: 2px !important;
    }

    [data-testid="stMetric"] {
        background: #0f223c;
        border: 1px solid #2d4d72;
        border-radius: 14px;
        padding: 14px;
    }

    [data-testid="stMetricLabel"] {
        color: #bed0e5 !important;
    }

    [data-testid="stMetricValue"] {
        color: #ffffff !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# LOGIN
# ============================================================

if not st.session_state.authenticated:

    st.title("🐎 VasuDev Cricket AI")

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
    "Men's Big Bash League":
        "https://cricsheet.org/downloads/bbl_json.zip",

    "Women's Big Bash League":
        "https://cricsheet.org/downloads/wbb_json.zip",
}

LEAGUES = list(DBS.keys())


# ============================================================
# BALL HELPERS
# ============================================================

def parse_ball(value):

    try:

        text = str(value)

        if "." not in text:
            return None

        over, ball = text.split(".", 1)

        over = int(over)
        ball = int(ball)

        if over < 0:
            return None

        if ball <= 0 or ball > 6:
            return None

        return over * 6 + ball

    except Exception:

        return None


def display_over(balls):

    balls = int(balls)

    if balls <= 0:
        return "0.0"

    return (
        f"{(balls - 1) // 6}."
        f"{((balls - 1) % 6) + 1}"
    )


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

    connection = sqlite3.connect(
        str(path),
        timeout=60,
    )

    try:

        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                """
            )
        }

        if "deliveries" not in tables:
            return

        columns = table_columns(
            connection,
            "deliveries",
        )

        if "ball_pos" not in columns:

            connection.execute(
                """
                ALTER TABLE deliveries
                ADD COLUMN ball_pos INTEGER
                """
            )

            rows = connection.execute(
                """
                SELECT id, ball_no
                FROM deliveries
                WHERE ball_pos IS NULL
                """
            ).fetchall()

            updates = []

            for row_id, ball_no in rows:

                position = parse_ball(ball_no)

                if position is not None:

                    updates.append(
                        (
                            position,
                            row_id,
                        )
                    )

            if updates:

                connection.executemany(
                    """
                    UPDATE deliveries
                    SET ball_pos=?
                    WHERE id=?
                    """,
                    updates,
                )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deliveries_state
            ON deliveries(
                league,
                innings_no,
                ball_pos
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deliveries_match
            ON deliveries(
                match_id,
                innings_no,
                ball_pos
            )
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

    connection.execute(
        "PRAGMA query_only=ON"
    )

    connection.execute(
        "PRAGMA cache_size=-8000"
    )

    return connection


# ============================================================
# DATABASE BUILDER
# ============================================================

def build_database(
    path,
    league,
    archive,
):

    temporary = path.with_suffix(".tmp")

    if temporary.exists():
        temporary.unlink()

    connection = sqlite3.connect(
        str(temporary)
    )

    try:

        connection.execute(
            "PRAGMA journal_mode=OFF"
        )

        connection.execute(
            "PRAGMA synchronous=OFF"
        )

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

        matches_buffer = []
        deliveries_buffer = []

        with zipfile.ZipFile(archive) as source:

            for filename in source.namelist():

                if not filename.lower().endswith(".json"):
                    continue

                try:

                    raw = source.read(filename)

                    data = json.loads(
                        raw.decode("utf-8")
                    )

                    info = data.get(
                        "info",
                        {}
                    )

                    teams = info.get(
                        "teams",
                        []
                    )

                    if len(teams) < 2:
                        continue

                    outcome = (
                        info.get(
                            "outcome",
                            {}
                        )
                        or {}
                    )

                    winner = str(
                        outcome.get(
                            "winner",
                            ""
                        )
                        or outcome.get(
                            "eliminator",
                            ""
                        )
                        or ""
                    )

                    match_id = Path(
                        filename
                    ).stem

                    matches_buffer.append(
                        (
                            match_id,
                            str(
                                info.get(
                                    "venue",
                                    ""
                                )
                                or ""
                            ),
                            winner,
                            league,
                        )
                    )

                    for innings_no, innings in enumerate(
                        data.get(
                            "innings",
                            []
                        ),
                        1,
                    ):

                        if innings.get(
                            "super_over"
                        ):
                            continue

                        batting = innings.get(
                            "team",
                            ""
                        )

                        bowling = next(
                            (
                                team
                                for team in teams
                                if team != batting
                            ),
                            "",
                        )

                        for over in innings.get(
                            "overs",
                            []
                        ):

                            over_no = int(
                                over.get(
                                    "over",
                                    0
                                )
                            )

                            for delivery_index, delivery in enumerate(
                                over.get(
                                    "deliveries",
                                    []
                                ),
                                1,
                            ):

                                actual = delivery.get(
                                    "actual_delivery"
                                )

                                if actual:

                                    ball_text = str(
                                        actual
                                    )

                                else:

                                    ball_text = (
                                        f"{over_no}."
                                        f"{delivery_index}"
                                    )

                                ball_pos = parse_ball(
                                    ball_text
                                )

                                if ball_pos is None:
                                    continue

                                runs_data = (
                                    delivery.get(
                                        "runs"
                                    )
                                    or {}
                                )

                                runs = int(
                                    runs_data.get(
                                        "total",
                                        0
                                    )
                                    or 0
                                )

                                wickets = len(
                                    delivery.get(
                                        "wickets"
                                    )
                                    or []
                                )

                                deliveries_buffer.append(
                                    (
                                        match_id,
                                        innings_no,
                                        batting,
                                        bowling,
                                        over_no,
                                        ball_text,
                                        ball_pos,
                                        runs,
                                        wickets,
                                        league,
                                    )
                                )

                    if len(matches_buffer) >= 100:

                        connection.executemany(
                            """
                            INSERT OR REPLACE INTO matches
                            VALUES(?,?,?,?)
                            """,
                            matches_buffer,
                        )

                        matches_buffer.clear()

                    if len(deliveries_buffer) >= 5000:

                        connection.executemany(
                            """
                            INSERT INTO deliveries(
                                match_id,
                                innings_no,
                                batting_team,
                                bowling_team,
                                over_no,
                                ball_no,
                                ball_pos,
                                runs,
                                wickets,
                                league
                            )
                            VALUES(?,?,?,?,?,?,?,?,?,?)
                            """,
                            deliveries_buffer,
                        )

                        deliveries_buffer.clear()

                except Exception:

                    continue

        if matches_buffer:

            connection.executemany(
                """
                INSERT OR REPLACE INTO matches
                VALUES(?,?,?,?)
                """,
                matches_buffer,
            )

        if deliveries_buffer:

            connection.executemany(
                """
                INSERT INTO deliveries(
                    match_id,
                    innings_no,
                    batting_team,
                    bowling_team,
                    over_no,
                    ball_no,
                    ball_pos,
                    runs,
                    wickets,
                    league
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                deliveries_buffer,
            )

        connection.execute(
            """
            CREATE INDEX idx_deliveries_state
            ON deliveries(
                league,
                innings_no,
                ball_pos
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_deliveries_match
            ON deliveries(
                match_id,
                innings_no,
                ball_pos
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_matches_league
            ON matches(league)
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

    building = path.with_suffix(
        ".building"
    )

    try:

        with tempfile.TemporaryDirectory() as directory:

            archive = (
                Path(directory)
                / "matches.zip"
            )

            urllib.request.urlretrieve(
                URLS[league],
                archive,
            )

            build_database(
                building,
                league,
                archive,
            )

        building.replace(path)

        return path

    except Exception:

        if building.exists():
            building.unlink()

        raise


# ============================================================
# SIMPLE DB VALUES
# ============================================================

def values(
    connection,
    sql,
    league,
):

    return [
        row[0]
        for row in connection.execute(
            sql,
            (league,),
        ).fetchall()
        if row[0]
    ]


# ============================================================
# SCORE AT A BALL
# ============================================================

def score_at(
    connection,
    match_id,
    innings_no,
    end_ball,
):

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
        (
            match_id,
            innings_no,
            end_ball,
        ),
    ).fetchone()

    return (
        int(row[0] or 0),
        int(row[1] or 0),
    )


# ============================================================
# FIND SIMILAR HISTORICAL STATES
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
            max(
                1,
                current_ball - 2
            ),
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
            abs(
                score - current_runs
            ) <= 30
            and
            abs(
                wickets - current_wickets
            ) <= 3
        ):

            weight = (
                1
                /
                (
                    1
                    +
                    abs(
                        score - current_runs
                    )
                )
                /
                (
                    1
                    +
                    abs(
                        wickets - current_wickets
                    )
                )
                /
                (
                    1
                    +
                    abs(
                        row["ball_pos"] - current_ball
                    )
                )
            )

            result.append(
                (
                    row["match_id"],
                    int(row["innings_no"]),
                    weight,
                )
            )

    result.sort(
        key=lambda x: x[2],
        reverse=True,
    )

    return result[:800]


# ============================================================
# SESSION EXPECTED SCORE
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

    end_ball = int(
        session_over
    ) * 6

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

        score = score_at(
            connection,
            match_id,
            inn,
            end_ball,
        )[0]

        scores.append(score)
        weights.append(weight)

    total_weight = sum(weights)

    if total_weight <= 0:

        return (
            current_runs,
            current_runs + 1,
            float(current_runs),
            0,
        )

    expected = (
        sum(
            score * weight
            for score, weight
            in zip(scores, weights)
        )
        /
        total_weight
    )

    low = max(
        current_runs,
        int(round(expected)),
    )

    return (
        low,
        low + 1,
        expected,
        len(scores),
    )


# ============================================================
# SESSION YES / NO
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

    end_ball = int(
        session_over
    ) * 6

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

    scores = []

    for match_id, inn, _ in matches:

        score = score_at(
            connection,
            match_id,
            inn,
            end_ball,
        )[0]

        scores.append(score)

    if not scores:
        return None

    yes_count = sum(
        score >= threshold
        for score in scores
    )

    yes = (
        yes_count
        /
        len(scores)
        *
        100
    )

    ordered = sorted(scores)

    low_index = max(
        0,
        int(len(ordered) * 0.10) - 1,
    )

    high_index = max(
        0,
        int(len(ordered) * 0.90) - 1,
    )

    return {
        "yes": yes,
        "no": 100 - yes,
        "samples": len(scores),
        "expected": (
            sum(scores)
            /
            len(scores)
        ),
        "low": ordered[low_index],
        "high": ordered[high_index],
    }


# ============================================================
# TEAM WINNING
# ============================================================

def calculate_winning_result(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    batting,
    bowling,
):

    matches = similar_matches(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        120,
    )

    if not matches:
        return None

    batting_weight = 0.0
    bowling_weight = 0.0

    batting_count = 0
    bowling_count = 0

    for match_id, _, weight in matches:

        row = connection.execute(
            """
            SELECT winner
            FROM matches
            WHERE match_id=?
            LIMIT 1
            """,
            (match_id,),
        ).fetchone()

        if not row:
            continue

        winner = str(
            row["winner"] or ""
        ).strip()

        if winner == batting:

            batting_weight += weight
            batting_count += 1

        elif winner == bowling:

            bowling_weight += weight
            bowling_count += 1

    total_weight = (
        batting_weight
        +
        bowling_weight
    )

    total_count = (
        batting_count
        +
        bowling_count
    )

    if total_weight <= 0 or total_count <= 0:
        return None

    batting_percent = (
        batting_weight
        /
        total_weight
        *
        100
    )

    bowling_percent = (
        bowling_weight
        /
        total_weight
        *
        100
    )

    return {
        "batting": batting_percent,
        "bowling": bowling_percent,
        "batting_count": batting_count,
        "bowling_count": bowling_count,
        "samples": total_count,
    }


# ============================================================
# SESSION STATE
# ============================================================

defaults = {
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
    "session_mode": "Auto",
}

for key, value in defaults.items():

    st.session_state.setdefault(
        key,
        value,
    )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("Match Setup")

    league = st.selectbox(
        "League",
        LEAGUES,
        key="league_choice",
    )

    try:

        database_path = ensure_database(
            league
        )

        connection = readonly(
            database_path
        )

    except Exception as error:

        st.error(
            f"Historical database error: {error}"
        )

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
    )

    if not venues:
        venues = ["Unknown"]

    if not teams:

        st.error(
            "No teams found in database."
        )

        st.stop()

    batting = st.selectbox(
        "Batting Team",
        teams,
        key="batting_team",
    )

    bowling_options = [
        team
        for team in teams
        if team != batting
    ]

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
        [
            "1st Innings",
            "2nd Innings",
        ],
        key="innings",
    )

    innings_no = (
        1
        if innings_label == "1st Innings"
        else 2
    )

    session_over = st.number_input(
        "Session Over",
        min_value=1,
        max_value=20,
        value=int(
            st.session_state.session_over
        ),
        step=1,
        key="session_over_input",
    )

    target = st.number_input(
        "Target Runs",
        min_value=0,
        max_value=400,
        value=int(
            st.session_state.target
        ),
        step=1,
        key="target_input",
    )

    st.session_state.session_over = int(
        session_over
    )

    st.session_state.target = int(
        target
    )

    points = ["0.0"]

    for over in range(20):

        for ball in range(1, 7):

            points.append(
                f"{over}.{ball}"
            )

    start_over = st.selectbox(
        "Start Over / Ball",
        points,
        index=19,
        key="start_over",
    )

    start_runs = st.number_input(
        "Start Runs",
        min_value=0,
        max_value=400,
        value=16,
        step=1,
        key="start_runs",
    )

    start_wickets = st.number_input(
        "Start Wickets",
        min_value=0,
        max_value=10,
        value=1,
        step=1,
        key="start_wickets",
    )

    if st.button(
        "Set Current Match Situation",
        use_container_width=True,
        key="set_situation",
    ):

        parsed = parse_ball(
            start_over
        )

        if parsed is None:

            st.error(
                "Invalid over/ball."
            )

        else:

            st.session_state.runs = int(
                start_runs
            )

            st.session_state.wickets = int(
                start_wickets
            )

            st.session_state.balls = int(
                parsed
            )

            st.session_state.undo = []

            st.session_state.last = (
                "Starting situation set"
            )

            st.rerun()

    if st.button(
        "Reset Live Situation",
        use_container_width=True,
        key="reset_live",
    ):

        st.session_state.runs = 0
        st.session_state.wickets = 0
        st.session_state.balls = 0
        st.session_state.undo = []
        st.session_state.last = ""

        st.rerun()


# ============================================================
# CURRENT STATE
# ============================================================

runs = int(
    st.session_state.runs
)

wickets = int(
    st.session_state.wickets
)

balls = int(
    st.session_state.balls
)


# ============================================================
# SESSION MODE
# ============================================================

mode = st.radio(
    "Session Mode",
    ["Auto", "Manual"],
    index=(
        0
        if st.session_state.session_mode == "Auto"
        else 1
    ),
    horizontal=True,
    key="session_mode",
)

st.session_state.manual = (
    mode == "Manual"
)


# ============================================================
# AUTO HISTORICAL LINE
# ============================================================

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
# SESSION ANALYSIS
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


# ============================================================
# TEAM WINNING ANALYSIS
# ============================================================

winning_analysis = calculate_winning_result(
    connection,
    league,
    innings_no,
    balls,
    runs,
    wickets,
    batting,
    bowling,
)


# ============================================================
# LIVE SCORE
# ============================================================

st.subheader("Live Score")

live_col1, live_col2 = st.columns(
    [1, 3],
    gap="small",
)

with live_col1:

    st.metric(
        batting,
        f"{runs}/{wickets}",
        f"{display_over(balls)} overs",
    )

with live_col2:

    st.caption(
        f"{batting} batting • "
        f"{bowling} bowling • "
        f"{innings_label}"
    )

    st.caption(
        f"Last action: "
        f"{st.session_state.last}"
    )


# ============================================================
# BALL BUTTONS
# ============================================================

st.markdown("**Live Ball Controls**")

buttons = [
    ("Dot", 0, 0, True),
    ("1", 1, 0, True),
    ("2", 2, 0, True),
    ("3", 3, 0, True),
    ("4", 4, 0, True),
    ("6", 6, 0, True),
    ("Wkt", 0, 1, True),
    ("Wide", 1, 0, False),
]

cols = st.columns(
    len(buttons),
    gap="small",
)

for index, (
    label,
    run_value,
    wicket_value,
    legal_ball,
) in enumerate(buttons):

    with cols[index]:

        if st.button(
            label,
            use_container_width=True,
            key=f"ball_{label}",
        ):

            st.session_state.undo.append(
                (
                    runs,
                    wickets,
                    balls,
                    st.session_state.last,
                )
            )

            st.session_state.runs = (
                runs + run_value
            )

            st.session_state.wickets = min(
                10,
                wickets + wicket_value,
            )

            if legal_ball:

                st.session_state.balls = (
                    balls + 1
                )

            st.session_state.last = label

            st.rerun()


# ============================================================
# UNDO
# ============================================================

undo_col, empty_col = st.columns(
    [1, 7],
    gap="small",
)

with undo_col:

    if st.button(
        "↩ Undo",
        use_container_width=True,
        key="undo",
    ):

        if st.session_state.undo:

            (
                old_runs,
                old_wickets,
                old_balls,
                old_last,
            ) = st.session_state.undo.pop()

            st.session_state.runs = old_runs
            st.session_state.wickets = old_wickets
            st.session_state.balls = old_balls
            st.session_state.last = old_last

            st.rerun()


# ============================================================
# MAIN RESULTS
# ============================================================

st.divider()

session_column, winning_column = st.columns(
    2,
    gap="small",
)


# ============================================================
# SESSION RESULT
# ============================================================

with session_column:

    st.subheader("Session Result")

    if session_analysis:

        yes = float(
            session_analysis["yes"]
        )

        no = float(
            session_analysis["no"]
        )

        if yes >= no:

            result_label = "YES"
            result_percent = yes

            st.success(
                f"## YES — {result_percent:.1f}%"
            )

        else:

            result_label = "NO"
            result_percent = no

            st.error(
                f"## NO — {result_percent:.1f}%"
            )

        st.metric(
            "Avg Score",
            f"{session_analysis['expected']:.1f}",
        )

    else:

        st.info(
            "Not enough similar historical "
            "situations available."
        )


# ============================================================
# TEAM WINNING
# ============================================================

with winning_column:

    st.subheader("Team Winning")

    if winning_analysis:

        batting_probability = float(
            winning_analysis["batting"]
        )

        bowling_probability = float(
            winning_analysis["bowling"]
        )

        if (
            batting_probability
            >=
            bowling_probability
        ):

            winning_team = batting
            winning_percent = (
                batting_probability
            )

        else:

            winning_team = bowling
            winning_percent = (
                bowling_probability
            )

        st.success(
            f"## {winning_team}"
        )

        st.metric(
            "Historical Win Estimate",
            f"{winning_percent:.1f}%",
        )

        st.caption(
            f"{batting}: {batting_probability:.1f}%"
            f"  •  "
            f"{bowling}: {bowling_probability:.1f}%"
        )

    else:

        st.info(
            "Not enough historical winner "
            "data for this situation."
        )


# ============================================================
# MANUAL SESSION SETTINGS
# ============================================================

if st.session_state.manual:

    with st.expander(
        "Manual Session Settings"
    ):

        manual_low, manual_high = st.columns(
            2,
            gap="small",
        )

        with manual_low:

            low_value = st.number_input(
                "Session Low",
                min_value=0,
                max_value=400,
                value=int(
                    st.session_state.low
                ),
                step=1,
                key="manual_low",
            )

        with manual_high:

            high_value = st.number_input(
                "Session High",
                min_value=0,
                max_value=400,
                value=int(
                    st.session_state.high
                ),
                step=1,
                key="manual_high",
            )

        if st.button(
            "Apply Manual Session",
            use_container_width=True,
            key="apply_manual",
        ):

            st.session_state.low = int(
                low_value
            )

            st.session_state.high = max(
                int(low_value) + 1,
                int(high_value),
            )

            st.rerun()


# ============================================================
# DETAILS
# ============================================================

with st.expander("Details"):

    st.write(
        f"**League:** {league}"
    )

    st.write(
        f"**Situation:** "
        f"{batting} {runs}/{wickets} "
        f"at {display_over(balls)} overs"
    )

    st.write(
        f"**Session:** "
        f"{int(st.session_state.low)} - "
        f"{int(st.session_state.high)}"
    )

    if session_analysis:

        st.write(
            f"**Expected Score:** "
            f"{session_analysis['expected']:.1f}"
        )

        st.write(
            f"**YES:** "
            f"{session_analysis['yes']:.1f}%"
        )

        st.write(
            f"**NO:** "
            f"{session_analysis['no']:.1f}%"
        )

        st.write(
            f"**Similar Historical States:** "
            f"{session_analysis['samples']}"
        )

    if winning_analysis:

        st.write(
            f"**{batting} historical WIN:** "
            f"{winning_analysis['batting']:.1f}%"
        )

        st.write(
            f"**{bowling} historical WIN:** "
            f"{winning_analysis['bowling']:.1f}%"
        )

        st.write(
            f"**Winning samples:** "
            f"{winning_analysis['samples']}"
        )

    st.write(
        f"**Ground:** {venue}"
    )

    if innings_no == 2 and target > 0:

        st.write(
            f"**Target:** {target}"
        )


# ============================================================
# FOOTER
# ============================================================

st.caption(
    "Historical estimate only; it is not a guarantee."
)
