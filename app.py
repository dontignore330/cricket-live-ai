import os
import hmac
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st


# =========================================================
# PAGE / APP CONFIG
# =========================================================

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide"
)

st.markdown("""
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

.session-box {
    background: #0f223c;
    border: 2px solid #4777a8;
    border-radius: 16px;
    padding: 15px;
    text-align: center;
    min-height: 130px;
}

.win-box {
    background: #151132;
    border: 2px solid #8256c8;
    border-radius: 16px;
    padding: 15px;
    text-align: center;
    min-height: 130px;
}

.yes {
    background: #07552f;
    border: 2px solid #20c77a;
    padding: 16px;
    border-radius: 16px;
    text-align: center;
    margin-top: 12px;
}

.no {
    background: #651b1b;
    border: 2px solid #ef5350;
    padding: 16px;
    border-radius: 16px;
    text-align: center;
    margin-top: 12px;
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
    border: 1px solid #72a6dc;
}

[data-testid="stHorizontalBlock"] {
    gap: 0.15rem !important;
}

[data-testid="stColumn"] {
    padding-left: 0 !important;
    padding-right: 0 !important;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# PASSWORD PROTECTION
# =========================================================

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not PASSWORD:
    st.error("VASUDEV_PASSWORD Render Environment Variable me set karein.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🐎 VasuDev Cricket AI")

    password = st.text_input(
        "Password",
        type="password",
        key="auth_password"
    )

    if st.button("Unlock", use_container_width=True, key="unlock_button"):
        if hmac.compare_digest(password, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("auth_password", None)
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()


# =========================================================
# DATABASE SETTINGS
# =========================================================

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


# =========================================================
# BASIC HELPERS
# =========================================================

def parse_ball(value):
    """
    Convert cricket notation:
    0.1 -> 1
    3.3 -> 21
    10.6 -> 66
    """
    try:
        over, ball = str(value).split(".", 1)
        over = int(over)
        ball = int(ball)

        if over < 0 or ball <= 0:
            return None

        return over * 6 + ball

    except Exception:
        return None


def display_over(balls):
    """
    Convert total delivered balls back to cricket notation.
    1 -> 0.1
    6 -> 0.6
    7 -> 1.1
    """
    try:
        balls = int(balls)
    except Exception:
        return "0.0"

    if balls <= 0:
        return "0.0"

    over = (balls - 1) // 6
    ball = ((balls - 1) % 6) + 1

    return f"{over}.{ball}"


def get_table_names(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def get_table_columns(connection, table_name):
    return {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


# =========================================================
# DATABASE CREATE / MIGRATE
# =========================================================

def create_indexes(connection):
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_deliveries_lookup
        ON deliveries(league, innings_no, ball_pos)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_deliveries_match
        ON deliveries(match_id, innings_no, ball_pos)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_deliveries_teams
        ON deliveries(league, innings_no, batting_team, bowling_team)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_matches_league
        ON matches(league)
    """)


def migrate_database(database_path):
    """
    Old database compatibility:
    - Adds ball_pos if it does not exist.
    - Adds useful indexes.
    - Does not rely on complicated SQL migration tables.
    """
    if not database_path.exists():
        return

    connection = sqlite3.connect(str(database_path), timeout=60)

    try:
        tables = get_table_names(connection)

        if "deliveries" not in tables:
            return

        columns = get_table_columns(connection, "deliveries")

        if "ball_pos" not in columns:
            connection.execute(
                "ALTER TABLE deliveries ADD COLUMN ball_pos INTEGER"
            )

            old_rows = connection.execute("""
                SELECT id, ball_no
                FROM deliveries
                WHERE ball_pos IS NULL
            """).fetchall()

            updates = []

            for row_id, ball_no in old_rows:
                updates.append((
                    parse_ball(ball_no),
                    row_id
                ))

            if updates:
                connection.executemany("""
                    UPDATE deliveries
                    SET ball_pos=?
                    WHERE id=?
                """, updates)

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()


