# VasuDev Cricket AI - "FINEST" app.py
#
# Everything from the previous fixed version, PLUS:
#
#   1. PLAYER-LEVEL FORM (new): tracks each ball's batter/bowler and the
#      batter actually dismissed, so a specific striker's Strike Rate /
#      Average and a specific bowler's Economy (within this league's
#      dataset) can be computed and blended into the projection as a
#      bounded, confidence-scaled nudge - never overriding the historical
#      team-level model, only adjusting it.
#      LIMITATIONS (being upfront): bowler economy counts all runs
#      conceded off that ball, including extras, which is standard but
#      slightly generous to spinners bowled with fewer wides; "wickets"
#      counts any dismissal on that bowler's delivery, which very rarely
#      over-counts run-outs (Cricsheet's dismissal *type* isn't stored
#      here). Good enough for a form signal, not a scorecard.
#   2. PHASE-SPECIFIC MODELING (new): Powerplay (overs 1-6), Middle
#      (7-15) and Death (16-20) each get their own historical par run
#      rate for this league/innings, used to shape the score trajectory
#      realistically instead of a flat straight-line projection.
#   3. SCORE TRAJECTORY CHART (new): an over-by-over line chart showing
#      where your match is projected to land vs the league's average
#      scoring pace, built from the phase par rates above and anchored
#      to the model's actual projected total (not just a rough sketch).
#   4. Everything from the previous fix stays: window-scoped Score
#      Target Analysis (never mixed with full-innings numbers), toss as
#      a similarity factor, neutral terminology (no "cross/stay-under"
#      betting-style wording), auto-recalculation on every ball, Current
#      Run Rate / Required Run Rate / Momentum, Head-to-Head record,
#      and generic support for all 4 leagues (IPL, BBL, WBBL, CSA Pro
#      T20 Cup).
#
# NOTE ON DATABASE REBUILD: this version adds new columns (batter,
# bowler, batter_runs, player_out) to the deliveries table. Any database
# built by an earlier version of this app will fail validation and be
# automatically rebuilt (re-downloaded from Cricsheet) ONE TIME the next
# time each league is opened. This is expected and by design - no action
# needed.

import hmac
import json
import os
import re
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd
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
# SMALL FORMAT HELPER
# ============================================================

def fmt_int(value):
    """Thousands-separated integer for display, e.g. 1550 -> '1,550'."""
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


# ============================================================
# SESSION PERSISTENCE (refresh should NOT log out or lose progress)
# ============================================================

SESSION_STATE_FILE = Path(".vasudev_session_state.json")

PERSISTED_KEYS = [
    "authenticated",
    "runs", "wickets", "balls", "last", "undo_stack", "target",
    "win_probability", "win_probability_raw", "win_samples",
    "full_historical_average", "full_historical_average_raw",
    "full_historical_low", "full_historical_high", "full_historical_samples",
    "projection_end_over", "score_prediction",
    "window_historical_average", "window_historical_average_raw",
    "window_historical_low", "window_historical_high",
    "window_historical_samples",
    "window_cross_chance", "window_stay_chance", "window_samples",
    "persisted_league",
    "persisted_batting_team",
    "persisted_bowling_team",
    "persisted_ground",
    "persisted_innings_label",
    "persisted_toss_winner",
    "persisted_toss_decision",
    "persisted_striker",
    "persisted_current_bowler",
]


def load_persisted_session():
    try:
        if SESSION_STATE_FILE.exists():
            data = json.loads(SESSION_STATE_FILE.read_text())
            for key, value in data.items():
                st.session_state.setdefault(key, value)
    except Exception:
        pass


def save_persisted_session():
    try:
        snapshot = {
            key: st.session_state[key]
            for key in PERSISTED_KEYS
            if key in st.session_state
        }
        SESSION_STATE_FILE.write_text(json.dumps(snapshot))
    except Exception:
        pass


def clear_persisted_session():
    try:
        if SESSION_STATE_FILE.exists():
            SESSION_STATE_FILE.unlink()
    except Exception:
        pass


if "authenticated" not in st.session_state:
    load_persisted_session()


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
            save_persisted_session()
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()


# ============================================================
# DATABASE SETTINGS
# ============================================================

BASE = Path(".")

CSA_PRO_T20_TEAMS = [
    "Eastern Storm",
    "South Africa Emerging",
    "Titans",
    "Dolphins",
    "Warriors",
    "Lions",
    "Knights",
    "Western Province",
    "Northern Cape Heat",
    "Mpumalanga Rhinos",
    "Tuskers",
    "Eastern Cape Iinyathi",
    "Limpopo Impalas",
    "North West Dragons",
    "Rocks",
    "Garden Route Badgers",
]


def team_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip())
    return slug.strip("_")


DATABASES = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db",
    "CSA Pro T20 Cup": BASE / "csa_pro_t20_history.db",
}

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
    "CSA Pro T20 Cup": [
        f"https://cricsheet.org/downloads/{team_slug(team)}_male_json.zip"
        for team in CSA_PRO_T20_TEAMS
    ],
}

RESTRICT_TEAMS = {
    "CSA Pro T20 Cup": {team.strip().lower() for team in CSA_PRO_T20_TEAMS},
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

    NOTE: toss_winner/toss_decision (matches) and batter/bowler/
    batter_runs/player_out (deliveries) were added in this version. Any
    database built before this fix is treated as invalid ONCE, which
    automatically triggers a clean rebuild - no manual migration needed.
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
            "ball_pos", "runs", "wickets", "league",
            "batter", "bowler", "batter_runs", "player_out",
        }
        required_match = {
            "match_id", "venue", "winner", "league", "season",
            "toss_winner", "toss_decision",
        }

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
        CREATE INDEX IF NOT EXISTS idx_deliveries_batter
        ON deliveries(league, batter)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_deliveries_bowler
        ON deliveries(league, bowler)
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

