# VasuDev Cricket AI - "FAST" app.py
#
# Changes in THIS version (see chat for full explanation):
#
#   1. REMOVED: "Abu Dhabi T10 League". This isn't a partial fix - it's a
#      hard data-availability limit. Cricsheet has NO T10-format data at
#      all: not a competition zip, not any of the 8 team archives tried
#      (all returned HTTP 404), and T10 doesn't appear anywhere in
#      Cricsheet's full competition list. Rather than keep guessing team
#      names that will keep failing, this league is removed until/unless
#      Cricsheet ever adds T10 coverage.
#
#   2. ADDED: "ODI Cricket (International)". Built from Cricsheet's own
#      direct ODI archive (odis_male_json.zip) - a single, real
#      competition-level file, not a merge-of-teams guess like the T10
#      attempt was. 50 overs per innings, with REAL ODI phase boundaries
#      (Powerplay 1: overs 1-10, Death: overs 41-50), not a generic
#      percentage formula.
#
#   3. MANUAL ENTRY: Ground, Batsman 1, Batsman 2, and Current Bowler
#      dropdowns now include an "Other / Type manually" option at the
#      bottom, so a ground or player not yet in Cricsheet's data can
#      still be typed in by hand (used for display/matching, but with no
#      historical stats since there's nothing to look up for a brand-new
#      name - the app says so plainly rather than pretending).
#
#   4. LONGER ROSTER WINDOW FOR ODI: T20 league rosters still look at the
#      latest 1-2 seasons (franchise squads turn over fast). ODI rosters
#      now look back 5 seasons, since international players appear far
#      less often per season and a 1-2 season window was missing most of
#      the current squad.
#
#   5. MAJOR PERFORMANCE REWRITE (the ~10 second lag): the old engine ran
#      a SEPARATE small SQL query for EVERY single similar historical
#      match it found - often 1,000-2,500 of them, times 4 separate model
#      calls per ball, i.e. tens of thousands of tiny queries per tap.
#      That's rewritten now: for each of the two distinct projections
#      needed (the window check and the full-innings check), the engine
#      does ONE bulk query that pulls every relevant ball for every
#      candidate match at once, then does the cumulative-score math in
#      memory (pandas) instead of asking the database over and over. The
#      window and full-innings calculations that used to each trigger
#      their OWN duplicate search now share a single search each. Same
#      math, same historical-matching logic, same results - just without
#      the repeated round trips. This should take ball updates from
#      ~10 seconds down to close to instant.
#
#   Everything else from the previous version is unchanged: window-scoped
#   Score Target Analysis, toss as a similarity factor, neutral
#   terminology, Current Run Rate / Required Run Rate / Momentum,
#   Head-to-Head, player Strike Rate / Economy form, Pitch Condition
#   nudge, two-batsmen auto strike rotation, decluttered UI (score shown
#   once, everything auxiliary tucked into one collapsed expander).

import bisect
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
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


MANUAL_OPTION_LABEL = "Other / Type manually"


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
    "persisted_ground_manual",
    "persisted_innings_label",
    "persisted_toss_winner",
    "persisted_toss_decision",
    "persisted_batsman_a",
    "persisted_batsman_a_manual",
    "persisted_batsman_b",
    "persisted_batsman_b_manual",
    "persisted_current_bowler",
    "persisted_current_bowler_manual",
    "persisted_pitch_condition",
    "on_strike_index",
    "dismissed_batsmen",
    "awaiting_new_batsman",
    "out_slot_index",
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
    "ODI Cricket (International)": BASE / "odi_history.db",
}

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
    "CSA Pro T20 Cup": [
        f"https://cricsheet.org/downloads/{team_slug(team)}_male_json.zip"
        for team in CSA_PRO_T20_TEAMS
    ],
    # Direct competition-level archive - all international men's ODIs.
    "ODI Cricket (International)": "https://cricsheet.org/downloads/odis_male_json.zip",
}

RESTRICT_TEAMS = {
    "CSA Pro T20 Cup": {team.strip().lower() for team in CSA_PRO_T20_TEAMS},
}

# Format-aware: overs per innings for each league.
LEAGUE_FORMAT_OVERS = {
    "IPL": 20,
    "Men's Big Bash League": 20,
    "Women's Big Bash League": 20,
    "CSA Pro T20 Cup": 20,
    "ODI Cricket (International)": 50,
}

LEAGUES = list(DATABASES.keys())

# How many trailing seasons feed the Batsman/Bowler roster dropdowns.
# Franchise T20 squads turn over almost entirely every season, so a short
# window keeps the list current; international players appear in far
# fewer matches per season, so ODI needs a longer window to actually
# surface the current squad.
DEFAULT_ROSTER_LOOKBACK_SEASONS = 2
LEAGUE_ROSTER_LOOKBACK_SEASONS = {
    "ODI Cricket (International)": 5,
}

