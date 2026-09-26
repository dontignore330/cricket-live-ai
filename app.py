# VasuDev Cricket AI - final updated app.py
# Built from the complete code supplied in this conversation.

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

    /* Keep the sidebar arrow visible and slightly lower. */
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

    .session-box,
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
    "CSA Pro20 Cup": BASE / "pro20_history.db",
}

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbbl_json.zip",
}

PRO20 = "CSA Pro20 Cup"
PRO20_DB = BASE / "pro20_history.db"
PRO20_REFRESH_HOURS = 24
PRO20_ARCHIVE_URLS = (
    "https://cricsheet.org/downloads/ctc_json.zip",
    "https://cricsheet.org/downloads/south_africa_male_json.zip",
    "https://cricsheet.org/downloads/2026_json.zip",
)

PRO20_TEAMS = [
    "Boland", "CSA High Performance", "WSB Eastern Storm",
    "Flexbrands Knights", "Mpumalanga Rhinos", "Momentum Multiply Titans",
    "Tuskers", "YesPlay Cobras", "Hollywoodbets Dolphins",
    "Eastern Cape Iinyathi", "Garden Route Badgers", "Wenbro Impalas",
    "DP World Lions", "North West Dragons", "Northern Cape Heat",
    "Dafabet Warriors",
]

LEAGUES = list(DATABASES.keys())


# ============================================================
# BASIC HELPERS
# ============================================================

def parse_ball(value):
    """Convert over.ball to legal-ball position.

    0.0 is valid and means zero completed legal balls.
    1.0 means six completed legal balls.
    Ball labels 1-6 are valid; 4.7/4.8 are rejected.
    """
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