def build_database(database_path, league, archive_paths, restrict_teams=None):
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
                league TEXT,
                season INTEGER,
                toss_winner TEXT,
                toss_decision TEXT
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
                league TEXT,
                batter TEXT,
                bowler TEXT,
                batter_runs INTEGER,
                player_out TEXT
            )
            """
        )

        match_rows = []
        delivery_rows = []
        json_files_seen = 0
        seen_match_ids = set()

        for archive_path in archive_paths:
            with zipfile.ZipFile(archive_path) as source_zip:
                for filename in source_zip.namelist():
                    if not filename.lower().endswith(".json"):
                        continue

                    match_id = Path(filename).stem

                    if match_id in seen_match_ids:
                        continue

                    json_files_seen += 1

                    try:
                        data = json.loads(source_zip.read(filename))
                        info = data.get("info", {}) or {}
                        teams = info.get("teams", []) or []

                        if len(teams) < 2:
                            continue

                        if restrict_teams is not None:
                            team_names_lower = {
                                str(t).strip().lower() for t in teams
                            }
                            if not team_names_lower.issubset(restrict_teams):
                                continue

                        seen_match_ids.add(match_id)

                        outcome = info.get("outcome", {}) or {}
                        winner = str(
                            outcome.get("winner", "")
                            or outcome.get("eliminator", "")
                            or ""
                        )

                        venue = str(info.get("venue", "") or "")

                        toss_info = info.get("toss", {}) or {}
                        toss_winner = str(toss_info.get("winner", "") or "")
                        toss_decision = str(
                            toss_info.get("decision", "") or ""
                        ).strip().lower()

                        season_year = None
                        season_field = str(info.get("season", "") or "")
                        digits = "".join(ch for ch in season_field if ch.isdigit())
                        if len(digits) >= 4:
                            try:
                                season_year = int(digits[:4])
                            except ValueError:
                                season_year = None

                        if season_year is None:
                            match_dates = info.get("dates") or []
                            if match_dates:
                                try:
                                    season_year = int(str(match_dates[0])[:4])
                                except (ValueError, TypeError):
                                    season_year = None

                        match_rows.append(
                            (
                                match_id, venue, winner, league, season_year,
                                toss_winner, toss_decision,
                            )
                        )

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

                                    runs_block = delivery.get("runs") or {}
                                    runs = int(runs_block.get("total", 0) or 0)
                                    batter_runs = int(runs_block.get("batter", 0) or 0)
                                    wickets_list = delivery.get("wickets") or []
                                    wickets = len(wickets_list)

                                    batter_name = str(delivery.get("batter", "") or "")
                                    bowler_name = str(delivery.get("bowler", "") or "")
                                    player_out = (
                                        str(wickets_list[0].get("player_out", "") or "")
                                        if wickets_list
                                        else ""
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
                                            batter_name,
                                            bowler_name,
                                            batter_runs,
                                            player_out,
                                        )
                                    )

                        if len(match_rows) >= 200:
                            connection.executemany(
                                """
                                INSERT OR REPLACE INTO matches(
                                    match_id, venue, winner, league, season,
                                    toss_winner, toss_decision
                                ) VALUES(?,?,?,?,?,?,?)
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
                                    ball_pos, runs, wickets, league,
                                    batter, bowler, batter_runs, player_out
                                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    match_id, venue, winner, league, season,
                    toss_winner, toss_decision
                ) VALUES(?,?,?,?,?,?,?)
                """,
                match_rows,
            )

        if delivery_rows:
            connection.executemany(
                """
                INSERT INTO deliveries(
                    match_id, innings_no, batting_team,
                    bowling_team, over_no, ball_no,
                    ball_pos, runs, wickets, league,
                    batter, bowler, batter_runs, player_out
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                delivery_rows,
            )

        create_indexes(connection)
        connection.commit()

        if json_files_seen == 0:
            raise RuntimeError(
                f"No usable JSON match files found for {league}."
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
                f"{league} archive(s) downloaded but no usable match data was built."
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
            preview = destination.read_bytes()[:200].decode("utf-8", errors="ignore")
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
    urls = DOWNLOAD_URLS[league]
    is_merge_league = isinstance(urls, (list, tuple))
    url_list = list(urls) if is_merge_league else [urls]
    restrict_teams = RESTRICT_TEAMS.get(league)

    try:
        if building_path.exists():
            building_path.unlink()

        with tempfile.TemporaryDirectory() as temp_directory:
            archive_paths = []
            failed_sources = []

            for index, url in enumerate(url_list):
                archive_path = Path(temp_directory) / f"matches_{index}.zip"
                try:
                    download_archive(url, archive_path)
                    archive_paths.append(archive_path)
                except Exception as download_error:
                    failed_sources.append((url, str(download_error)))
                    continue

            if not archive_paths:
                raise RuntimeError(
                    f"Could not download any source archive for {league}. "
                    f"Failures: {failed_sources}"
                )

            build_database(
                building_path,
                league,
                archive_paths,
                restrict_teams=restrict_teams,
            )

            if is_merge_league and failed_sources:
                st.session_state.setdefault("league_build_warnings", {})
                st.session_state["league_build_warnings"][league] = [
                    url for url, _ in failed_sources
                ]

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
# DATABASE QUERIES - TEAM / MATCH LEVEL
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


def get_latest_season(connection, league):
    row = connection.execute(
        "SELECT MAX(season) FROM matches WHERE league=? AND season IS NOT NULL",
        (league,),
    ).fetchone()
    value = row[0] if row else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_current_teams(connection, league):
    latest_season = get_latest_season(connection, league)

    def teams_for_seasons(seasons):
        placeholders = ",".join("?" for _ in seasons)
        rows = connection.execute(
            f"""
            SELECT DISTINCT d.batting_team
            FROM deliveries d
            JOIN matches m ON m.match_id=d.match_id AND m.league=d.league
            WHERE d.league=?
            AND d.batting_team<>''
            AND m.season IN ({placeholders})
            ORDER BY d.batting_team
            """,
            [league, *seasons],
        ).fetchall()
        return [str(row[0]).strip() for row in rows if row[0]]

    if latest_season is not None:
        teams = teams_for_seasons([latest_season])

        if len(teams) < 6:
            teams = sorted(
                set(teams_for_seasons([latest_season, latest_season - 1]))
            )

        if teams:
            return teams

    return get_values(
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


def get_head_to_head(connection, league, team_a, team_b):
    """All-time head-to-head record between two teams in this league,
    based on 1st-innings batting/bowling pairing (each match counted once)."""
    rows = connection.execute(
        """
        SELECT DISTINCT d.match_id, m.winner
        FROM deliveries d
        JOIN matches m ON m.match_id=d.match_id AND m.league=d.league
        WHERE d.league=?
        AND d.innings_no=1
        AND (
            (d.batting_team=? AND d.bowling_team=?)
            OR (d.batting_team=? AND d.bowling_team=?)
        )
        """,
        (league, team_a, team_b, team_b, team_a),
    ).fetchall()

    total = len(rows)
    a_wins = sum(1 for row in rows if str(row["winner"] or "").strip() == team_a)
    b_wins = sum(1 for row in rows if str(row["winner"] or "").strip() == team_b)

    return {"total": total, "a_wins": a_wins, "b_wins": b_wins}


def compute_recent_run_rate(undo_stack, current_runs, current_balls, window_balls=12):
    """Run rate over the last `window_balls` legal balls of THIS live match
    (default: last 2 overs), used as a momentum/form indicator. Returns None
    when there isn't yet enough recorded history since 'Set Current Match
    Situation' was last pressed (undo_stack only tracks from that point)."""
    if current_balls <= 0 or not undo_stack:
        return None

    target_ball = max(0, current_balls - window_balls)
    reference_runs = None
    reference_balls = None

    for state in reversed(undo_stack):
        if state["balls"] <= target_ball:
            reference_runs = state["runs"]
            reference_balls = state["balls"]
            break

    if reference_runs is None:
        return None

    balls_elapsed = current_balls - reference_balls
    if balls_elapsed <= 0:
        return None

    runs_scored = current_runs - reference_runs
    return (runs_scored / balls_elapsed) * 6.0


# ============================================================
# DATABASE QUERIES - PLAYER LEVEL (new)
# ============================================================

def get_team_roster(connection, league, team, role):
    """Distinct batter/bowler names for a team, preferring the most recent
    season(s) so an old, no-longer-playing name doesn't clutter the list."""
    if not team:
        return []

    column = "batter" if role == "batting" else "bowler"
    team_column = "batting_team" if role == "batting" else "bowling_team"
    latest_season = get_latest_season(connection, league)

    def names_for_seasons(seasons):
        placeholders = ",".join("?" for _ in seasons)
        rows = connection.execute(
            f"""
            SELECT DISTINCT d.{column}
            FROM deliveries d
            JOIN matches m ON m.match_id=d.match_id AND m.league=d.league
            WHERE d.league=? AND d.{team_column}=? AND d.{column}<>''
            AND m.season IN ({placeholders})
            ORDER BY d.{column}
            """,
            [league, team, *seasons],
        ).fetchall()
        return [str(row[0]).strip() for row in rows if row[0]]

    if latest_season is not None:
        names = names_for_seasons([latest_season])
        if len(names) < 3:
            names = sorted(set(names_for_seasons([latest_season, latest_season - 1])))
        if names:
            return names

    rows = connection.execute(
        f"""
        SELECT DISTINCT {column} FROM deliveries
        WHERE league=? AND {team_column}=? AND {column}<>''
        ORDER BY {column}
        """,
        (league, team),
    ).fetchall()
    return [str(row[0]).strip() for row in rows if row[0]]


def get_batter_stats(connection, league, batter_name):
    """Career (within this league's dataset) Strike Rate and Average for
    one named batter. Returns None if no data is found for that name."""
    if not batter_name:
        return None

    row = connection.execute(
        """
        SELECT
            COALESCE(SUM(batter_runs), 0) AS runs,
            COUNT(*) AS balls,
            SUM(CASE WHEN player_out=batter THEN 1 ELSE 0 END) AS dismissals,
            COUNT(DISTINCT match_id) AS matches
        FROM deliveries
        WHERE league=? AND batter=?
        """,
        (league, batter_name),
    ).fetchone()

    balls = int(row["balls"] or 0)
    if balls == 0:
        return None

    runs = int(row["runs"] or 0)
    dismissals = int(row["dismissals"] or 0)

    return {
        "runs": runs,
        "balls": balls,
        "dismissals": dismissals,
        "strike_rate": (runs / balls) * 100.0,
        "average": (runs / dismissals) if dismissals > 0 else None,
        "matches": int(row["matches"] or 0),
    }


def get_bowler_stats(connection, league, bowler_name):
    """Career (within this league's dataset) Economy for one named bowler.
    See the LIMITATIONS note at the top of this file about wickets/extras
    approximation. Returns None if no data is found for that name."""
    if not bowler_name:
        return None

    row = connection.execute(
        """
        SELECT
            COALESCE(SUM(runs), 0) AS runs_conceded,
            COUNT(*) AS balls,
            SUM(CASE WHEN player_out IS NOT NULL AND player_out<>'' THEN 1 ELSE 0 END) AS wickets,
            COUNT(DISTINCT match_id) AS matches
        FROM deliveries
        WHERE league=? AND bowler=?
        """,
        (league, bowler_name),
    ).fetchone()

    balls = int(row["balls"] or 0)
    if balls == 0:
        return None

    runs_conceded = int(row["runs_conceded"] or 0)

    return {
        "runs_conceded": runs_conceded,
        "balls": balls,
        "wickets": int(row["wickets"] or 0),
        "economy": (runs_conceded / balls) * 6.0,
        "matches": int(row["matches"] or 0),
    }


@st.cache_data(show_spinner=False)
def get_league_batting_benchmark(_connection, league):
    """League-wide average strike rate, used to normalize an individual
    batter's form. Cached since this is a full-table aggregate that only
    changes when the database is rebuilt, not every ball."""
    row = _connection.execute(
        "SELECT COALESCE(SUM(batter_runs),0) AS runs, COUNT(*) AS balls "
        "FROM deliveries WHERE league=?",
        (league,),
    ).fetchone()
    balls = int(row["balls"] or 0)
    if balls == 0:
        return 130.0
    return (int(row["runs"] or 0) / balls) * 100.0


@st.cache_data(show_spinner=False)
def get_league_bowling_benchmark(_connection, league):
    """League-wide average economy rate, used to normalize an individual
    bowler's form."""
    row = _connection.execute(
        "SELECT COALESCE(SUM(runs),0) AS runs, COUNT(*) AS balls "
        "FROM deliveries WHERE league=?",
        (league,),
    ).fetchone()
    balls = int(row["balls"] or 0)
    if balls == 0:
        return 8.0
    return (int(row["runs"] or 0) / balls) * 6.0


@st.cache_data(show_spinner=False)
def get_phase_par_rates(_connection, league, innings_no):
    """Historical average run rate (runs per over) for Powerplay
    (overs 1-6), Middle (7-15) and Death (16-20) overs, for this league
    and innings. Used to shape the score trajectory chart realistically."""
    rows = _connection.execute(
        """
        SELECT
            CASE WHEN over_no < 6 THEN 'powerplay'
                 WHEN over_no < 15 THEN 'middle'
                 ELSE 'death' END AS phase,
            SUM(runs) AS total_runs,
            COUNT(*) AS balls
        FROM deliveries
        WHERE league=? AND innings_no=?
        GROUP BY phase
        """,
        (league, innings_no),
    ).fetchall()

    rates = {"powerplay": 7.5, "middle": 7.8, "death": 9.5}
    for row in rows:
        balls = int(row["balls"] or 0)
        if balls > 0:
            rates[row["phase"]] = (int(row["total_runs"] or 0) / balls) * 6.0
    return rates


def phase_rate_for_over(phase_rates, over_index):
    if over_index < 6:
        return phase_rates["powerplay"]
    if over_index < 15:
        return phase_rates["middle"]
    return phase_rates["death"]


def build_match_trajectory(current_ball, current_runs, window_end_over, target_total, phase_rates):
    """Over-by-over cumulative projection from the CURRENT point to
    window_end_over, landing exactly at target_total (the model's real
    projected score), shaped by phase par rates so the climb looks like a
    real innings (slower in the middle overs, faster at the death) instead
    of a flat straight line."""
    start_over_point = round(current_ball / 6.0, 2)
    current_over_completed = current_ball // 6
    remaining_overs = list(range(int(current_over_completed) + 1, int(window_end_over) + 1))

    trajectory = {start_over_point: float(current_runs)}

    if not remaining_overs:
        return trajectory

    weights = [phase_rate_for_over(phase_rates, o - 1) for o in remaining_overs]
    total_weight = sum(weights) or 1.0
    remaining_runs = max(0.0, float(target_total) - float(current_runs))

    cumulative = float(current_runs)
    for over_index, weight in zip(remaining_overs, weights):
        cumulative += remaining_runs * (weight / total_weight)
        trajectory[float(over_index)] = cumulative

    return trajectory


def build_par_trajectory(window_end_over, phase_rates):
    """League-average pace, from ball 0, ignoring the current match -
    a comparison line for the chart ('how a typical innings scores here')."""
    trajectory = {0.0: 0.0}
    cumulative = 0.0
    for over_index in range(1, int(window_end_over) + 1):
        cumulative += phase_rate_for_over(phase_rates, over_index - 1)
        trajectory[float(over_index)] = cumulative
    return trajectory


def compute_player_adjustment(batter_stats, bowler_stats, league_batting_benchmark, league_bowling_benchmark):
    """Bounded, confidence-scaled nudge to the projection based on the
    selected striker's Strike Rate and/or bowler's Economy relative to the
    league average. Returns (adjustment_ratio, confidence):
      - adjustment_ratio multiplies the REMAINING (not-yet-scored) runs in
        a projection. 1.0 = no change.
      - confidence (0 to 1) reflects how much real data backs the factor;
        with very few balls faced/bowled, the ratio is pulled back toward
        1.0 so a tiny sample can't swing the whole projection.
    The ratio itself is hard-capped so even a huge, well-established
    sample can only move a projection by up to ~15% either way - this is
    a nudge on top of the historical team-level model, not a replacement
    for it.
    """
    batter_factor = 1.0
    bowler_factor = 1.0
    batter_confidence = 0.0
    bowler_confidence = 0.0

    if batter_stats and league_batting_benchmark > 0:
        batter_factor = batter_stats["strike_rate"] / league_batting_benchmark
        batter_confidence = min(1.0, batter_stats["balls"] / 60.0)

    if bowler_stats and league_bowling_benchmark > 0 and bowler_stats["economy"] > 0:
        bowler_factor = league_bowling_benchmark / bowler_stats["economy"]
        bowler_confidence = min(1.0, bowler_stats["balls"] / 60.0)

    combined_confidence = max(batter_confidence, bowler_confidence)

    batter_factor = max(0.75, min(1.35, batter_factor))
    bowler_factor = max(0.75, min(1.35, bowler_factor))

    raw_ratio = (batter_factor + bowler_factor) / 2.0
    adjustment_ratio = 1.0 + (raw_ratio - 1.0) * combined_confidence * 0.5
    adjustment_ratio = max(0.85, min(1.20, adjustment_ratio))

    return adjustment_ratio, combined_confidence


def apply_player_adjustment_to_average(current_runs, base_average, base_low, base_high, adjustment_ratio):
    """Shift an average/low/high triple by scaling the REMAINING (not
    already-scored) portion by adjustment_ratio, then sliding low/high by
    the same amount so the range keeps its original shape."""
    delta = float(base_average) - float(current_runs)
    adjusted_average = float(current_runs) + delta * adjustment_ratio
    shift = adjusted_average - float(base_average)

    adjusted_low = max(int(current_runs), int(round(base_low + shift)))
    adjusted_high = max(adjusted_low, int(round(base_high + shift)))

    return adjusted_average, adjusted_low, adjusted_high


# ============================================================
# RECENCY WEIGHTING (2026 form counts more than 2010 form)
# ============================================================

RECENCY_HALF_LIFE_YEARS = 6.0


def recency_weight(season, latest_season):
    try:
        season = int(season)
        latest_season = int(latest_season)
    except (TypeError, ValueError):
        return 1.0

    age = max(0, latest_season - season)
    return 0.5 ** (age / RECENCY_HALF_LIFE_YEARS)


# ============================================================
# HISTORICAL MATCH MATCHING (toss-aware)
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
    exclude_match_id="",
    current_toss_role=None,
    current_toss_decision=None,
):
    """Find comparable historical live states.

    current_toss_role: "batting" if the CURRENT batting team won the toss,
        "bowling" if the current bowling team won it, or None if unknown.
    current_toss_decision: "bat" or "field", or None if unknown. Both are
        soft similarity features (like ground), never hard filters.
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

        if exclude_match_id:
            where_sql += " AND d.match_id<>?"
            params.append(str(exclude_match_id).strip())

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
                COALESCE(m.venue, '') AS venue,
                m.season AS season,
                COALESCE(m.toss_winner, '') AS toss_winner,
                COALESCE(m.toss_decision, '') AS toss_decision
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
                m.venue,
                m.season,
                m.toss_winner,
                m.toss_decision
            LIMIT 30000
        """
        return connection.execute(query, params).fetchall()

    candidates = fetch_candidates("both")
    if len(candidates) < 40:
        candidates = fetch_candidates("batting")
    if len(candidates) < 40:
        candidates = fetch_candidates("all")

    latest_season = get_latest_season(connection, league)

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
        historical_batting = str(row["batting_team"] or "")
        historical_bowling = str(row["bowling_team"] or "")
        if historical_batting != batting_team:
            team_gap += 7
        if historical_bowling != bowling_team:
            team_gap += 4

        historical_toss_winner = str(row["toss_winner"] or "").strip()
        if historical_toss_winner and historical_toss_winner == historical_batting:
            historical_toss_role = "batting"
        elif historical_toss_winner and historical_toss_winner == historical_bowling:
            historical_toss_role = "bowling"
        else:
            historical_toss_role = None

        toss_role_gap = 0
        if current_toss_role is not None and historical_toss_role is not None:
            toss_role_gap = 0 if current_toss_role == historical_toss_role else 3

        historical_decision = str(row["toss_decision"] or "").strip().lower() or None
        toss_decision_gap = 0
        if current_toss_decision is not None and historical_decision is not None:
            toss_decision_gap = (
                0 if current_toss_decision == historical_decision else 2
            )

        distance = (
            run_gap
            + (wicket_gap * 8)
            + (ball_gap * 2)
            + (rr_gap * 2.5)
            + team_gap
            + (0 if ground_match else 15)
            + toss_role_gap
            + toss_decision_gap
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
            "recency_weight": recency_weight(row["season"], latest_season),
        }

        if key not in best_states or state["distance"] < best_states[key]["distance"]:
            best_states[key] = state

    states = list(best_states.values())
    states.sort(key=lambda item: item["distance"])
    return states[:2500]


# ============================================================
# PAR SCORE (BASE-RATE PRIOR)
# ============================================================

CONFIDENCE_SAMPLES = 40.0


def get_par_score(
    connection,
    league,
    innings_no,
    end_ball,
    ground="",
    exclude_match_id="",
):
    params = [league, innings_no, int(end_ball)]
    join_sql = "LEFT JOIN matches m ON m.match_id=d.match_id AND m.league=d.league"
    extra_where = ""

    if ground:
        extra_where += " AND m.venue=?"
        params.append(ground)

    if exclude_match_id:
        extra_where += " AND d.match_id<>?"
        params.append(str(exclude_match_id).strip())

    query = f"""
        SELECT d.match_id, m.season AS season, SUM(d.runs) AS inn_score
        FROM deliveries d
        {join_sql}
        WHERE d.league=?
        AND d.innings_no=?
        AND d.ball_pos<=?
        {extra_where}
        GROUP BY d.match_id, m.season
    """

    rows = connection.execute(query, params).fetchall()
    if not rows:
        return None

    latest_season = get_latest_season(connection, league)

    total_weight = 0.0
    weighted_sum = 0.0
    for row in rows:
        score = row["inn_score"]
        if score is None:
            continue
        weight = recency_weight(row["season"], latest_season)
        weighted_sum += float(score) * weight
        total_weight += weight

    if total_weight <= 0:
        return None

    return weighted_sum / total_weight


def blend_with_par(estimate, samples, par_score):
    if par_score is None:
        return float(estimate)

    confidence = min(1.0, float(samples) / CONFIDENCE_SAMPLES)
    return (confidence * float(estimate)) + ((1.0 - confidence) * float(par_score))


# ============================================================
# HISTORICAL AVERAGE FOR A GIVEN WINDOW (any end_over)
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
    exclude_match_id="",
    current_toss_role=None,
    current_toss_decision=None,
):
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
        exclude_match_id=exclude_match_id,
        current_toss_role=current_toss_role,
        current_toss_decision=current_toss_decision,
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

        session_score = max(int(current_runs), int(session_score))
        weight = (
            1.0 / (1.0 + float(state["distance"]))
        ) * float(state.get("recency_weight", 1.0))

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

    par_score = get_par_score(
        connection,
        league,
        innings_no,
        end_ball,
        ground=ground,
        exclude_match_id=exclude_match_id,
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

    return {
        "average": float(blended_average),
        "low": low,
        "high": high,
        "samples": len(values),
    }


# ============================================================
# FULL-MATCH MODEL (always 20 overs - used for the match-winner box)
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
    exclude_match_id="",
    current_toss_role=None,
    current_toss_decision=None,
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
        exclude_match_id=exclude_match_id,
        current_toss_role=current_toss_role,
        current_toss_decision=current_toss_decision,
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

        session_score = max(int(current_runs), int(session_score))

        weight = (1.0 / (1.0 + float(state["distance"]))) * float(state.get("recency_weight", 1.0))
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

    raw_expected = (
        sum(score * weight for score, weight in zip(scores, weights)) / total_weight
        if total_weight > 0
        else float(current_runs)
    )

    par_score = get_par_score(
        connection,
        league,
        innings_no,
        end_ball,
        ground=ground,
        exclude_match_id=exclude_match_id,
    )

    expected = blend_with_par(raw_expected, len(states), par_score)

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
    exclude_match_id="",
    current_toss_role=None,
    current_toss_decision=None,
):
    """Probability of reaching / falling short of a chosen score line, for
    matches at the SAME window (session_over). This stays a pure
    historical-frequency estimate (no player-form nudge applied here) to
    keep the probability statistically honest and easy to reason about;
    the player-form nudge is applied to the AVERAGE/RANGE displays instead."""
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
        exclude_match_id=exclude_match_id,
        current_toss_role=current_toss_role,
        current_toss_decision=current_toss_decision,
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

        weight = (1.0 / (1.0 + float(state["distance"]))) * float(state.get("recency_weight", 1.0))
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
    "target": 0,
    "win_probability": None,
    "win_probability_raw": None,
    "win_samples": 0,
    "full_historical_average": 0.0,
    "full_historical_average_raw": 0.0,
    "full_historical_low": 0,
    "full_historical_high": 0,
    "full_historical_samples": 0,
    "projection_end_over": 6,
    "score_prediction": 0,
    "window_historical_average": 0.0,
    "window_historical_average_raw": 0.0,
    "window_historical_low": 0,
    "window_historical_high": 0,
    "window_historical_samples": 0,
    "window_cross_chance": 0.0,
    "window_stay_chance": 100.0,
    "window_samples": 0,
}

