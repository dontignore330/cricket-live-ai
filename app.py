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
        "expected":