def build_database(database_path, league, zip_path):
    """
    Create fresh SQLite database from Cricsheet JSON ZIP.
    """
    temporary_path = database_path.with_suffix(".tmp")

    if temporary_path.exists():
        temporary_path.unlink()

    connection = sqlite3.connect(str(temporary_path), timeout=120)

    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")

        connection.execute("""
            CREATE TABLE matches(
                match_id TEXT PRIMARY KEY,
                venue TEXT,
                winner TEXT,
                league TEXT
            )
        """)

        connection.execute("""
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
        """)

        match_rows = []
        delivery_rows = []

        with zipfile.ZipFile(zip_path) as source_zip:
            filenames = source_zip.namelist()

            for filename in filenames:
                if not filename.endswith(".json"):
                    continue

                try:
                    raw = source_zip.read(filename)
                    match_data = json.loads(raw)

                    info = match_data.get("info", {}) or {}
                    teams = info.get("teams", []) or []

                    if len(teams) < 2:
                        continue

                    outcome = info.get("outcome", {}) or {}

                    winner = (
                        outcome.get("winner", "")
                        or outcome.get("eliminator", "")
                        or ""
                    )

                    match_id = Path(filename).stem
                    venue = str(info.get("venue", "") or "")

                    match_rows.append((
                        match_id,
                        venue,
                        str(winner),
                        league
                    ))

                    innings_list = match_data.get("innings", []) or []

                    for innings_no, innings in enumerate(innings_list, start=1):
                        if innings.get("super_over"):
                            continue

                        batting_team = str(innings.get("team", "") or "")

                        bowling_team = next(
                            (
                                team
                                for team in teams
                                if team != batting_team
                            ),
                            ""
                        )

                        overs = innings.get("overs", []) or []

                        for over_data in overs:
                            over_no = int(over_data.get("over", 0) or 0)
                            deliveries = over_data.get("deliveries", []) or []

                            for delivery in deliveries:
                                delivery_value = delivery.get("actual_delivery")

                                if not delivery_value:
                                    try:
                                        delivery_value = (
                                            f"{over_no}."
                                            f"{int(delivery.get('ball'))}"
                                        )
                                    except Exception:
                                        continue

                                ball_pos = parse_ball(delivery_value)

                                if ball_pos is None:
                                    continue

                                runs_data = delivery.get("runs", {}) or {}
                                runs = int(runs_data.get("total", 0) or 0)

                                wickets = len(
                                    delivery.get("wickets", []) or []
                                )

                                delivery_rows.append((
                                    match_id,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    over_no,
                                    str(delivery_value),
                                    ball_pos,
                                    runs,
                                    wickets,
                                    league
                                ))

                    if len(match_rows) >= 200:
                        connection.executemany("""
                            INSERT OR REPLACE INTO matches(
                                match_id, venue, winner, league
                            )
                            VALUES(?,?,?,?)
                        """, match_rows)

                        match_rows.clear()

                    if len(delivery_rows) >= 10000:
                        connection.executemany("""
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
                        """, delivery_rows)

                        delivery_rows.clear()

                except Exception:
                    continue

        if match_rows:
            connection.executemany("""
                INSERT OR REPLACE INTO matches(
                    match_id, venue, winner, league
                )
                VALUES(?,?,?,?)
            """, match_rows)

        if delivery_rows:
            connection.executemany("""
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
            """, delivery_rows)

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()

    temporary_path.replace(database_path)


def ensure_database(league):
    """
    Use current DB if present.
    Otherwise download Cricsheet archive and build DB.
    """
    database_path = DATABASES[league]

    if database_path.exists():
        migrate_database(database_path)
        return database_path

    building_path = database_path.with_suffix(".building")

    try:
        if building_path.exists():
            building_path.unlink()

        with tempfile.TemporaryDirectory() as temp_directory:
            zip_path = Path(temp_directory) / "matches.zip"

            urllib.request.urlretrieve(
                DOWNLOAD_URLS[league],
                zip_path
            )

            build_database(
                building_path,
                league,
                zip_path
            )

        building_path.replace(database_path)

        return database_path

    except Exception:
        if building_path.exists():
            building_path.unlink()
        raise


@st.cache_resource
def get_connection(database_path_string):
    """
    Cached readonly SQLite connection.
    """
    database_path = Path(database_path_string)

    migrate_database(database_path)

    connection = sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=60
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-12000")

    return connection