for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("Match Setup")

    if st.button("Logout", use_container_width=True, key="logout_button"):
        clear_persisted_session()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    def restored_index(options, persisted_key):
        value = st.session_state.get(persisted_key)
        if value in options:
            return options.index(value)
        return 0

    league = st.selectbox(
        "League",
        LEAGUES,
        index=restored_index(LEAGUES, "persisted_league"),
        key="league_select",
    )
    st.session_state["persisted_league"] = league

    try:
        database_path = ensure_database(league)
        connection = get_connection(str(database_path.resolve()))
    except Exception as error:
        st.error("Database start nahi ho saka.")
        st.exception(error)
        st.stop()

    build_warnings = st.session_state.get("league_build_warnings", {}).get(league)
    if build_warnings:
        st.warning(
            f"{len(build_warnings)} team archive(s) could not be downloaded "
            "for this league (that team's own history may be missing)."
        )

    teams = get_current_teams(connection, league)

    if not teams:
        st.error("Database me team data nahi mila.")
        st.stop()

    batting_team = st.selectbox(
        "Batting Team",
        teams,
        index=restored_index(teams, "persisted_batting_team"),
        key="batting_team_select",
    )
    st.session_state["persisted_batting_team"] = batting_team

    bowling_options = [team for team in teams if team != batting_team]
    if not bowling_options:
        bowling_options = ["Unknown"]

    bowling_team = st.selectbox(
        "Bowling Team",
        bowling_options,
        index=restored_index(bowling_options, "persisted_bowling_team"),
        key="bowling_team_select",
    )
    st.session_state["persisted_bowling_team"] = bowling_team

    grounds = get_grounds(connection, league)
    if grounds:
        ground = st.selectbox(
            "Ground / Venue",
            grounds,
            index=restored_index(grounds, "persisted_ground"),
            key="ground_select",
        )
        st.session_state["persisted_ground"] = ground
    else:
        ground = ""
        st.info("Ground data available nahi hai.")

    toss_winner_options = ["Unknown", batting_team, bowling_team]
    toss_winner_choice = st.selectbox(
        "Toss Won By",
        toss_winner_options,
        index=restored_index(toss_winner_options, "persisted_toss_winner"),
        key="toss_winner_select",
    )
    st.session_state["persisted_toss_winner"] = toss_winner_choice

    toss_decision_options = ["Unknown", "Bat First", "Field First"]
    toss_decision_choice = st.selectbox(
        "Toss Decision",
        toss_decision_options,
        index=restored_index(toss_decision_options, "persisted_toss_decision"),
        key="toss_decision_select",
    )
    st.session_state["persisted_toss_decision"] = toss_decision_choice

    if toss_winner_choice == batting_team:
        current_toss_role = "batting"
    elif toss_winner_choice == bowling_team:
        current_toss_role = "bowling"
    else:
        current_toss_role = None

    if toss_decision_choice == "Bat First":
        current_toss_decision = "bat"
    elif toss_decision_choice == "Field First":
        current_toss_decision = "field"
    else:
        current_toss_decision = None

    st.markdown("---")
    st.subheader("Player Context (optional)")
    st.caption(
        "Adds a small, bounded form-based nudge using this player's history "
        "in this league. Leave as 'Not Selected' to use team-only data."
    )

    striker_roster = ["Not Selected"] + get_team_roster(
        connection, league, batting_team, "batting"
    )
    striker_choice = st.selectbox(
        "Current Striker",
        striker_roster,
        index=restored_index(striker_roster, "persisted_striker"),
        key="striker_select",
    )
    st.session_state["persisted_striker"] = striker_choice

    bowler_roster = ["Not Selected"] + get_team_roster(
        connection, league, bowling_team, "bowling"
    )
    current_bowler_choice = st.selectbox(
        "Current Bowler",
        bowler_roster,
        index=restored_index(bowler_roster, "persisted_current_bowler"),
        key="current_bowler_select",
    )
    st.session_state["persisted_current_bowler"] = current_bowler_choice

    innings_options = ["1st Innings", "2nd Innings"]
    innings_label = st.selectbox(
        "Innings",
        innings_options,
        index=restored_index(innings_options, "persisted_innings_label"),
        key="innings_select",
    )
    st.session_state["persisted_innings_label"] = innings_label

    innings_no = 1 if innings_label == "1st Innings" else 2

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

    if innings_no == 2:
        target = st.number_input(
            "Target Runs",
            min_value=0,
            max_value=400,
            value=int(st.session_state.target),
            step=1,
            key="target_runs_widget",
        )
        st.session_state.target = int(target)
    else:
        target = 0
        st.session_state.target = 0

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
    st.caption("Updates automatically after every ball/event")


