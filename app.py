import hmac
import json
import os
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🏏",
    layout="wide",
)


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
        max-width: 1450px;
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
    }

    [data-testid="stSidebar"] {
        background: #071a2e;
    }

    h1, h2, h3, h4, p, label, span {
        color: #f8fafc !important;
    }

    .card {
        background: #0f223c;
        border: 1px solid #2d4d72;
        border-radius: 15px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }

    .session-box,
    .winning-box {
        background: #0f223c;
        border: 2px solid #4777a8;
        border-radius: 16px;
        padding: 16px;
        text-align: center;
        min-height: 235px;
    }

    .winning-box {
        border-color: #8256c8;
    }

    .yes {
        background: #07552f;
        border: 2px solid #20c77a;
        padding: 14px;
        border-radius: 14px;
        text-align: center;
    }

    .no {
        background: #651b1b;
        border: 2px solid #ef5350;
        padding: 14px;
        border-radius: 14px;
        text-align: center;
    }

    .small {
        color: #bed0e5 !important;
        font-size: 13px;
    }

    div.stButton > button {
        min-height: 40px;
        border-radius: 8px;
        font-weight: 700;
        background: #12365f;
        color: #ffffff;
        border: 1px solid #3c6795;
    }

    div.stButton > button:hover {
        background: #1a4a7c;
        border-color: #72a6dc;
    }

    [data-testid="stHorizontalBlock"] {
        gap: 0.25rem !important;
    }

    [data-testid="stColumn"] {
        padding-left: 2px !important;
        padding-right: 2px !important;
    }

    [data-testid="stMetric"] {
        background: #0f223c;
        border: 1px solid #2d4d72;
        border-radius: 14px;
        padding: 12px;
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
# PASSWORD
# ============================================================

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False


if not st.session_state.authenticated:
    st.title("🏏 VasuDev Cricket AI")

    entered_password = st.text_input(
        "Password",
        type="password",
        key="login_password_input",
    )

    if st.button(
        "Unlock",
        use_container_width=True,
        key="login_unlock_button",
    ):
        if hmac.compare_digest(entered_password, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("login_password_input", None)
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()


# ============================================================
# DATABASE SETTINGS
# ============================================================

BASE = Path(".")

DATABASES = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db",
}

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbbl_json.zip",
}

LEAGUES = list(DATABASES.keys())


# ============================================================
# BASIC HELPERS
# ============================================================

def parse_ball(value):
    try:
        text = str(value).strip()

        if "." not in text:
            return None

        over_text, ball_text = text.split(".", 1)

        over = int(over_text)
        ball = int(ball_text)

        if over < 0 or ball <= 0 or ball > 6:
            return None

        return over * 6 + ball

    except Exception:
        return None


def display_over(total_balls):
    try:
        total_balls = int(total_balls)
    except Exception:
        return "0.0"

    if total_balls <= 0:
        return "0.0"

    return (
        f"{(total_balls - 1) // 6}."
        f"{((total_balls - 1) % 6) + 1}"
    )


def get_table_names(connection):
    return {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """
        ).fetchall()
    }


def get_table_columns(connection, table_name):
    return {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


# ============================================================
# DATABASE MIGRATION
# ============================================================

def create_indexes(connection):
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
        CREATE INDEX IF NOT EXISTS idx_deliveries_teams
        ON deliveries(
            league,
            innings_no,
            batting_team,
            bowling_team
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_matches_league
        ON matches(league)
        """
    )