# =========================================================
# DATABASE QUERY HELPERS
# =========================================================

def get_values(connection, query, league):
    rows = connection.execute(query, (league,)).fetchall()

    return [
        row[0]
        for row in rows
        if row[0]
    ]


def get_score_at_ball(connection, match_id, innings_no, ball_pos):
    """
    Current cumulative score at a ball position.
    """
    row = connection.execute("""
        SELECT
            COALESCE(SUM(runs), 0) AS total_runs,
            COALESCE(SUM(wickets), 0) AS total_wickets
        FROM deliveries
        WHERE match_id=?
          AND innings_no=?
          AND ball_pos<=?
    """, (
        match_id,
        innings_no,
        ball_pos
    )).fetchone()

    return int(row["total_runs"] or 0), int(row["total_wickets"] or 0)


def get_final_score(connection, match_id, innings_no):
    row = connection.execute("""
        SELECT COALESCE(SUM(runs), 0) AS final_runs
        FROM deliveries
        WHERE match_id=?
          AND innings_no=?
    """, (
        match_id,
        innings_no
    )).fetchone()

    return int(row["final_runs"] or 0)


def is_batting_team_winner(connection, match_id, batting_team):
    row = connection.execute("""
        SELECT winner
        FROM matches
        WHERE match_id=?
    """, (match_id,)).fetchone()

    if not row:
        return False

    winner = str(row["winner"] or "")
    return bool(winner and winner == batting_team)


# =========================================================
# HISTORICAL MODEL
# =========================================================

def find_similar_matches(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_end_ball,
    batting_team,
    bowling_team
):
    """
    Find original historical match states.

    Important:
    - First tries same batting + bowling teams.
    - If sample is low, expands to batting team only.
    - If still low, expands to entire league.
    - Only one closest state per historical match innings is retained.
    - No random values and no artificially generated data.
    """

    low_ball = max(1, int(current_ball) - 2)
    high_ball = min(
        int(session_end_ball),
        int(current_ball) + 2
    )

    def fetch_candidates(team_mode):
        filters = """
            league=?
            AND innings_no=?
            AND ball_pos BETWEEN ? AND ?
        """

        params = [
            league,
            innings_no,
            low_ball,
            high_ball
        ]

        if team_mode == "both":
            filters += """
                AND batting_team=?
                AND bowling_team=?
            """
            params.extend([batting_team, bowling_team])

        elif team_mode == "batting":
            filters += " AND batting_team=?"
            params.append(batting_team)

        query = f"""
            SELECT
                match_id,
                innings_no,
                ball_pos,
                batting_team,
                bowling_team
            FROM deliveries
            WHERE {filters}
            GROUP BY
                match_id,
                innings_no,
                ball_pos,
                batting_team,
                bowling_team
            LIMIT 20000
        """

        return connection.execute(query, params).fetchall()

    candidate_rows = fetch_candidates("both")

    if len(candidate_rows) < 40:
        candidate_rows = fetch_candidates("batting")

    if len(candidate_rows) < 40:
        candidate_rows = fetch_candidates("league")

    best_by_innings = {}

    for row in candidate_rows:
        match_id = row["match_id"]
        historical_innings = int(row["innings_no"])
        historical_ball = int(row["ball_pos"])

        historical_runs, historical_wickets = get_score_at_ball(
            connection,
            match_id,
            historical_innings,
            historical_ball
        )

        run_difference = abs(historical_runs - current_runs)
        wicket_difference = abs(
            historical_wickets - current_wickets
        )
        ball_difference = abs(historical_ball - current_ball)

        if run_difference > 35:
            continue

        if wicket_difference > 4:
            continue

        distance = (
            (run_difference * 1.0)
            + (wicket_difference * 8.0)
            + (ball_difference * 2.0)
        )

        key = (match_id, historical_innings)

        result = {
            "match_id": match_id,
            "innings_no": historical_innings,
            "ball_pos": historical_ball,
            "current_runs": historical_runs,
            "current_wickets": historical_wickets,
            "batting_team": row["batting_team"],
            "bowling_team": row["bowling_team"],
            "distance": float(distance)
        }

        if key not in best_by_innings:
            best_by_innings[key] = result

        elif result["distance"] < best_by_innings[key]["distance"]:
            best_by_innings[key] = result

    result_rows = list(best_by_innings.values())

    result_rows.sort(
        key=lambda item: item["distance"]
    )

    return result_rows[:3000]