# ============================================================
# CURRENT STATE
# ============================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

striker_name = None if striker_choice == "Not Selected" else striker_choice
bowler_name = None if current_bowler_choice == "Not Selected" else current_bowler_choice

batter_stats = get_batter_stats(connection, league, striker_name) if striker_name else None
bowler_stats = get_bowler_stats(connection, league, bowler_name) if bowler_name else None

league_batting_benchmark = get_league_batting_benchmark(connection, league)
league_bowling_benchmark = get_league_bowling_benchmark(connection, league)

player_adjustment_ratio, player_adjustment_confidence = compute_player_adjustment(
    batter_stats, bowler_stats, league_batting_benchmark, league_bowling_benchmark
)
player_context_active = bool(striker_name or bowler_name)


# ============================================================
# LIVE MODELS - ALL RECOMPUTE AUTOMATICALLY EVERY RERUN
# ============================================================
# Two SEPARATE, clearly-scoped computations, never mixed together:
#   1. FULL-MATCH model (always 20 overs) -> "Team Winning Result" box.
#   2. WINDOW model (whatever Projection End Over is picked) -> "Score
#      Target Analysis" box.
# Both blend past historical data with the current live score/wickets/
# run-rate/ground/toss, and both get a bounded player-form nudge on top
# when a striker/bowler is selected.