def database_is_valid(database_path, league):
    """Validate that an existing DB is actually usable.

    This specifically prevents an empty/partial WBBL database from being
    accepted merely because wbbl_history.db exists.
    """
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

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_matches_venue
        ON matches(league, venue)
        """
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
                    "UPDATE deliveries SET ball_pos=? WHERE id=?",
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

        with zipfile.ZipFile(archive_path) as source_zip:
            for filename in source_zip.namelist():
                if not filename.lower().endswith(".json"):
                    continue

                json_files_seen += 1

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

                    match_rows.append((match_id, venue, winner, league))

                    innings_list = data.get("innings", []) or []

                    for innings_no, innings in enumerate(innings_list, start=1):
                        if innings.get("super_over"):
                            continue

                        batting_team = str(innings.get("team", "") or "")
                        bowling_team = next(
                            (team for team in teams if team != batting_team),
                            "",
                        )

                        for over_data in innings.get("overs", []) or []:
                            over_no = int(over_data.get("over", 0) or 0)
                            deliveries = over_data.get("deliveries", []) or []

                            for delivery_index, delivery in enumerate(deliveries, start=1):
                                actual_delivery = delivery.get("actual_delivery")
                                ball_text = (
                                    str(actual_delivery)
                                    if actual_delivery
                                    else f"{over_no}.{delivery_index}"
                                )

                                ball_pos = parse_ball(ball_text)
                                if ball_pos is None:
                                    continue

                                runs = int((delivery.get("runs") or {}).get("total", 0) or 0)
                                wickets = len(delivery.get("wickets") or [])

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
                    # One malformed match should not destroy the whole archive.
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
                f"No JSON match files found in the {league} archive."
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
                f"{league} archive was downloaded but no usable match data was built."
            )

    finally:
        connection.close()

    temporary_path.replace(database_path)


# ============================================================
# CSA PRO20 DATA BUILDER
# ============================================================

PRO20_ALIAS_RULES = {
    "boland": "Boland", "dafabet boland": "Boland",
    "cape cobras": "YesPlay Cobras", "cobras": "YesPlay Cobras",
    "western province": "YesPlay Cobras", "yesplay cobras": "YesPlay Cobras",
    "titans": "Momentum Multiply Titans", "northerns": "Momentum Multiply Titans",
    "northern titans": "Momentum Multiply Titans", "momentum multiply titans": "Momentum Multiply Titans",
    "knights": "Flexbrands Knights", "free state": "Flexbrands Knights",
    "free state knights": "Flexbrands Knights", "flexbrands knights": "Flexbrands Knights",
    "dolphins": "Hollywoodbets Dolphins", "kwazulu natal": "Hollywoodbets Dolphins",
    "kwa zulu natal": "Hollywoodbets Dolphins", "kzn coastal": "Hollywoodbets Dolphins",
    "hollywoodbets dolphins": "Hollywoodbets Dolphins",
    "lions": "DP World Lions", "highveld lions": "DP World Lions", "dp world lions": "DP World Lions",
    "warriors": "Dafabet Warriors", "dafabet warriors": "Dafabet Warriors",
    "north west": "North West Dragons", "northwest": "North West Dragons",
    "north west dragons": "North West Dragons", "northwest dragons": "North West Dragons",
    "dragons": "North West Dragons",
    "northern cape": "Northern Cape Heat", "northern cape heat": "Northern Cape Heat", "heat": "Northern Cape Heat",
    "eastern province": "Eastern Cape Iinyathi", "eastern cape": "Eastern Cape Iinyathi",
    "eastern cape iinyathi": "Eastern Cape Iinyathi", "eastern province iinyathi": "Eastern Cape Iinyathi",
    "easterns": "WSB Eastern Storm", "eastern storm": "WSB Eastern Storm", "wsb eastern storm": "WSB Eastern Storm",
    "limpopo impalas": "Wenbro Impalas", "impalas": "Wenbro Impalas", "wenbro impalas": "Wenbro Impalas",
    "kzn inland": "Tuskers", "tuskers": "Tuskers", "kwazulu natal inland": "Tuskers",
    "rhinos": "Mpumalanga Rhinos", "mpumalanga rhinos": "Mpumalanga Rhinos",
    "south western districts": "Garden Route Badgers", "south western district": "Garden Route Badgers",
    "garden route badgers": "Garden Route Badgers", "badgers": "Garden Route Badgers",
    "csa emerging": "CSA High Performance", "south africa emerging": "CSA High Performance",
    "csa high performance": "CSA High Performance",
}

def canonical_pro20_team(name):
    text = " ".join(str(name or "").strip().lower().replace("&", "and").split())
    return PRO20_ALIAS_RULES.get(text, str(name or "").strip())

def build_pro20_database(database_path, archive_paths):
    temporary_path = database_path.with_suffix(".tmp")
    if temporary_path.exists(): temporary_path.unlink()
    connection = sqlite3.connect(str(temporary_path), timeout=180)
    seen_match_ids = set()
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("CREATE TABLE matches(match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT)")
        connection.execute("CREATE TABLE deliveries(id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, innings_no INTEGER, batting_team TEXT, bowling_team TEXT, over_no INTEGER, ball_no TEXT, ball_pos INTEGER, runs INTEGER, wickets INTEGER, league TEXT)")
        match_rows, delivery_rows = [], []
        usable_matches = 0
        json_files_seen = 0
        for archive_path in archive_paths:
            with zipfile.ZipFile(archive_path) as source_zip:
                for filename in source_zip.namelist():
                    if not filename.lower().endswith(".json"): continue
                    json_files_seen += 1
                    try:
                        data = json.loads(source_zip.read(filename))
                        info = data.get("info", {}) or {}
                        if str(info.get("match_type", "")).strip().upper() != "T20": continue
                        raw_teams = info.get("teams", []) or []
                        if len(raw_teams) < 2: continue
                        teams = [canonical_pro20_team(x) for x in raw_teams]
                        if len(set(teams)) < 2 or not all(x in PRO20_TEAMS for x in teams): continue
                        match_id = Path(filename).stem
                        if match_id in seen_match_ids: continue
                        seen_match_ids.add(match_id)
                        outcome = info.get("outcome", {}) or {}
                        winner = canonical_pro20_team(outcome.get("winner", "") or outcome.get("eliminator", "") or "")
                        match_rows.append((match_id, str(info.get("venue", "") or ""), winner, PRO20))
                        usable_matches += 1
                        for innings_no, innings in enumerate(data.get("innings", []) or [], start=1):
                            if innings.get("super_over"): continue
                            batting_team = canonical_pro20_team(innings.get("team", ""))
                            if batting_team not in PRO20_TEAMS: continue
                            bowling_team = next((team for team in teams if team != batting_team), "")
                            if bowling_team not in PRO20_TEAMS: continue
                            for over_data in innings.get("overs", []) or []:
                                over_no = int(over_data.get("over", 0) or 0)
                                for delivery_index, delivery in enumerate(over_data.get("deliveries", []) or [], start=1):
                                    actual_delivery = delivery.get("actual_delivery")
                                    ball_text = str(actual_delivery) if actual_delivery else f"{over_no}.{delivery_index}"
                                    ball_pos = parse_ball(ball_text)
                                    if ball_pos is None: continue
                                    runs = int((delivery.get("runs") or {}).get("total", 0) or 0)
                                    wickets = len(delivery.get("wickets") or [])
                                    delivery_rows.append((match_id, innings_no, batting_team, bowling_team, over_no, ball_text, ball_pos, runs, wickets, PRO20))
                        if len(match_rows) >= 200:
                            connection.executemany("INSERT OR REPLACE INTO matches(match_id,venue,winner,league) VALUES(?,?,?,?)", match_rows); match_rows.clear()
                        if len(delivery_rows) >= 10000:
                            connection.executemany("INSERT INTO deliveries(match_id,innings_no,batting_team,bowling_team,over_no,ball_no,ball_pos,runs,wickets,league) VALUES(?,?,?,?,?,?,?,?,?,?)", delivery_rows); delivery_rows.clear()
                    except Exception:
                        continue
        if match_rows:
            connection.executemany("INSERT OR REPLACE INTO matches(match_id,venue,winner,league) VALUES(?,?,?,?)", match_rows)
        if delivery_rows:
            connection.executemany("INSERT INTO deliveries(match_id,innings_no,batting_team,bowling_team,over_no,ball_no,ball_pos,runs,wickets,league) VALUES(?,?,?,?,?,?,?,?,?,?)", delivery_rows)
        create_indexes(connection)
        connection.commit()
        delivery_count = connection.execute("SELECT COUNT(*) FROM deliveries WHERE league=?", (PRO20,)).fetchone()[0]
        if json_files_seen == 0 or usable_matches == 0 or int(delivery_count) == 0:
            raise RuntimeError("CSA Pro20 build me koi usable South African domestic T20 match nahi mila.")
    finally:
        connection.close()
    temporary_path.replace(database_path)

def ensure_pro20_database():
    database_path = PRO20_DB
    if database_is_valid(database_path, PRO20):
        # Existing DB is retained for 24h; this prevents a temporary remote
        # archive failure from breaking a previously working deployment.
        import time
        if time.time() - database_path.stat().st_mtime < PRO20_REFRESH_HOURS * 3600:
            migrate_database(database_path)
            return database_path
    building_path = database_path.with_suffix(".building")
    if building_path.exists(): building_path.unlink()
    try:
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_paths = []
            for index, url in enumerate(PRO20_ARCHIVE_URLS, start=1):
                archive_path = Path(temp_directory) / f"pro20_source_{index}.zip"
                download_archive(url, archive_path)
                archive_paths.append(archive_path)
            build_pro20_database(building_path, archive_paths)
        if not database_is_valid(building_path, PRO20):
            raise RuntimeError("CSA Pro20 database build completed but validation failed.")
        building_path.replace(database_path)
        return database_path
    except Exception:
        if building_path.exists(): building_path.unlink()
        if database_is_valid(database_path, PRO20): return database_path
        raise

def download_archive(url, destination):
    """Download a Cricsheet archive with validation and a browser-like UA."""
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
        # Keep the error short; do not attempt to feed HTML into ZipFile.
        try:
            preview = destination.read_bytes()[:200].decode("utf-8", errors="ignore")
        except Exception:
            preview = ""

        raise RuntimeError(
            "Cricsheet download was not a valid ZIP archive. "
            f"Server response preview: {preview[:120]!r}"
        )


def ensure_database(league):
    if league == PRO20:
        return ensure_pro20_database()

    database_path = DATABASES[league]

    # Existing valid DB: keep it exactly as-is.
    if database_is_valid(database_path, league):
        migrate_database(database_path)
        return database_path

    # Existing but empty/corrupt/partial DB: rebuild it.
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
            archive_path = Path(temp_directory) / "matches.zip"
            download_archive(DOWNLOAD_URLS[league], archive_path)

            build_database(
                building_path,
                league,
                archive_path,
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
        SELECT DISTINCT venue
        FROM matches
        WHERE league=?
        AND TRIM(COALESCE(venue,''))<>''
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
        WHERE match_id=?
        AND innings_no=?
        AND ball_pos<=?
        """,
        (match_id, innings_no, end_ball),
    ).fetchone()

    return int(row["total_runs"] or 0), int(row["total_wickets"] or 0)