def calculate_live_model(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    batting_team,
    bowling_team,
    target
):
    """
    Calculates:
    - Auto session line.
    - Probability of crossing that line.
    - Batting-team win probability.

    All values are derived from historical match records.
    """

    session_end_ball = int(session_over) * 6

    if current_ball >= session_end_ball:
        return {
            "low": int(current_runs),
            "high": int(current_runs) + 1,
            "expected": float(current_runs),
            "session_yes": 0.0,
            "session_no": 100.0,
            "win_probability": None,
            "sample_count": 0
        }

    similar_rows = find_similar_matches(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=current_ball,
        current_runs=current_runs,
        current_wickets=current_wickets,
        session_end_ball=session_end_ball,
        batting_team=batting_team,
        bowling_team=bowling_team
    )

    if not similar_rows:
        return {
            "low": int(current_runs),
            "high": int(current_runs) + 1,
            "expected": float(current_runs),
            "session_yes": 0.0,
            "session_no": 100.0,
            "win_probability": None,
            "sample_count": 0
        }

    score_samples = []
    win_samples = []
    weights = []

    for item in similar_rows:
        future_score, _ = get_score_at_ball(
            connection,
            item["match_id"],
            item["innings_no"],
            session_end_ball
        )

        if future_score < item["current_runs"]:
            future_score = get_final_score(
                connection,
                item["match_id"],
                item["innings_no"]
            )

        weight = 1.0 / (1.0 + float(item["distance"]))

        score_samples.append(int(future_score))
        weights.append(weight)

        if innings_no == 1:
            historical_win = is_batting_team_winner(
                connection,
                item["match_id"],
                item["batting_team"]
            )
            win_samples.append(1 if historical_win else 0)

        elif innings_no == 2 and int(target) > 0:
            historical_final = get_final_score(
                connection,
                item["match_id"],
                item["innings_no"]
            )
            win_samples.append(
                1 if historical_final >= int(target) else 0
            )

    total_weight = sum(weights)

    if total_weight <= 0:
        expected = float(current_runs)
    else:
        expected = sum(
            score * weight
            for score, weight in zip(score_samples, weights)
        ) / total_weight

    auto_low = max(
        int(current_runs),
        int(round(expected))
    )
    auto_high = auto_low + 1

    session_yes_weight = sum(
        weight
        for score, weight in zip(score_samples, weights)
        if score >= auto_high
    )

    session_yes = (
        session_yes_weight / total_weight * 100
        if total_weight > 0 else 0.0
    )

    win_probability = None

    if win_samples and len(win_samples) == len(weights):
        weighted_wins = sum(
            result * weight
            for result, weight in zip(win_samples, weights)
        )

        win_probability = (
            weighted_wins / total_weight * 100
            if total_weight > 0 else None
        )

    return {
        "low": int(auto_low),
        "high": int(auto_high),
        "expected": float(expected),
        "session_yes": float(session_yes),
        "session_no": float(100 - session_yes),
        "win_probability": win_probability,
        "sample_count": len(similar_rows)
    }


def calculate_manual_session_probability(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    batting_team,
    bowling_team,
    manual_high
):
    """
    Recalculate YES / NO for a user-selected manual session line.
    """

    session_end_ball = int(session_over) * 6

    similar_rows = find_similar_matches(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=current_ball,
        current_runs=current_runs,
        current_wickets=current_wickets,
        session_end_ball=session_end_ball,
        batting_team=batting_team,
        bowling_team=bowling_team
    )

    if not similar_rows:
        return {
            "yes": 0.0,
            "no": 100.0,
            "samples": 0
        }

    total_weight = 0.0
    yes_weight = 0.0

    for item in similar_rows:
        final_session_score, _ = get_score_at_ball(
            connection,
            item["match_id"],
            item["innings_no"],
            session_end_ball
        )

        if final_session_score < item["current_runs"]:
            final_session_score = get_final_score(
                connection,
                item["match_id"],
                item["innings_no"]
            )

        weight = 1.0 / (1.0 + float(item["distance"]))
        total_weight += weight

        if final_session_score >= int(manual_high):
            yes_weight += weight

    yes = (
        yes_weight / total_weight * 100
        if total_weight > 0 else 0.0
    )

    return {
        "yes": float(yes),
        "no": float(100 - yes),
        "samples": len(similar_rows)
    }