FULL_INNINGS_OVERS = 20
projection_end_over_current = int(st.session_state.projection_end_over)

try:
    full_match_model = calculate_auto_model(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=balls,
        current_runs=runs,
        current_wickets=wickets,
        session_over=FULL_INNINGS_OVERS,
        batting_team=batting_team,
        bowling_team=bowling_team,
        target=int(target),
        ground=ground,
        current_toss_role=current_toss_role,
        current_toss_decision=current_toss_decision,
    )

    full_historical_model = calculate_historical_average(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=balls,
        current_runs=runs,
        current_wickets=wickets,
        session_over=FULL_INNINGS_OVERS,
        batting_team=batting_team,
        bowling_team=bowling_team,
        ground=ground,
        current_toss_role=current_toss_role,
        current_toss_decision=current_toss_decision,
    )

except Exception as error:
    st.error("Model calculation failed.")
    st.exception(error)
    st.stop()

full_raw_average = float(full_historical_model["average"])
full_adjusted_average, full_adjusted_low, full_adjusted_high = apply_player_adjustment_to_average(
    runs, full_raw_average, full_historical_model["low"], full_historical_model["high"],
    player_adjustment_ratio,
)

st.session_state.full_historical_average = float(full_adjusted_average)
st.session_state.full_historical_average_raw = float(full_raw_average)
st.session_state.full_historical_low = int(full_adjusted_low)
st.session_state.full_historical_high = int(full_adjusted_high)
st.session_state.full_historical_samples = int(full_historical_model["samples"])