def final_score(connection, match_id, innings_no):
    row = connection.execute(
        """
        SELECT COALESCE(SUM(runs), 0) AS final_runs
        FROM deliveries
        WHERE match_id=?
        AND innings_no=?
        """,
        (match_id, innings_no),
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
    return str(row["winner"] or "").strip() if row else ""


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
    ground="",
):
    """Find comparable historical live states.

    Ground is a similarity feature rather than a hard filter, so the model
    can fall back to wider historical evidence when the selected venue has
    too few comparable states.
    """
    low_ball = max(0, int(current_ball) - 2)
    high_ball = min(int(end_ball), int(current_ball) + 2)

    def fetch_candidates(mode):
        where_sql = """
            d.league=?
            AND d.innings_no=?
            AND d.ball_pos BETWEEN ? AND ?
        """
        params = [league, innings_no, low_ball, high_ball]

        if mode == "both":
            where_sql += """
                AND d.batting_team=?
                AND d.bowling_team=?
            """
            params.extend([batting_team, bowling_team])
        elif mode == "batting":
            where_sql += " AND d.batting_team=?"
            params.append(batting_team)

        query = f"""
            SELECT
                d.match_id,
                d.innings_no,
                d.ball_pos,
                d.batting_team,
                d.bowling_team,
                COALESCE(m.venue, '') AS venue
            FROM deliveries d
            LEFT JOIN matches m
                ON m.match_id=d.match_id
                AND m.league=d.league
            WHERE {where_sql}
            GROUP BY
                d.match_id,
                d.innings_no,
                d.ball_pos,
                d.batting_team,
                d.bowling_team,
                m.venue
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
    current_rr = (
        float(current_runs) / current_overs
        if current_overs > 0
        else 0.0
    )

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

        # Context-rich distance: ball, score, wickets, run rate, teams and venue.
        distance = (
            run_gap
            + (wicket_gap * 8)
            + (ball_gap * 2)
            + (rr_gap * 2.5)
            + team_gap
            + (0 if ground_match else 15)
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
# INDEPENDENT HISTORICAL AVERAGE
# ============================================================

def calculate_historical_average(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    batting_team,
    bowling_team,
    ground,
):
    """Calculate historical score independently of the live session line."""
    end_ball = int(session_over) * 6

    if int(current_ball) >= end_ball:
        return {
            "average": float(current_runs),
            "low": int(current_runs),
            "high": int(current_runs),
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
        ground,
    )

    if not states:
        return {
            "average": float(current_runs),
            "low": int(current_runs),
            "high": int(current_runs),
            "samples": 0,
        }

    values = []
    weights = []

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

        # Never let a historical result fall below the current live score.
        session_score = max(int(current_runs), int(session_score))
        weight = 1.0 / (1.0 + float(state["distance"]))

        values.append(session_score)
        weights.append(weight)

    if not values or sum(weights) <= 0:
        return {
            "average": float(current_runs),
            "low": int(current_runs),
            "high": int(current_runs),
            "samples": 0,
        }

    total_weight = sum(weights)
    weighted_average = sum(v * w for v, w in zip(values, weights)) / total_weight

    # Weighted 25th/75th percentile range, with a small fallback when needed.
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

    low = max(int(current_runs), int(q25))
    high = max(low, int(q75))

    return {
        "average": float(weighted_average),
        "low": low,
        "high": high,
        "samples": len(values),
    }


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
    ground="",
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
        ground,
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

        weight = 1.0 / (1.0 + float(state["distance"]))
        scores.append(int(session_score))
        weights.append(float(weight))

        historical_winner = match_winner(connection, state["match_id"])

        if int(innings_no) == 1:
            win_results.append(
                1 if historical_winner == batting_team else 0
            )
        elif int(innings_no) == 2 and int(target) > 0:
            historical_final = final_score(
                connection,
                state["match_id"],
                state["innings_no"],
            )
            win_results.append(
                1 if historical_final >= int(target) else 0
            )

    total_weight = sum(weights)

    expected = (
        sum(score * weight for score, weight in zip(scores, weights)) / total_weight
        if total_weight > 0
        else float(current_runs)
    )

    # Keep the existing session-line output behavior: a one-run interval around
    # the model's expected result. The independent historical range is shown
    # separately and does not use the session/bookie line.
    low = max(int(current_runs), int(round(expected)))
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

    if win_results and len(win_results) == len(weights) and total_weight > 0:
        win_probability = (
            sum(result * weight for result, weight in zip(win_results, weights))
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
    ground="",
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
        ground,
    )

    if not states:
        return {"yes": 0.0, "no": 100.0, "samples": 0}

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

        weight = 1.0 / (1.0 + float(state["distance"]))
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
    "historical_average": 0.0,
    "historical_low": 0,
    "historical_high": 0,
    "historical_samples": 0,
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
        connection = get_connection(str(database_path.resolve()))
    except Exception as error:
        st.error("Database start nahi ho saka.")
        st.exception(error)
        st.stop()

    if league == PRO20:
        teams = list(PRO20_TEAMS)
    else:
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

    bowling_options = [team for team in teams if team != batting_team]
    if not bowling_options:
        bowling_options = ["Unknown"]

    bowling_team = st.selectbox(
        "Bowling Team",
        bowling_options,
        key="bowling_team_select",
    )

    grounds = get_grounds(connection, league)
    if grounds:
        ground = st.selectbox(
            "Ground / Venue",
            grounds,
            key="ground_select",
        )
    else:
        ground = ""
        st.info("Ground data available nahi hai.")

    innings_label = st.selectbox(
        "Innings",
        ["1st Innings", "2nd Innings"],
        key="innings_select",
    )

    innings_no = 1 if innings_label == "1st Innings" else 2

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

    # Start position is only the initial state. Once live buttons are used,
    # the canonical state is st.session_state.runs/wickets/balls.
    over_points = ["0.0"]
    for over in range(20):
        for ball in range(1, 7):
            over_points.append(f"{over}.{ball}")
    over_points.append("20.0")

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

    # Sidebar and main-page live state always read the same canonical state.
    st.markdown("---")
    st.subheader("Current Live State")
    st.metric(
        "Score",
        f"{int(st.session_state.runs)}/{int(st.session_state.wickets)}",
    )
    st.metric(
        "Over / Ball",
        display_over(st.session_state.balls),
    )
    st.caption(
        f"Target Over: {int(st.session_state.session_over)} • "
        "Updates after every ball/event"
    )


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
        ground=ground,
    )

    historical_model = calculate_historical_average(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=balls,
        current_runs=runs,
        current_wickets=wickets,
        session_over=int(session_over),
        batting_team=batting_team,
        bowling_team=bowling_team,
        ground=ground,
    )

except Exception as error:
    st.error("Model calculation failed.")
    st.exception(error)
    st.stop()


# Session DNA auto output follows current live state every rerun/ball.
if not st.session_state.manual_mode:
    st.session_state.session_low = int(auto_model["low"])
    st.session_state.session_high = int(auto_model["high"])
    st.session_state.expected_score = float(auto_model["expected"])
    st.session_state.win_probability = auto_model["win_probability"]

st.session_state.historical_average = float(historical_model["average"])
st.session_state.historical_low = int(historical_model["low"])
st.session_state.historical_high = int(historical_model["high"])
st.session_state.historical_samples = int(historical_model["samples"])


# ============================================================
# TOP SCORE + SESSION MODE
# ============================================================

score_column, mode_column = st.columns([8, 2], gap="small")

with score_column:
    st.html(
        f"""
        <div class="card">
            <h2 style="margin:0">
                {batting_team} {runs}/{wickets}
            </h2>
            <p class="small" style="margin:5px 0 0">
                {display_over(balls)} ov
                • Session End: {session_over} ov
                • Target: {target if target > 0 else "Not set"}
                • Ground: {ground or "—"}
                • Last: {st.session_state.last or "—"}
            </p>
        </div>
        """
    )

with mode_column:
    selected_mode = st.radio(
        "Mode",
        ["AUTO", "MANUAL"],
        index=1 if st.session_state.manual_mode else 0,
        horizontal=True,
        key="session_mode_radio",
    )
    st.session_state.manual_mode = selected_mode == "MANUAL"


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

action_columns = st.columns(len(actions), gap="small")

for index, (label, add_runs, add_wicket, legal_ball) in enumerate(actions):
    with action_columns[index]:
        if st.button(
            label,
            use_container_width=True,
            key=f"live_action_button_{index}",
        ):
            if label == "Undo":
                if st.session_state.undo_stack:
                    old_state = st.session_state.undo_stack.pop()
                    st.session_state.runs = old_state["runs"]
                    st.session_state.wickets = old_state["wickets"]
                    st.session_state.balls = old_state["balls"]
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

                st.session_state.runs = runs + int(add_runs)
                st.session_state.wickets = min(10, wickets + int(add_wicket))

                if legal_ball:
                    st.session_state.balls = balls + 1

                st.session_state.last = label

            st.rerun()


# ============================================================
# SESSION + WINNING + HISTORICAL SUMMARY
# ============================================================

session_column, historical_column, winning_column = st.columns(
    3,
    gap="small",
)

with session_column:
    st.html(
        f"""
        <div class="session-box">
            <h3 style="margin:0">Session DNA</h3>
            <h1 style="margin:8px 0">
                {int(st.session_state.session_low)}
                -
                {int(st.session_state.session_high)}
            </h1>
            <p class="small">
                Expected: {float(st.session_state.expected_score):.1f}
                • End: {session_over} ov
            </p>
            <p class="small">
                Current Line is separate from historical memory.
            </p>
        </div>
        """
    )

with historical_column:
    st.html(
        f"""
        <div class="historical-box">
            <h3 style="margin:0">Historical Situation</h3>
            <h1 style="margin:8px 0">
                {float(st.session_state.historical_average):.1f}
            </h1>
            <p class="small">
                Historical Avg Score
            </p>
            <p class="small">
                Range: <b>
                {int(st.session_state.historical_low)}
                -
                {int(st.session_state.historical_high)}
                </b>
            </p>
            <p class="small">
                Comparable samples: {int(st.session_state.historical_samples)}
            </p>
        </div>
        """
    )

with winning_column:
    probability = st.session_state.win_probability
    probability_text = f"{float(probability):.1f}%" if probability is not None else "—"

    st.html(
        f"""
        <div class="winning-box">
            <h3 style="margin:0">
                {batting_team} Win
            </h3>
            <h1 style="margin:8px 0">
                {probability_text}
            </h1>
            <p class="small">
                Current live situation + historical context
            </p>
        </div>
        """
    )


# ============================================================
# MANUAL SESSION CONTROLS
# ============================================================

manual_low_column, manual_high_column = st.columns(2, gap="small")

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

manual_button, auto_button = st.columns(2, gap="small")

with manual_button:
    if st.button(
        "Apply Manual Session",
        use_container_width=True,
        key="apply_manual_session_button",
    ):
        st.session_state.manual_mode = True
        st.session_state.session_low = int(manual_low)
        st.session_state.session_high = max(int(manual_low) + 1, int(manual_high))
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
            line_high=int(st.session_state.session_high),
            ground=ground,
        )

        session_yes = float(manual_result["yes"])
        session_no = float(manual_result["no"])
        session_samples = int(manual_result["samples"])

    except Exception as error:
        st.error("Manual session calculation failed.")
        st.exception(error)
        session_yes = 0.0
        session_no = 100.0
        session_samples = 0

else:
    session_yes = float(auto_model["session_yes"])
    session_no = float(auto_model["session_no"])
    session_samples = int(auto_model["samples"])


result_label = "YES" if session_yes >= session_no else "NO"
result_class = "yes" if result_label == "YES" else "no"
result_percent = max(session_yes, session_no)

st.subheader("VasuDev Result")

st.html(
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
            Historical Avg:
            <b>{float(st.session_state.historical_average):.1f}</b>
            • Historical Range:
            <b>
                {int(st.session_state.historical_low)}-
                {int(st.session_state.historical_high)}
            </b>
        </p>
        <p style="margin:5px 0 0">
            Similar Matches: <b>{session_samples}</b>
        </p>
    </div>
    """
)