# Manual pitch-behaviour nudge (Cricsheet has no pitch-type data).
PITCH_CONDITIONS = {
    "Not Selected / Unknown": 1.00,
    "Batting Paradise (very flat, high-scoring)": 1.12,
    "Good for Batting (flat, true bounce)": 1.06,
    "Balanced (even contest)": 1.00,
    "Slow & Low (hard to score freely)": 0.92,
    "Seam-Friendly / Green Top (helps fast bowlers)": 0.90,
    "Spin-Friendly / Dry & Turning (helps spinners)": 0.90,
    "Two-Paced / Tricky (inconsistent bounce)": 0.88,
}

# Real, format-specific Powerplay/Death boundaries where they're known
# (T20's 6/15 split, T10's 3/8, ODI's actual Powerplay-1-ends-at-10 /
# last-10-overs-are-death convention), rather than one generic formula
# for every format.
KNOWN_PHASE_BOUNDARIES = {
    20: (6, 15),
    10: (3, 8),
    50: (10, 40),
}


def get_phase_boundaries(total_overs):
    total_overs = max(1, int(total_overs))
    if total_overs in KNOWN_PHASE_BOUNDARIES:
        return KNOWN_PHASE_BOUNDARIES[total_overs]
    powerplay_end = max(1, round(total_overs * 0.30))
    death_start = max(powerplay_end + 1, round(total_overs * 0.75))
    death_start = min(death_start, total_overs)
    return powerplay_end, death_start


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