def migrate_database(database_path):
    if not database_path.exists():
        return

    connection = sqlite3.connect(
        str(database_path),
        timeout=120,
    )

    try:
        tables = get_table_names(connection)

        if "deliveries" not in tables:
            return

        columns = get_table_columns(
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
                    updates.append((position, row_id))

            if updates:
                connection.executemany(
                    """
                    UPDATE deliveries
                    SET ball_pos=?
                    WHERE id=?
                    """,
                    updates,
                )

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()


# ============================================================
# DATABASE BUILDER
# ============================================================

def build_database(database_path, league, archive_path):
    temporary_path = database_path.with_suffix(".tmp")

    if temporary_path.exists():
        temporary_path.unlink()

    connection = sqlite3.connect(
        str(temporary_path),
        timeout=180,
    )

    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")

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

        match_rows = []
        delivery_rows = []

        with zipfile.ZipFile(archive_path) as source_zip:
            for filename in source_zip.namelist():
                if not filename.lower().endswith(".json"):
                    continue

                try:
                    data = json.loads(source_zip.read(filename))

                    info = data.get("info", {}) or {}
                    teams = info.get("teams", []) or []

                    if len(teams) < 2:
                        continue

                    outcome = info.get("outcome", {}) or {}

                    winner = str(
                        outcome.get("winner", "")
                        or outcome.get("eliminator", "")
                        or ""
                    )

                    match_id = Path(filename).stem
                    venue = str(info.get("venue", "") or "")

                    match_rows.append(
                        (
                            match_id,
                            venue,
                            winner,
                            league,
                        )
                    )

                    innings_list = data.get("innings", []) or []

                    for innings_no, innings in enumerate(
                        innings_list,
                        start=1,
                    ):
                        if innings.get("super_over"):
                            continue

                        batting_team = str(
                            innings.get("team", "") or ""
                        )

                        bowling_team = next(
                            (
                                team
                                for team in teams
                                if team != batting_team
                            ),
                            "",
                        )

                        for over_data in innings.get(
                            "overs",
                            [],
                        ):
                            over_no = int(
                                over_data.get("over", 0) or 0
                            )

                            deliveries = over_data.get(
                                "deliveries",
                                [],
                            ) or []

                            for delivery_index, delivery in enumerate(
                                deliveries,
                                start=1,
                            ):
                                actual_delivery = delivery.get(
                                    "actual_delivery"
                                )

                                if actual_delivery:
                                    ball_text = str(actual_delivery)
                                else:
                                    ball_text = (
                                        f"{over_no}."
                                        f"{delivery_index}"
                                    )

                                ball_pos = parse_ball(ball_text)

                                if ball_pos is None:
                                    continue

                                runs = int(
                                    (
                                        delivery.get("runs")
                                        or {}
                                    ).get("total", 0)
                                    or 0
                                )

                                wickets = len(
                                    delivery.get("wickets")
                                    or []
                                )

                                delivery_rows.append(
                                    (
                                        match_id,
                                        innings_no,
                                        batting_team,
                                        bowling_team,
                                        over_no,
                                        ball_text,
                                        ball_pos,
                                        runs,
                                        wickets,
                                        league,
                                    )
                                )

                    if len(match_rows) >= 200:
                        connection.executemany(
                            """
                            INSERT OR REPLACE INTO matches(
                                match_id,
                                venue,
                                winner,
                                league
                            )
                            VALUES(?,?,?,?)
                            """,
                            match_rows,
                        )
                        match_rows.clear()

                    if len(delivery_rows) >= 10000:
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
                            delivery_rows,
                        )
                        delivery_rows.clear()

                except Exception:
                    continue

        if match_rows:
            connection.executemany(
                """
                INSERT OR REPLACE INTO matches(
                    match_id,
                    venue,
                    winner,
                    league
                )
                VALUES(?,?,?,?)
                """,
                match_rows,
            )

        if delivery_rows:
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
                delivery_rows,
            )

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()

    temporary_path.replace(database_path)


def ensure_database(league):
    database_path = DATABASES[league]

    if database_path.exists():
        migrate_database(database_path)
        return database_path

    building_path = database_path.with_suffix(".building")

    try:
        if building_path.exists():
            building_path.unlink()

        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "matches.zip"

            urllib.request.urlretrieve(
                DOWNLOAD_URLS[league],
                archive_path,
            )

            build_database(
                building_path,
                league,
                archive_path,
            )

        building_path.replace(database_path)
        return database_path

    except Exception:
        if building_path.exists():
            building_path.unlink()

        raise


@st.cache_resource
def get_connection(database_path_text):
    database_path = Path(database_path_text)

    migrate_database(database_path)

    connection = sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=120,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-12000")

    return connection


# ============================================================
# DATABASE QUERIES
# ============================================================

def get_values(connection, query, league):
    rows = connection.execute(
        query,
        (league,),
    ).fetchall()

    return [
        row[0]
        for row in rows
        if row[0]
    ]