# ============================================================
# TEAM WINNING RESULT
# ============================================================

final_win_probability = st.session_state.win_probability

if final_win_probability is not None:
    batting_win = float(final_win_probability)
    bowling_win = 100.0 - batting_win

    if batting_win >= bowling_win:
        winner_name = batting_team
        winner_percent = batting_win
        winner_class = "yes"
    else:
        winner_name = bowling_team
        winner_percent = bowling_win
        winner_class = "no"

    st.html(
        f"""
        <div class="{winner_class}">
            <h1 style="margin:0">
                {winner_name.upper()}
                WIN — {winner_percent:.1f}%
            </h1>
            <p style="margin:8px 0 0">
                {batting_team}: <b>{batting_win:.1f}%</b>
                •
                {bowling_team}: <b>{bowling_win:.1f}%</b>
            </p>
            <p style="margin:5px 0 0">
                {("Historical winner estimate" if innings_no == 1 else f"Target: {target}")}
            </p>
        </div>
        """
    )

else:
    if innings_no == 2 and int(target) <= 0:
        st.info("2nd innings winning probability ke liye Target Runs set karein.")
    else:
        st.info("Winning estimate ke liye sufficient historical result data nahi mila.")


# ============================================================
# DETAILS
# ============================================================

with st.expander("Match & Analysis Details", expanded=False):
    st.write(f"**League:** {league}")
    st.write(
        f"**Current Situation:** {batting_team} {runs}/{wickets} "
        f"at {display_over(balls)} overs"
    )
    st.write(f"**Innings:** {innings_label}")
    st.write(f"**Ground / Venue:** {ground or '—'}")
    st.write(f"**Session End:** {session_over} overs")
    st.write(
        f"**Session Line:** {int(st.session_state.session_low)} - "
        f"{int(st.session_state.session_high)}"
    )
    st.write(
        f"**Expected Session Score:** "
        f"{float(st.session_state.expected_score):.1f}"
    )
    st.write(
        f"**Historical Situation Average:** "
        f"{float(st.session_state.historical_average):.1f}"
    )
    st.write(
        f"**Historical Situation Range:** "
        f"{int(st.session_state.historical_low)} - "
        f"{int(st.session_state.historical_high)}"
    )
    st.write(
        f"**Historical Comparable Samples:** "
        f"{int(st.session_state.historical_samples)}"
    )
    st.write(f"**Session YES:** {session_yes:.1f}%")
    st.write(f"**Session NO:** {session_no:.1f}%")
    st.write(f"**Similar Historical Matches:** {session_samples}")

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
        st.write(f"**Target:** {int(target)}")

    st.write(
        "**Similarity Context:** Over/Ball + Runs + Wickets + Run Rate + "
        "Batting Team + Bowling Team + Ground + Innings"
    )


st.caption(
    "Historical estimate only. This is not a guarantee of the live match result."
)
