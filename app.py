# VasuDev Cricket AI - final updated app.py
# CSA Pro T20 Cup (2019+) merged data support added.

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

st.html(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #061426, #081c35);
        color: #f8fafc;
    }

    header[data-testid="stHeader"] {
        background: transparent !important;
        height: 2.5rem !important;
        min-height: 2.5rem !important;
        box-shadow: none !important;
        border: none !important;
    }

    header[data-testid="stHeader"] > div {
        background: transparent !important;
    }

    [data-testid="stAppViewContainer"] {
        padding-top: 0 !important;
    }

    [data-testid="stHeader"] button {
        background: transparent !important;
        color: #ffffff !important;
        position: relative !important;
        top: 6px !important;
        z-index: 999999 !important;
    }

    [data-testid="stHeader"] svg {
        color: #ffffff !important;
        fill: #ffffff !important;
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

    .projection-box,
    .winning-box,
    .historical-box {
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

    .historical-box {
        border-color: #2e9c8f;
        min-height: 210px;
    }

    .positive {
        background: #07552f;
        border: 2px solid #20c77a;
        padding: 14px;
        border-radius: 14px;
        text-align: center;
    }

    .negative {
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
    """
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
    "CSA Pro T20 Cup": BASE / "csa_pro_t20_history.db",
}

# Single URL = one archive. List = multiple archives merged into one DB.
DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
    "CSA Pro T20 Cup": [
        "https://cricsheet.org/downloads/csa_t20_json.zip",
        "https://cricsheet.org/downloads/csa_provincial_t20_json.zip",
    ],
}

LEAGUES = list(DATABASES.keys())

# Minimum year of matches to keep in the database.
# All CSA Pro T20 Cup data older than this is discarded during build.
MIN_MATCH_YEAR = 2019
YEAR_FILTER_LEAGUES = {"CSA Pro T20 Cup"}


# ============================================================
# CSA TEAM NAME UNIFICATION
# ============================================================

CSA_TEAM_ALIASES = {
    # Division 1 franchises - historical/alternate names -> current
    "Cape Cobras": "Western Province",
    "Cobras": "Western Province",
    "Highveld Lions": "Lions",
    "Imperial Lions": "Lions",
    "bizhub Lions": "Lions",
    "Dafabet Warriors": "Warriors",
    "Hollywoodbets Dolphins": "Dolphins",
    "Momentum Multiply Titans": "Titans",
    "VKB Knights": "Knights",
    "ITEC Knights": "Knights",
    "North West Dragons": "North West",
    "Dragons": "North West",
    "Rocks": "Boland",
    "Garden Route Badgers": "South Western Districts",
    "Badgers": "South Western Districts",
    "Eastern Storm": "Easterns",
    "Wenbro Impalas": "Limpopo",
    "Impalas": "Limpopo",
    "Mpumalanga Rhinos": "Mpumalanga",
    "Rhinos": "Mpumalanga",
    "N.C. Heat": "Northern Cape",
    "Northern Cape Heat": "Northern Cape",
    "E.C. Iinyathi": "Border",
    "Eastern Cape Iinyathi": "Border",
    "Iinyathi": "Border",
    "Free State": "Knights",
    "Eastern Province": "Warriors",
    "Northerns": "Titans",
    "Gauteng": "Lions",
    "KwaZulu-Natal": "Dolphins",
    "KwaZulu-Natal Inland": "Tuskers",
}


def unify_csa_team(name):
    name = str(name or "").strip()
    return CSA_TEAM_ALIASES.get(name, name)


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
        if over < 0 or ball < 0 or ball > 6:
            return None
        if ball == 0:
            return over * 6
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
    return f"{(total_balls - 1) // 6}.{((total_balls - 1) % 6) + 1}"


def get_match_year(info):
    """Extract the earliest year from Cricsheet 'dates' list."""
    dates = info.get("dates", []) or []
    years = []
    for d in dates:
        try:
            years.append(int(str(d).split("-")[0]))
        except Exception:
            continue
    return min(years) if years else None


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


def database_is_valid(database_path, league):
    if not database_path.exists() or database_path.stat().st_size == 0:
        return False

    connection = None
    try:
        connection = sqlite3.connect(str(database_path), timeout=30)
        tables = get_table_names(connection)

        if "matches" not in tables or "deliveries" not in tables:
            return False

        delivery_columns = get_table_columns(connection, "deliveries")
        match_columns = get_table_columns(connection, "matches")

        required_delivery = {
            "match_id", "innings_no", "batting_team", "bowling_team",
            "ball_pos", "runs", "wickets", "league"
        }
        required_match = {"match_id", "venue", "winner", "league"}

        if not required_delivery.issubset(delivery_columns):
            return False
        if not required_match.issubset(match_columns):
            return False

        delivery_count = connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE league=?",
            (league,),
        ).fetchone()[0]

        match_count = connection.execute(
            "SELECT COUNT(*) FROM matches WHERE league=?",
            (league,),
        ).fetchone()[0]

        return int(delivery_count) > 0 and int(match_count) > 0

    except Exception:
        return False
    finally:
        if connection is not None:
            connection.close()


# ============================================================
# DATABASE MIGRATION
# ============================================================

def create_indexes(connection):
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_deliveries_state "
        "ON deliveries(league, innings_no, ball_pos)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_deliveries_match "
        "ON deliveries(match_id, innings_no, ball_pos)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_deliveries_teams "
        "ON deliveries(league, innings_no, batting_team, bowling_team)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_matches_venue ON matches(league, venue)"
    )


def migrate_database(database_path):
    if not database_path.exists():
        return

    connection = sqlite3.connect(str(database_path), timeout=120)
    try:
        tables = get_table_names(connection)
        if "deliveries" not in tables or "matches" not in tables:
            return

        columns = get_table_columns(connection, "deliveries")
        if "ball_pos" not in columns:
            connection.execute(
                "ALTER TABLE deliveries ADD COLUMN ball_pos INTEGER"
            )
            rows = connection.execute(
                "SELECT id, ball_no FROM deliveries WHERE ball_pos IS NULL"
            ).fetchall()
            updates = []
            for row_id, ball_no in rows:
                position = parse_ball(ball_no)
                if position is not None:
                    updates.append((position, row_id))
            if updates:
                connection.executemany(
                    "UPDATE deliveries SET ball_pos=? WHERE id=?",
                    updates,
                )

        create_indexes(connection)
        connection.commit()
    finally:
        connection.close()


# ============================================================
# DATABASE BUILDER (multiple archives + team unification + year filter)
# ============================================================

def build_database(
    database_path,
    league,
    archive_paths,
    unify_teams=False,
    min_year=None,
):
    temporary_path = database_path.with_suffix(".tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection = sqlite3.connect(str(temporary_path), timeout=180)
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
        json_files_seen = 0
        json_files_kept = 0
        archive_count = len(archive_paths)

        for archive_path in archive_paths:
            with zipfile.ZipFile(archive_path) as source_zip:
                for filename in source_zip.namelist():
                    if not filename.lower().endswith(".json"):
                        continue
                    json_files_seen += 1

                    try:
                        data = json.loads(source_zip.read(filename))
                        info = data.get("info", {}) or {}

                        # Year filter (for CSA Pro T20 Cup only)
                        if min_year is not None:
                            match_year = get_match_year(info)
                            if match_year is None or match_year < min_year:
                                continue

                        teams = info.get("teams", []) or []
                        if len(teams) < 2:
                            continue

                        json_files_kept += 1

                        outcome = info.get("outcome", {}) or {}
                        winner = str(
                            outcome.get("winner", "")
                            or outcome.get("eliminator", "")
                            or ""
                        )

                        match_id = Path(filename).stem
                        venue = str(info.get("venue", "") or "")

                        if unify_teams:
                            teams = [unify_csa_team(t) for t in teams]
                            winner = unify_csa_team(winner)

                        match_rows.append((match_id, venue, winner, league))

                        innings_list = data.get("innings", []) or []
                        for innings_no, innings in enumerate(innings_list, start=1):
                            if innings.get("super_over"):
                                continue

                            batting_team = str(innings.get("team", "") or "")
                            if unify_teams:
                                batting_team = unify_csa_team(batting_team)

                            bowling_team = next(
                                (t for t in teams if t != batting_team),
                                "",
                            )

                            for over_data in innings.get("overs", []) or []:
                                over_no = int(over_data.get("over", 0) or 0)
                                deliveries = over_data.get("deliveries", []) or []
                                for delivery_index, delivery in enumerate(
                                    deliveries, start=1
                                ):
                                    actual_delivery = delivery.get(
                                        "actual_delivery"
                                    )
                                    ball_text = (
                                        str(actual_delivery)
                                        if actual_delivery
                                        else f"{over_no}.{delivery_index}"
                                    )
                                    ball_pos = parse_ball(ball_text)
                                    if ball_pos is None:
                                        continue

                                    runs = int(
                                        (delivery.get("runs") or {}).get(
                                            "total", 0
                                        )
                                        or 0
                                    )
                                    wickets = len(
                                        delivery.get("wickets") or []
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
                                    match_id, venue, winner, league
                                ) VALUES(?,?,?,?)
                                """,
                                match_rows,
                            )
                            match_rows.clear()

                        if len(delivery_rows) >= 10000:
                            connection.executemany(
                                """
                                INSERT INTO deliveries(
                                    match_id, innings_no, batting_team,
                                    bowling_team, over_no, ball_no,
                                    ball_pos, runs, wickets, league
                                ) VALUES(?,?,?,?,?,?,?,?,?,?)
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
                    match_id, venue, winner, league
                ) VALUES(?,?,?,?)
                """,
                match_rows,
            )
        if delivery_rows:
            connection.executemany(
                """
                INSERT INTO deliveries(
                    match_id, innings_no, batting_team,
                    bowling_team, over_no, ball_no,
                    ball_pos, runs, wickets, league
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                delivery_rows,
            )

        create_indexes(connection)
        connection.commit()

        if json_files_seen == 0:
            raise RuntimeError(
                f"No JSON match files found in {archive_count} archive(s) for {league}."
            )

        delivery_count = connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE league=?",
            (league,),
        ).fetchone()[0]
        match_count = connection.execute(
            "SELECT COUNT(*) FROM matches WHERE league=?",
            (league,),
        ).fetchone()[0]

        if int(delivery_count) == 0 or int(match_count) == 0:
            raise RuntimeError(
                f"{league} archives were downloaded but no usable match data was built "
                f"(year filter >= {min_year} may have removed everything)."
            )

    finally:
        connection.close()

    temporary_path.replace(database_path)


def download_archive(url, destination):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 VasuDev Cricket Historical Analyzer",
            "Accept": "application/zip,application/octet-stream,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()
    destination.write_bytes(data)

    if not zipfile.is_zipfile(destination):
        try:
            preview = destination.read_bytes()[:200].decode(
                "utf-8", errors="ignore"
            )
        except Exception:
            preview = ""
        raise RuntimeError(
            "Cricsheet download was not a valid ZIP archive. "
            f"Server response preview: {preview[:120]!r}"
        )


def ensure_database(league):
    database_path = DATABASES[league]

    if database_is_valid(database_path, league):
        migrate_database(database_path)
        return database_path

    if database_path.exists():
        try:
            database_path.unlink()
        except Exception:
            pass

    building_path = database_path.with_suffix(".building")

    try:
        if building_path.exists():
            building_path.unlink()

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_dir = Path(temp_directory)
            urls = DOWNLOAD_URLS[league]
            if isinstance(urls, str):
                urls = [urls]

            archive_paths = []
            for i, url in enumerate(urls):
                archive_path = temp_dir / f"matches_{i}.zip"
                download_archive(url, archive_path)
                archive_paths.append(archive_path)

            unify = league == "CSA Pro T20 Cup"
            min_year = MIN_MATCH_YEAR if league in YEAR_FILTER_LEAGUES else None

            build_database(
                building_path,
                league,
                archive_paths,
                unify_teams=unify,
                min_year=min_year,
            )

        if not database_is_valid(building_path, league):
            raise RuntimeError(
                f"{league} database build completed but validation failed."
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
    rows = connection.execute(query, (league,)).fetchall()
    return [row[0] for row in rows if row[0]]


def get_grounds(connection, league):
    rows = connection.execute(
        """
        SELECT DISTINCT venue FROM matches
        WHERE league=? AND TRIM(COALESCE(venue,''))<>''
        ORDER BY venue
        """,
        (league,),
    ).fetchall()
    return [str(row[0]).strip() for row in rows if row[0]]


def score_at(connection, match_id, innings_no, end_ball):
    row = connection.execute(
        """
        SELECT
            COALESCE(SUM(runs), 0) AS total_runs,
            COALESCE(SUM(wickets), 0) AS total_wickets
        FROM deliveries
        WHERE match_id=? AND innings_no=? AND ball_pos<=?
        """,
        (match_id, innings_no, end_ball),
    ).fetchone()
    return int(row["total_runs"] or 0), int(row["total_wickets"] or 0)


def final_score(connection, match_id, innings_no):
    row = connection.execute(
        """
        SELECT COALESCE(SUM(runs), 0) AS final_runs
        FROM deliveries
        WHERE match_id=? AND innings_no=?
        """,
        (match_id, innings_no),
    ).fetchone()
    return int(row["final_runs"] or 0)


def match_winner(connection, match_id):
    row = connection.execute(
        "SELECT winner FROM matches WHERE match_id=? LIMIT 1",
        (match_id,),
    ).fetchone()
    return str(row["winner"] or "").strip() if row else ""


# ============================================================
# HISTORICAL MATCH MATCHING
# ============================================================

def find_similar_states(
    connection, league, innings_no, current_ball, current_runs,
    current_wickets, end_ball, batting_team, bowling_team,
    ground="", exclude_match_id="",
):
    low_ball = max(0, int(current_ball) - 2)
    high_ball = min(int(end_ball), int(current_ball) + 2)

    def fetch_candidates(mode):
        where_sql = """
            d.league=? AND d.innings_no=?
            AND d.ball_pos BETWEEN ? AND ?
        """
        params = [league, innings_no, low_ball, high_ball]

        if exclude_match_id:
            where_sql += " AND d.match_id<>?"
            params.append(str(exclude_match_id).strip())

        if mode == "both":
            where_sql += " AND d.batting_team=? AND d.bowling_team=?"
            params.extend([batting_team, bowling_team])
        elif mode == "batting":
            where_sql += " AND d.batting_team=?"
            params.append(batting_team)

        query = f"""
            SELECT
                d.match_id, d.innings_no, d.ball_pos,
                d.batting_team, d.bowling_team,
                COALESCE(m.venue, '') AS venue
            FROM deliveries d
            LEFT JOIN matches m
                ON m.match_id=d.match_id AND m.league=d.league
            WHERE {where_sql}
            GROUP BY d.match_id, d.innings_no, d.ball_pos,
                     d.batting_team, d.bowling_team, m.venue
            LIMIT 30000
        """
        return connection.execute(query, params).fetchall()

    candidates = fetch_candidates("both")
    if len(candidates) < 40:
        candidates = fetch_candidates("batting")
    if len(candidates) < 40:
        candidates = fetch_candidates("all")

    current_ball_float = max(0.0, float(current_ball))
    current_overs = current_ball_float / 6.0
    current_rr = float(current_runs) / current_overs if current_overs > 0 else 0.0

    best_states = {}
    for row in candidates:
        match_id = row["match_id"]
        historical_innings = int(row["innings_no"])
        historical_ball = int(row["ball_pos"])

        historical_runs, historical_wickets = score_at(
            connection, match_id, historical_innings, historical_ball
        )

        run_gap = abs(historical_runs - int(current_runs))
        wicket_gap = abs(historical_wickets - int(current_wickets))
        ball_gap = abs(historical_ball - int(current_ball))

        if run_gap > 35 or wicket_gap > 4:
            continue

        historical_overs = max(0.0001, historical_ball / 6.0)
        historical_rr = historical_runs / historical_overs
        rr_gap = abs(historical_rr - current_rr)

        venue = str(row["venue"] or "").strip()
        if ground:
            ground_match = venue.casefold() == str(ground).strip().casefold()
        else:
            ground_match = True

        team_gap = 0
        if str(row["batting_team"] or "") != batting_team:
            team_gap += 7
        if str(row["bowling_team"] or "") != bowling_team:
            team_gap += 4

        distance = (
            run_gap + (wicket_gap * 8) + (ball_gap * 2)
            + (rr_gap * 2.5) + team_gap + (0 if ground_match else 15)
        )

        key = (match_id, historical_innings)
        state = {
            "match_id": match_id,
            "innings_no": historical_innings,
            "ball_pos": historical_ball,
            "runs": historical_runs,
            "wickets": historical_wickets,
            "batting_team": row["batting_team"],
            "bowling_team": row["bowling_team"],
            "venue": venue,
            "ground_match": ground_match,
            "distance": float(distance),
        }
        if key not in best_states or state["distance"] < best_states[key]["distance"]:
            best_states[key] = state

    states = list(best_states.values())
    states.sort(key=lambda item: item["distance"])
    return states[:2500]


# ============================================================
# PAR SCORE
# ============================================================

CONFIDENCE_SAMPLES = 40.0


def get_par_score(
    connection, league, innings_no, end_ball,
    ground="", exclude_match_id="",
):
    params = [league, innings_no, int(end_ball)]
    join_sql = ""
    extra_where = ""

    if ground:
        join_sql = "JOIN matches m ON m.match_id=d.match_id AND m.league=d.league"
        extra_where += " AND m.venue=?"
        params.append(ground)

    if exclude_match_id:
        extra_where += " AND d.match_id<>?"
        params.append(str(exclude_match_id).strip())

    query = f"""
        SELECT AVG(inn_score) FROM (
            SELECT d.match_id, SUM(d.runs) AS inn_score
            FROM deliveries d
            {join_sql}
            WHERE d.league=? AND d.innings_no=? AND d.ball_pos<=?
            {extra_where}
            GROUP BY d.match_id
        )
    """
    row = connection.execute(query, params).fetchone()
    value = row[0] if row else None
    return float(value) if value is not None else None


def blend_with_par(estimate, samples, par_score):
    if par_score is None:
        return float(estimate)
    confidence = min(1.0, float(samples) / CONFIDENCE_SAMPLES)
    return (confidence * float(estimate)) + ((1.0 - confidence) * float(par_score))


# ============================================================
# INDEPENDENT HISTORICAL AVERAGE
# ============================================================

def calculate_historical_average(
    connection, league, innings_no, current_ball, current_runs,
    current_wickets, session_over, batting_team, bowling_team,
    ground, exclude_match_id="",
):
    end_ball = int(session_over) * 6
    if int(current_ball) >= end_ball:
        return {"average": float(current_runs), "low": int(current_runs),
                "high": int(current_runs), "samples": 0}

    states = find_similar_states(
        connection, league, innings_no, current_ball, current_runs,
        current_wickets, end_ball, batting_team, bowling_team,
        ground, exclude_match_id=exclude_match_id,
    )
    if not states:
        return {"average": float(current_runs), "low": int(current_runs),
                "high": int(current_runs), "samples": 0}

    values = []
    weights = []
    for state in states:
        session_score, _ = score_at(
            connection, state["match_id"], state["innings_no"], end_ball
        )
        if session_score < state["runs"]:
            session_score = final_score(
                connection, state["match_id"], state["innings_no"]
            )
        session_score = max(int(current_runs), int(session_score))
        weight = 1.0 / (1.0 + float(state["distance"]))
        values.append(session_score)
        weights.append(weight)

    if not values or sum(weights) <= 0:
        return {"average": float(current_runs), "low": int(current_runs),
                "high": int(current_runs), "samples": 0}

    total_weight = sum(weights)
    weighted_average = sum(v * w for v, w in zip(values, weights)) / total_weight
    par_score = get_par_score(
        connection, league, innings_no, end_ball,
        ground=ground, exclude_match_id=exclude_match_id,
    )
    blended_average = blend_with_par(weighted_average, len(values), par_score)
    shift = blended_average - weighted_average

    paired = sorted(zip(values, weights), key=lambda x: x[0])
    cumulative = 0.0
    q25 = paired[0][0]
    q75 = paired[-1][0]
    for value, weight in paired:
        cumulative += weight
        if cumulative >= total_weight * 0.25:
            q25 = value
            break
    cumulative = 0.0
    for value, weight in paired:
        cumulative += weight
        if cumulative >= total_weight * 0.75:
            q75 = value
            break

    low = max(int(current_runs), int(round(q25 + shift)))
    high = max(low, int(round(q75 + shift)))

    return {"average": float(blended_average), "low": low,
            "high": high, "samples": len(values)}


# ============================================================
# MODEL
# ============================================================

def calculate_auto_model(
    connection, league, innings_no, current_ball, current_runs,
    current_wickets, session_over, batting_team, bowling_team,
    target, ground="", exclude_match_id="",
):
    end_ball = int(session_over) * 6
    if int(current_ball) >= end_ball:
        return {"low": int(current_runs), "high": int(current_runs) + 1,
                "expected": float(current_runs), "session_yes": 0.0,
                "session_no": 100.0, "win_probability": None, "samples": 0}

    states = find_similar_states(
        connection, league, innings_no, current_ball, current_runs,
        current_wickets, end_ball, batting_team, bowling_team,
        ground, exclude_match_id=exclude_match_id,
    )
    if not states:
        return {"low": int(current_runs), "high": int(current_runs) + 1,
                "expected": float(current_runs), "session_yes": 0.0,
                "session_no": 100.0, "win_probability": None, "samples": 0}

    scores = []
    weights = []
    win_results = []
    for state in states:
        session_score, _ = score_at(
            connection, state["match_id"], state["innings_no"], end_ball
        )
        if session_score < state["runs"]:
            session_score = final_score(
                connection, state["match_id"], state["innings_no"]
            )
        session_score = max(int(current_runs), int(session_score))
        weight = 1.0 / (1.0 + float(state["distance"]))
        scores.append(int(session_score))
        weights.append(float(weight))

        historical_winner = match_winner(connection, state["match_id"])
        if int(innings_no) == 1:
            win_results.append(1 if historical_winner == batting_team else 0)
        elif int(innings_no) == 2 and int(target) > 0:
            historical_final = final_score(
                connection, state["match_id"], state["innings_no"]
            )
            win_results.append(1 if historical_final >= int(target) else 0)

    total_weight = sum(weights)
    raw_expected = (
        sum(s * w for s, w in zip(scores, weights)) / total_weight
        if total_weight > 