# =========================================================
# SESSION STATE
# =========================================================

default_state = {
    "runs": 16,
    "wickets": 1,
    "balls": 19,
    "last": "Starting situation",
    "undo_stack": [],
    "session_over_value": 6,
    "target_value": 0,
    "manual_mode": False,
    "session_low": 0,
    "session_high": 1,
    "expected_score": 0.0,
    "win_probability": None,
    "manual_result": None
}

for state_key, state_value in default_state.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_value


# =========================================================
# SIDEBAR SETTINGS
# =========================================================

with st.sidebar:
    st.header("Match Setup")

    league = st.selectbox(
        "League",
        LEAGUES,
        key="league_selection"
    )

    try:
        database_path = ensure_database(league)
        connection = get_connection(
            str(database_path.resolve())
        )

    except Exception as error:
        st.error("Historical database start nahi ho saka.")
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
        league
    )

    if not teams:
        st.error("Database me teams nahi mile.")
        st.stop()

    batting_team = st.selectbox(
        "Batting Team",
        teams,
        key="batting_team_selection"
    )

    bowling_options = [
        team
        for team in teams
        if team != batting_team
    ]

    bowling_team = st.selectbox(
        "Bowling Team",
        bowling_options,
        key="bowling_team_selection"
    )

    innings_label = st.selectbox(
        "Innings",
        ["1st Innings", "2nd Innings"],
        key="innings_selection"
    )

    innings_no = 1 if innings_label == "1st Innings" else 2

    session_over = st.number_input(
        "Session Over",
        min_value=1,
        max_value=20,
        value=int(st.session_state.session_over_value),
        step=1,
        key="session_over_input"
    )

    target = st.number_input(
        "Target Runs",
        min_value=0,
        max_value=400,
        value=int(st.session_state.target_value),
        step=1,
        key="target_runs_input"
    )

    st.session_state.session_over_value = int(session_over)
    st.session_state.target_value = int(target)

    ball_points = ["0.0"] + [
        f"{over}.{ball}"
        for over in range(20)
        for ball in range(1, 7)
    ]

    start_over = st.selectbox(
        "Start Over / Ball",
        ball_points,
        index=19,
        key="start_over_selection"
    )

    start_runs = st.number_input(
        "Start Runs",
        min_value=0,
        max_value=400,
        value=16,
        step=1,
        key="start_runs_input"
    )

    start_wickets = st.number_input(
        "Start Wickets",
        min_value=0,
        max_value=10,
        value=1,
        step=1,
        key="start_wickets_input"
    )

    if st.button(
        "Set Current Match Situation",
        use_container_width=True,
        key="set_current_match"
    ):
        st.session_state.runs = int(start_runs)
        st.session_state.wickets = int(start_wickets)
        st.session_state.balls = parse_ball(start_over) or 0
        st.session_state.undo_stack = []
        st.session_state.last = "Starting situation set"
        st.session_state.manual_result = None
        st.rerun()

    if st.button(
        "Reset Live Situation",
        use_container_width=True,
        key="reset_live_match"
    ):
        st.session_state.runs = 0
        st.session_state.wickets = 0
        st.session_state.balls = 0
        st.session_state.undo_stack = []
        st.session_state.last = ""
        st.session_state.manual_result = None
        st.rerun()


# =========================================================
# CURRENT LIVE MODEL
# =========================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

try:
    live_model = calculate_live_model(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=balls,
        current_runs=runs,
        current_wickets=wickets,
        session_over=int(session_over),
        batting_team=batting_team,
        bowling_team=bowling_team,
        target=int(target)
    )

except Exception as error:
    st.error("Model calculation error.")
    st.exception(error)
    st.stop()