raw_win_probability = full_match_model["win_probability"]
if raw_win_probability is not None:
    win_nudge = (player_adjustment_ratio - 1.0) * 40.0
    adjusted_win_probability = min(99.0, max(1.0, float(raw_win_probability) + win_nudge))
else:
    adjusted_win_probability = None

st.session_state.win_probability = adjusted_win_probability
st.session_state.win_probability_raw = raw_win_probability
st.session_state.win_samples = int(full_match_model["samples"])


# ============================================================
# TOP SCORE
# ============================================================

st.html(
    f"""
    <div class="card">
        <h2 style="margin:0">
            {batting_team} {runs}/{wickets}
        </h2>
        <p class="small" style="margin:5px 0 0">
            {display_over(balls)} ov
            • Ground: {ground or "—"}
            • Toss: {toss_winner_choice if toss_winner_choice != "Unknown" else "—"}
            {("(" + toss_decision_choice + ")") if toss_decision_choice != "Unknown" else ""}
            • Target: {target if target > 0 else "Not set"}
            • Last: {st.session_state.last or "—"}
        </p>
    </div>
    """
)

# ------------------------------------------------------------
# Match Context: Current Run Rate, Required Run Rate, Momentum
# ------------------------------------------------------------

current_run_rate = (runs / (balls / 6.0)) if balls > 0 else 0.0

required_run_rate = None
if innings_no == 2 and int(target) > 0:
    remaining_runs = max(0, int(target) - runs + 1)
    remaining_balls = max(0, (FULL_INNINGS_OVERS * 6) - balls)
    if remaining_balls > 0:
        required_run_rate = (remaining_runs / remaining_balls) * 6.0

recent_run_rate = compute_recent_run_rate(
    st.session_state.undo_stack, runs, balls, window_balls=12
)

context_columns = st.columns(3, gap="small")

with context_columns[0]:
    st.metric("Current Run Rate", f"{current_run_rate:.2f}")

with context_columns[1]:
    if required_run_rate is not None:
        st.metric("Required Run Rate", f"{required_run_rate:.2f}")
    else:
        st.metric("Required Run Rate", "—")

with context_columns[2]:
    if recent_run_rate is not None:
        st.metric("Momentum (last 2 ov)", f"{recent_run_rate:.2f}")
    else:
        st.metric("Momentum (last 2 ov)", "—")