@st.cache_data(show_spinner=False)
def get_grounds(_connection, league):
    rows = _connection.execute(
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


@st.cache_data(show_spinner=False)
def get_latest_season(_connection, league):
    row = _connection.execute(
        "SELECT MAX(season) FROM matches WHERE league=? AND season IS NOT NULL",
        (league,),
    ).fetchone()
    value = row[0] if row else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@st.cache_data(show_spinner=False)
def get_current_teams(_connection, league):
    latest_season = get_latest_season(_connection, league)

    def teams_for_seasons(seasons):
        placeholders = ",".join("?" for _ in seasons)
        rows = _connection.execute(
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
        _connection,
        """
        SELECT DISTINCT batting_team
        FROM deliveries
        WHERE league=?
        AND batting_team<>''
        ORDER BY batting_team
        """,
        league,
    )


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


@st.cache_data(show_spinner=False)
def get_head_to_head(_connection, league, team_a, team_b):
    rows = _connection.execute(
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
# DATABASE QUERIES - PLAYER LEVEL
# ============================================================

@st.cache_data(show_spinner=False)
def get_team_roster(_connection, league, team, role):
    if not team:
        return []

    column = "batter" if role == "batting" else "bowler"
    team_column = "batting_team" if role == "batting" else "bowling_team"
    latest_season = get_latest_season(_connection, league)
    lookback = LEAGUE_ROSTER_LOOKBACK_SEASONS.get(league, DEFAULT_ROSTER_LOOKBACK_SEASONS)

    def names_for_seasons(seasons):
        placeholders = ",".join("?" for _ in seasons)
        rows = _connection.execute(
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
        seasons_to_try = [latest_season - offset for offset in range(lookback)]
        names = names_for_seasons(seasons_to_try)
        if names:
            return names

    rows = _connection.execute(
        f"""
        SELECT DISTINCT {column} FROM deliveries
        WHERE league=? AND {team_column}=? AND {column}<>''
        ORDER BY {column}
        """,
        (league, team),
    ).fetchall()
    return [str(row[0]).strip() for row in rows if row[0]]


def get_batter_stats(connection, league, batter_name):
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
def get_phase_par_rates(_connection, league, innings_no, powerplay_end, death_start):
    rows = _connection.execute(
        f"""
        SELECT
            CASE WHEN over_no < {int(powerplay_end)} THEN 'powerplay'
                 WHEN over_no < {int(death_start)} THEN 'middle'
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


def phase_rate_for_over(phase_rates, over_index, powerplay_end, death_start):
    if over_index < powerplay_end:
        return phase_rates["powerplay"]
    if over_index < death_start:
        return phase_rates["middle"]
    return phase_rates["death"]


def build_match_trajectory(current_ball, current_runs, window_end_over, target_total, phase_rates, powerplay_end, death_start):
    start_over_point = round(current_ball / 6.0, 2)
    current_over_completed = current_ball // 6
    remaining_overs = list(range(int(current_over_completed) + 1, int(window_end_over) + 1))

    trajectory = {start_over_point: float(current_runs)}

    if not remaining_overs:
        return trajectory

    weights = [
        phase_rate_for_over(phase_rates, o - 1, powerplay_end, death_start)
        for o in remaining_overs
    ]
    total_weight = sum(weights) or 1.0
    remaining_runs = max(0.0, float(target_total) - float(current_runs))

    cumulative = float(current_runs)
    for over_index, weight in zip(remaining_overs, weights):
        cumulative += remaining_runs * (weight / total_weight)
        trajectory[float(over_index)] = cumulative

    return trajectory


def build_par_trajectory(window_end_over, phase_rates, powerplay_end, death_start):
    trajectory = {0.0: 0.0}
    cumulative = 0.0
    for over_index in range(1, int(window_end_over) + 1):
        cumulative += phase_rate_for_over(phase_rates, over_index - 1, powerplay_end, death_start)
        trajectory[float(over_index)] = cumulative
    return trajectory


def compute_player_adjustment(batter_stats, bowler_stats, league_batting_benchmark, league_bowling_benchmark):
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


def apply_adjustment_to_average(current_runs, base_average, base_low, base_high, adjustment_ratio):
    delta = float(base_average) - float(current_runs)
    adjusted_average = float(current_runs) + delta * adjustment_ratio
    shift = adjusted_average - float(base_average)

    adjusted_low = max(int(current_runs), int(round(base_low + shift)))
    adjusted_high = max(adjusted_low, int(round(base_high + shift)))

    return adjusted_average, adjusted_low, adjusted_high


# ============================================================
# RECENCY WEIGHTING
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
# BULK DATA HELPERS (the performance fix, v2)
# ============================================================
#
# v1 of this fix (previous version) still fetched EVERY ball of EVERY
# candidate match into Python and used pandas to cumsum it. That scales
# with (matches × balls elapsed) - so it got slower and slower as an
# innings went on, which is exactly the "fine for over 1, crawling by
# over 10" symptom reported.
#
# v2: let SQLite do the summing. A single query with conditional SUM(...)
# expressions returns ONE ROW PER MATCH with the cumulative value already
# computed - no per-ball rows ever cross into Python, and no pandas. Cost
# scales with the number of candidate MATCHES, not balls elapsed, so it
# stays fast no matter how deep into the innings the game is.

def bulk_cumulative_at_thresholds(connection, league, innings_no, match_ids, thresholds):
    """For each match_id: cumulative (runs, wickets) at EACH of the given
    ball_pos thresholds, in one query. Used during matching, where the
    handful of candidate ball positions (current ball ±2) are the
    thresholds needed."""
    if not match_ids or not thresholds:
        return {}

    threshold_list = sorted({int(t) for t in thresholds})
    runs_exprs = ", ".join(
        f"SUM(CASE WHEN ball_pos<={t} THEN runs ELSE 0 END) AS r{i}"
        for i, t in enumerate(threshold_list)
    )
    wkts_exprs = ", ".join(
        f"SUM(CASE WHEN ball_pos<={t} THEN wickets ELSE 0 END) AS w{i}"
        for i, t in enumerate(threshold_list)
    )
    placeholders = ",".join("?" for _ in match_ids)

    query = f"""
        SELECT match_id, {runs_exprs}, {wkts_exprs}
        FROM deliveries
        WHERE league=? AND innings_no=? AND match_id IN ({placeholders})
        GROUP BY match_id
    """
    rows = connection.execute(query, [league, innings_no, *match_ids]).fetchall()

    result = {}
    for row in rows:
        per_threshold = {}
        for i, t in enumerate(threshold_list):
            per_threshold[t] = (int(row[f"r{i}"] or 0), int(row[f"w{i}"] or 0))
        result[row["match_id"]] = per_threshold
    return result


def bulk_scores_and_finals(connection, league, innings_no, match_ids, end_ball):
    """For each match_id: score at end_ball AND the innings' final total,
    both in one query, one row per match. Used for scoring the eventual
    OUTCOME of each already-filtered similar state."""
    if not match_ids:
        return {}
    placeholders = ",".join("?" for _ in match_ids)
    rows = connection.execute(
        f"""
        SELECT match_id,
            SUM(CASE WHEN ball_pos<=? THEN runs ELSE 0 END) AS score_at_end,
            SUM(runs) AS final_runs
        FROM deliveries
        WHERE league=? AND innings_no=? AND match_id IN ({placeholders})
        GROUP BY match_id
        """,
        [int(end_ball), league, innings_no, *match_ids],
    ).fetchall()
    return {
        row["match_id"]: (int(row["score_at_end"] or 0), int(row["final_runs"] or 0))
        for row in rows
    }


def bulk_match_winners(connection, match_ids):
    if not match_ids:
        return {}
    placeholders = ",".join("?" for _ in match_ids)
    rows = connection.execute(
        f"SELECT match_id, winner FROM matches WHERE match_id IN ({placeholders})",
        list(match_ids),
    ).fetchall()
    return {row["match_id"]: str(row["winner"] or "").strip() for row in rows}


# ============================================================
# HISTORICAL MATCH MATCHING (toss-aware, SQL-side scoring)
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
    """Returns states: the ranked list of comparable historical
    situations. The eventual OUTCOME (score at end_ball / final score) is
    NOT computed here - the caller fetches that separately, in bulk, only
    for the much smaller final states list (see bulk_scores_and_finals)."""
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
            LIMIT 3000
        """
        return connection.execute(query, params).fetchall()

    candidates = fetch_candidates("both")
    if len(candidates) < 40:
        candidates = fetch_candidates("batting")
    if len(candidates) < 40:
        candidates = fetch_candidates("all")

    if not candidates:
        return []

    match_ids = sorted({row["match_id"] for row in candidates})
    thresholds = sorted({int(row["ball_pos"]) for row in candidates})
    threshold_data = bulk_cumulative_at_thresholds(connection, league, innings_no, match_ids, thresholds)

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

        per_threshold = threshold_data.get(match_id)
        if per_threshold is None:
            continue

        historical_runs, historical_wickets = per_threshold.get(historical_ball, (0, 0))

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
    return states[:600]


# ============================================================
# PAR SCORE (BASE-RATE PRIOR)
# ============================================================

CONFIDENCE_SAMPLES = 40.0


@st.cache_data(show_spinner=False)
def get_par_score(
    _connection,
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

    rows = _connection.execute(query, params).fetchall()
    if not rows:
        return None

    latest_season = get_latest_season(_connection, league)

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
# HISTORICAL AVERAGE FOR A GIVEN WINDOW (bulk-scored)
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
    states=None,
    scores_and_finals=None,
):
    end_ball = int(session_over) * 6

    if int(current_ball) >= end_ball:
        return {
            "average": float(current_runs),
            "low": int(current_runs),
            "high": int(current_runs),
            "samples": 0,
        }

    if states is None:
        states = find_similar_states(
            connection, league, innings_no, current_ball, current_runs,
            current_wickets, end_ball, batting_team, bowling_team, ground,
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

    if scores_and_finals is None:
        scores_and_finals = bulk_scores_and_finals(
            connection, league, innings_no,
            [state["match_id"] for state in states], end_ball,
        )

    values = []
    weights = []

    for state in states:
        data = scores_and_finals.get(state["match_id"])
        if data is None:
            continue

        session_score, final_runs = data
        if session_score < state["runs"]:
            session_score = final_runs

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
# FULL-MATCH MODEL (bulk-scored)
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
    states=None,
    scores_and_finals=None,
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

    if states is None:
        states = find_similar_states(
            connection, league, innings_no, current_ball, current_runs,
            current_wickets, end_ball, batting_team, bowling_team, ground,
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

    if scores_and_finals is None:
        scores_and_finals = bulk_scores_and_finals(
            connection, league, innings_no,
            [state["match_id"] for state in states], end_ball,
        )

    winners = bulk_match_winners(connection, [state["match_id"] for state in states])

    scores = []
    weights = []
    win_results = []

    for state in states:
        data = scores_and_finals.get(state["match_id"])
        if data is None:
            continue

        session_score, final_runs = data
        if session_score < state["runs"]:
            session_score = final_runs

        session_score = max(int(current_runs), int(session_score))

        weight = (1.0 / (1.0 + float(state["distance"]))) * float(state.get("recency_weight", 1.0))
        scores.append(int(session_score))
        weights.append(float(weight))

        historical_winner = winners.get(state["match_id"], "")

        if int(innings_no) == 1:
            win_results.append(
                1 if historical_winner == batting_team else 0
            )
        elif int(innings_no) == 2 and int(target) > 0:
            win_results.append(
                1 if final_runs >= int(target) else 0
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
    states=None,
    scores_and_finals=None,
):
    end_ball = int(session_over) * 6

    if states is None:
        states = find_similar_states(
            connection, league, innings_no, current_ball, current_runs,
            current_wickets, end_ball, batting_team, bowling_team, ground,
            exclude_match_id=exclude_match_id,
            current_toss_role=current_toss_role,
            current_toss_decision=current_toss_decision,
        )

    if not states:
        return {"yes": 0.0, "no": 100.0, "samples": 0}

    if scores_and_finals is None:
        scores_and_finals = bulk_scores_and_finals(
            connection, league, innings_no,
            [state["match_id"] for state in states], end_ball,
        )

    total_weight = 0.0
    yes_weight = 0.0

    for state in states:
        data = scores_and_finals.get(state["match_id"])
        if data is None:
            continue

        session_score, final_runs = data
        if session_score < state["runs"]:
            session_score = final_runs

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
    "on_strike_index": 0,
    "dismissed_batsmen": [],
    "awaiting_new_batsman": False,
    "out_slot_index": None,
}

for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


# ============================================================
# MANUAL-ENTRY DROPDOWN HELPER
# ============================================================

def select_with_manual_option(label, options, persisted_select_key, persisted_manual_key, widget_key, restored_index_fn):
    """A selectbox with an 'Other / Type manually' option at the end. If
    chosen, a text box appears to type a name Cricsheet doesn't have yet.
    Returns the effective value to use (typed text if manual, else the
    picked option)."""
    combined = list(options) + [MANUAL_OPTION_LABEL]
    choice = st.selectbox(
        label,
        combined,
        index=restored_index_fn(combined, persisted_select_key),
        key=f"{widget_key}_select",
    )
    st.session_state[persisted_select_key] = choice

    if choice == MANUAL_OPTION_LABEL:
        manual_default = st.session_state.get(persisted_manual_key, "")
        manual_value = st.text_input(
            f"Type {label}",
            value=manual_default,
            key=f"{widget_key}_manual",
        )
        manual_value = manual_value.strip()
        st.session_state[persisted_manual_key] = manual_value
        return manual_value if manual_value else "Not Selected"

    st.session_state[persisted_manual_key] = ""
    return choice


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

    FULL_INNINGS_OVERS = LEAGUE_FORMAT_OVERS.get(league, 20)

    ready_leagues = st.session_state.setdefault("ready_leagues", {})

    try:
        if league in ready_leagues:
            # Already confirmed valid earlier this session - skip
            # re-running database_is_valid's fresh connection + COUNT
            # queries on every single ball tap.
            database_path = Path(ready_leagues[league])
        else:
            database_path = ensure_database(league)
            ready_leagues[league] = str(database_path.resolve())
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
    ground = select_with_manual_option(
        "Ground / Venue",
        grounds,
        "persisted_ground",
        "persisted_ground_manual",
        "ground",
        restored_index,
    )
    if ground == "Not Selected":
        ground = ""

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
    st.subheader("Pitch Condition (manual, optional)")
    st.caption(
        "Cricsheet has no pitch-type data, so this is YOUR read of the "
        "surface, applied as a bounded nudge - not a historical match."
    )
    pitch_options = list(PITCH_CONDITIONS.keys())
    pitch_choice = st.selectbox(
        "Pitch Behaviour",
        pitch_options,
        index=restored_index(pitch_options, "persisted_pitch_condition"),
        key="pitch_condition_select",
    )
    st.session_state["persisted_pitch_condition"] = pitch_choice
    pitch_adjustment_ratio = PITCH_CONDITIONS[pitch_choice]

    st.markdown("---")
    st.subheader("Batsmen & Bowler (optional)")
    st.caption(
        "Set both batsmen once - strike rotates automatically on odd runs "
        "and at the end of each over. Pick 'Other / Type manually' for "
        "anyone not yet in Cricsheet's data."
    )

    batting_roster = get_team_roster(connection, league, batting_team, "batting")
    batsman_options = ["Not Selected"] + batting_roster

    batsman_a_choice = select_with_manual_option(
        "Batsman 1",
        batsman_options,
        "persisted_batsman_a",
        "persisted_batsman_a_manual",
        "batsman_a",
        restored_index,
    )

    batsman_b_choice = select_with_manual_option(
        "Batsman 2",
        batsman_options,
        "persisted_batsman_b",
        "persisted_batsman_b_manual",
        "batsman_b",
        restored_index,
    )

    on_strike_index = int(st.session_state.get("on_strike_index", 0))
    on_strike_name = batsman_a_choice if on_strike_index == 0 else batsman_b_choice

    st.caption(
        f"Currently facing: **{on_strike_name if on_strike_name != 'Not Selected' else '—'}**"
    )

    if st.button("Swap Strike Manually", use_container_width=True, key="swap_strike_button"):
        st.session_state.on_strike_index = 1 - on_strike_index
        st.rerun()

    bowler_options = ["Not Selected"] + get_team_roster(
        connection, league, bowling_team, "bowling"
    )
    current_bowler_choice = select_with_manual_option(
        "Current Bowler",
        bowler_options,
        "persisted_current_bowler",
        "persisted_current_bowler_manual",
        "current_bowler",
        restored_index,
    )

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
    for over in range(FULL_INNINGS_OVERS):
        for ball in range(1, 7):
            over_points.append(f"{over}.{ball}")
    over_points.append(f"{FULL_INNINGS_OVERS}.0")

    default_start_index = min(19, len(over_points) - 1)
    start_over = st.selectbox(
        "Start Over / Ball",
        over_points,
        index=default_start_index,
        key="start_over_select",
    )

    start_runs = st.number_input(
        "Start Runs",
        min_value=0,
        max_value=500,
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
            st.session_state.on_strike_index = 0
            st.session_state.dismissed_batsmen = []
            st.session_state.awaiting_new_batsman = False
            st.session_state.out_slot_index = None
            st.rerun()

    if innings_no == 2:
        target = st.number_input(
            "Target Runs",
            min_value=0,
            max_value=500,
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
        st.session_state.on_strike_index = 0
        st.session_state.dismissed_batsmen = []
        st.session_state.awaiting_new_batsman = False
        st.session_state.out_slot_index = None
        st.rerun()


# ============================================================
# CURRENT STATE
# ============================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

striker_name = None if on_strike_name in (None, "Not Selected") else on_strike_name
bowler_name = None if current_bowler_choice == "Not Selected" else current_bowler_choice

batter_stats = get_batter_stats(connection, league, striker_name) if striker_name else None
bowler_stats = get_bowler_stats(connection, league, bowler_name) if bowler_name else None

league_batting_benchmark = get_league_batting_benchmark(connection, league)
league_bowling_benchmark = get_league_bowling_benchmark(connection, league)

player_adjustment_ratio, player_adjustment_confidence = compute_player_adjustment(
    batter_stats, bowler_stats, league_batting_benchmark, league_bowling_benchmark
)
player_context_active = bool(striker_name or bowler_name)
pitch_context_active = pitch_choice != "Not Selected / Unknown"

combined_adjustment_ratio = max(
    0.80, min(1.30, player_adjustment_ratio * pitch_adjustment_ratio)
)

powerplay_end, death_start = get_phase_boundaries(FULL_INNINGS_OVERS)


# ============================================================
# TOP SCORE (the ONLY place the live score is shown) - instant,
# needs nothing beyond runs/wickets/balls, no database work at all.
# ============================================================

st.html(
    f"""
    <div class="card">
        <h2 style="margin:0">
            {batting_team} {runs}/{wickets}
        </h2>
        <p class="small" style="margin:5px 0 0">
            {display_over(balls)} / {FULL_INNINGS_OVERS} ov
            • {league}
            • Ground: {ground or "—"}
            • Last: {st.session_state.last or "—"}
        </p>
    </div>
    """
)


# ============================================================
# BALL CONTROLS - INSTANT. This is the actual fix for the lag: tapping
# a ball only ever touches st.session_state (runs/wickets/balls/strike
# rotation) and reruns the script - it never runs a database query and
# never touches the historical-similarity search. Updating the score is
# now as fast as Streamlit itself can rerun a script (a fraction of a
# second), regardless of how big the league's database is.
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
                    new_balls = balls + 1
                    st.session_state.balls = new_balls

                    if label == "Wicket":
                        st.session_state.awaiting_new_batsman = True
                        st.session_state.out_slot_index = st.session_state.get("on_strike_index", 0)
                        if on_strike_name and on_strike_name != "Not Selected":
                            st.session_state.dismissed_batsmen.append(on_strike_name)
                    elif int(add_runs or 0) % 2 == 1:
                        st.session_state.on_strike_index = 1 - st.session_state.get("on_strike_index", 0)

                    if new_balls % 6 == 0:
                        st.session_state.on_strike_index = 1 - st.session_state.get("on_strike_index", 0)

                st.session_state.last = label

            st.rerun()

if st.session_state.get("awaiting_new_batsman"):
    out_slot = st.session_state.get("out_slot_index", 0)
    other_slot_name = batsman_b_choice if out_slot == 0 else batsman_a_choice
    dismissed_set = set(st.session_state.get("dismissed_batsmen", []))
    incoming_options = ["Not Selected"] + [
        name for name in batting_roster
        if name not in dismissed_set and name != other_slot_name
    ]
    incoming_choice = st.selectbox(
        f"New batsman in (replacing Batsman {out_slot + 1}):",
        incoming_options,
        key="incoming_batsman_select",
    )
    if st.button("Confirm New Batsman", key="confirm_new_batsman_button"):
        if out_slot == 0:
            st.session_state["persisted_batsman_a"] = incoming_choice
        else:
            st.session_state["persisted_batsman_b"] = incoming_choice
        st.session_state.awaiting_new_batsman = False
        st.session_state.out_slot_index = None
        st.rerun()


# ============================================================
# SCORE TARGET ANALYSIS - just the two inputs here, still instant.
# ============================================================

st.subheader("Score Target Analysis")
st.caption(f"Current: {runs}/{wickets} at over {display_over(balls)}")

check_col4, check_col5 = st.columns(2, gap="small")

with check_col4:
    projection_end_over = st.number_input(
        "Projection End Over",
        min_value=1,
        max_value=FULL_INNINGS_OVERS,
        value=min(int(st.session_state.projection_end_over), FULL_INNINGS_OVERS),
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
        max_value=500,
        value=default_prediction,
        step=1,
        key="score_prediction_widget",
    )

st.session_state.projection_end_over = int(projection_end_over)
st.session_state.score_prediction = int(score_prediction)

window_over = max(int(projection_end_over), (balls + 5) // 6 if balls % 6 else balls // 6)
window_over = min(window_over, FULL_INNINGS_OVERS)
if window_over != int(projection_end_over):
    st.caption(
        f"Note: Over {int(projection_end_over)} is already behind the current "
        f"ball ({display_over(balls)}), so the window was adjusted to Over {window_over}."
    )

window_end_ball = window_over * 6


# ============================================================
# UPDATE PREDICTION - the ONLY thing that runs the historical-
# similarity search. This is the deliberate trade the person asked
# for: scoring stays instant (above), and the heavy calculation - which
# already automatically factors in toss, ground, pitch condition,
# player form, and recency - runs only when this button is pressed, on
# the CURRENT live score at that moment. It also runs once automatically
# on first load so the boxes below are never empty.
# ============================================================

state_signature = (
    league, batting_team, bowling_team, ground, innings_no, int(target),
    runs, wickets, balls, current_toss_role, current_toss_decision,
    window_over, int(st.session_state.score_prediction),
    striker_name, bowler_name, pitch_choice,
)

is_stale = st.session_state.get("prediction_signature") != state_signature

update_clicked = st.button(
    "🔄 Update Prediction (uses the score above)",
    use_container_width=True,
    key="update_prediction_button",
    type="primary",
)

should_compute = update_clicked or "prediction_signature" not in st.session_state

if should_compute:
    full_end_ball = FULL_INNINGS_OVERS * 6

    try:
        full_states = find_similar_states(
            connection=connection,
            league=league,
            innings_no=innings_no,
            current_ball=balls,
            current_runs=runs,
            current_wickets=wickets,
            end_ball=full_end_ball,
            batting_team=batting_team,
            bowling_team=bowling_team,
            ground=ground,
            current_toss_role=current_toss_role,
            current_toss_decision=current_toss_decision,
        )

        full_scores_and_finals = bulk_scores_and_finals(
            connection, league, innings_no,
            [state["match_id"] for state in full_states], full_end_ball,
        )

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
            states=full_states,
            scores_and_finals=full_scores_and_finals,
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
            states=full_states,
            scores_and_finals=full_scores_and_finals,
        )

        full_raw_average = float(full_historical_model["average"])
        full_adjusted_average, full_adjusted_low, full_adjusted_high = apply_adjustment_to_average(
            runs, full_raw_average, full_historical_model["low"], full_historical_model["high"],
            combined_adjustment_ratio,
        )

        st.session_state.full_historical_average = float(full_adjusted_average)
        st.session_state.full_historical_average_raw = float(full_raw_average)
        st.session_state.full_historical_low = int(full_adjusted_low)
        st.session_state.full_historical_high = int(full_adjusted_high)
        st.session_state.full_historical_samples = int(full_historical_model["samples"])

        raw_win_probability = full_match_model["win_probability"]
        if raw_win_probability is not None:
            win_nudge = (combined_adjustment_ratio - 1.0) * 40.0
            adjusted_win_probability = min(99.0, max(1.0, float(raw_win_probability) + win_nudge))
        else:
            adjusted_win_probability = None

        st.session_state.win_probability = adjusted_win_probability
        st.session_state.win_probability_raw = raw_win_probability
        st.session_state.win_samples = int(full_match_model["samples"])

        if window_over == FULL_INNINGS_OVERS:
            # Same window as the full-innings search above - reuse it
            # instead of searching again.
            window_states, window_scores_and_finals = full_states, full_scores_and_finals
        else:
            window_states = find_similar_states(
                connection=connection,
                league=league,
                innings_no=innings_no,
                current_ball=balls,
                current_runs=runs,
                current_wickets=wickets,
                end_ball=window_end_ball,
                batting_team=batting_team,
                bowling_team=bowling_team,
                ground=ground,
                current_toss_role=current_toss_role,
                current_toss_decision=current_toss_decision,
            )
            window_scores_and_finals = bulk_scores_and_finals(
                connection, league, innings_no,
                [state["match_id"] for state in window_states], window_end_ball,
            )

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
            states=window_states,
            scores_and_finals=window_scores_and_finals,
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
            states=window_states,
            scores_and_finals=window_scores_and_finals,
        )

        window_raw_average = float(window_historical_model["average"])
        window_adjusted_average, window_adjusted_low, window_adjusted_high = apply_adjustment_to_average(
            runs, window_raw_average, window_historical_model["low"], window_historical_model["high"],
            combined_adjustment_ratio,
        )

        st.session_state.window_cross_chance = float(window_check_result["yes"])
        st.session_state.window_stay_chance = float(window_check_result["no"])
        st.session_state.window_samples = int(window_check_result["samples"])
        st.session_state.window_historical_average = float(window_adjusted_average)
        st.session_state.window_historical_average_raw = float(window_raw_average)
        st.session_state.window_historical_low = int(window_adjusted_low)
        st.session_state.window_historical_high = int(window_adjusted_high)
        st.session_state.window_historical_samples = int(window_historical_model["samples"])

        st.session_state.prediction_signature = state_signature

    except Exception as error:
        st.error("Prediction calculation failed.")
        st.exception(error)

elif is_stale:
    st.caption(
        "⚠️ Score or settings changed since the last update - tap "
        "'Update Prediction' to refresh the boxes below."
    )
else:
    st.caption("✅ Prediction is up to date with the current score.")


# ============================================================
# RESULT BOX 1: VASUDEV PREDICTION (window-scoped)
# ============================================================

window_confidence_label = (
    "High"
    if int(st.session_state.window_historical_samples) >= 150
    else "Medium"
    if int(st.session_state.window_historical_samples) >= 40
    else "Low"
)

cross = float(st.session_state.window_cross_chance)
under = float(st.session_state.window_stay_chance)
result_class = "positive" if cross >= under else "negative"

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
        situations
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
        </div>
    </div>
    """
)


# ============================================================
# RESULT BOX 2: TEAM WINNING RESULT (whole innings, this league's format)
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
                • Based on {fmt_int(win_samples)} historical situations
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
# EVERYTHING ELSE - tucked into one collapsed expander
# ============================================================

with st.expander("More Insights & Details", expanded=False):

    # --- Match Context ---
    st.write("#### Match Context")

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
        st.metric("Required Run Rate", f"{required_run_rate:.2f}" if required_run_rate is not None else "—")
    with context_columns[2]:
        st.metric("Momentum (last 2 ov)", f"{recent_run_rate:.2f}" if recent_run_rate is not None else "—")

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

    # --- Player Form ---
    if player_context_active:
        st.write("#### Player Form")
        player_columns = st.columns(2, gap="small")

        with player_columns[0]:
            if batter_stats:
                avg_text = f"{batter_stats['average']:.1f}" if batter_stats["average"] is not None else "Not out yet"
                st.markdown(
                    f"**{striker_name}** — SR: **{batter_stats['strike_rate']:.1f}** • "
                    f"Avg: **{avg_text}**  \n"
                    f"<span class='small'>{fmt_int(batter_stats['balls'])} balls faced, "
                    f"{fmt_int(batter_stats['matches'])} matches in {league}</span>",
                    unsafe_allow_html=True,
                )
            elif striker_name:
                st.caption(f"No historical data found for {striker_name} in {league}.")

        with player_columns[1]:
            if bowler_stats:
                st.markdown(
                    f"**{bowler_name}** — Economy: **{bowler_stats['economy']:.2f}** • "
                    f"Wickets: **{fmt_int(bowler_stats['wickets'])}**  \n"
                    f"<span class='small'>{fmt_int(bowler_stats['balls'])} balls bowled, "
                    f"{fmt_int(bowler_stats['matches'])} matches in {league}</span>",
                    unsafe_allow_html=True,
                )
            elif bowler_name:
                st.caption(f"No historical data found for {bowler_name} in {league}.")

    if player_context_active or pitch_context_active:
        st.caption(
            f"Combined adjustment applied to the boxes above: "
            f"×{combined_adjustment_ratio:.3f} on remaining runs "
            f"(player factor ×{player_adjustment_ratio:.3f}, "
            f"pitch factor ×{pitch_adjustment_ratio:.3f})."
        )

    # --- Score Trajectory Chart ---
    st.write("#### Score Trajectory")

    try:
        phase_rates = get_phase_par_rates(connection, league, innings_no, powerplay_end, death_start)
    except Exception:
        phase_rates = {"powerplay": 7.5, "middle": 7.8, "death": 9.5}

    try:
        match_trajectory = build_match_trajectory(
            current_ball=balls,
            current_runs=runs,
            window_end_over=window_over,
            target_total=float(st.session_state.window_historical_average),
            phase_rates=phase_rates,
            powerplay_end=powerplay_end,
            death_start=death_start,
        )
        par_trajectory = build_par_trajectory(window_over, phase_rates, powerplay_end, death_start)

        all_overs = sorted(set(list(match_trajectory.keys()) + list(par_trajectory.keys())))
        chart_df = pd.DataFrame({"Over": all_overs})
        chart_df["Your Match (Projected)"] = chart_df["Over"].map(match_trajectory)
        chart_df["League Average Pace"] = chart_df["Over"].map(par_trajectory)
        chart_df = chart_df.set_index("Over")

        st.line_chart(chart_df)
        st.caption(
            f"Powerplay (overs 1-{powerplay_end}): {phase_rates['powerplay']:.1f} rpo • "
            f"Middle (overs {powerplay_end + 1}-{death_start}): {phase_rates['middle']:.1f} rpo • "
            f"Death (overs {death_start + 1}-{FULL_INNINGS_OVERS}): {phase_rates['death']:.1f} rpo"
        )
    except Exception:
        st.info("Trajectory chart could not be built for this situation.")

    # --- Full Breakdown ---
    st.write("#### Full Breakdown")
    st.write(f"**League:** {league} ({FULL_INNINGS_OVERS}-over format)")
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
    st.write(f"**Pitch Condition:** {pitch_choice}")

    st.write("---")
    st.write(f"**Score Prediction Window: Over {window_over}**")
    st.write(
        f"- Historical Average, team-only (by Over {window_over}): "
        f"{float(st.session_state.window_historical_average_raw):.1f}"
    )
    st.write(
        f"- Historical Average, adjusted (by Over {window_over}): "
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

    st.write("---")
    st.write(f"**Full-Innings Projection ({FULL_INNINGS_OVERS} overs)** — used for Winner estimate only")
    st.write(f"- Historical Average, team-only: {float(st.session_state.full_historical_average_raw):.1f}")
    st.write(f"- Historical Average, adjusted: {float(st.session_state.full_historical_average):.1f}")
    st.write(
        f"- Historical Range: "
        f"{int(st.session_state.full_historical_low)} - "
        f"{int(st.session_state.full_historical_high)}"
    )
    st.write(f"- Similar Historical Samples: {fmt_int(st.session_state.full_historical_samples)}")

    if final_win_probability is not None:
        st.write(f"- **{batting_team} Win Probability (adjusted):** {float(final_win_probability):.1f}%")
        if st.session_state.win_probability_raw is not None:
            st.write(f"- {batting_team} Win Probability (team-only): {float(st.session_state.win_probability_raw):.1f}%")
        st.write(f"- **{bowling_team} Win Probability (adjusted):** {100.0 - float(final_win_probability):.1f}%")
        st.write(f"- Based on {fmt_int(win_samples)} historical situations")

    if innings_no == 2 and int(target) > 0:
        st.write(f"**Target:** {int(target)}")

    st.write(
        "**Similarity Context used everywhere above:** Over/Ball + Runs + "
        "Wickets + Run Rate + Batting Team + Bowling Team + Ground + Toss "
        "(winner + decision) + Innings + Recency. Player form and Pitch "
        "Condition are separate bounded nudges applied on top, not part of "
        "the similarity search itself."
    )


st.caption(
    "Historical estimate only. This is not a guarantee of the live match result."
)


# Save the current state so a browser refresh restores it instead of
# resetting to login/defaults. Only explicit Logout clears this.
save_persisted_session()