if not st.session_state.manual_mode:
    st.session_state.session_low = int(live_model["low"])
    st.session_state.session_high = int(live_model["high"])
    st.session_state.expected_score = float(live_model["expected"])
    st.session_state.win_probability = live_model["win_probability"]


# =========================================================
# TOP SCORE + MODE
# =========================================================

top_left, top_right = st.columns([8, 2])

with top_left:
    st.markdown(
        f"""
        <div class="card">
            <h2 style="margin:0">
                {batting_team} {runs}/{wickets}
            </h2>
            <p class="small" style="margin:4px 0 0">
                {display_over(balls)} ov
                • Session End: {session_over} ov
                • Target: {target if target > 0 else "Not set"}
                • Last: {st.session_state.last or "—"}
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

with top_right:
    selected_mode = st.radio(
        "Mode",
        options=["AUTO", "MANUAL"],
        index=1 if st.session_state.manual_mode else 0,
        horizontal=True,
        key="mode_radio"
    )

    st.session_state.manual_mode = (
        selected_mode == "MANUAL"
    )


# =========================================================
# LIVE BALL BUTTONS
# =========================================================

st.subheader("Ball-by-Ball Update")

actions = [
    ("Dot", 0, False),
    ("1", 1, False),
    ("2", 2, False),
    ("3", 3, False),
    ("4", 4, False),
    ("6", 6, False),
    ("Wicket", 0, True),
    ("Undo", None, False)
]

button_columns = st.columns(8)

for index, (label, run_value, wicket_value) in enumerate(actions):
    with button_columns[index]:
        if st.button(
            label,
            use_container_width=True,
            key=f"live_ball_button_{index}"
        ):
            if label == "Undo":
                if st.session_state.undo_stack:
                    old_state = st.session_state.undo_stack.pop()

                    st.session_state.runs = old_state["runs"]
                    st.session_state.wickets = old_state["wickets"]
                    st.session_state.balls = old_state["balls"]
                    st.session_state.last = "Undo"

            else:
                st.session_state.undo_stack.append({
                    "runs": runs,
                    "wickets": wickets,
                    "balls": balls,
                    "last": st.session_state.last
                })

                st.session_state.runs = int(runs) + int(run_value)
                st.session_state.wickets = min(
                    10,
                    int(wickets) + int(wicket_value)
                )
                st.session_state.balls = int(balls) + 1
                st.session_state.last = label

            st.session_state.manual_result = None
            st.rerun()


# =========================================================
# SESSION + WIN BOXES
# =========================================================

session_column, winning_column = st.columns(2)

with session_column:
    st.markdown(
        f"""
        <div class="session-box">
            <h3 style="margin:0">Session</h3>
            <h1 style="margin:8px 0">
                {int(st.session_state.session_low)}-
                {int(st.session_state.session_high)}
            </h1>
            <p class="small" style="margin:0">
                Expected: {float(st.session_state.expected_score):.1f}
                • End: {session_over} ov
            </p>
        </div>
        """,
        unsafe_allow_html=True
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
        <div class="win-box">
            <h3 style="margin:0">{batting_team} Win</h3>
            <h1 style="margin:8px 0">{probability_text}</h1>
            <p class="small" style="margin:0">
                Current score + historical match situations
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )


# =========================================================
# MANUAL SESSION SETTINGS
# =========================================================

manual_low_column, manual_high_column = st.columns(2)

with manual_low_column:
    manual_low = st.number_input(
        "Manual Session Low",
        min_value=0,
        max_value=400,
        value=int(st.session_state.session_low),
        step=1,
        key="manual_session_low_input"
    )

with manual_high_column:
    manual_high = st.number_input(
        "Manual Session High",
        min_value=0,
        max_value=400,
        value=int(st.session_state.session_high),
        step=1,
        key="manual_session_high_input"
    )

control_one, control_two, control_three = st.columns(3)

with control_one:
    if st.button(
        "Apply Manual Session",
        use_container_width=True,
        key="apply_manual_session"
    ):
        st.session_state.manual_mode = True
        st.session_state.session_low = int(manual_low)
        st.session_state.session_high = max(
            int(manual_low) + 1,
            int(manual_high)
        )

        try:
            st.session_state.manual_result = (
                calculate_manual_session_probability(
                    connection=connection,
                    league=league,
                    innings_no=innings_no,
                    current_ball=balls,
                    current_runs=runs,
                    current_wickets=wickets,
                    session_over=int(session_over),
                    batting_team=batting_team,
                    bowling_team=bowling_team,
                    manual_high=int(st.session_state.session_high)
                )
            )
        except Exception as error:
            st.error("Manual session calculation error.")
            st.exception(error)

        st.rerun()

with control_two:
    if st.button(
        "Use Auto Session",
        use_container_width=True,
        key="use_auto_session"
    ):
        st.session_state.manual_mode = False
        st.session_state.manual_result = None
        st.rerun()

with control_three:
    if st.button(
        "Refresh Result",
        use_container_width=True,
        key="refresh_result"
    ):
        st.session_state.manual_result = None
        st.rerun()


# =========================================================
# FINAL RESULT
# =========================================================

if st.session_state.manual_mode:
    manual_result = st.session_state.manual_result

    if manual_result is None:
        try:
            manual_result = calculate_manual_session_probability(
                connection=connection,
                league=league,
                innings_no=innings_no,
                current_ball=balls,
                current_runs=runs,
                current_wickets=wickets,
                session_over=int(session_over),
                batting_team=batting_team,
                bowling_team=bowling_team,
                manual_high=int(st.session_state.session_high)
            )
        except Exception as error:
            st.error("Manual result calculation error.")
            st.exception(error)
            manual_result = {
                "yes": 0.0,
                "no": 100.0,
                "samples": 0
            }

    final_yes = float(manual_result["yes"])
    final_no = float(manual_result["no"])

else:
    final_yes = float(live_model["session_yes"])
    final_no = float(live_model["session_no"])

final_label = "YES" if final_yes >= final_no else "NO"
final_css = "yes" if final_label == "YES" else "no"
final_probability = max(final_yes, final_no)

st.subheader("VasuDev Result")

st.markdown(
    f"""
    <div class="{final_css}">
        <h1 style="margin:0">
            SESSION {final_label} — {final_probability:.1f}%
        </h1>
        <p style="margin:8px 0 0">
            Session Line:
            <b>
                {int(st.session_state.session_low)}-
                {int(st.session_state.session_high)}
            </b>
        </p>
    </div>
    """,
    unsafe_allow_html=True
)

win_probability = st.session_state.win_probability

if win_probability is not None:
    batting_win = float(win_probability)
    bowling_win = 100.0 - batting_win

    likely_winner = (
        batting_team
        if batting_win >= bowling_win
        else bowling_team
    )

    winner_probability = max(
        batting_win,
        bowling_win
    )

    win_css = (
        "yes"
        if likely_winner == batting_team
        else "no"
    )

    st.markdown(
        f"""
        <div class="{win_css}">
            <h1 style="margin:0">
                {likely_winner.upper()} WIN — {winner_probability:.1f}%
            </h1>
            <p style="margin:8px 0 0">
                {batting_team}: <b>{batting_win:.1f}%</b>
                •
                {bowling_team}: <b>{bowling_win:.1f}%</b>
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

else:
    if innings_no == 2 and int(target) <= 0:
        st.info(
            "2nd innings winning probability ke liye Target Runs set karein."
        )
    else:
        st.info(
            "Winning estimate ke liye sufficient historical result data nahi mila."
        )

st.caption(
    "Historical estimate only. Ye guarantee nahi hai aur live match ke result ko confirm nahi karta."
)

with st.expander("Model Details"):
    st.write(
        f"Auto expected session-end score: **{live_model['expected']:.1f}**"
    )
    st.write(
        f"Session YES: **{final_yes:.1f}%** • "
        f"Session NO: **{final_no:.1f}%**"
    )

    if win_probability is not None:
        st.write(
            f"{batting_team} win probability: "
            f"**{float(win_probability):.1f}%**"
        )

    st.write(
        "Historical model current runs, wickets, ball position, innings and "
        "available team context ko compare karta hai. Har historical innings "
        "se sirf closest matching state use hoti hai, isliye ek hi match "
        "ki multiple deliveries result ko artificially inflate nahi karti."
    )