try:
    head_to_head = get_head_to_head(connection, league, batting_team, bowling_team)
    if head_to_head["total"] > 0:
        st.caption(
            f"Head-to-Head (all-time, {league}): {batting_team} "
            f"{head_to_head['a_wins']} — {head_to_head['b_wins']} {bowling_team} "
            f"across {fmt_int(head_to_head['total'])} matches"
        )
    else:
        st.caption(f"Head-to-Head: no prior {batting_team} vs {bowling_team} matches found.")
except Exception:
    pass

# ------------------------------------------------------------
# Player Form (only shown when a striker/bowler is selected)
# ------------------------------------------------------------

if player_context_active:
    player_columns = st.columns(2, gap="small")

    with player_columns[0]:
        if batter_stats:
            avg_text = f"{batter_stats['average']:.1f}" if batter_stats["average"] is not None else "Not out yet"
            st.html(
                f"""
                <div class="card">
                    <p class="small" style="margin:0"><b>{striker_name} — Striker Form</b></p>
                    <p style="margin:4px 0 0">
                        SR: <b>{batter_stats['strike_rate']:.1f}</b>
                        • Avg: <b>{avg_text}</b>
                    </p>
                    <p class="small" style="margin:4px 0 0">
                        {fmt_int(batter_stats['balls'])} balls faced across
                        {fmt_int(batter_stats['matches'])} matches in {league}
                    </p>
                </div>
                """
            )
        elif striker_name:
            st.caption(f"No historical data found for {striker_name} in {league}.")

    with player_columns[1]:
        if bowler_stats:
            st.html(
                f"""
                <div class="card">
                    <p class="small" style="margin:0"><b>{bowler_name} — Bowler Form</b></p>
                    <p style="margin:4px 0 0">
                        Economy: <b>{bowler_stats['economy']:.2f}</b>
                        • Wickets: <b>{fmt_int(bowler_stats['wickets'])}</b>
                    </p>
                    <p class="small" style="margin:4px 0 0">
                        {fmt_int(bowler_stats['balls'])} balls bowled across
                        {fmt_int(bowler_stats['matches'])} matches in {league}
                    </p>
                </div>
                """
            )
        elif bowler_name:
            st.caption(f"No historical data found for {bowler_name} in {league}.")

    st.caption(
        f"Form adjustment applied to projections below: "
        f"×{player_adjustment_ratio:.3f} on remaining runs "
        f"(confidence {player_adjustment_confidence * 100:.0f}% based on sample size)."
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
# SCORE TARGET ANALYSIS (window-scoped, auto-recalculated every ball)
# ============================================================

st.subheader("Score Target Analysis")

check_col1, check_col2, check_col3, check_col4, check_col5 = st.columns(
    5, gap="small"
)

with check_col1:
    st.metric("Runs", runs)

with check_col2:
    st.metric("Over", display_over(balls))

with check_col3:
    st.metric("Wkt", wickets)

with check_col4:
    projection_end_over = st.number_input(
        "Projection End Over",
        min_value=1,
        max_value=20,
        value=projection_end_over_current,
        step=1,
        key="projection_end_over_widget",
    )

with check_col5:
    default_prediction = int(st.session_state.score_prediction)
    if default_prediction <= 0:
        default_prediction = runs + 10
    score_prediction = st.number_input(
        "Score Prediction",
        min_value=0,
        max_value=400,
        value=default_prediction,
        step=1,
        key="score_prediction_widget",
    )

st.session_state.projection_end_over = int(projection_end_over)
st.session_state.score_prediction = int(score_prediction)

window_over = max(int(projection_end_over), (balls + 5) // 6 if balls % 6 else balls // 6)
if window_over != int(projection_end_over):
    st.caption(
        f"Note: Over {int(projection_end_over)} is already behind the current "
        f"ball ({display_over(balls)}), so the window was adjusted to Over {window_over}."
    )

try:
    window_check_result = calculate_manual_probability(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=balls,
        current_runs=runs,
        current_wickets=wickets,
        session_over=window_over,
        batting_team=batting_team,
        bowling_team=bowling_team,
        line_high=int(st.session_state.score_prediction),
        ground=ground,
        current_toss_role=current_toss_role,
        current_toss_decision=current_toss_decision,
    )

    window_historical_model = calculate_historical_average(
        connection=connection,
        league=league,
        innings_no=innings_no,
        current_ball=balls,
        current_runs=runs,
        current_wickets=wickets,
        session_over=window_over,
        batting_team=batting_team,
        bowling_team=bowling_team,
        ground=ground,
        current_toss_role=current_toss_role,
        current_toss_decision=current_toss_decision,
    )

    window_raw_average = float(window_historical_model["average"])
    window_adjusted_average, window_adjusted_low, window_adjusted_high = apply_player_adjustment_to_average(
        runs, window_raw_average, window_historical_model["low"], window_historical_model["high"],
        player_adjustment_ratio,
    )

    st.session_state.window_cross_chance = float(window_check_result["yes"])
    st.session_state.window_stay_chance = float(window_check_result["no"])
    st.session_state.window_samples = int(window_check_result["samples"])
    st.session_state.window_historical_average = float(window_adjusted_average)
    st.session_state.window_historical_average_raw = float(window_raw_average)
    st.session_state.window_historical_low = int(window_adjusted_low)
    st.session_state.window_historical_high = int(window_adjusted_high)
    st.session_state.window_historical_samples = int(window_historical_model["samples"])

except Exception as error:
    st.error("Score Target Analysis calculation failed.")
    st.exception(error)


# ============================================================
# VASUDEV PREDICTION (window-scoped box - Over {window_over} only)
# ============================================================

window_confidence_label = (
    "High"
    if int(st.session_state.window_historical_samples) >= 150
    else "Medium"
    if int(st.session_state.window_historical_samples) >= 40
    else "Low"
)

st.subheader("VasuDev Prediction")

cross = float(st.session_state.window_cross_chance)
under = float(st.session_state.window_stay_chance)
result_class = "positive" if cross >= under else "negative"

player_line = ""
if player_context_active:
    player_line = (
        f"<p class=\"small\" style=\"margin:5px 0 0\">"
        f"Team-only estimate: <b>{float(st.session_state.window_historical_average_raw):.1f}</b>"
        f" • Player-adjusted: <b>{float(st.session_state.window_historical_average):.1f}</b>"
        f"</p>"
    )

check_html = f"""
    <h1 style="margin:0">
        Score Prediction: {int(st.session_state.score_prediction)}
        by Over {window_over}
    </h1>
    <p style="margin:8px 0 0">
        Probability of Reaching This Score: <b>{cross:.1f}%</b>
        •
        Probability of Falling Short: <b>{under:.1f}%</b>
    </p>
    <p class="small" style="margin:5px 0 0">
        Based on {fmt_int(st.session_state.window_samples)} similar historical
        situations (Over {window_over} window)
    </p>
"""

st.html(
    f"""
    <div class="{result_class}">
        {check_html}
        <div style="margin-top:12px; padding-top:12px; border-top:1px solid #4777a8;">
            <p style="margin:0 0 6px">
                Historical Average by Over {window_over}:
                <b>{float(st.session_state.window_historical_average):.1f}</b>
            </p>
            <p style="margin:5px 0">
                Historical Range by Over {window_over}:
                <b>{int(st.session_state.window_historical_low)} - {int(st.session_state.window_historical_high)}</b>
            </p>
            <p style="margin:5px 0 0">
                Similar Historical Samples:
                <b>{fmt_int(st.session_state.window_historical_samples)}</b>
                • Confidence: <b>{window_confidence_label}</b>
            </p>
            {player_line}
        </div>
    </div>
    """
)

st.caption(
    "Auto-updates on every ball: current run-rate, wickets, ground, toss and "
    "(if selected) player form are blended with matching historical situations "
    "at this exact window."
)


# ============================================================
# SCORE TRAJECTORY CHART (new)
# ============================================================

st.subheader("Score Trajectory")

try:
    phase_rates = get_phase_par_rates(connection, league, innings_no)
except Exception:
    phase_rates = {"powerplay": 7.5, "middle": 7.8, "death": 9.5}

try:
    match_trajectory = build_match_trajectory(
        current_ball=balls,
        current_runs=runs,
        window_end_over=window_over,
        target_total=float(st.session_state.window_historical_average),
        phase_rates=phase_rates,
    )
    par_trajectory = build_par_trajectory(window_over, phase_rates)

    all_overs = sorted(set(list(match_trajectory.keys()) + list(par_trajectory.keys())))
    chart_df = pd.DataFrame({"Over": all_overs})
    chart_df["Your Match (Projected)"] = chart_df["Over"].map(match_trajectory)
    chart_df["League Average Pace"] = chart_df["Over"].map(par_trajectory)
    chart_df = chart_df.set_index("Over")

    st.line_chart(chart_df)
    st.caption(
        f"Shaped by this league's Powerplay ({phase_rates['powerplay']:.1f} rpo), "
        f"Middle ({phase_rates['middle']:.1f} rpo) and Death "
        f"({phase_rates['death']:.1f} rpo) par run rates for "
        f"{'1st' if innings_no == 1 else '2nd'} innings, anchored to the "
        f"Over {window_over} projection above."
    )
except Exception as error:
    st.info("Trajectory chart could not be built for this situation.")


# ============================================================
# TEAM WINNING RESULT (always full 20-over match outcome)
# ============================================================

final_win_probability = st.session_state.win_probability
win_samples = int(st.session_state.win_samples)

if final_win_probability is not None:
    batting_win = float(final_win_probability)
    bowling_win = 100.0 - batting_win

    if batting_win >= bowling_win:
        winner_name = batting_team
        winner_percent = batting_win
        winner_class = "positive"
    else:
        winner_name = bowling_team
        winner_percent = bowling_win
        winner_class = "negative"

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
                • Based on {fmt_int(win_samples)} full-match historical situations
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
    st.write(
        f"**Toss:** "
        f"{toss_winner_choice if toss_winner_choice != 'Unknown' else 'Unknown'} "
        f"{'(' + toss_decision_choice + ')' if toss_decision_choice != 'Unknown' else ''}"
    )
    if player_context_active:
        st.write(
            f"**Player Context:** Striker = {striker_name or '—'}, "
            f"Bowler = {bowler_name or '—'} "
            f"(adjustment ratio ×{player_adjustment_ratio:.3f}, "
            f"confidence {player_adjustment_confidence * 100:.0f}%)"
        )

    st.write("---")
    st.write(f"**Score Prediction Window: Over {window_over}**")
    st.write(
        f"- Historical Average, team-only (by Over {window_over}): "
        f"{float(st.session_state.window_historical_average_raw):.1f}"
    )
    st.write(
        f"- Historical Average, player-adjusted (by Over {window_over}): "
        f"{float(st.session_state.window_historical_average):.1f}"
    )
    st.write(
        f"- Historical Range (by Over {window_over}): "
        f"{int(st.session_state.window_historical_low)} - "
        f"{int(st.session_state.window_historical_high)}"
    )
    st.write(
        f"- Similar Historical Samples: "
        f"{fmt_int(st.session_state.window_historical_samples)} "
        f"(Confidence: {window_confidence_label})"
    )
    st.write(
        f"- Score Target Analysis: {int(st.session_state.score_prediction)} "
        f"by over {window_over}"
    )
    st.write(
        f"- Probability of Reaching This Score: "
        f"{float(st.session_state.window_cross_chance):.1f}%"
    )
    st.write(
        f"- Probability of Falling Short: "
        f"{float(st.session_state.window_stay_chance):.1f}%"
    )

    st.write("---")
    st.write("**Full-Match Projection (20 overs)** — used for Winner estimate only")
    st.write(
        f"- Historical Average, team-only: "
        f"{float(st.session_state.full_historical_average_raw):.1f}"
    )
    st.write(
        f"- Historical Average, player-adjusted: "
        f"{float(st.session_state.full_historical_average):.1f}"
    )
    st.write(
        f"- Historical Range: "
        f"{int(st.session_state.full_historical_low)} - "
        f"{int(st.session_state.full_historical_high)}"
    )
    st.write(
        f"- Similar Historical Samples: {fmt_int(st.session_state.full_historical_samples)}"
    )

    if final_win_probability is not None:
        st.write(
            f"- **{batting_team} Win Probability (player-adjusted):** "
            f"{float(final_win_probability):.1f}%"
        )
        if st.session_state.win_probability_raw is not None:
            st.write(
                f"- {batting_team} Win Probability (team-only): "
                f"{float(st.session_state.win_probability_raw):.1f}%"
            )
        st.write(
            f"- **{bowling_team} Win Probability (player-adjusted):** "
            f"{100.0 - float(final_win_probability):.1f}%"
        )
        st.write(f"- Based on {fmt_int(win_samples)} full-match historical situations")

    if innings_no == 2 and int(target) > 0:
        st.write(f"**Target:** {int(target)}")

    st.write("---")
    st.write(
        f"**Phase Par Rates (this league, {'1st' if innings_no == 1 else '2nd'} innings):** "
        f"Powerplay {phase_rates['powerplay']:.2f} rpo • "
        f"Middle {phase_rates['middle']:.2f} rpo • "
        f"Death {phase_rates['death']:.2f} rpo"
    )

    st.write(
        "**Similarity Context used everywhere above:** Over/Ball + Runs + "
        "Wickets + Run Rate + Batting Team + Bowling Team + Ground + Toss "
        "(winner + decision) + Innings + Recency (recent seasons weighted "
        "more than older ones). Player form (Striker SR / Bowler Economy) "
        "is applied as a separate bounded nudge on top, not as part of the "
        "similarity search itself."
    )


st.caption(
    "Historical estimate only. This is not a guarantee of the live match result."
)


# Save the current state so a browser refresh restores it instead of
# resetting to login/defaults. Only explicit Logout clears this.
save_persisted_session()