def score_at(connection, match_id, innings_no, end_ball):
    row = connection.execute(
        """
        SELECT
            COALESCE(SUM(runs), 0) AS total_runs,
            COALESCE(SUM(wickets), 0) AS total_wickets
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
        int(row["total_runs"] or 0),
        int(row["total_wickets"] or 0),
    )


def final_score(connection, match_id, innings_no):
    row = connection.execute(
        """
        SELECT COALESCE(SUM(runs), 0) AS final_runs
        FROM deliveries
        WHERE match_id=?
        AND innings_no=?
        """,
        (
            match_id,
            innings_no,
        ),
    ).fetchone()

    return int(row["final_runs"] or 0)


def match_winner(connection, match_id):
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
        return ""

    return str(row["winner"] or "").strip()


# ============================================================
# HISTORICAL MATCH MATCHING
# ============================================================

def find_similar_states(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    end_ball,
    batting_team,
    bowling_team,
):
    low_ball = max(1, int(current_ball) - 2)
    high_ball = min(
        int(end_ball),
        int(current_ball) + 2,
    )

    def fetch_candidates(mode):
        where_sql = """
            league=?
            AND innings_no=?
            AND ball_pos BETWEEN ? AND ?
        """

        params = [
            league,
            innings_no,
            low_ball,
            high_ball,
        ]

        if mode == "both":
            where_sql += """
                AND batting_team=?
                AND bowling_team=?
            """
            params.extend(
                [
                    batting_team,
                    bowling_team,
                ]
            )

        elif mode == "batting":
            where_sql += " AND batting_team=?"
            params.append(batting_team)

        query = f"""
            SELECT
                match_id,
                innings_no,
                ball_pos,
                batting_team,
                bowling_team
            FROM deliveries
            WHERE {where_sql}
            GROUP BY
                match_id,
                innings_no,
                ball_pos,
                batting_team,
                bowling_team
            LIMIT 20000
        """

        return connection.execute(
            query,
            params,
        ).fetchall()

    candidates = fetch_candidates("both")

    if len(candidates) < 40:
        candidates = fetch_candidates("batting")

    if len(candidates) < 40:
        candidates = fetch_candidates("all")

    best_states = {}

    for row in candidates:
        match_id = row["match_id"]
        historical_innings = int(row["innings_no"])
        historical_ball = int(row["ball_pos"])

        historical_runs, historical_wickets = score_at(
            connection,
            match_id,
            historical_innings,
            historical_ball,
        )

        run_gap = abs(
            historical_runs - int(current_runs)
        )

        wicket_gap = abs(
            historical_wickets - int(current_wickets)
        )

        ball_gap = abs(
            historical_ball - int(current_ball)
        )

        if run_gap > 35 or wicket_gap > 4:
            continue

        distance = (
            run_gap
            + (wicket_gap * 8)
            + (ball_gap * 2)
        )

        key = (
            match_id,
            historical_innings,
        )

        state = {
            "match_id": match_id,
            "innings_no": historical_innings,
            "ball_pos": historical_ball,
            "runs": historical_runs,
            "wickets": historical_wickets,
            "batting_team": row["batting_team"],
            "bowling_team": row["bowling_team"],
            "distance": float(distance),
        }

        if (
            key not in best_states
            or state["distance"]
            < best_states[key]["distance"]
        ):
            best_states[key] = state

    states = list(best_states.values())

    states.sort(
        key=lambda item: item["distance"]
    )

    return states[:2500]


# ============================================================
# MODEL
# ============================================================

def calculate_auto_model(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    batting_team,
    bowling_team,
    target,
):
    end_ball = int(session_over) * 6

    if int(current_ball) >= end_ball:
        return {
            "low": int(current_runs),
            "high": int(current_runs) + 1,
            "expected": float(current_runs),
            "session_yes": 0.0,
            "session_no": 100.0,
            "win_probability": None,
            "samples": 0,
        }

    states = find_similar_states(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        end_ball,
        batting_team,
        bowling_team,
    )

    if not states:
        return {
            "low": int(current_runs),
            "high": int(current_runs) + 1,
            "expected": float(current_runs),
            "session_yes": 0.0,
            "session_no": 100.0,
            "win_probability": None,
            "samples": 0,
        }

    scores = []
    weights = []
    win_results = []

    for state in states:
        session_score, _ = score_at(
            connection,
            state["match_id"],
            state["innings_no"],
            end_ball,
        )

        if session_score < state["runs"]:
            session_score = final_score(
                connection,
                state["match_id"],
                state["innings_no"],
            )

        weight = 1.0 / (
            1.0 + float(state["distance"])
        )

        scores.append(int(session_score))
        weights.append(float(weight))

        historical_winner = match_winner(
            connection,
            state["match_id"],
        )

        if int(innings_no) == 1:
            win_results.append(
                1
                if historical_winner == batting_team
                else 0
            )

        elif int(innings_no) == 2 and int(target) > 0:
            historical_final = final_score(
                connection,
                state["match_id"],
                state["innings_no"],
            )

            win_results.append(
                1
                if historical_final >= int(target)
                else 0
            )

    total_weight = sum(weights)

    if total_weight <= 0:
        expected = float(current_runs)
    else:
        expected = sum(
            score * weight
            for score, weight in zip(scores, weights)
        ) / total_weight

    low = max(
        int(current_runs),
        int(round(expected)),
    )

    high = low + 1

    yes_weight = sum(
        weight
        for score, weight in zip(scores, weights)
        if score >= high
    )

    session_yes = (
        yes_weight / total_weight * 100
        if total_weight > 0
        else 0.0
    )

    win_probability = None

    if (
        win_results
        and len(win_results) == len(weights)
        and total_weight > 0
    ):
        win_probability = (
            sum(
                result * weight
                for result, weight
                in zip(win_results, weights)
            )
            / total_weight
            * 100
        )

    return {
        "low": int(low),
        "high": int(high),
        "expected": float(expected),
        "session_yes": float(session_yes),
        "session_no": float(100.0 - session_yes),
        "win_probability": win_probability,
        "samples": len(states),
    }


def calculate_manual_probability(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    batting_team,
    bowling_team,
    line_high,
):
    end_ball = int(session_over) * 6

    states = find_similar_states(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        end_ball,
        batting_team,
        bowling_team,
    )

    if not states:
        return {
            "yes": 0.0,
            "no": 100.0,
            "samples": 0,
        }

    total_weight = 0.0
    yes_weight = 0.0

    for state in states:
        session_score, _ = score_at(
            connection,
            state["match_id"],
            state["innings_no"],
            end_ball,
        )

        if session_score < state["runs"]:
            session_score = final_score(
                connection,
                state["match_id"],
                state["innings_no"],
            )

        weight = 1.0 / (
            1.0 + float(state["distance"])
        )

        total_weight += weight

        if session_score >= int(line_high):
            yes_weight += weight

    yes_probability = (
        yes_weight / total_weight * 100
        if total_weight > 0
        else 0.0
    )

    return {
        "yes": float(yes_probability),
        "no": float(100.0 - yes_probability),
        "samples": len(states),
    }


# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "runs": 16,
    "wickets": 1,
    "balls": 19,
    "last": "Starting situation",
    "undo_stack": [],
    "session_over": 6,
    "target": 0,
    "manual_mode": False,
    "session_low": 0,
    "session_high": 1,
    "expected_score": 0.0,
    "win_probability": None,
}

for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("Match Setup")

    league = st.selectbox(
        "League",
        LEAGUES,
        key="league_select",
    )

    try:
        database_path = ensure_database(league)

        connection = get_connection(
            str(database_path.resolve())
        )

    except Exception as error:
        st.error("Database start nahi ho saka.")
        st.exception(error)
        st.stop()

    teams = get_values(
        connection,
        """
        SELECT DISTINCT batting_team
        FROM deliveries
        WHERE league=?
        AND batting_team<>''
        ORDER BY batting_team
        """,
        league,
    )

    if not teams:
        st.error("Database me team data nahi mila.")
        st.stop()

    batting_team = st.selectbox(
        "Batting Team",
        teams,
        key="batting_team_select",
    )

    bowling_options = [
        team
        for team in teams
        if team != batting_team
    ]

    if not bowling_options:
        bowling_options = ["Unknown"]

    bowling_team = st.selectbox(
        "Bowling Team",
        bowling_options,
        key="bowling_team_select",
    )

    innings_label = st.selectbox(
        "Innings",
        [
            "1st Innings",
            "2nd Innings",
        ],
        key="innings_select",
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
        value=int(st.session_state.session_over),
        step=1,
        key="session_over_widget",
    )

    target = st.number_input(
        "Target Runs",
        min_value=0,
        max_value=400,
        value=int(st.session_state.target),
        step=1,
        key="target_runs_widget",
    )

    st.session_state.session_over = int(session_over)
    st.session_state.target = int(target)

    over_points = ["0.0"]

    for over in range(20):
        for ball in range(1, 7):
            over_points.append(f"{over}.{ball}")

    start_over = st.selectbox(
        "Start Over / Ball",
        over_points,
        index=19,
        key="start_over_select",
    )

    start_runs = st.number_input(
        "Start Runs",
        min_value=0,
        max_value=400,
        value=16,
        step=1,
        key="start_runs_widget",
    )

    start_wickets = st.number_input(
        "Start Wickets",
        min_value=0,
        max_value=10,
        value=1,
        step=1,
        key="start_wickets_widget",
    )

    if st.button(
        "Set Current Match Situation",
        use_container_width=True,
        key="set_situation_button",
    ):
        parsed_ball = parse_ball(start_over)

        if parsed_ball is None:
            st.error("Invalid over/ball.")
        else:
            st.session_state.runs = int(start_runs)
            st.session_state.wickets = int(start_wickets)
            st.session_state.balls = int(parsed_ball)
            st.session_state.undo_stack = []
            st.session_state.last = "Starting situation set"
            st.rerun()

    if st.button(
        "Reset Live Situation",
        use_container_width=True,
        key="reset_live_button",
    ):
        st.session_state.runs = 0
        st.session_state.wickets = 0
        st.session_state.balls = 0
        st.session_state.undo_stack = []
        st.session_state.last = ""
        st.rerun()


# ============================================================
# CURRENT STATE
# ============================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)


# ============================================================
# CURRENT MODEL
# ============================================================

try:
    auto_model = calculate_auto_model(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=balls,
        current_runs=runs,
        current_wickets=wickets,
        session_over=int(session_over),
        batting_team=batting_team,
        bowling_team=bowling_team,
        target=int(target),
    )

except Exception as error:
    st.error("Model calculation failed.")
    st.exception(error)
    st.stop()


if not st.session_state.manual_mode:
    st.session_state.session_low = int(
        auto_model["low"]
    )

    st.session_state.session_high = int(
        auto_model["high"]
    )

    st.session_state.expected_score = float(
        auto_model["expected"]
    )

    st.session_state.win_probability = (
        auto_model["win_probability"]
    )


# ============================================================
# TOP SCORE + SESSION MODE
# ============================================================

score_column, mode_column = st.columns(
    [8, 2],
    gap="small",
)

with score_column:
    st.markdown(
        f"""
        <div class="card">
            <h2 style="margin:0">
                {batting_team} {runs}/{wickets}
            </h2>

            <p class="small" style="margin:5px 0 0">
                {display_over(balls)} ov
                • Session End: {session_over} ov
                • Target: {target if target > 0 else "Not set"}
                • Last: {st.session_state.last or "—"}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with mode_column:
    selected_mode = st.radio(
        "Mode",
        [
            "AUTO",
            "MANUAL",
        ],
        index=(
            1
            if st.session_state.manual_mode
            else 0
        ),
        horizontal=True,
        key="session_mode_radio",
    )

    # This modifies a different state key, not the radio widget key.
    st.session_state.manual_mode = (
        selected_mode == "MANUAL"
    )


# ============================================================
# BALL CONTROLS
# ============================================================

st.subheader("Ball-by-Ball Update")

actions = [
    ("Dot", 0, 0, True),
    ("1", 1, 0, True),
    ("2", 2, 0, True),
    ("3", 3, 0, True),
    ("4", 4, 0, True),
    ("6", 6, 0, True),
    ("Wicket", 0, 1, True),
    ("Wide", 1, 0, False),
    ("No Ball", 1, 0, False),
    ("Undo", None, 0, False),
]

action_columns = st.columns(
    len(actions),
    gap="small",
)

for index, (
    label,
    add_runs,
    add_wicket,
    legal_ball,
) in enumerate(actions):

    with action_columns[index]:
        if st.button(
            label,
            use_container_width=True,
            key=f"live_action_button_{index}",
        ):
            if label == "Undo":
                if st.session_state.undo_stack:
                    old_state = (
                        st.session_state.undo_stack.pop()
                    )

                    st.session_state.runs = (
                        old_state["runs"]
                    )

                    st.session_state.wickets = (
                        old_state["wickets"]
                    )

                    st.session_state.balls = (
                        old_state["balls"]
                    )

                    st.session_state.last = "Undo"

            else:
                st.session_state.undo_stack.append(
                    {
                        "runs": runs,
                        "wickets": wickets,
                        "balls": balls,
                        "last": st.session_state.last,
                    }
                )

                st.session_state.runs = (
                    runs + int(add_runs)
                )

                st.session_state.wickets = min(
                    10,
                    wickets + int(add_wicket),
                )

                if legal_ball:
                    st.session_state.balls = balls + 1

                st.session_state.last = label

            st.rerun()


# ============================================================
# SESSION + WINNING SUMMARY
# ============================================================

session_column, winning_column = st.columns(
    2,
    gap="small",
)

with session_column:
    st.markdown(
        f"""
        <div class="session-box">
            <h3 style="margin:0">Session</h3>

            <h1 style="margin:8px 0">
                {int(st.session_state.session_low)}
                -
                {int(st.session_state.session_high)}
            </h1>

            <p class="small">
                Expected:
                {float(st.session_state.expected_score):.1f}
                • End: {session_over} ov
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with winning_column:
    probability = st.session_state.win_probability

    probability_text = (
        f"{float(probability):.1f}%"
        if probability is not None
        else "—"
    )

    st.markdown(
        f"""
        <div class="winning-box">
            <h3 style="margin:0">
                {batting_team} Win
            </h3>

            <h1 style="margin:8px 0">
                {probability_text}
            </h1>

            <p class="small">
                Historical situations + current score
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# MANUAL SESSION CONTROLS
# ============================================================

manual_low_column, manual_high_column = st.columns(
    2,
    gap="small",
)

with manual_low_column:
    manual_low = st.number_input(
        "Manual Session Low",
        min_value=0,
        max_value=400,
        value=int(st.session_state.session_low),
        step=1,
        key="manual_low_widget",
    )

with manual_high_column:
    manual_high = st.number_input(
        "Manual Session High",
        min_value=0,
        max_value=400,
        value=int(st.session_state.session_high),
        step=1,
        key="manual_high_widget",
    )

manual_button, auto_button = st.columns(
    2,
    gap="small",
)

with manual_button:
    if st.button(
        "Apply Manual Session",
        use_container_width=True,
        key="apply_manual_session_button",
    ):
        st.session_state.manual_mode = True
        st.session_state.session_low = int(manual_low)
        st.session_state.session_high = max(
            int(manual_low) + 1,
            int(manual_high),
        )
        st.rerun()

with auto_button:
    if st.button(
        "Use Auto Session",
        use_container_width=True,
        key="use_auto_session_button",
    ):
        st.session_state.manual_mode = False
        st.rerun()


# ============================================================
# FINAL SESSION RESULT
# ============================================================

if st.session_state.manual_mode:
    try:
        manual_result = calculate_manual_probability(
            connection=connection,
            league=league,
            innings_no=innings_no,
            current_ball=balls,
            current_runs=runs,
            current_wickets=wickets,
            session_over=int(session_over),
            batting_team=batting_team,
            bowling_team=bowling_team,
            line_high=int(
                st.session_state.session_high
            ),
        )

        session_yes = float(
            manual_result["yes"]
        )

        session_no = float(
            manual_result["no"]
        )

        session_samples = int(
            manual_result["samples"]
        )

    except Exception as error:
        st.error("Manual session calculation failed.")
        st.exception(error)
        session_yes = 0.0
        session_no = 100.0
        session_samples = 0

else:
    session_yes = float(
        auto_model["session_yes"]
    )

    session_no = float(
        auto_model["session_no"]
    )

    session_samples = int(
        auto_model["samples"]
    )


result_label = (
    "YES"
    if session_yes >= session_no
    else "NO"
)

result_class = (
    "yes"
    if result_label == "YES"
    else "no"
)

result_percent = max(
    session_yes,
    session_no,
)

st.subheader("VasuDev Result")

st.markdown(
    f"""
    <div class="{result_class}">
        <h1 style="margin:0">
            SESSION {result_label}
            — {result_percent:.1f}%
        </h1>

        <p style="margin:8px 0 0">
            Session Line:
            <b>
                {int(st.session_state.session_low)}
                -
                {int(st.session_state.session_high)}
            </b>
        </p>

        <p style="margin:5px 0 0">
            Avg Score:
            <b>{float(st.session_state.expected_score):.1f}</b>
        </p>

        <p style="margin:5px 0 0">
            Similar Matches:
            <b>{session_samples}</b>
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# TEAM WINNING RESULT
# ============================================================

final_win_probability = (
    st.session_state.win_probability
)

if final_win_probability is not None:
    batting_win = float(
        final_win_probability
    )

    bowling_win = 100.0 - batting_win

    if batting_win >= bowling_win:
        winner_name = batting_team
        winner_percent = batting_win
        winner_class = "yes"
    else:
        winner_name = bowling_team
        winner_percent = bowling_win
        winner_class = "no"

    st.markdown(
        f"""
        <div class="{winner_class}">
            <h1 style="margin:0">
                {winner_name.upper()}
                WIN — {winner_percent:.1f}%
            </h1>

            <p style="margin:8px 0 0">
                {batting_team}:
                <b>{batting_win:.1f}%</b>
                •
                {bowling_team}:
                <b>{bowling_win:.1f}%</b>
            </p>

            <p style="margin:5px 0 0">
                {("Historical winner estimate"
                  if innings_no == 1
                  else f"Target: {target}")}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

else:
    if innings_no == 2 and int(target) <= 0:
        st.info(
            "2nd innings winning probability ke liye "
            "Target Runs set karein."
        )
    else:
        st.info(
            "Winning estimate ke liye sufficient "
            "historical result data nahi mila."
        )


# ============================================================
# MATCH DETAILS
# ============================================================

st.subheader("Match Detail")

detail_columns = st.columns(4)

detail_columns[0].metric(
    "Batting",
    batting_team,
)

detail_columns[1].metric(
    "Bowling",
    bowling_team,
)

detail_columns[2].metric(
    "Innings",
    innings_label,
)

detail_columns[3].metric(
    "Overs",
    f"{display_over(balls)} / {session_over}",
)


# ============================================================
# DETAILS
# ============================================================

with st.expander("Details"):
    st.write(
        f"**League:** {league}"
    )

    st.write(
        f"**Current Situation:** "
        f"{batting_team} {runs}/{wickets} "
        f"at {display_over(balls)} overs"
    )

    st.write(
        f"**Session Line:** "
        f"{int(st.session_state.session_low)} - "
        f"{int(st.session_state.session_high)}"
    )

    st.write(
        f"**Expected Session Score:** "
        f"{float(st.session_state.expected_score):.1f}"
    )

    st.write(
        f"**Session YES:** "
        f"{session_yes:.1f}%"
    )

    st.write(
        f"**Session NO:** "
        f"{session_no:.1f}%"
    )

    st.write(
        f"**Similar Historical Matches:** "
        f"{session_samples}"
    )

    if final_win_probability is not None:
        st.write(
            f"**{batting_team} Win Probability:** "
            f"{float(final_win_probability):.1f}%"
        )

        st.write(
            f"**{bowling_team} Win Probability:** "
            f"{100.0 - float(final_win_probability):.1f}%"
        )

    if innings_no == 2 and int(target) > 0:
        st.write(
            f"**Target:** {int(target)}"
        )

    st.write(
        f"**Ground:** Database venue selection is available "
        f"in the current match setup."
    )


st.caption(
    "Historical estimate only. This is not a guarantee of the live match result."
)
