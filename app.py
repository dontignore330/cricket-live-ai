# VasuDev Cricket AI - "ENGINE v1" app.py
#
# What changed (short):
#   * NEW ENGINE (replaces the lookalike-averaging that kept giving
#     ~50-50): a trained remaining-runs regression + logistic win models
#     + ELO team ratings. Every factor below now changes the result:
#     wickets in hand, current batters, last 2-3 overs momentum, league
#     phase par (death-overs scoring), ground + ground death-overs record
#     + boundary size, pitch, bowlers (current bowler AND team death
#     attack), head-to-head, batter-vs-bowler history, day/night dew,
#     Impact-Player era, new-batter effect.
#   * DATABASE BUG FIXED: the old builder mislabelled balls after wides
#     / no-balls and dropped the last delivery of such overs, so
#     historical scores were slightly low. Legal-ball counting is now
#     correct. Existing databases are rebuilt ONCE automatically.
#   * Prediction is a formula now (~1 ms) - no Update button, everything
#     refreshes on every ball instantly.
#   * "Engine report" (in the details expander) shows out-of-sample
#     accuracy numbers measured on real history for the selected league.

import bisect
import hmac
import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
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
    "recent_balls", "pending_extras", "bsw",
    "projection_end_over", "score_prediction",
    "persisted_league", "persisted_batting_team", "persisted_bowling_team",
    "persisted_ground", "persisted_ground_manual", "persisted_innings_label",
    "persisted_batsman_a", "persisted_batsman_a_manual",
    "persisted_batsman_b", "persisted_batsman_b_manual",
    "persisted_current_bowler", "persisted_current_bowler_manual",
    "persisted_pitch_condition", "persisted_dew",
    "persisted_batting_xi", "persisted_bowling_xi",
    "on_strike_index", "dismissed_batsmen", "awaiting_new_batsman", "out_slot_index",
    "batter_live", "bowler_live", "partnership_runs", "this_over", "over_history",
    "live_mode_on", "live_matches", "live_selected_id", "live_match_raw",
    "live_ingested_keys", "live_last_fetch_note",
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

def team_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip())
    return slug.strip("_")


DATABASES = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db",
    "ODI Cricket (International)": BASE / "odi_history.db",
}

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
    # Direct competition-level archive - all international men's ODIs.
    "ODI Cricket (International)": "https://cricsheet.org/downloads/odis_male_json.zip",
}

RESTRICT_TEAMS = {}

# Format-aware: overs per innings for each league.
LEAGUE_FORMAT_OVERS = {
    "IPL": 20,
    "Men's Big Bash League": 20,
    "Women's Big Bash League": 20,
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

# Manual pitch-behaviour multiplier on the projected remaining runs.
# The GROUND's normal scoring level is already learned from data, so
# these only express how today's surface differs from that ground's norm.
# Cricsheet has no pitch-type data, so these are judgement values, not
# fitted ones.
PITCH_CONDITIONS = {
    "Normal / Not sure": 1.00,
    "Batting Paradise (very flat, high-scoring)": 1.08,
    "Good for Batting (flat, true bounce)": 1.04,
    "Slow & Low (hard to score freely)": 0.94,
    "Seam-Friendly / Green Top": 0.93,
    "Spin-Friendly / Dry & Turning": 0.94,
    "Two-Paced / Tricky": 0.92,
}

# Dew (evening games): helps the chasing side. Judgement values.
DEW_OPTIONS = {
    "No dew / day game": "none",
    "Some dew": "some",
    "Heavy dew": "heavy",
}

# Per-league training settings: recency half-life (years), the season
# from which a rule change lifted scoring (IPL Impact Player, 2023),
# ELO between-season carry-over, and a cap on how many of the most
# recent matches are used (keeps training memory small on a tiny server).
ENGINE_CFG = {
    "IPL": {"half_life": 4.0, "era_start": 2023, "elo_keep": 0.75, "cap": None},
    "Men's Big Bash League": {"half_life": 5.0, "era_start": None, "elo_keep": 0.75, "cap": None},
    "Women's Big Bash League": {"half_life": 5.0, "era_start": None, "elo_keep": 0.75, "cap": None},
    "ODI Cricket (International)": {"half_life": 4.0, "era_start": None, "elo_keep": 0.90, "cap": 700},
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

SCHEMA_VERSION = "3"


def display_over(total_balls):
    try:
        total_balls = int(total_balls)
    except Exception:
        return "0.0"
    if total_balls <= 0:
        return "0.0"
    overs, balls_in_over = divmod(total_balls, 6)
    return f"{overs}.{balls_in_over}"


def over_to_balls(text):
    """'3.4' -> 22 legal balls. '0.0' -> 0. '20.0' -> 120."""
    try:
        over_text, ball_text = str(text).strip().split(".", 1)
        over, ball = int(over_text), int(ball_text)
        if over < 0 or ball < 0 or ball > 6:
            return None
        return over * 6 + ball
    except Exception:
        return None


def get_table_names(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def get_table_columns(connection, table_name):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def database_is_valid(database_path, league):
    """Valid = right tables, right columns AND schema_version 3 (the
    version with correct legal-ball counting). Older databases fail this
    check on purpose, which triggers one clean rebuild."""
    if not database_path.exists() or database_path.stat().st_size == 0:
        return False

    connection = None
    try:
        connection = sqlite3.connect(str(database_path), timeout=30)
        tables = get_table_names(connection)
        if not {"matches", "deliveries", "meta"}.issubset(tables):
            return False

        version = connection.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if not version or str(version[0]) != SCHEMA_VERSION:
            return False

        delivery_columns = get_table_columns(connection, "deliveries")
        match_columns = get_table_columns(connection, "matches")
        required_delivery = {
            "match_id", "innings_no", "batting_team", "bowling_team", "over_no",
            "ball_pos", "runs", "wickets", "league", "batter", "bowler",
            "batter_runs", "player_out", "legal", "bowler_runs", "bowler_wkts",
        }
        required_match = {
            "match_id", "venue", "winner", "league", "season", "match_overs", "dls",
        }
        if not required_delivery.issubset(delivery_columns):
            return False
        if not required_match.issubset(match_columns):
            return False

        delivery_count = connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE league=?", (league,)
        ).fetchone()[0]
        match_count = connection.execute(
            "SELECT COUNT(*) FROM matches WHERE league=?", (league,)
        ).fetchone()[0]
        return int(delivery_count) > 0 and int(match_count) > 0
    except Exception:
        return False
    finally:
        if connection is not None:
            connection.close()


# ============================================================
# DATABASE BUILDER (v3)
# ============================================================

BOWLER_WICKET_KINDS = {
    "bowled", "caught", "lbw", "stumped", "caught and bowled", "hit wicket",
}


def create_indexes(connection):
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_del_state ON deliveries(league, innings_no, ball_pos)",
        "CREATE INDEX IF NOT EXISTS idx_del_match ON deliveries(match_id, innings_no, ball_pos)",
        "CREATE INDEX IF NOT EXISTS idx_del_batter ON deliveries(league, batter)",
        "CREATE INDEX IF NOT EXISTS idx_del_bowler ON deliveries(league, bowler)",
        "CREATE INDEX IF NOT EXISTS idx_del_pair ON deliveries(league, batter, bowler)",
        "CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)",
        "CREATE INDEX IF NOT EXISTS idx_matches_venue ON matches(league, venue)",
    ):
        connection.execute(statement)


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
            """CREATE TABLE matches(
                match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT,
                season INTEGER, toss_winner TEXT, toss_decision TEXT,
                match_overs INTEGER, dls INTEGER)"""
        )
        connection.execute(
            """CREATE TABLE deliveries(
                id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, innings_no INTEGER,
                batting_team TEXT, bowling_team TEXT, over_no INTEGER, ball_no TEXT,
                ball_pos INTEGER, runs INTEGER, wickets INTEGER, league TEXT,
                batter TEXT, bowler TEXT, batter_runs INTEGER, player_out TEXT,
                legal INTEGER, bowler_runs INTEGER, bowler_wkts INTEGER)"""
        )
        connection.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")

        match_rows, delivery_rows = [], []
        json_files_seen = 0
        seen_match_ids = set()

        def flush_deliveries():
            connection.executemany(
                """INSERT INTO deliveries(match_id, innings_no, batting_team, bowling_team,
                    over_no, ball_no, ball_pos, runs, wickets, league, batter, bowler,
                    batter_runs, player_out, legal, bowler_runs, bowler_wkts)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                delivery_rows,
            )
            delivery_rows.clear()

        def flush_matches():
            connection.executemany(
                """INSERT OR REPLACE INTO matches(match_id, venue, winner, league, season,
                    toss_winner, toss_decision, match_overs, dls) VALUES(?,?,?,?,?,?,?,?,?)""",
                match_rows,
            )
            match_rows.clear()

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
                            names = {str(t).strip().lower() for t in teams}
                            if not names.issubset(restrict_teams):
                                continue
                        seen_match_ids.add(match_id)

                        outcome = info.get("outcome", {}) or {}
                        winner = str(outcome.get("winner", "") or "")
                        dls = 1 if outcome.get("method") else 0
                        venue = str(info.get("venue", "") or "")
                        toss = info.get("toss", {}) or {}

                        season_year = None
                        digits = "".join(ch for ch in str(info.get("season", "") or "") if ch.isdigit())
                        if len(digits) >= 4:
                            season_year = int(digits[:4])
                        if season_year is None:
                            dates = info.get("dates") or []
                            if dates:
                                try:
                                    season_year = int(str(dates[0])[:4])
                                except (ValueError, TypeError):
                                    season_year = None

                        match_overs = info.get("overs")
                        try:
                            match_overs = int(match_overs)
                        except (TypeError, ValueError):
                            match_overs = 0

                        innings_list = data.get("innings", []) or []
                        pending = []
                        for innings_no, innings in enumerate(innings_list, start=1):
                            if innings.get("super_over"):
                                continue
                            batting_team = str(innings.get("team", "") or "")
                            bowling_team = next((t for t in teams if t != batting_team), "")
                            legal_count = 0
                            for over_data in innings.get("overs", []) or []:
                                over_no = int(over_data.get("over", 0) or 0)
                                for delivery in over_data.get("deliveries", []) or []:
                                    extras = delivery.get("extras") or {}
                                    is_legal = 0 if ("wides" in extras or "noballs" in extras) else 1
                                    legal_count += is_legal

                                    runs_block = delivery.get("runs") or {}
                                    runs = int(runs_block.get("total", 0) or 0)
                                    batter_runs = int(runs_block.get("batter", 0) or 0)
                                    charged = batter_runs + int(extras.get("wides", 0) or 0) + int(extras.get("noballs", 0) or 0)

                                    wicket_list = delivery.get("wickets") or []
                                    bowler_w = sum(
                                        1 for wk in wicket_list
                                        if str(wk.get("kind", "")).lower() in BOWLER_WICKET_KINDS
                                    )
                                    player_out = (
                                        str(wicket_list[0].get("player_out", "") or "") if wicket_list else ""
                                    )
                                    pending.append((
                                        match_id, innings_no, batting_team, bowling_team, over_no,
                                        f"{over_no}.{legal_count}", legal_count, runs, len(wicket_list),
                                        league, str(delivery.get("batter", "") or ""),
                                        str(delivery.get("bowler", "") or ""), batter_runs, player_out,
                                        is_legal, charged, bowler_w,
                                    ))

                        delivery_rows.extend(pending)
                        match_rows.append((
                            match_id, venue, winner, league, season_year,
                            str(toss.get("winner", "") or ""),
                            str(toss.get("decision", "") or "").lower(),
                            match_overs, dls,
                        ))
                        if len(match_rows) >= 200:
                            flush_matches()
                        if len(delivery_rows) >= 20000:
                            flush_deliveries()
                    except Exception:
                        continue

        if match_rows:
            flush_matches()
        if delivery_rows:
            flush_deliveries()

        connection.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (SCHEMA_VERSION,))
        create_indexes(connection)
        connection.commit()

        if json_files_seen == 0:
            raise RuntimeError(f"No usable JSON match files found for {league}.")
        delivery_count = connection.execute("SELECT COUNT(*) FROM deliveries WHERE league=?", (league,)).fetchone()[0]
        match_count = connection.execute("SELECT COUNT(*) FROM matches WHERE league=?", (league,)).fetchone()[0]
        if int(delivery_count) == 0 or int(match_count) == 0:
            raise RuntimeError(f"{league} archive(s) downloaded but no usable match data was built.")
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
        return database_path

    if database_path.exists():
        try:
            database_path.unlink()
        except Exception:
            pass
    # A stale engine file belongs to the old database - remove it too.
    engine_file = engine_path_for(league)
    if engine_file.exists():
        try:
            engine_file.unlink()
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
            archive_paths, failed_sources = [], []
            for index, url in enumerate(url_list):
                archive_path = Path(temp_directory) / f"matches_{index}.zip"
                try:
                    download_archive(url, archive_path)
                    archive_paths.append(archive_path)
                except Exception as download_error:
                    failed_sources.append((url, str(download_error)))

            if not archive_paths:
                raise RuntimeError(
                    f"Could not download any source archive for {league}. Failures: {failed_sources}"
                )

            build_database(building_path, league, archive_paths, restrict_teams=restrict_teams)

            if is_merge_league and failed_sources:
                st.session_state.setdefault("league_build_warnings", {})
                st.session_state["league_build_warnings"][league] = [u for u, _ in failed_sources]

        if not database_is_valid(building_path, league):
            raise RuntimeError(f"{league} database build completed but validation failed.")

        building_path.replace(database_path)
        return database_path
    except Exception:
        if building_path.exists():
            building_path.unlink()
        raise


@st.cache_resource
def get_connection(database_path_text):
    connection = sqlite3.connect(
        f"file:{Path(database_path_text).resolve()}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=120,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-12000")
    return connection


def engine_path_for(league):
    slug = re.sub(r"[^a-z0-9]+", "_", league.lower()).strip("_")
    return BASE / f"engine_{slug}.json"
# ============================================================
# VASUDEV ENGINE v1  (no streamlit dependency)
# ============================================================
#
# Replaces the old "lookalike averaging" engine.
#
#  RUNS MODEL (per innings): weighted ridge regression that predicts the
#  runs still to come over ANY horizon H (next over, next 6 overs, rest
#  of innings) from: league phase par, pace vs par, last 2 overs
#  momentum, wickets lost, new-batter effect, ground scoring / death /
#  boundary record, batting-team and bowling-attack strength (death and
#  non-death), ELO gap and era (Impact Player). The spread comes from
#  OUT-OF-FOLD residual quantiles (real, not assumed-normal).
#
#  WIN MODELS (logistic regression, IRLS):
#   1st innings: P(bat-first wins | final score) fitted on real results
#     (score vs ground par, ELO gap, head-to-head, ground chase bias),
#     integrated over the predicted final-score distribution.
#   2nd innings: P(chase wins) from (predicted remaining runs - needed)
#     / spread, ELO gap, head-to-head, wickets, required rate.
#
#  ELO: chronological, with between-season regression to the mean.
#  Everything is cross-fitted by match (5 folds) so the reported
#  Brier / MAE numbers are out-of-sample.

import json
import math
import sqlite3
import time

import numpy as np
import pandas as pd

ENGINE_VERSION = 1
N_FOLDS = 5
Q_GRID = np.arange(1, 100) / 100.0
H_BIN_EDGES = [6, 12, 24, 36, 60, 84, 120, 180, 300]

FEATURE_NAMES = [
    "par", "pace", "mom", "wk", "wk_late", "newbat",
    "g_nd", "g_d", "g_bnd",
    "bat_nd", "bowl_nd", "bat_d", "bowl_d",
    "elo", "era", "rate",
]

FEATURE_GROUPS = {
    "Phase par (league scoring curve)": ["par", "rate"],
    "Scoring pace vs par": ["pace"],
    "Last 2-3 overs momentum": ["mom"],
    "Wickets lost / in hand": ["wk", "wk_late"],
    "New batter effect": ["newbat"],
    "Ground scoring + boundary size": ["g_nd", "g_bnd"],
    "Ground death-overs record": ["g_d"],
    "Batting team strength": ["bat_nd", "bat_d"],
    "Bowling attack (incl. death bowlers)": ["bowl_nd", "bowl_d"],
    "Team rating (ELO)": ["elo"],
    "Era (Impact Player etc.)": ["era"],
}


# ------------------------------------------------------------
# small math helpers
# ------------------------------------------------------------

def sigmoid(x):
    x = np.clip(x, -30, 30)
    return 1.0 / (1.0 + np.exp(-x))


def fit_ridge(X, y, w, alpha=50.0):
    w = np.asarray(w, dtype=np.float64)
    w = w / w.mean()
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    sw = w.sum()
    mu = (X * w[:, None]).sum(0) / sw
    sd = np.sqrt((((X - mu) ** 2) * w[:, None]).sum(0) / sw)
    sd[sd < 1e-9] = 1.0
    Z = (X - mu) / sd
    ym = (w * y).sum() / sw
    A = Z.T @ (Z * w[:, None]) + alpha * np.eye(X.shape[1])
    b = Z.T @ (w * (y - ym))
    coef = np.linalg.solve(A, b)
    return {"mu": mu, "sd": sd, "coef": coef, "intercept": float(ym)}


def ridge_predict(M, X):
    return M["intercept"] + ((np.asarray(X, dtype=np.float64) - M["mu"]) / M["sd"]) @ M["coef"]


def fit_logistic(X, y, w=None, l2=1.0, iters=30):
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n, k = X.shape
    w = np.ones(n) if w is None else np.asarray(w, dtype=np.float64)
    w = w / w.mean()
    Xb = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    pen = np.eye(k + 1) * l2
    pen[0, 0] = 0.0
    for _ in range(iters):
        eta = Xb @ beta
        p = sigmoid(eta)
        W = w * p * (1 - p) + 1e-9
        grad = Xb.T @ (w * (y - p)) - pen @ beta
        hess = Xb.T @ (Xb * W[:, None]) + pen
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-7:
            break
    return beta


def logistic_predict(beta, X):
    X = np.asarray(X, dtype=np.float64)
    return sigmoid(beta[0] + X @ beta[1:])


def brier(p, y, w=None):
    p = np.asarray(p); y = np.asarray(y)
    e = (p - y) ** 2
    return float(np.average(e, weights=w))


def logloss(p, y, w=None):
    p = np.clip(np.asarray(p), 1e-4, 1 - 1e-4); y = np.asarray(y)
    e = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    return float(np.average(e, weights=w))


def calibration_table(p, y, bins=10):
    p = np.asarray(p); y = np.asarray(y)
    out = []
    edges = np.linspace(0, 1, bins + 1)
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        if m.sum() >= 30:
            out.append([round(float(p[m].mean()), 3), round(float(y[m].mean()), 3), int(m.sum())])
    return out


# ------------------------------------------------------------
# feature builder (shared by training and live prediction)
# ------------------------------------------------------------

def make_features(b, r, w, last_r, last_n, bsw, H, T, par_cum, d_start, ctx):
    """All arguments are numpy arrays of the same length (or scalars
    broadcast). Returns (n, len(FEATURE_NAMES)) float matrix."""
    b = np.asarray(b, dtype=np.int64)
    r = np.asarray(r, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)
    last_r = np.asarray(last_r, dtype=np.float64)
    last_n = np.asarray(last_n, dtype=np.int64)
    bsw = np.asarray(bsw, dtype=np.float64)
    H = np.asarray(H, dtype=np.int64)

    e = np.minimum(b + H, T)
    He = (e - b).astype(np.float64)
    par_h = par_cum[e] - par_cum[b]
    p = par_cum[T] / T
    par_b = par_cum[b]
    pace_ratio = (r + 12.0 * p) / (par_b + 12.0 * p)
    par_last = par_cum[b] - par_cum[np.maximum(b - last_n, 0)]
    mom_ratio = (last_r + 6.0 * p) / (par_last + 6.0 * p)

    d_h = np.maximum(0, e - np.maximum(b, d_start)).astype(np.float64)
    nd_h = He - d_h

    nb = np.where(bsw < 99, np.maximum(0.0, 12.0 - bsw) / 12.0, 0.0)

    cols = [
        par_h,
        (pace_ratio - 1.0) * par_h,
        (mom_ratio - 1.0) * par_h,
        w * He / 6.0,
        np.maximum(0.0, w - 5.0) * He / 6.0,
        nb * np.minimum(He, 12.0) / 6.0,
        ctx["g_nd"] * nd_h / 6.0,
        ctx["g_d"] * d_h / 6.0,
        ctx["g_bnd"] * He / 6.0,
        ctx["bat_nd"] * nd_h / 6.0,
        ctx["bowl_nd"] * nd_h / 6.0,
        ctx["bat_d"] * d_h / 6.0,
        ctx["bowl_d"] * d_h / 6.0,
        ctx["elo"] / 100.0 * He / 6.0,
        ctx["era"] * He / 6.0,
        He / 6.0,
    ]
    return np.column_stack([np.broadcast_to(c, b.shape).astype(np.float64) for c in cols])


def train_config(T):
    if T <= 130:
        return 6, [6, 12, 18, 24, 30, 36, 48, 60, 72, 90, 108]
    return 12, [6, 12, 24, 36, 60, 90, 120, 180, 240]


def _shrunk(sum_num, sum_den, L, K):
    return (sum_num + K * L) / (sum_den + K)


def _loo(df, key, num, den, L, K, wcol="w"):
    w = df[wcol]
    n_ = w * df[num]
    d_ = w * df[den]
    gn = n_.groupby(df[key]).transform("sum")
    gd = d_.groupby(df[key]).transform("sum")
    return (gn - n_ + K * L) / (gd - d_ + K)


# ------------------------------------------------------------
# training
# ------------------------------------------------------------

def train_engine(db_path, league, T_overs, pp_end, death_over, half_life,
                 era_start=None, elo_keep=0.75, cap=None, log=print):
    t0 = time.time()
    T = int(T_overs) * 6
    d_start = int(death_over) * 6

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    m = pd.read_sql_query(
        "SELECT rowid AS mid, match_id, venue, winner, season, match_overs, dls "
        "FROM matches WHERE league=?", con, params=(league,))
    m = m[(m.match_overs == T_overs) & (m.dls == 0) & m.season.notna()].copy()
    m["idnum"] = pd.to_numeric(m.match_id, errors="coerce").fillna(0)
    m = m.sort_values(["season", "idnum"])
    if cap:
        m = m.tail(int(cap))
    m = m.reset_index(drop=True)
    if len(m) < 60:
        con.close()
        raise RuntimeError(f"Only {len(m)} usable full-length matches found for {league}; need at least 60.")

    def _query_by_match_batches(sql_template, match_ids, extra_params=()):
        """Run sql_template (with a {ph} placeholder for the IN-clause and
        a leading `league` param already baked in by the caller) against
        only the given match_id batch, chunked to stay well under any
        SQLite build's bound-variable limit, and concatenate the results.
        This is THE fix for the memory crash: only matches actually kept
        in `m` after filtering/capping are ever pulled into pandas -
        never the league's entire history."""
        frames = []
        batch_size = 500
        for start in range(0, len(match_ids), batch_size):
            batch = match_ids[start:start + batch_size]
            placeholders = ",".join("?" for _ in batch)
            frames.append(pd.read_sql_query(
                sql_template.format(ph=placeholders), con, params=(*extra_params, *batch)))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    match_id_list = m.match_id.tolist()
    d = _query_by_match_batches(
        "SELECT m.rowid AS mid, d.innings_no AS inn, d.over_no AS ov, d.runs, "
        "d.wickets AS wk, d.batter_runs AS br, d.legal "
        "FROM deliveries d JOIN matches m ON m.match_id=d.match_id AND m.league=d.league "
        "WHERE d.league=? AND d.match_id IN ({ph}) ORDER BY d.id",
        match_id_list, extra_params=(league,))
    teams = _query_by_match_batches(
        "SELECT m.rowid AS mid, d.innings_no AS inn, MIN(d.batting_team) AS bat, "
        "MIN(d.bowling_team) AS bowl FROM deliveries d JOIN matches m "
        "ON m.match_id=d.match_id AND m.league=d.league "
        "WHERE d.league=? AND d.match_id IN ({ph}) GROUP BY m.rowid, d.innings_no",
        match_id_list, extra_params=(league,))
    con.close()
    log(f"loaded {len(m)} matches, {len(d)} deliveries in {time.time()-t0:.1f}s")

    d = d[d.inn.isin([1, 2])].reset_index(drop=True)
    for c in ("ov", "runs", "wk", "br", "legal"):
        d[c] = d[c].astype(np.int32)

    latest = int(m.season.max())
    m["w"] = 0.5 ** (np.maximum(0, latest - m.season) / half_life)
    if era_start:
        m["w"] = m["w"] * np.where(m.season < era_start, 0.6, 1.0)

    # ---- innings ids ----
    key = d.mid.values.astype(np.int64) * 4 + d.inn.values
    iid, uniq = pd.factorize(key)
    iid = iid.astype(np.int64)
    n_inn = len(uniq)
    d["iid"] = iid
    g = d.groupby("iid", sort=False)
    d["lb"] = g.legal.cumsum()
    d["cr"] = g.runs.cumsum()
    d["cw"] = g.wk.cumsum()

    is_d = (d.ov.values >= death_over)
    legal = d.legal.values
    runs_v = d.runs.values
    bnd = (((d.br.values == 4) | (d.br.values == 6)) & (legal == 1)).astype(np.float64)

    runs_tot = np.bincount(iid, weights=runs_v, minlength=n_inn)
    balls_tot = np.bincount(iid, weights=legal, minlength=n_inn)
    nd_runs = np.bincount(iid, weights=runs_v * (~is_d), minlength=n_inn)
    nd_balls = np.bincount(iid, weights=legal * (~is_d), minlength=n_inn)
    bnd_tot = np.bincount(iid, weights=bnd, minlength=n_inn)

    inn = pd.DataFrame({
        "iid": np.arange(n_inn), "mid": (uniq // 4).astype(np.int64), "inn": (uniq % 4).astype(np.int64),
        "runs_tot": runs_tot, "balls_tot": balls_tot,
        "nd_runs": nd_runs, "nd_balls": nd_balls,
        "d_runs": runs_tot - nd_runs, "d_balls": balls_tot - nd_balls, "bnd": bnd_tot,
    })
    inn = inn.merge(teams, on=["mid", "inn"], how="left")
    inn = inn.merge(m[["mid", "season", "venue", "winner", "w"]], on="mid", how="left")
    inn["one"] = 1.0
    inn = inn[inn.bat.notna()].reset_index(drop=True)

    # league baselines (weighted, per ball)
    W = inn.w
    L_nd = (W * inn.nd_runs).sum() / (W * inn.nd_balls).sum()
    L_d = (W * inn.d_runs).sum() / max(1.0, (W * inn.d_balls).sum())
    L_b = (W * inn.bnd).sum() / (W * inn.balls_tot).sum()

    # ---- per-over league par curve, per innings ----
    par_cum = {}
    par_rate_over = {}
    w_row = d.mid.map(m.set_index("mid").w).values
    for k in (1, 2):
        mk = d.inn.values == k
        ov = np.minimum(d.ov.values[mk], T_overs - 1)
        num = np.bincount(ov, weights=runs_v[mk] * w_row[mk], minlength=T_overs)
        den = np.bincount(ov, weights=legal[mk] * w_row[mk], minlength=T_overs)
        rate = np.where(den > 0, num / np.maximum(den, 1e-9), num.sum() / max(den.sum(), 1e-9))
        par_rate_over[k] = rate
        per_ball = np.repeat(rate, 6)[:T]
        par_cum[k] = np.concatenate([[0.0], np.cumsum(per_ball)])

    # ---- ground stats (LOO for training rows) ----
    K_G_ND, K_G_D, K_G_B = 600.0, 150.0, 600.0
    inn["g_nd"] = (_loo(inn, "venue", "nd_runs", "nd_balls", L_nd, K_G_ND) - L_nd) * 6.0
    inn["g_d"] = (_loo(inn, "venue", "d_runs", "d_balls", L_d, K_G_D) - L_d) * 6.0
    inn["g_bnd"] = (_loo(inn, "venue", "bnd", "balls_tot", L_b, K_G_B) - L_b) * 100.0

    # ---- team-season stats (unweighted, LOO) ----
    K_T_ND, K_T_D = 300.0, 90.0
    inn["bkey"] = inn.bat.astype(str) + "|" + inn.season.astype(int).astype(str)
    inn["wkey"] = inn.bowl.astype(str) + "|" + inn.season.astype(int).astype(str)
    Lu_nd = inn.nd_runs.sum() / inn.nd_balls.sum()
    Lu_d = inn.d_runs.sum() / max(1.0, inn.d_balls.sum())
    inn["bat_nd"] = (_loo(inn, "bkey", "nd_runs", "nd_balls", Lu_nd, K_T_ND, "one") - Lu_nd) * 6.0
    inn["bat_d"] = (_loo(inn, "bkey", "d_runs", "d_balls", Lu_d, K_T_D, "one") - Lu_d) * 6.0
    inn["bowl_nd"] = (_loo(inn, "wkey", "nd_runs", "nd_balls", Lu_nd, K_T_ND, "one") - Lu_nd) * 6.0
    inn["bowl_d"] = (_loo(inn, "wkey", "d_runs", "d_balls", Lu_d, K_T_D, "one") - Lu_d) * 6.0

    # ---- match level frame (bat first / second) ----
    i1 = inn[inn.inn == 1].set_index("mid")
    i2 = inn[inn.inn == 2].set_index("mid")
    mm = m.set_index("mid").join(i1[["bat", "bowl", "runs_tot"]].rename(
        columns={"bat": "bat1", "bowl": "bat2x", "runs_tot": "F1"}), how="inner")
    mm = mm.join(i2[["bat", "runs_tot"]].rename(columns={"bat": "bat2", "runs_tot": "F2"}), how="left")
    mm = mm.reset_index().sort_values(["season", "idnum"]).reset_index(drop=True)
    mm["bat2"] = mm.bat2.fillna(mm.bat2x)

    # ---- ELO + head-to-head (chronological, point-in-time) ----
    ratings, h2h, pre = {}, {}, {}
    last_season = None
    for row in mm.itertuples():
        if last_season is not None and row.season != last_season:
            for t in ratings:
                ratings[t] = 1500.0 + (ratings[t] - 1500.0) * elo_keep
        last_season = row.season
        a, b_ = row.bat1, row.bat2
        ra, rb = ratings.get(a, 1500.0), ratings.get(b_, 1500.0)
        k_ = (a, b_) if a < b_ else (b_, a)
        wins = h2h.get(k_, [0, 0])
        wa = wins[0] if a == k_[0] else wins[1]
        wb = wins[1] if a == k_[0] else wins[0]
        pre[row.mid] = (ra - rb, (wa - wb) / (wa + wb + 4.0))
        if row.winner in (a, b_):
            exp_a = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
            s_a = 1.0 if row.winner == a else 0.0
            ratings[a] = ra + 20.0 * (s_a - exp_a)
            ratings[b_] = rb - 20.0 * (s_a - exp_a)
            idx = 0 if row.winner == k_[0] else 1
            wins = list(wins); wins[idx] += 1
            h2h[k_] = wins
        else:
            h2h.setdefault(k_, wins)

    mm["elo1"] = mm.mid.map(lambda x: pre[x][0])
    mm["h2h1"] = mm.mid.map(lambda x: pre[x][1])

    # ---- home venue detection (purely from data - no hand-typed mapping) ----
    # A team's "home" venue is one it plays at far more often than the
    # league average team does, with enough matches there to be sure it
    # is not a fluke. This naturally finds Wankhede for MI, Eden Gardens
    # for KKR, etc. without anyone maintaining a list, and a team with no
    # clear home venue (or a genuinely neutral ground) just gets none.
    venue_team_ct = {}
    venue_total_ct = {}
    for row in mm.itertuples():
        venue_total_ct[row.venue] = venue_total_ct.get(row.venue, 0) + 1
        for t in (row.bat1, row.bat2):
            venue_team_ct.setdefault(row.venue, {})
            venue_team_ct[row.venue][t] = venue_team_ct[row.venue].get(t, 0) + 1
    team_candidates = {}
    for venue, counts in venue_team_ct.items():
        total = venue_total_ct[venue]
        for team, cnt in counts.items():
            share = cnt / total
            team_candidates.setdefault(team, []).append((venue, cnt, share))
    team_home = {}
    for team, cands in team_candidates.items():
        eligible = [(v, c, s) for v, c, s in cands if c >= 6 and s >= 0.35]
        if eligible:
            eligible.sort(key=lambda x: -x[1])
            team_home[team] = eligible[0][0]

    def home_flag(team, venue):
        return 1.0 if team_home.get(team) == venue else 0.0

    mm["home_adv"] = [
        home_flag(r.bat1, r.venue) - home_flag(r.bat2, r.venue) for r in mm.itertuples()
    ]

    # ---- ground first-innings par + chase bias (LOO) on match frame ----
    mm["decided"] = (mm.winner == mm.bat1) | (mm.winner == mm.bat2)
    mm["bf_win"] = (mm.winner == mm.bat1).astype(float)
    mm["one"] = 1.0
    LF = (mm.w * mm.F1).sum() / mm.w.sum()
    dec = mm[mm.decided].copy()
    Lbf = (dec.w * dec.bf_win).sum() / dec.w.sum()
    mm["G1"] = _loo(mm, "venue", "F1", "one", LF, 5.0)
    dec["gbias"] = (_loo(dec, "venue", "bf_win", "one", Lbf, 8.0) - Lbf)
    mm = mm.merge(dec[["mid", "gbias"]], on="mid", how="left")
    mm["gbias"] = mm.gbias.fillna(0.0)

    # ---- per innings context arrays ----
    fold_m = (mm.mid % N_FOLDS).astype(int)
    mm = mm.assign(fold=fold_m)
    mm_idx = mm.set_index("mid")
    inn = inn[inn.mid.isin(mm.mid)].reset_index(drop=True)
    # re-map iid to positional index of legal frame
    old2new = -np.ones(n_inn, dtype=np.int64)
    old2new[inn.iid.values] = np.arange(len(inn))
    d["iid2"] = old2new[d.iid.values]
    d = d[d.iid2 >= 0].reset_index(drop=True)
    d["iid"] = d.iid2
    n_inn2 = len(inn)

    elo_i = np.where(inn.inn.values == 1, inn.mid.map(lambda x: pre[x][0]).values,
                     -inn.mid.map(lambda x: pre[x][0]).values)
    h2h_i = np.where(inn.inn.values == 1, inn.mid.map(lambda x: pre[x][1]).values,
                     -inn.mid.map(lambda x: pre[x][1]).values)
    home_i = np.array([
        home_flag(bat, ven) - home_flag(bowl, ven)
        for bat, bowl, ven in zip(inn.bat.values, inn.bowl.values, inn.venue.values)
    ])
    era_i = (inn.season.values >= era_start).astype(float) if era_start else np.zeros(n_inn2)
    fold_i = (inn.mid.values % N_FOLDS).astype(int)
    w_i = inn.w.values
    T_i = inn.balls_tot.values.astype(np.int64)
    fin_i = inn.runs_tot.values
    inn_no = inn.inn.values
    winner_i = inn.winner.values
    bat_i = inn.bat.values
    chase_won_i = (inn_no == 2) & (winner_i == bat_i)
    # first-innings final per innings (for target)
    f1_map = dict(zip(mm.mid.values, mm.F1.values))
    target_i = inn.mid.map(f1_map).values + 1.0

    ctx_i = {
        "g_nd": inn.g_nd.values, "g_d": inn.g_d.values, "g_bnd": inn.g_bnd.values,
        "bat_nd": inn.bat_nd.values, "bowl_nd": inn.bowl_nd.values,
        "bat_d": inn.bat_d.values, "bowl_d": inn.bowl_d.values,
        "elo": elo_i, "era": era_i,
    }

    # ---- legal frame ----
    lmask = d.legal.values == 1
    iid_l = d.iid.values[lmask]
    lb_l = d.lb.values[lmask].astype(np.int64)
    cr_l = d.cr.values[lmask].astype(np.float64)
    cw_l = d.cw.values[lmask].astype(np.int64)
    KM = T + 16
    key_l = iid_l.astype(np.int64) * KM + lb_l
    order = np.argsort(key_l, kind="stable")
    iid_l, lb_l, cr_l, cw_l, key_l = iid_l[order], lb_l[order], cr_l[order], cw_l[order], key_l[order]
    prev_cw = np.roll(cw_l, 1)
    same = np.roll(iid_l, 1) == iid_l
    prev_cw = np.where(same, prev_cw, 0)
    event = cw_l > prev_cw
    last_w = pd.Series(np.where(event, lb_l, 0)).groupby(iid_l).cummax().values
    bsw_l = np.where(last_w > 0, lb_l - last_w, 99).astype(np.float64)

    step, Hs = train_config(T)
    cp_mask = (lb_l % step == 0) & (lb_l < T_i[iid_l])
    cp_iid = iid_l[cp_mask]
    cp_b = lb_l[cp_mask]
    cp_r = cr_l[cp_mask]
    cp_w = cw_l[cp_mask]
    cp_bsw = bsw_l[cp_mask]
    cp_key = key_l[cp_mask]
    prev_pos = np.searchsorted(key_l, cp_key - 12)
    prev_pos = np.minimum(prev_pos, len(key_l) - 1)
    cr_prev = np.where(cp_b > 12, cr_l[prev_pos], 0.0)
    cp_last_r = cp_r - cr_prev
    cp_last_n = np.minimum(12, cp_b)
    # b = 0 checkpoints
    z_iid = np.arange(n_inn2)[T_i > 0]
    cp_iid = np.concatenate([z_iid, cp_iid])
    cp_b = np.concatenate([np.zeros(len(z_iid), dtype=np.int64), cp_b])
    cp_r = np.concatenate([np.zeros(len(z_iid)), cp_r])
    cp_w = np.concatenate([np.zeros(len(z_iid), dtype=np.int64), cp_w])
    cp_bsw = np.concatenate([np.full(len(z_iid), 99.0), cp_bsw])
    cp_last_r = np.concatenate([np.zeros(len(z_iid)), cp_last_r])
    cp_last_n = np.concatenate([np.zeros(len(z_iid), dtype=np.int64), cp_last_n])
    keep = cp_w < 10
    cp_iid, cp_b, cp_r, cp_w, cp_bsw, cp_last_r, cp_last_n = (
        cp_iid[keep], cp_b[keep], cp_r[keep], cp_w[keep], cp_bsw[keep], cp_last_r[keep], cp_last_n[keep])

    def runs_at(iid_arr, e_arr):
        pos = np.searchsorted(key_l, iid_arr.astype(np.int64) * KM + e_arr)
        pos = np.minimum(pos, len(key_l) - 1)
        ok = key_l[pos] == iid_arr.astype(np.int64) * KM + e_arr
        return np.where(ok, cr_l[pos], np.nan)

    def expand(inn_k):
        sel = inn_no[cp_iid] == inn_k
        parts = []
        for H in Hs + [None]:
            Hv = (T - cp_b[sel]) if H is None else np.full(sel.sum(), H, dtype=np.int64)
            okH = (cp_b[sel] + Hv) <= T
            idx = np.where(sel)[0][okH]
            parts.append((idx, Hv[okH]))
        idx = np.concatenate([p[0] for p in parts])
        Hv = np.concatenate([p[1] for p in parts])
        return idx, Hv

    rng = np.random.default_rng(7)
    models, resid_tab, oof_store = {}, {}, {}
    metrics = {"n_matches": int(len(mm)), "seasons": [int(m.season.min()), int(m.season.max())]}

    for k in (1, 2):
        idx, Hv = expand(k)
        if len(idx) > 260000:
            sub = rng.choice(len(idx), 260000, replace=False)
            idx, Hv = idx[sub], Hv[sub]
        ii = cp_iid[idx]
        b_ = cp_b[idx]; r_ = cp_r[idx]
        e_ = b_ + Hv
        ra = runs_at(ii, e_)
        finished_early = e_ >= T_i[ii]
        y = np.where(finished_early, fin_i[ii] - r_, ra - r_)
        valid = ~np.isnan(y)
        if k == 2:
            valid &= ~(chase_won_i[ii] & (e_ > T_i[ii]))
        ctx = {kk: v[ii] for kk, v in ctx_i.items()}
        X = make_features(b_, r_, cp_w[idx], cp_last_r[idx], cp_last_n[idx], cp_bsw[idx], Hv, T, par_cum[k], d_start, ctx)
        X, y, ii, Hv, b_, r_ = X[valid], y[valid], ii[valid], Hv[valid], b_[valid], r_[valid]
        wts = w_i[ii]
        fo = fold_i[ii]
        oof = np.zeros(len(y))
        fold_models = []
        for f in range(N_FOLDS):
            tr = fo != f
            Mf = fit_ridge(X[tr], y[tr], wts[tr])
            fold_models.append(Mf)
            oof[~tr] = ridge_predict(Mf, X[~tr])
        Mall = fit_ridge(X, y, wts)
        res = y - oof
        He = np.minimum(b_ + Hv, T) - b_
        qs = []
        edges = H_BIN_EDGES
        for bi, hi in enumerate(edges):
            lo = edges[bi - 1] if bi > 0 else 0
            mk = (He > lo) & (He <= hi)
            if mk.sum() >= 300:
                qs.append(np.quantile(res[mk], Q_GRID))
            else:
                qs.append(None)
        # fill empties with nearest
        for bi in range(len(qs)):
            if qs[bi] is None:
                cand = [j for j in range(len(qs)) if qs[j] is not None]
                if cand:
                    j = min(cand, key=lambda z: abs(z - bi))
                    qs[bi] = qs[j]
                else:
                    qs[bi] = np.quantile(res, Q_GRID)
        models[k] = Mall
        resid_tab[k] = np.array(qs)
        oof_store[k] = (fold_models,)

        # metrics: end-horizon MAE vs naive pace projection (innings 1 clean)
        end_m = (b_ + Hv) == T
        rep = {}
        for bb in (36, 60, 84, 102) if T == 120 else (60, 120, 180, 240):
            mk = end_m & (b_ == bb)
            if mk.sum() >= 50:
                naive = r_[mk] * T / bb - r_[mk]
                rep[str(bb)] = {
                    "n": int(mk.sum()),
                    "mae_model": round(float(np.mean(np.abs(res[mk]))), 2),
                    "mae_naive": round(float(np.mean(np.abs(y[mk] - naive))), 2),
                }
        metrics[f"runs_inn{k}"] = rep
        log(f"innings {k} runs model: {len(y)} rows, {time.time()-t0:.1f}s")

    # ---- W1: first innings win (match level logistic on true F) ----
    d1 = mm[mm.decided].copy()
    X1 = np.column_stack([
        (d1.F1.values - d1.G1.values) / 10.0,
        d1.elo1.values / 100.0,
        d1.h2h1.values,
        d1.gbias.values * 10.0,
        d1.home_adv.values,
    ])
    y1 = d1.bf_win.values
    w1 = d1.w.values
    f1 = d1.fold.values
    p1 = np.zeros(len(y1))
    for f in range(N_FOLDS):
        tr = f1 != f
        bt = fit_logistic(X1[tr], y1[tr], w1[tr], l2=2.0)
        p1[~tr] = logistic_predict(bt, X1[~tr])
    beta1 = fit_logistic(X1, y1, w1, l2=2.0)
    base = float(np.average(y1, weights=w1))
    metrics["w1"] = {
        "n": int(len(y1)), "brier": round(brier(p1, y1, w1), 4),
        "brier_baseline": round(brier(np.full(len(y1), base), y1, w1), 4),
        "logloss": round(logloss(p1, y1, w1), 4), "base_rate": round(base, 3),
        "calibration": calibration_table(p1, y1),
    }

    # ---- W2: chase win (checkpoint level logistic) ----
    sel2 = inn_no[cp_iid] == 2
    idx2 = np.where(sel2)[0]
    ii = cp_iid[idx2]
    win_ok = np.isin(winner_i[ii], [bat_i[ii]]) | (winner_i[ii] == inn.bowl.values[ii])
    idx2, ii = idx2[win_ok], ii[win_ok]
    b_ = cp_b[idx2]; r_ = cp_r[idx2]; w_ = cp_w[idx2]
    needed = target_i[ii] - r_
    okr = (needed > 0) & (T - b_ > 0)
    idx2, ii, b_, r_, w_, needed = idx2[okr], ii[okr], b_[okr], r_[okr], w_[okr], needed[okr]
    Hend = T - b_
    ctx = {kk: v[ii] for kk, v in ctx_i.items()}
    Xe = make_features(b_, r_, w_, cp_last_r[idx2], cp_last_n[idx2], cp_bsw[idx2], Hend, T, par_cum[2], d_start, ctx)
    fo = fold_i[ii]
    mu_end = np.zeros(len(ii))
    for f in range(N_FOLDS):
        mk = fo == f
        if mk.any():
            mu_end[mk] = ridge_predict(oof_store[2][0][f], Xe[mk])
    edges = H_BIN_EDGES
    binidx = np.minimum(np.searchsorted(edges, Hend, side="left"), len(edges) - 1)
    q2 = resid_tab[2]
    sig_end = np.maximum((q2[binidx, 83] - q2[binidx, 15]) / 2.0, 1.0)
    par_rpo = par_cum[2][T] / T * 6.0
    rrr = needed * 6.0 / Hend
    X2 = np.column_stack([
        (mu_end - needed) / sig_end,
        ctx["elo"] / 100.0,
        h2h_i[ii],
        (10 - w_) / 10.0,
        (rrr - par_rpo) / 4.0,
        home_i[ii],
    ])
    y2 = chase_won_i[ii].astype(float)
    w2 = w_i[ii]
    f2 = fo
    p2 = np.zeros(len(y2))
    for f in range(N_FOLDS):
        tr = f2 != f
        bt = fit_logistic(X2[tr], y2[tr], w2[tr], l2=2.0)
        p2[~tr] = logistic_predict(bt, X2[~tr])
    beta2 = fit_logistic(X2, y2, w2, l2=2.0)
    base2 = float(np.average(y2, weights=w2))
    stage = {}
    for bb in ((0, 36, 60, 84, 102) if T == 120 else (0, 60, 120, 180, 240)):
        mk = b_ == bb
        if mk.sum() >= 50:
            stage[str(bb)] = {"n": int(mk.sum()), "brier": round(brier(p2[mk], y2[mk]), 4),
                              "brier_baseline": round(brier(np.full(mk.sum(), base2), y2[mk]), 4)}
    metrics["w2"] = {
        "n": int(len(y2)), "brier": round(brier(p2, y2, w2), 4),
        "brier_baseline": round(brier(np.full(len(y2), base2), y2, w2), 4),
        "logloss": round(logloss(p2, y2, w2), 4), "base_rate": round(base2, 3),
        "calibration": calibration_table(p2, y2), "by_ball": stage,
    }

    # ---- inference tables ----
    inn_all = inn.copy()
    gnd = {}
    for v, grp in inn_all.groupby("venue"):
        ww = grp.w
        gnd[str(v)] = {
            "g_nd": float((_shrunk((ww * grp.nd_runs).sum(), (ww * grp.nd_balls).sum(), L_nd, K_G_ND) - L_nd) * 6.0),
            "g_d": float((_shrunk((ww * grp.d_runs).sum(), (ww * grp.d_balls).sum(), L_d, K_G_D) - L_d) * 6.0),
            "g_bnd": float((_shrunk((ww * grp.bnd).sum(), (ww * grp.balls_tot).sum(), L_b, K_G_B) - L_b) * 100.0),
            "n": int(len(grp) // 2),
        }
    ms = mm.groupby("venue")
    for v, grp in ms:
        ww = grp.w
        e = gnd.setdefault(str(v), {"g_nd": 0.0, "g_d": 0.0, "g_bnd": 0.0, "n": 0})
        e["G1"] = float((( ww * grp.F1).sum() + 5.0 * LF) / (ww.sum() + 5.0))
        dg = grp[grp.decided]
        if len(dg):
            e["gbias"] = float(((dg.w * dg.bf_win).sum() + 8.0 * Lbf) / (dg.w.sum() + 8.0) - Lbf)
        else:
            e["gbias"] = 0.0
    team = {}
    latest_by_team = {}
    for t in set(inn_all.bat.unique()) | set(inn_all.bowl.unique()):
        sb = inn_all[inn_all.bat == t]
        sw = inn_all[inn_all.bowl == t]
        seasons = []
        if len(sb): seasons.append(sb.season.max())
        if len(sw): seasons.append(sw.season.max())
        ls = max(seasons)
        sb = sb[sb.season == ls]; sw = sw[sw.season == ls]
        team[str(t)] = {
            "bat_nd": float((_shrunk(sb.nd_runs.sum(), sb.nd_balls.sum(), Lu_nd, K_T_ND) - Lu_nd) * 6.0),
            "bat_d": float((_shrunk(sb.d_runs.sum(), sb.d_balls.sum(), Lu_d, K_T_D) - Lu_d) * 6.0),
            "bowl_nd": float((_shrunk(sw.nd_runs.sum(), sw.nd_balls.sum(), Lu_nd, K_T_ND) - Lu_nd) * 6.0),
            "bowl_d": float((_shrunk(sw.d_runs.sum(), sw.d_balls.sum(), Lu_d, K_T_D) - Lu_d) * 6.0),
            "season": int(ls),
        }

    # league phase baselines for player factors (per legal ball)
    ov_all = np.minimum(d.ov.values, T_overs - 1)
    phase = np.where(ov_all < pp_end, 0, np.where(ov_all < death_over, 1, 2))
    lg_bat = [float(np.sum(d.br.values[(phase == p) & (legal == 1)]) / max(1, np.sum((phase == p) & (legal == 1)))) for p in range(3)]
    lg_bowl = [float(np.sum(runs_v[(phase == p) & (legal == 1)]) / max(1, np.sum((phase == p) & (legal == 1)))) for p in range(3)]

    out = {
        "version": ENGINE_VERSION, "league": league, "T": T, "T_overs": int(T_overs),
        "pp_end": int(pp_end), "death_over": int(death_over), "d_start": int(d_start),
        "latest_season": latest, "era_start": era_start,
        "par_cum": {str(k): par_cum[k].tolist() for k in par_cum},
        "par_rate_over": {str(k): par_rate_over[k].tolist() for k in par_rate_over},
        "models": {str(k): {kk: (v.tolist() if hasattr(v, "tolist") else v) for kk, v in models[k].items()} for k in models},
        "resid": {str(k): resid_tab[k].tolist() for k in resid_tab},
        "w1": beta1.tolist(), "w2": beta2.tolist(),
        "ground": gnd, "team": team,
        "elo": {str(k): float(v) for k, v in ratings.items()},
        "h2h": {f"{a}|{b}": v for (a, b), v in h2h.items()},
        "team_home": team_home,
        "league_first_mean": float(LF), "bat_first_win_rate": float(Lbf),
        "lg_bat_ball": lg_bat, "lg_bowl_ball": lg_bowl,
        "metrics": metrics, "train_seconds": round(time.time() - t0, 1),
    }
    log(f"done in {time.time()-t0:.1f}s")
    return out


# ------------------------------------------------------------
# inference
# ------------------------------------------------------------

def prepare_engine(raw):
    E = dict(raw)
    E["par_cum_np"] = {int(k): np.array(v) for k, v in raw["par_cum"].items()}
    E["models_np"] = {}
    for k, mdl in raw["models"].items():
        E["models_np"][int(k)] = {"mu": np.array(mdl["mu"]), "sd": np.array(mdl["sd"]),
                                  "coef": np.array(mdl["coef"]), "intercept": float(mdl["intercept"])}
    E["resid_np"] = {int(k): np.array(v) for k, v in raw["resid"].items()}
    E["w1_np"] = np.array(raw["w1"]); E["w2_np"] = np.array(raw["w2"])
    return E


def _resid_row(E, inn, He):
    tab = E["resid_np"][inn]
    bi = int(min(np.searchsorted(H_BIN_EDGES, He, side="left"), len(H_BIN_EDGES) - 1))
    return tab[bi]


def home_advantage(E, batting_team, bowling_team, ground):
    th = E.get("team_home", {})
    bat_home = 1.0 if th.get(batting_team) == ground else 0.0
    bowl_home = 1.0 if th.get(bowling_team) == ground else 0.0
    return bat_home - bowl_home, bat_home, bowl_home


def team_ctx(E, batting_team, bowling_team, ground, innings, squad=None):
    """squad (optional): {"bat_nd","bat_d","bat_conf","bowl_nd","bowl_d","bowl_conf"} -
    computed from the announced Playing XI. Blended with the team's own
    season average by confidence (0 = no XI data, use team average as
    before; 1 = fully trust the named XI)."""
    g = E["ground"].get(ground or "", {})
    tb = E["team"].get(batting_team, {})
    tw = E["team"].get(bowling_team, {})
    eb = E["elo"].get(batting_team, 1500.0)
    ew = E["elo"].get(bowling_team, 1500.0)
    era = 1.0 if (E.get("era_start") and E["latest_season"] >= E["era_start"]) else 0.0
    a, b_ = batting_team, bowling_team
    k_ = (a, b_) if a < b_ else (b_, a)
    wins = E["h2h"].get(f"{k_[0]}|{k_[1]}", [0, 0])
    wa = wins[0] if a == k_[0] else wins[1]
    wb = wins[1] if a == k_[0] else wins[0]
    h2h = (wa - wb) / (wa + wb + 4.0)

    bat_nd, bat_d = tb.get("bat_nd", 0.0), tb.get("bat_d", 0.0)
    bowl_nd, bowl_d = tw.get("bowl_nd", 0.0), tw.get("bowl_d", 0.0)
    if squad:
        bc = float(squad.get("bat_conf", 0.0))
        wc = float(squad.get("bowl_conf", 0.0))
        if bc > 0:
            bat_nd = bc * squad["bat_nd"] + (1 - bc) * bat_nd
            bat_d = bc * squad["bat_d"] + (1 - bc) * bat_d
        if wc > 0:
            bowl_nd = wc * squad["bowl_nd"] + (1 - wc) * bowl_nd
            bowl_d = wc * squad["bowl_d"] + (1 - wc) * bowl_d

    home_adv, bat_home, bowl_home = home_advantage(E, batting_team, bowling_team, ground)
    return {
        "g_nd": g.get("g_nd", 0.0), "g_d": g.get("g_d", 0.0), "g_bnd": g.get("g_bnd", 0.0),
        "bat_nd": bat_nd, "bat_d": bat_d, "bowl_nd": bowl_nd, "bowl_d": bowl_d,
        "elo": eb - ew, "era": era,
    }, h2h, (wa, wb), home_adv, (bat_home, bowl_home)


def mean_runs(E, inn, b, r, w, last_r, last_n, bsw, H, ctx):
    T = E["T"]
    X = make_features(np.array([b]), np.array([r]), np.array([w]), np.array([last_r]),
                      np.array([last_n]), np.array([bsw]), np.array([H]), T,
                      E["par_cum_np"][inn], E["d_start"], {k: np.array([v]) for k, v in ctx.items()})
    M = E["models_np"][inn]
    mu = float(ridge_predict(M, X)[0])
    contrib = (M["coef"] * X[0] / M["sd"])
    return max(mu, 0.0), contrib


def phase_of(E, over_idx):
    if over_idx < E["pp_end"]:
        return 0
    if over_idx < E["death_over"]:
        return 1
    return 2


def player_delta(E, b, mu_h, H_eff, bat_info, bowl_info, match_info):
    """Bounded, shrunk player effect on the projection (heuristic weights).
    bat_info: list of (weight, runs, balls) per batter for the CURRENT phase;
    bowl_info: (runs_conceded, balls); match_info: list of (weight, runs, balls) striker-vs-bowler."""
    T = E["T"]
    par = E["par_cum_np"][1]
    ph = phase_of(E, b // 6)
    l_bat = E["lg_bat_ball"][ph]
    l_bowl = E["lg_bowl_ball"][ph]
    stretch = max(6, int(0.2 * T))
    hb = min(H_eff, stretch)
    e_stretch = (par[min(b + hb, T)] - par[b])
    delta = 0.0
    notes = []
    bat_ratio = 1.0
    if bat_info:
        num = 0.0; den = 0.0
        for wgt, runs, balls in bat_info:
            sh = (runs + 40.0 * l_bat) / (balls + 40.0)
            num += wgt * (sh / max(l_bat, 1e-6)); den += wgt
        bat_ratio = num / den if den else 1.0
        d_bat = (bat_ratio - 1.0) * e_stretch * 0.5
        delta += d_bat
        notes.append(("Current batters (phase strike rate, shrunk)", d_bat))
    bowl_ratio = 1.0
    if bowl_info:
        runs, balls = bowl_info
        sh = (runs + 48.0 * l_bowl) / (balls + 48.0)
        bowl_ratio = sh / max(l_bowl, 1e-6)
        left_in_over = 6 - (b % 6) if (b % 6) else 6
        ho = min(H_eff, left_in_over)
        e_over = par[min(b + ho, T)] - par[b]
        d_bowl = (bowl_ratio - 1.0) * e_over * 0.6
        delta += d_bowl
        notes.append(("Current bowler (phase economy, shrunk)", d_bowl))
        if match_info:
            num = 0.0; den = 0.0
            for wgt, mr, mb in match_info:
                expected = l_bat * bat_ratio * bowl_ratio
                sh = (mr + 18.0 * expected) / (mb + 18.0)
                num += wgt * (sh / max(expected, 1e-6)); den += wgt
            mratio = num / den if den else 1.0
            d_m = (mratio - 1.0) * e_over * 0.3
            delta += d_m
            notes.append(("Batter vs bowler history", d_m))
    cap = 0.12 * mu_h
    delta = max(-cap, min(cap, delta))
    return delta, notes


def predict(E, s):
    """s keys: innings, b, r, w, last_r, last_n, bsw, window_over, line,
    batting_team, bowling_team, ground, target, pitch_mult, dew_level,
    player (dict or None), squad (dict or None, from Playing XI)."""
    T = E["T"]
    inn = int(s["innings"])
    b = min(int(s["b"]), T); r = float(s["r"]); w = min(int(s["w"]), 10)
    ctx, h2h, (wa, wb), home_adv, (bat_home, bowl_home) = team_ctx(
        E, s["batting_team"], s["bowling_team"], s.get("ground", ""), inn, squad=s.get("squad")
    )
    common = (E, inn, b, r, w, s["last_r"], s["last_n"], s["bsw"])

    innings_over = (w >= 10) or (b >= T)
    H_end = 0 if innings_over else max(0, T - b)
    win_end = int(min(max(s["window_over"] * 6, b), T))
    H_win = 0 if innings_over else max(0, win_end - b)

    pitch = float(s.get("pitch_mult", 1.0))
    dew = {"none": 1.0, "some": 1.03, "heavy": 1.06}.get(s.get("dew_level", "none"), 1.0) if inn == 2 else 1.0
    mult = pitch * dew

    out = {"b": b, "r": r, "w": w, "T": T}
    contribs = None
    results = {}
    for tag, H in (("end", H_end), ("win", H_win)):
        if H <= 0:
            results[tag] = {"mu": 0.0, "grid": np.zeros(len(Q_GRID))}
            continue
        mu, contrib = mean_runs(*common, H, ctx)
        adj_pitch = mu * (mult - 1.0)
        mu_adj = mu * mult
        pl_delta, notes = 0.0, []
        if s.get("player"):
            pi = s["player"]
            pl_delta, notes = player_delta(E, b, mu_adj, H, pi.get("bat"), pi.get("bowl"), pi.get("match"))
        mu_final = max(0.0, mu_adj + pl_delta)
        q = _resid_row(E, inn, H)
        grid = np.maximum(0.0, mu_final + q)
        results[tag] = {"mu": mu_final, "mu_raw": mu, "grid": grid, "pitch_dew": adj_pitch,
                        "player": pl_delta, "notes": notes, "contrib": contrib, "H": H}
        if tag == "end":
            contribs = contrib

    win = results["win"]
    out["window_over"] = win_end // 6 if win_end % 6 == 0 else win_end / 6.0
    out["window_expected"] = r + win["mu"]
    out["window_p10"] = r + float(np.percentile(win["grid"], 10))
    out["window_p90"] = r + float(np.percentile(win["grid"], 90))
    line = float(s.get("line", 0))
    if H_win > 0:
        need = line - r
        # P(y >= need) with continuity correction
        g = np.sort(win["grid"])
        p_reach = float(1.0 - np.interp(need - 0.5, g, Q_GRID, left=0.0, right=1.0))
        out["p_reach"] = min(0.995, max(0.005, p_reach))
    else:
        out["p_reach"] = 1.0 if r >= line else 0.0

    end = results["end"]
    out["final_expected"] = r + end["mu"]
    out["final_p10"] = r + float(np.percentile(end["grid"], 10))
    out["final_p90"] = r + float(np.percentile(end["grid"], 90))

    # ---- win probability ----
    wp = None
    dew_shift = {"none": 0.0, "some": 0.15, "heavy": 0.35}.get(s.get("dew_level", "none"), 0.0)
    if inn == 1:
        gr = E["ground"].get(s.get("ground", ""), {})
        G1 = gr.get("G1", E["league_first_mean"])
        gbias = gr.get("gbias", 0.0)
        F = r + end["grid"]
        X = np.column_stack([(F - G1) / 10.0, np.full(len(F), ctx["elo"] / 100.0),
                             np.full(len(F), h2h), np.full(len(F), gbias * 10.0),
                             np.full(len(F), home_adv)])
        p = float(np.mean(logistic_predict(E["w1_np"], X)))
        p = float(sigmoid(np.log(p / (1 - p)) - dew_shift))
        wp = p
    else:
        tgt = float(s.get("target", 0))
        if tgt > 0:
            need = tgt - r
            if need <= 0:
                wp = 1.0
            elif b >= T or w >= 10:
                wp = 0.0
            else:
                q = _resid_row(E, 2, H_end)
                sig = max((q[83] - q[15]) / 2.0, 1.0)
                par_rpo = E["par_cum_np"][2][T] / T * 6.0
                rrr = need * 6.0 / H_end
                x = np.array([[(end["mu"] - need) / sig, ctx["elo"] / 100.0, h2h,
                               (10 - w) / 10.0, (rrr - par_rpo) / 4.0, home_adv]])
                wp = float(logistic_predict(E["w2_np"], x)[0])
            out["needed"] = need
    out["win_prob"] = None if wp is None else min(0.995, max(0.005, wp))
    out["h2h"] = (wa, wb)
    out["home"] = (bat_home, bowl_home)
    out["par_now"] = float(E["par_cum_np"][inn][b])

    # ---- factor breakdown (runs impact on the rest-of-innings projection) ----
    rows = []
    if contribs is not None:
        for gname, feats in FEATURE_GROUPS.items():
            if gname.startswith("Phase par"):
                continue
            val = sum(contribs[FEATURE_NAMES.index(f)] for f in feats)
            rows.append((gname, float(val)))
        if end.get("pitch_dew"):
            rows.append(("Pitch condition + dew (manual)", float(end["pitch_dew"])))
        for nm, v in end.get("notes", []):
            rows.append((nm, float(v)))
    out["factors"] = sorted(rows, key=lambda x: -abs(x[1]))
    out["end_mu_raw"] = end.get("mu_raw", 0.0)
    return out


def predict_path(E, s):
    """Expected score + 10/90 range at the end of every remaining over."""
    T = E["T"]
    inn = int(s["innings"]); b = min(int(s["b"]), T); r = float(s["r"]); w = min(int(s["w"]), 10)
    ctx, _, _ = team_ctx(E, s["batting_team"], s["bowling_team"], s.get("ground", ""), inn)
    if w >= 10:
        return []
    ends = [e for e in range(((b // 6) + 1) * 6, T + 1, 6)]
    if not ends:
        return []
    Hs = np.array([e - b for e in ends])
    n = len(Hs)
    X = make_features(np.full(n, b), np.full(n, r), np.full(n, w), np.full(n, s["last_r"]),
                      np.full(n, s["last_n"]), np.full(n, s["bsw"]), Hs, T,
                      E["par_cum_np"][inn], E["d_start"], {k: np.full(n, v) for k, v in ctx.items()})
    mu = np.maximum(ridge_predict(E["models_np"][inn], X), 0.0)
    dew = {"none": 1.0, "some": 1.03, "heavy": 1.06}.get(s.get("dew_level", "none"), 1.0) if inn == 2 else 1.0
    mu = mu * float(s.get("pitch_mult", 1.0)) * dew
    rows = []
    for e, m_, H in zip(ends, mu, Hs):
        q = _resid_row(E, inn, int(H))
        rows.append((e // 6, r + m_, r + max(0.0, m_ + q[9]), r + max(0.0, m_ + q[89])))
    return rows


# ============================================================
# CACHED DATABASE LOOKUPS (static per league/team - never per ball)
# ============================================================

@st.cache_data(show_spinner=False)
def get_grounds(_connection, league):
    rows = _connection.execute(
        "SELECT venue, COUNT(*) AS n FROM matches WHERE league=? AND TRIM(COALESCE(venue,''))<>'' "
        "GROUP BY venue ORDER BY n DESC, venue", (league,)).fetchall()
    return [str(r[0]).strip() for r in rows]


@st.cache_data(show_spinner=False)
def get_latest_season(_connection, league):
    row = _connection.execute(
        "SELECT MAX(season) FROM matches WHERE league=? AND season IS NOT NULL", (league,)).fetchone()
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


@st.cache_data(show_spinner=False)
def get_current_teams(_connection, league):
    latest = get_latest_season(_connection, league)

    def teams_for(seasons):
        ph = ",".join("?" for _ in seasons)
        rows = _connection.execute(
            f"SELECT DISTINCT d.batting_team FROM deliveries d JOIN matches m "
            f"ON m.match_id=d.match_id AND m.league=d.league WHERE d.league=? "
            f"AND d.batting_team<>'' AND m.season IN ({ph}) ORDER BY d.batting_team",
            [league, *seasons]).fetchall()
        return [str(r[0]).strip() for r in rows]

    if latest is not None:
        teams = teams_for([latest])
        if len(teams) < 6:
            teams = sorted(set(teams_for([latest, latest - 1])))
        if teams:
            return teams
    rows = _connection.execute(
        "SELECT DISTINCT batting_team FROM deliveries WHERE league=? AND batting_team<>'' "
        "ORDER BY batting_team", (league,)).fetchall()
    return [str(r[0]).strip() for r in rows]


@st.cache_data(show_spinner=False)
def get_team_roster(_connection, league, team, role):
    if not team:
        return []
    column = "batter" if role == "batting" else "bowler"
    team_column = "batting_team" if role == "batting" else "bowling_team"
    latest = get_latest_season(_connection, league)
    lookback = LEAGUE_ROSTER_LOOKBACK_SEASONS.get(league, DEFAULT_ROSTER_LOOKBACK_SEASONS)

    def names_for(seasons):
        ph = ",".join("?" for _ in seasons)
        rows = _connection.execute(
            f"SELECT DISTINCT d.{column} FROM deliveries d JOIN matches m "
            f"ON m.match_id=d.match_id AND m.league=d.league WHERE d.league=? "
            f"AND d.{team_column}=? AND d.{column}<>'' AND m.season IN ({ph}) "
            f"ORDER BY d.{column}", [league, team, *seasons]).fetchall()
        return [str(r[0]).strip() for r in rows]

    if latest is not None:
        names = names_for([latest - k for k in range(lookback)])
        if names:
            return names
    rows = _connection.execute(
        f"SELECT DISTINCT {column} FROM deliveries WHERE league=? AND {team_column}=? "
        f"AND {column}<>'' ORDER BY {column}", (league, team)).fetchall()
    return [str(r[0]).strip() for r in rows]


@st.cache_data(show_spinner=False)
def player_batting_phase(_connection, league, name, pp_end, death_over):
    """{phase: (batter_runs, legal_balls)} + dismissals, for one batter."""
    rows = _connection.execute(
        "SELECT CASE WHEN over_no < ? THEN 0 WHEN over_no < ? THEN 1 ELSE 2 END AS ph, "
        "SUM(batter_runs), SUM(legal), SUM(CASE WHEN player_out=batter THEN 1 ELSE 0 END) "
        "FROM deliveries WHERE league=? AND batter=? GROUP BY ph",
        (pp_end, death_over, league, name)).fetchall()
    out = {0: (0, 0), 1: (0, 0), 2: (0, 0)}
    dis = 0
    for ph, runs, balls, d in rows:
        out[int(ph)] = (int(runs or 0), int(balls or 0))
        dis += int(d or 0)
    return {"phase": out, "dismissals": dis}


@st.cache_data(show_spinner=False)
def player_bowling_phase(_connection, league, name, pp_end, death_over):
    rows = _connection.execute(
        "SELECT CASE WHEN over_no < ? THEN 0 WHEN over_no < ? THEN 1 ELSE 2 END AS ph, "
        "SUM(bowler_runs), SUM(legal), SUM(bowler_wkts) "
        "FROM deliveries WHERE league=? AND bowler=? GROUP BY ph",
        (pp_end, death_over, league, name)).fetchall()
    out = {0: (0, 0), 1: (0, 0), 2: (0, 0)}
    wk = 0
    for ph, runs, balls, w in rows:
        out[int(ph)] = (int(runs or 0), int(balls or 0))
        wk += int(w or 0)
    return {"phase": out, "wickets": wk}


@st.cache_data(show_spinner=False)
def matchup_stats(_connection, league, batter, bowler):
    row = _connection.execute(
        "SELECT SUM(batter_runs), SUM(legal), SUM(CASE WHEN player_out=batter THEN 1 ELSE 0 END) "
        "FROM deliveries WHERE league=? AND batter=? AND bowler=?",
        (league, batter, bowler)).fetchone()
    return (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))


@st.cache_data(show_spinner=False)
def squad_batting_strength(_connection, league, names, pp_end, death_over, lg_bat_ball):
    """Average, shrunk, phase-split batting strength of a named XI, in the
    SAME units as the team-level bat_nd/bat_d features (runs/over vs
    league). Confidence (0-1) reflects how much real ball data backs the
    named players - a freshly-typed / unknown name contributes nothing,
    so an XI of mostly-unknown names safely falls back to the team
    average rather than distorting the projection."""
    if not names:
        return 0.0, 0.0, 0.0
    l_nd = (lg_bat_ball[0] + lg_bat_ball[1]) / 2.0
    l_d = lg_bat_ball[2]
    nd_vals, d_vals, confs = [], [], []
    for name in names:
        stats = player_batting_phase(_connection, league, name, pp_end, death_over)
        ph = stats["phase"]
        nd_runs, nd_balls = ph[0][0] + ph[1][0], ph[0][1] + ph[1][1]
        d_runs, d_balls = ph[2]
        nd_vals.append((nd_runs + 150.0 * l_nd) / (nd_balls + 150.0))
        d_vals.append((d_runs + 40.0 * l_d) / (d_balls + 40.0))
        confs.append(min(1.0, (nd_balls + d_balls) / 220.0))
    conf = sum(confs) / len(confs)
    return (sum(nd_vals) / len(nd_vals) - l_nd) * 6.0, (sum(d_vals) / len(d_vals) - l_d) * 6.0, conf


@st.cache_data(show_spinner=False)
def squad_bowling_strength(_connection, league, names, pp_end, death_over, lg_bowl_ball):
    if not names:
        return 0.0, 0.0, 0.0
    l_nd = (lg_bowl_ball[0] + lg_bowl_ball[1]) / 2.0
    l_d = lg_bowl_ball[2]
    nd_vals, d_vals, confs = [], [], []
    for name in names:
        stats = player_bowling_phase(_connection, league, name, pp_end, death_over)
        ph = stats["phase"]
        nd_runs, nd_balls = ph[0][0] + ph[1][0], ph[0][1] + ph[1][1]
        d_runs, d_balls = ph[2]
        nd_vals.append((nd_runs + 150.0 * l_nd) / (nd_balls + 150.0))
        d_vals.append((d_runs + 40.0 * l_d) / (d_balls + 40.0))
        confs.append(min(1.0, (nd_balls + d_balls) / 220.0))
    conf = sum(confs) / len(confs)
    return (sum(nd_vals) / len(nd_vals) - l_nd) * 6.0, (sum(d_vals) / len(d_vals) - l_d) * 6.0, conf


def build_player_info(connection, E, league, striker, non_striker, bowler, b):
    """Turns the selected players into the phase-specific numbers the
    engine's bounded player adjustment needs. Manual / unknown names have
    no history, so they come out neutral (zero balls)."""
    if not (striker or non_striker or bowler):
        return None
    ph = phase_of(E, b // 6)
    pp, dv = E["pp_end"], E["death_over"]
    bat = []
    for weight, name in ((0.6, striker), (0.4, non_striker)):
        if name:
            stats = player_batting_phase(connection, league, name, pp, dv)
            bat.append((weight, *stats["phase"][ph]))
    bowl = None
    match = []
    if bowler:
        stats = player_bowling_phase(connection, league, bowler, pp, dv)
        bowl = stats["phase"][ph]
        for weight, name in ((0.6, striker), (0.4, non_striker)):
            if name:
                runs, balls, _ = matchup_stats(connection, league, name, bowler)
                match.append((weight, runs, balls))
    return {"bat": bat or None, "bowl": bowl, "match": match or None}


# ============================================================
# ENGINE LOADER (trains once per league, then reads a small JSON)
# ============================================================

@st.cache_resource(show_spinner=False)
def get_engine(league, db_signature):
    path = engine_path_for(league)
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            if raw.get("version") == ENGINE_VERSION and raw.get("db_sig") == db_signature:
                return prepare_engine(raw)
        except Exception:
            pass
    cfg = ENGINE_CFG[league]
    t_overs = LEAGUE_FORMAT_OVERS[league]
    pp, dv = get_phase_boundaries(t_overs)
    raw = train_engine(
        str(DATABASES[league].resolve()), league, t_overs, pp, dv,
        cfg["half_life"], cfg["era_start"], cfg["elo_keep"], cfg["cap"], log=lambda *_: None,
    )
    raw["db_sig"] = db_signature
    try:
        path.write_text(json.dumps(raw))
    except Exception:
        pass
    return prepare_engine(raw)


# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "runs": 0, "wickets": 0, "balls": 0, "last": "New innings",
    "undo_stack": [], "target": 0,
    "recent_balls": [], "pending_extras": 0.0, "bsw": 99,
    "projection_end_over": 6, "score_prediction": 0,
    "on_strike_index": 0, "dismissed_batsmen": [],
    "awaiting_new_batsman": False, "out_slot_index": None,
    "batter_live": {}, "bowler_live": {}, "partnership_runs": 0,
    "this_over": [], "over_history": [],
}
for _key, _value in DEFAULTS.items():
    st.session_state.setdefault(_key, _value)


MANUAL_OPTION_LABEL = "Other / Type manually"


def restored_index(options, persisted_key):
    value = st.session_state.get(persisted_key)
    return options.index(value) if value in options else 0


def select_with_manual_option(label, options, persisted_select_key, persisted_manual_key, widget_key):
    """Selectbox with an 'Other / Type manually' entry for names that are
    not in Cricsheet yet (debutants, new grounds)."""
    combined = list(options) + [MANUAL_OPTION_LABEL]
    choice = st.selectbox(label, combined, index=restored_index(combined, persisted_select_key),
                          key=f"{widget_key}_select")
    st.session_state[persisted_select_key] = choice
    if choice == MANUAL_OPTION_LABEL:
        typed = st.text_input(f"Type {label}", value=st.session_state.get(persisted_manual_key, ""),
                              key=f"{widget_key}_manual").strip()
        st.session_state[persisted_manual_key] = typed
        return typed if typed else "Not Selected"
    st.session_state[persisted_manual_key] = ""
    return choice


# ============================================================
# SIDEBAR - set up once
# ============================================================


# ============================================================
# LIVE CRICKET API MODE (additive - manual mode is untouched)
# ============================================================
#
# Provider: CricketData.org / CricAPI (https://cricapi.com), selected as
# the initial provider per the request. All API-specific code is isolated
# in this section (fetch_live_matches, fetch_match_details,
# fetch_ball_by_ball) so a different provider could be swapped in later
# without touching the prediction engine or the rest of the app.
#
# IMPORTANT CAVEAT (being upfront rather than guessing silently): the
# exact JSON field names below are CricAPI's documented/typical shape at
# the time this was written. Live providers do change field names, and
# this sandbox has no network access to verify against a real response.
# The parsing below is defensive (tries several plausible key names and
# never crashes on a missing field), and the sidebar shows the raw JSON
# in an expander so a mismatch is easy to spot and the key names easy to
# adjust if the provider's actual response differs.
#
# Architecture (per the request, not changed):
#   LIVE API -> actual match state -> existing VasuDev engine ->
#   existing features / Playing-XI / ground / ELO -> existing result
#   boxes. The API NEVER supplies a prediction or win probability -
#   only raw match facts.

LIVE_API_BASE = "https://api.cricapi.com/v1"


def _live_api_get(path, params):
    """One HTTP GET to the live provider. Never raises - returns
    (data_or_None, error_message_or_None). This is the ONLY function that
    talks to the network for live data, so rate-limit/quota control and
    error handling live in exactly one place."""
    api_key = os.environ.get("CRICKET_API_KEY", "").strip()
    if not api_key:
        return None, "CRICKET_API_KEY is not set - Live Mode is unavailable. Manual Mode still works normally."

    query = urllib.parse.urlencode({**params, "apikey": api_key})
    url = f"{LIVE_API_BASE}/{path}?{query}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "VasuDev Cricket AI (Live Mode)"})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_bytes = response.read()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return None, "Live API rejected the request - the API key may be invalid."
        if error.code == 429:
            return None, "Live API quota/rate limit exceeded - try again later."
        return None, f"Live API HTTP error {error.code}."
    except urllib.error.URLError as error:
        return None, f"Live API unreachable ({error.reason}). Check your network/hosting egress."
    except TimeoutError:
        return None, "Live API request timed out."
    except Exception as error:
        return None, f"Live API request failed: {error}"

    try:
        data = json.loads(raw_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "Live API returned a response that could not be parsed (malformed)."

    if isinstance(data, dict) and data.get("status") not in (None, "success"):
        msg = str(data.get("message") or data.get("status") or "unknown error")
        if "quota" in msg.lower() or "limit" in msg.lower():
            return None, f"Live API quota exceeded: {msg}"
        return None, f"Live API error: {msg}"

    return data, None


def fetch_live_matches():
    """Today's / currently live matches. Returns (list_of_matches, error)."""
    data, error = _live_api_get("currentMatches", {"offset": 0})
    if error:
        return [], error
    matches = data.get("data") if isinstance(data, dict) else None
    if not isinstance(matches, list):
        return [], "Live API response had no usable match list."
    return matches, None


def fetch_match_details(match_id):
    """Full detail for one match: teams, venue, toss, playing XI if the
    provider includes it, and the score array (per-innings r/w/o).
    Returns (raw_dict_or_None, error)."""
    if not match_id:
        return None, "No match selected."
    data, error = _live_api_get("match_info", {"id": match_id})
    if error:
        return None, error
    info = data.get("data") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        return None, "Live API returned no match details for this match."
    return info, None


def fetch_ball_by_ball(match_id):
    """Best-effort ball-by-ball for the current innings. Many free-tier
    plans on this provider do not expose this endpoint - if it is not
    available, this returns (None, note) rather than inventing deliveries,
    and the caller falls back to syncing the cumulative score only."""
    if not match_id:
        return None, "No match selected."
    data, error = _live_api_get("match_bbb", {"id": match_id})
    if error:
        return None, "Ball-by-ball not available from this API plan/endpoint - using the cumulative score only."
    info = data.get("data") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        return None, "Ball-by-ball response had no usable data - using the cumulative score only."
    return info, None


def _normalize_name(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def match_name_to_roster(api_name, roster_options):
    """Fuzzy-match an API team/ground name to one already in this
    league's historical data. Returns the matching roster string, or None
    if nothing is confident enough - callers must NOT guess further than
    this; None means 'ask the person to pick it manually'."""
    if not api_name or not roster_options:
        return None
    norm_api = _normalize_name(api_name)
    for option in roster_options:
        if _normalize_name(option) == norm_api:
            return option
    candidates = [
        option for option in roster_options
        if norm_api and (norm_api in _normalize_name(option) or _normalize_name(option) in norm_api)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def guess_league_for_match(match_type, series_name):
    """Best-effort league auto-selection so the person doesn't have to
    manually pick it before loading a match. Returns a league name from
    LEAGUES, or None if unsure (the person keeps whatever league is
    already selected)."""
    mt = str(match_type or "").lower()
    name = str(series_name or "").lower()
    if "odi" in mt:
        return "ODI Cricket (International)" if "ODI Cricket (International)" in LEAGUES else None
    if "t20" in mt or "twenty20" in mt:
        if "ipl" in name or "indian premier league" in name:
            return "IPL" if "IPL" in LEAGUES else None
        if "big bash" in name or "bbl" in name:
            if "women" in name and "Women's Big Bash League" in LEAGUES:
                return "Women's Big Bash League"
            if "Men's Big Bash League" in LEAGUES:
                return "Men's Big Bash League"
    return None


def parse_live_match(raw):
    """Turn CricAPI's match_info payload into the plain fields this app
    actually uses. Every value defaults to None/[] rather than a guess if
    the provider didn't include it - callers must check for that."""
    if not isinstance(raw, dict):
        return {}

    teams = raw.get("teams") or []
    venue = raw.get("venue") or raw.get("venueName") or ""
    status = raw.get("status") or ""
    match_type = raw.get("matchType") or ""
    series_name = raw.get("series") or raw.get("name") or ""

    toss_info = raw.get("toss") if isinstance(raw.get("toss"), dict) else {}
    toss_winner = raw.get("tossWinner") or toss_info.get("winner")
    toss_choice = raw.get("tossChoice") or toss_info.get("decision")

    score_list = raw.get("score") if isinstance(raw.get("score"), list) else []
    current = score_list[-1] if score_list else {}
    innings_label = str(current.get("inning", "") or "")
    runs = current.get("r")
    wickets = current.get("w")
    overs = current.get("o")

    players_by_team = {}
    for block in (raw.get("players") or []):
        if not isinstance(block, dict):
            continue
        team_name = block.get("team") or block.get("teamName") or block.get("shortname") or ""
        names = []
        for player in (block.get("playing11") or block.get("players") or block.get("squad") or []):
            if isinstance(player, dict):
                nm = player.get("name") or player.get("fullname") or player.get("player") or ""
            else:
                nm = str(player)
            if nm:
                names.append(nm)
        if team_name and names:
            players_by_team[team_name] = names

    return {
        "teams": [str(t) for t in teams], "venue": str(venue), "status": str(status),
        "match_type": str(match_type), "series_name": str(series_name),
        "toss_winner": toss_winner, "toss_choice": toss_choice,
        "innings_label": innings_label, "runs": runs, "wickets": wickets, "overs": overs,
        "players_by_team": players_by_team, "score_list": score_list,
    }


def parse_over_ball(overs_value):
    """CricAPI reports overs as a float like 14.2 (14 overs, 2 balls) -
    already the same 'over.ball' convention this app uses, so this is
    just a defensive float parse, not a re-derivation."""
    try:
        text = f"{float(overs_value):.1f}"
        return over_to_balls(text)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------
# SIDEBAR - STAGE A: pick a live match (before the league's own
# team/ground lists are available, since a league hasn't been resolved
# from this match yet)
# ------------------------------------------------------------

st.sidebar.markdown("---")
live_mode_on = st.sidebar.checkbox(
    "🔴 LIVE MODE", value=bool(st.session_state.get("live_mode_on", False)), key="live_mode_checkbox",
)
st.session_state["live_mode_on"] = live_mode_on

if live_mode_on:
    with st.sidebar:
        st.caption(
            "Loads today's match facts (teams, venue, score) from a live provider. "
            "The prediction itself always comes from VasuDev's own historical engine, "
            "never from the live provider."
        )

        if not os.environ.get("CRICKET_API_KEY", "").strip():
            st.warning(
                "CRICKET_API_KEY is not set in this environment. Live Mode can't fetch anything "
                "until it is - Manual Mode below still works normally."
            )
        else:
            if st.button("🔄 Refresh Match List", use_container_width=True, key="refresh_live_matches_button"):
                matches, error = fetch_live_matches()
                st.session_state["live_matches"] = matches
                st.session_state["live_last_fetch_note"] = error or f"{len(matches)} match(es) found."
                st.rerun()

            note = st.session_state.get("live_last_fetch_note")
            if note:
                st.caption(note)

            live_matches = st.session_state.get("live_matches") or []
            if live_matches:
                def _match_label(m):
                    teams = m.get("teams") or []
                    vs = " vs ".join(teams) if teams else m.get("name", "Match")
                    return f"{vs} ({m.get('status', '')})" if m.get("status") else vs

                labels = [_match_label(m) for m in live_matches]
                chosen_idx = st.selectbox(
                    "Select a live match", list(range(len(live_matches))),
                    format_func=lambda i: labels[i], key="live_match_select",
                )
                if st.button("📥 Load Selected Match", use_container_width=True, key="load_live_match_button"):
                    chosen = live_matches[chosen_idx]
                    st.session_state["live_selected_id"] = chosen.get("id")
                    detail, error = fetch_match_details(chosen.get("id"))
                    if error:
                        st.session_state["live_last_fetch_note"] = error
                    else:
                        st.session_state["live_match_raw"] = detail
                        st.session_state["live_applied_league_for"] = None  # trigger Stage B mapping
                        guessed_league = guess_league_for_match(
                            detail.get("matchType"), detail.get("series") or detail.get("name"))
                        if guessed_league:
                            st.session_state["persisted_league"] = guessed_league
                        st.session_state["live_last_fetch_note"] = "Match loaded - resolving teams/ground below."
                    st.rerun()
            elif os.environ.get("CRICKET_API_KEY", "").strip():
                st.caption("Tap 'Refresh Match List' to see today's live matches.")

with st.sidebar:
    st.header("Match Setup")
    if st.button("Logout", use_container_width=True, key="logout_button"):
        clear_persisted_session()
        for _k in list(st.session_state.keys()):
            del st.session_state[_k]
        st.rerun()

    league = st.selectbox("League", LEAGUES, index=restored_index(LEAGUES, "persisted_league"),
                          key="league_select")
    st.session_state["persisted_league"] = league
    FULL_OVERS = LEAGUE_FORMAT_OVERS.get(league, 20)
    TOTAL_BALLS = FULL_OVERS * 6

    ready = st.session_state.setdefault("ready_leagues", {})
    try:
        if league in ready and Path(ready[league]).exists():
            database_path = Path(ready[league])
        else:
            with st.spinner(f"Preparing {league} database (one-time download, a few minutes)..."):
                database_path = ensure_database(league)
            ready[league] = str(database_path.resolve())
        connection = get_connection(str(database_path.resolve()))
    except Exception as error:
        st.error("Database start nahi ho saka.")
        st.exception(error)
        st.stop()

    try:
        with st.spinner(f"Training the {league} engine (one-time, uses full history)..."):
            E = get_engine(league, f"{database_path.stat().st_size}")
    except Exception as error:
        st.error("Engine training failed.")
        st.exception(error)
        st.stop()

    warn = st.session_state.get("league_build_warnings", {}).get(league)
    if warn:
        st.warning(f"{len(warn)} team archive(s) could not be downloaded for this league.")

    teams = get_current_teams(connection, league)
    if not teams:
        st.error("Database me team data nahi mila.")
        st.stop()

    grounds_list = get_grounds(connection, league)

    # --- Live Mode Stage B: apply a freshly-loaded match's teams/venue
    # to THIS league's actual roster, once, the first time this league is
    # seen after loading. After that the person can freely change the
    # dropdowns by hand without the live mapping overriding them again. ---
    live_raw = st.session_state.get("live_match_raw")
    if st.session_state.get("live_mode_on") and live_raw and st.session_state.get("live_applied_league_for") != league:
        parsed_live = parse_live_match(live_raw)
        api_teams = parsed_live.get("teams") or []
        mapped_bat = match_name_to_roster(api_teams[0], teams) if len(api_teams) > 0 else None
        mapped_bowl = match_name_to_roster(api_teams[1], teams) if len(api_teams) > 1 else None
        if mapped_bat:
            st.session_state["persisted_batting_team"] = mapped_bat
        if mapped_bowl:
            st.session_state["persisted_bowling_team"] = mapped_bowl
        mapped_ground = match_name_to_roster(parsed_live.get("venue"), grounds_list)
        if mapped_ground:
            st.session_state["persisted_ground"] = mapped_ground
        elif parsed_live.get("venue"):
            st.session_state["persisted_ground"] = MANUAL_OPTION_LABEL
            st.session_state["persisted_ground_manual"] = parsed_live["venue"]
        unmatched = [n for n, m in ((api_teams[0] if api_teams else None, mapped_bat),
                                    (api_teams[1] if len(api_teams) > 1 else None, mapped_bowl)) if n and not m]
        if unmatched:
            st.session_state["live_last_fetch_note"] = (
                f"Loaded, but couldn't match {', '.join(unmatched)} to a team in {league}'s data - "
                "pick manually below if needed."
            )
        st.session_state["live_applied_league_for"] = league
        st.rerun()

    batting_team = st.selectbox("Batting Team", teams,
                                index=restored_index(teams, "persisted_batting_team"), key="batting_team_select")
    st.session_state["persisted_batting_team"] = batting_team
    bowling_options = [t for t in teams if t != batting_team] or ["Unknown"]
    bowling_team = st.selectbox("Bowling Team", bowling_options,
                                index=restored_index(bowling_options, "persisted_bowling_team"),
                                key="bowling_team_select")
    st.session_state["persisted_bowling_team"] = bowling_team

    ground = select_with_manual_option("Ground / Venue", grounds_list,
                                       "persisted_ground", "persisted_ground_manual", "ground")
    if ground == "Not Selected":
        ground = ""

    innings_options = ["1st Innings", "2nd Innings"]
    innings_label = st.selectbox("Innings", innings_options,
                                 index=restored_index(innings_options, "persisted_innings_label"),
                                 key="innings_select")
    st.session_state["persisted_innings_label"] = innings_label
    innings_no = 1 if innings_label == "1st Innings" else 2

    if innings_no == 2:
        target = st.number_input("Target Runs", min_value=0, max_value=600,
                                 value=int(st.session_state.target), step=1, key="target_runs_widget")
        st.session_state.target = int(target)
    else:
        target = 0
        st.session_state.target = 0

    st.markdown("---")
    st.subheader("Conditions")
    pitch_options = list(PITCH_CONDITIONS.keys())
    pitch_choice = st.selectbox("Pitch", pitch_options,
                                index=restored_index(pitch_options, "persisted_pitch_condition"),
                                key="pitch_condition_select")
    st.session_state["persisted_pitch_condition"] = pitch_choice
    dew_options = list(DEW_OPTIONS.keys())
    dew_choice = st.selectbox("Dew", dew_options, index=restored_index(dew_options, "persisted_dew"),
                              key="dew_select")
    st.session_state["persisted_dew"] = dew_choice

    st.markdown("---")
    st.subheader("Players (optional)")
    st.caption("Set once. Strike rotates automatically; a wicket asks for the next batter.")
batting_roster = get_team_roster(connection, league, batting_team, "batting")
batsman_options = ["Not Selected"] + batting_roster
batsman_a = select_with_manual_option("Batsman 1", batsman_options, "persisted_batsman_a",
"persisted_batsman_a_manual", "batsman_a")
batsman_b = select_with_manual_option("Batsman 2", batsman_options, "persisted_batsman_b",
"persisted_batsman_b_manual", "batsman_b")
strike_idx = int(st.session_state.get("on_strike_index", 0))
on_strike_name = batsman_a if strike_idx == 0 else batsman_b
st.caption(f"On strike: {on_strike_name if on_strike_name != 'Not Selected' else '-'}")
if st.button("Swap Strike", use_container_width=True, key="swap_strike_button"):
st.session_state.on_strike_index = 1 - strike_idx
st.rerun()
bowler_options = ["Not Selected"] + get_team_roster(connection, league, bowling_team, "bowling")
bowler_choice = select_with_manual_option("Current Bowler", bowler_options, "persisted_current_bowler",
"persisted_current_bowler_manual", "current_bowler")

bowling_roster_full = get_team_roster(connection, league, bowling_team, "bowling")  

if (st.session_state.get("live_mode_on") and live_raw  
        and st.session_state.get("live_applied_xi_for") != st.session_state.get("live_selected_id")):  
    parsed_live = parse_live_match(live_raw)  
    players_by_team = parsed_live.get("players_by_team") or {}  
    for api_team_name, names in players_by_team.items():  
        target_roster, target_key, is_bat = None, None, None  
        if match_name_to_roster(api_team_name, [batting_team]):  
            target_roster, target_key, is_bat = batting_roster, "persisted_batting_xi", True  
        elif match_name_to_roster(api_team_name, [bowling_team]):  
            target_roster, target_key, is_bat = bowling_roster_full, "persisted_bowling_xi", False  
        if target_roster is None:  
            continue  
        mapped = [match_name_to_roster(n, target_roster) for n in names]  
        mapped = [m for m in mapped if m]  
        if mapped:  
            st.session_state[target_key] = mapped  
    st.session_state["live_applied_xi_for"] = st.session_state.get("live_selected_id")  

st.markdown("---")  
st.subheader("Playing XI (optional)")  
st.caption(  
    "If today's actual XI differs from the season average (injuries, "  
    "rotation, a strong/weak XI), naming them here shifts the "  
    "prediction toward THIS XI's real record instead of the team's "  
    "season-wide average. Leave empty to just use the team average."  
)  
batting_xi = st.multiselect(  
    f"{batting_team} Playing XI (batters)", batting_roster,  
    default=[n for n in st.session_state.get("persisted_batting_xi", []) if n in batting_roster],  
    key="batting_xi_select",  
)  
st.session_state["persisted_batting_xi"] = batting_xi  
bowling_xi = st.multiselect(  
    f"{bowling_team} Playing XI (bowlers)", bowling_roster_full,  
    default=[n for n in st.session_state.get("persisted_bowling_xi", []) if n in bowling_roster_full],  
    key="bowling_xi_select",  
)  
st.session_state["persisted_bowling_xi"] = bowling_xi  

# --- Live Mode: controlled score sync (only on explicit tap) ---  
if st.session_state.get("live_mode_on"):  
    st.markdown("---")  
    st.subheader("Live Score Sync")  
    if not st.session_state.get("live_selected_id"):  
        st.caption("Load a match above first.")  
    else:  
        if st.button("🔄 FETCH LIVE UPDATE", use_container_width=True, type="primary", key="fetch_live_update_button"):  
            detail, error = fetch_match_details(st.session_state["live_selected_id"])  
            if error:  
                st.session_state["live_last_fetch_note"] = error  
            else:  
                st.session_state["live_match_raw"] = detail  
                parsed = parse_live_match(detail)  
                new_balls = parse_over_ball(parsed.get("overs"))  
                new_runs = parsed.get("runs")  
                new_wkts = parsed.get("wickets")  
                inn_key = f"{st.session_state['live_selected_id']}|{parsed.get('innings_label')}"  
                ingested = st.session_state.setdefault("live_ingested_keys", {})  
                prev = ingested.get(inn_key)  

                if new_balls is None or new_runs is None:  
                    st.session_state["live_last_fetch_note"] = (  
                        "Live API didn't return a usable current score for this match right now."  
                    )  
                elif prev and new_balls < prev["balls"]:  
                    # A NEW innings started (ball count went backwards) -  
                    # treat as fresh rather than corrupting the old one.  
                    ingested[inn_key] = {"balls": new_balls, "runs": new_runs, "wickets": new_wkts or 0}  
                    st.session_state.runs = int(new_runs)  
                    st.session_state.wickets = int(new_wkts or 0)  
                    st.session_state.balls = int(new_balls)  
                    st.session_state.recent_balls = []  
                    st.session_state.last = "Live sync (new innings)"  
                    st.session_state["live_last_fetch_note"] = (  
                        f"Synced fresh innings: {new_runs}/{new_wkts or 0} at "  
                        f"{display_over(new_balls)}."  
                    )  
                elif not prev:  
                    ingested[inn_key] = {"balls": new_balls, "runs": new_runs, "wickets": new_wkts or 0}  
                    st.session_state.runs = int(new_runs)  
                    st.session_state.wickets = int(new_wkts or 0)  
                    st.session_state.balls = int(new_balls)  
                    st.session_state.last = "Live sync"  
                    st.session_state["live_last_fetch_note"] = (  
                        f"First sync for this innings: {new_runs}/{new_wkts or 0} at "  
                        f"{display_over(new_balls)}."  
                    )  
                else:  
                    balls_gained = new_balls - prev["balls"]  
                    runs_gained = new_runs - prev["runs"]  
                    if balls_gained == 0:  
                        note = "Already up to date - no new balls since the last fetch."  
                    else:  
                        # True ball-by-ball is not reliably available on  
                        # this plan (see fetch_ball_by_ball) - we do NOT  
                        # invent individual deliveries. Instead the  
                        # actual runs-per-ball since the last fetch is  
                        # recorded as one momentum sample, which is  
                        # honest about what is and isn't known.  
                        avg_per_ball = runs_gained / balls_gained if balls_gained else 0.0  
                        st.session_state.recent_balls = (  
                            list(st.session_state.recent_balls) + [avg_per_ball] * min(balls_gained, 18)  
                        )[-18:]  
                        note = (  
                            f"Synced {balls_gained} ball(s), {runs_gained} run(s) since last fetch "  
                            f"(gap covered as an average rate, not invented ball-by-ball)."  
                        )  
                    ingested[inn_key] = {"balls": new_balls, "runs": new_runs, "wickets": new_wkts or 0}  
                    st.session_state.runs = int(new_runs)  
                    st.session_state.wickets = int(new_wkts or 0)  
                    st.session_state.balls = int(new_balls)  
                    st.session_state.last = "Live sync"  
                    st.session_state["live_last_fetch_note"] = note  

                # First innings score becomes the live target, same as  
                # the manual Target Runs field.  
                if len(parsed.get("score_list") or []) >= 2:  
                    try:  
                        st.session_state.target = int(parsed["score_list"][0].get("r", 0)) + 1  
                    except (TypeError, ValueError):  
                        pass  
            st.rerun()  

        live_note = st.session_state.get("live_last_fetch_note")  
        if live_note:  
            st.caption(live_note)  
        with st.expander("Raw live match JSON (for checking field names)", expanded=False):  
            st.write(st.session_state.get("live_match_raw") or {})  

st.markdown("---")  
st.subheader("Start / Reset")  
over_points = ["0.0"] + [f"{o}.{k}" for o in range(FULL_OVERS) for k in range(1, 7)] + [f"{FULL_OVERS}.0"]  
start_over = st.selectbox("Over / Ball now", over_points, index=0, key="start_over_select")  
start_runs = st.number_input("Runs now", 0, 600, 0, 1, key="start_runs_widget")  
start_wickets = st.number_input("Wickets now", 0, 10, 0, 1, key="start_wickets_widget")  
start_last12 = st.number_input("Runs in last 2 overs (-1 = unknown)", -1, 80, -1, 1, key="start_last12_widget")  
start_bsw = st.number_input("Balls since last wicket (99 = none)", 0, 99, 99, 1, key="start_bsw_widget")  

if st.button("Set Current Match Situation", use_container_width=True, key="set_situation_button"):  
    parsed = over_to_balls(start_over)  
    if parsed is None:  
        st.error("Invalid over/ball.")  
    else:  
        n_recent = min(12, parsed)  
        if parsed == 0:  
            seed = []  
        elif start_last12 >= 0 and parsed >= 12:  
            seed = [start_last12 / 12.0] * 12  
        else:  
            seed = [start_runs / parsed] * n_recent  
        st.session_state.runs = int(start_runs)  
        st.session_state.wickets = int(start_wickets)  
        st.session_state.balls = int(parsed)  
        st.session_state.recent_balls = seed  
        st.session_state.pending_extras = 0.0  
        st.session_state.bsw = int(start_bsw)  
        st.session_state.undo_stack = []  
        st.session_state.last = "Situation set"  
        st.session_state.on_strike_index = 0  
        st.session_state.dismissed_batsmen = []  
        st.session_state.awaiting_new_batsman = False  
        st.session_state.out_slot_index = None  
        st.session_state.batter_live = {}  
        st.session_state.bowler_live = {}  
        st.session_state.partnership_runs = 0  
        st.session_state.this_over = []  
        st.session_state.over_history = []  
        st.rerun()  

if st.button("Reset (new innings)", use_container_width=True, key="reset_live_button"):  
    for _k in ("runs", "wickets", "balls"):  
        st.session_state[_k] = 0  
    st.session_state.recent_balls = []  
    st.session_state.pending_extras = 0.0  
    st.session_state.bsw = 99  
    st.session_state.undo_stack = []  
    st.session_state.last = "New innings"  
    st.session_state.on_strike_index = 0  
    st.session_state.dismissed_batsmen = []  
    st.session_state.awaiting_new_batsman = False  
    st.session_state.out_slot_index = None  
    st.session_state.batter_live = {}  
    st.session_state.bowler_live = {}  
    st.session_state.partnership_runs = 0  
    st.session_state.this_over = []  
    st.session_state.over_history = []  
    st.rerun()  

if st.button("Retrain engine from scratch", use_container_width=True, key="retrain_button"):  
    try:  
        engine_path_for(league).unlink()  
    except Exception:  
        pass  
    get_engine.clear()  
    st.rerun()

============================================================

CURRENT STATE

============================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

striker_name = None if on_strike_name in (None, "Not Selected") else on_strike_name
other_name = batsman_b if strike_idx == 0 else batsman_a
non_striker_name = None if other_name in (None, "Not Selected") else other_name
bowler_name = None if bowler_choice in (None, "Not Selected") else bowler_choice

recent = st.session_state.recent_balls[-12:]
last_n = len(recent)
last_r = float(sum(recent))

BALL_DOT_LABELS = {"Dot": "•", "1": "1", "2": "2", "3": "3", "4": "4", "6": "6",
"Wicket": "W", "Wide": "wd", "No Ball": "nb"}

def _current_batter_key():
name = on_strike_name if (on_strike_name and on_strike_name != "Not Selected") else None
return name or f"Batsman {st.session_state.get('on_strike_index', 0) + 1}"

def _current_bowler_key():
return bowler_name if (bowler_name and bowler_name != "Not Selected") else "Current bowler"

============================================================

TOP SCORE (the only place the live score is shown) - scoreboard-style

header: score bar, CRR/RRR/target row, ball-by-over dots, current

batsmen and bowler figures. Built entirely from state this app already

tracks live - no extra data source.

============================================================

_crr = (runs / (balls / 6.0)) if balls > 0 else 0.0
_rrr = None
_need_line = ""
if innings_no == 2 and target > 0:
_remaining_balls = max(0, TOTAL_BALLS - balls)
_remaining_runs = max(0, target - runs)
if _remaining_balls > 0 and wickets < 10:
_rrr = _remaining_runs * 6.0 / _remaining_balls
_need_line = f'<p style="margin:6px 0 0;color:#ffd166">Need {_remaining_runs} runs in {_remaining_balls} balls</p>'
elif wickets >= 10:
_need_line = '<p style="margin:6px 0 0;color:#ffd166">All out</p>'
elif runs >= target:
_need_line = '<p style="margin:6px 0 0;color:#8fe3a0">Target achieved</p>'

st.html(
f"""
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap">
<h2 style="margin:0">{batting_team} {runs}/{wickets}</h2>
<span class="small">{display_over(balls)} / {FULL_OVERS} ov</span>
</div>
<p class="small" style="margin:5px 0 0">{league} • {ground or "ground not set"} • vs {bowling_team}</p>
<div style="display:flex;gap:18px;margin-top:10px;flex-wrap:wrap">
<div><span class="small">CRR</span><br><b style="font-size:18px">{_crr:.2f}</b></div>
<div><span class="small">RRR</span><br><b style="font-size:18px">{f'{_rrr:.2f}' if _rrr is not None else '-'}</b></div>
<div><span class="small">Target</span><br><b style="font-size:18px">{target if target > 0 else '-'}</b></div>
</div>
{_need_line}
</div>
"""
)

--- Ball-by-over dots (recent overs + the one in progress) ---

_over_rows = list(st.session_state.get("over_history", []))[-3:]
_dots_html = ""
for _row in _over_rows:
_balls_html = " ".join(f"<span class='dot'>{b}</span>" for b in _row["balls"])
_dots_html += f"<div class='over-row'><span class='small'>Ov {_row['over']}</span> {_balls_html} <span class='small'>= {_row['runs_after']}</span></div>"
_this_over_no = balls // 6 + 1
_this_dots = " ".join(f"<span class='dot'>{b}</span>" for b in st.session_state.get("this_over", []))
_dots_html += f"<div class='over-row'><b class='small'>Ov {_this_over_no} (current)</b> {_this_dots}</div>"

st.html(
f"""
<style>
.dot {{ display:inline-block; min-width:22px; padding:2px 5px; margin:2px; border-radius:50%;
background:#12365f; text-align:center; font-size:13px; }}
.over-row {{ margin:3px 0; }}
</style>
<div class="card">{_dots_html}</div>
"""
)

--- Partnership + current batsmen + bowler ---

_slot_a_name = batsman_a if batsman_a != "Not Selected" else "Batsman 1"
_slot_b_name = batsman_b if batsman_b != "Not Selected" else "Batsman 2"
_bat_rows = ""
for _nm in (_slot_a_name, _slot_b_name):
st = st.session_state.get("batter_live", {}).get(_nm)
if st:
_sr = (st["runs"] / st["balls"] * 100) if st["balls"] else 0.0
_mark = " *" if _nm == (batsman_a if strike_idx == 0 else batsman_b) else ""
_bat_rows += (
f"<tr><td>{_nm}{_mark}</td><td>{st['runs']}</td><td>{st['balls']}</td>"
f"<td>{st['fours']}</td><td>{st['sixes']}</td><td>{_sr:.1f}</td></tr>"
)
_bowl_key = _current_bowler_key()
_bowl_stats = st.session_state.get("bowler_live", {}).get(_bowl_key)
_bowl_line = ""
if _bowl_stats:
_overs_bowled = display_over(_bowl_stats["balls"])
_econ = (_bowl_stats["runs"] / (_bowl_stats["balls"] / 6.0)) if _bowl_stats["balls"] else 0.0
_bowl_line = (
f"<p style='margin:8px 0 0'><b>{_bowl_key}</b>: {_bowl_stats['wickets']}-{_bowl_stats['runs']} "
f"({_overs_bowled} ov, econ {_econ:.2f})</p>"
)

if _bat_rows:
st.html(
f"""
<div class="card">
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr class="small"><th style="text-align:left">Batter</th><th>R</th><th>B</th>
<th>4s</th><th>6s</th><th>SR</th></tr>
{_bat_rows}
</table>
<p class="small" style="margin:6px 0 0">Partnership: {st.session_state.get('partnership_runs', 0)} runs</p>
{_bowl_line}
</div>
"""
)

============================================================

BALL CONTROLS

============================================================

def apply_ball(label, add_runs, add_wicket, legal_ball):
ss = st.session_state
if label != "Undo" and (ss.wickets >= 10 or ss.balls >= TOTAL_BALLS):
ss.last = "Innings already complete - use Reset for a new innings"
return
if label == "Undo":
if ss.undo_stack:
old = ss.undo_stack.pop()
for k in ("runs", "wickets", "balls", "recent_balls", "pending_extras", "bsw",
"on_strike_index", "dismissed_batsmen", "awaiting_new_batsman", "out_slot_index",
"batter_live", "bowler_live", "partnership_runs", "this_over", "over_history"):
ss[k] = old[k]
ss.last = "Undo"
return
ss.undo_stack.append({
"runs": ss.runs, "wickets": ss.wickets, "balls": ss.balls,
"recent_balls": list(ss.recent_balls), "pending_extras": ss.pending_extras, "bsw": ss.bsw,
"on_strike_index": ss.on_strike_index, "dismissed_batsmen": list(ss.dismissed_batsmen),
"awaiting_new_batsman": ss.awaiting_new_batsman, "out_slot_index": ss.out_slot_index,
"batter_live": {k: dict(v) for k, v in ss.batter_live.items()},
"bowler_live": {k: dict(v) for k, v in ss.bowler_live.items()},
"partnership_runs": ss.partnership_runs,
"this_over": list(ss.this_over), "over_history": list(ss.over_history),
})
ss.undo_stack = ss.undo_stack[-60:]
ss.runs += int(add_runs)
ss.wickets = min(10, ss.wickets + int(add_wicket))
ss.partnership_runs = 0 if label == "Wicket" else ss.partnership_runs + int(add_runs)

bat_key = _current_batter_key()  
bowl_key = _current_bowler_key()  
bat_stats = dict(ss.batter_live.get(bat_key, {"runs": 0, "balls": 0, "fours": 0, "sixes": 0}))  
bowl_stats = dict(ss.bowler_live.get(bowl_key, {"runs": 0, "balls": 0, "wickets": 0}))  

if legal_ball:  
    ss.recent_balls = (list(ss.recent_balls) + [float(add_runs) + float(ss.pending_extras)])[-18:]  
    ss.pending_extras = 0.0  
    ss.balls += 1  
    ss.bsw = 0 if add_wicket else (min(99, ss.bsw + 1) if ss.bsw < 99 else 99)  

    bat_stats["balls"] += 1  
    bat_stats["runs"] += int(add_runs)  
    if add_runs == 4:  
        bat_stats["fours"] += 1  
    elif add_runs == 6:  
        bat_stats["sixes"] += 1  
    bowl_stats["balls"] += 1  
    bowl_stats["runs"] += int(add_runs)  
    if add_wicket:  
        bowl_stats["wickets"] += 1  

    if label == "Wicket":  
        ss.awaiting_new_batsman = True  
        ss.out_slot_index = ss.on_strike_index  
        if on_strike_name and on_strike_name != "Not Selected":  
            ss.dismissed_batsmen = list(ss.dismissed_batsmen) + [on_strike_name]  
    elif int(add_runs) % 2 == 1:  
        ss.on_strike_index = 1 - ss.on_strike_index  
    if ss.balls % 6 == 0:  
        ss.on_strike_index = 1 - ss.on_strike_index  
else:  
    ss.pending_extras = float(ss.pending_extras) + float(add_runs)  
    bowl_stats["runs"] += int(add_runs)  

ss.batter_live = {**ss.batter_live, bat_key: bat_stats}  
ss.bowler_live = {**ss.bowler_live, bowl_key: bowl_stats}  

ss.this_over = list(ss.this_over) + [BALL_DOT_LABELS.get(label, label)]  
if legal_ball and ss.balls % 6 == 0:  
    ss.over_history = (list(ss.over_history) + [{  
        "over": ss.balls // 6, "balls": list(ss.this_over), "runs_after": ss.runs,  
    }])[-6:]  
    ss.this_over = []  

ss.last = label

st.subheader("Ball-by-Ball Update")
actions = [
("Dot", 0, 0, True), ("1", 1, 0, True), ("2", 2, 0, True), ("3", 3, 0, True),
("4", 4, 0, True), ("6", 6, 0, True), ("Wicket", 0, 1, True),
("Wide", 1, 0, False), ("No Ball", 1, 0, False), ("Undo", 0, 0, False),
]
action_columns = st.columns(len(actions), gap="small")
for _i, (_label, _r, _w, _legal) in enumerate(actions):
with action_columns[_i]:
if st.button(label, use_container_width=True, key=f"live_action_button{_i}"):
apply_ball(_label, _r, _w, _legal)
st.rerun()

if st.session_state.get("awaiting_new_batsman"):
out_slot = st.session_state.get("out_slot_index") or 0
other_slot_name = batsman_b if out_slot == 0 else batsman_a
dismissed = set(st.session_state.get("dismissed_batsmen", []))
incoming_options = ["Not Selected"] + [
n for n in batting_roster if n not in dismissed and n != other_slot_name]
incoming = st.selectbox(f"New batsman in (replacing Batsman {out_slot + 1}):",
incoming_options, key="incoming_batsman_select")
if st.button("Confirm New Batsman", key="confirm_new_batsman_button"):
st.session_state["persisted_batsman_a" if out_slot == 0 else "persisted_batsman_b"] = incoming
st.session_state.awaiting_new_batsman = False
st.session_state.out_slot_index = None
st.rerun()

============================================================

PROJECTION INPUTS (the only two things typed during the match)

============================================================

st.subheader("Projection")
c1, c2 = st.columns(2, gap="small")
with c1:
proj_over = st.number_input("Projection End Over", min_value=1, max_value=FULL_OVERS,
value=min(int(st.session_state.projection_end_over), FULL_OVERS), step=1,
key="projection_end_over_widget")
st.session_state.projection_end_over = int(proj_over)

player_info = build_player_info(connection, E, league, striker_name, non_striker_name, bowler_name, balls)

squad_info = None
if batting_xi or bowling_xi:
b_nd, b_d, b_conf = squad_batting_strength(
connection, league, tuple(batting_xi), E["pp_end"], E["death_over"], tuple(E["lg_bat_ball"]))
w_nd, w_d, w_conf = squad_bowling_strength(
connection, league, tuple(bowling_xi), E["pp_end"], E["death_over"], tuple(E["lg_bowl_ball"]))
squad_info = {
"bat_nd": b_nd, "bat_d": b_d, "bat_conf": b_conf,
"bowl_nd": w_nd, "bowl_d": w_d, "bowl_conf": w_conf,
}

state = {
"innings": innings_no, "b": balls, "r": runs, "w": wickets,
"last_r": last_r, "last_n": last_n, "bsw": int(st.session_state.bsw),
"window_over": int(proj_over), "line": 0,
"batting_team": batting_team, "bowling_team": bowling_team, "ground": ground,
"target": int(target), "pitch_mult": PITCH_CONDITIONS[pitch_choice],
"dew_level": DEW_OPTIONS[dew_choice], "player": player_info, "squad": squad_info,
}
_pre = predict(E, state)
default_line = int(st.session_state.score_prediction)
if default_line <= 0:
default_line = int(round(_pre["window_expected"]))
with c2:
line = st.number_input("Score Prediction (runs)", min_value=0, max_value=700, value=default_line,
step=1, key="score_prediction_widget")
st.session_state.score_prediction = int(line)
state["line"] = int(line)
result = predict(E, state)

============================================================

RESULT BOX 1 - SCORE

============================================================

p_reach = result["p_reach"] * 100
box_class = "positive" if p_reach >= 50 else "negative"
over_label = int(proj_over)
ahead = runs - result["par_now"]
st.html(
f"""
<div class="{box_class}">
<h1 style="margin:0">Expected {result['window_expected']:.0f} by over {over_label}</h1>
<p style="margin:6px 0 0">80% range: <b>{result['window_p10']:.0f} - {result['window_p90']:.0f}</b></p>
<p style="margin:8px 0 0;font-size:20px">
{int(line)} or more: <b>{p_reach:.0f}%</b>  • 
under {int(line)}: <b>{100 - p_reach:.0f}%</b>
</p>
<p class="small" style="margin:6px 0 0">
Full innings projection {result['final_expected']:.0f}
({result['final_p10']:.0f}-{result['final_p90']:.0f})
• {ahead:+.0f} runs vs league par at this stage
</p>
</div>
"""
)

============================================================

RESULT BOX 2 - WIN

============================================================

wp = result["win_prob"]
if wp is not None:
bat_win = wp * 100
bowl_win = 100 - bat_win
if bat_win >= bowl_win:
w_name, w_pct, w_class = batting_team, bat_win, "positive"
else:
w_name, w_pct, w_class = bowling_team, bowl_win, "negative"
basis = ("Based on projected final score vs ground par, team rating, head-to-head"
if innings_no == 1 else f"Target {int(target)} • needs {result.get('needed', 0):.0f} more")
st.html(
f"""
<div class="{w_class}">
<h1 style="margin:0">{w_name.upper()} WIN - {w_pct:.0f}%</h1>
<p style="margin:8px 0 0">
{batting_team}: <b>{bat_win:.1f}%</b>  •  {bowling_team}: <b>{bowl_win:.1f}%</b>
</p>
<p class="small" style="margin:5px 0 0">{basis}</p>
</div>
"""
)
else:
st.info("2nd innings win % ke liye sidebar me Target Runs set karein.")

============================================================

DETAILS

============================================================

with st.expander("More Insights & Details", expanded=False):
st.write("#### What is moving the projection (runs, rest of innings)")
st.caption("Positive = adds runs, negative = costs runs, vs a neutral situation. "
"Each of these is learned from history except pitch/dew and the player nudges, which are bounded judgement values.")
if result["factors"]:
df_f = pd.DataFrame(result["factors"], columns=["Factor", "Runs impact"])
df_f["Runs impact"] = df_f["Runs impact"].round(1)
st.dataframe(df_f, hide_index=True, use_container_width=True)

st.write("#### Score path")  
try:  
    path_rows = predict_path(E, state)  
    par_curve = E["par_cum_np"][innings_no]  
    pts = [(balls / 6.0, float(runs), float(runs), float(runs), float(par_curve[balls]))]  
    for ov, mid, lo, hi in path_rows:  
        pts.append((float(ov), float(mid), float(lo), float(hi), float(par_curve[int(ov) * 6])))  
    chart_df = pd.DataFrame(pts, columns=["Over", "Expected", "Low (10%)", "High (90%)", "League par"]).set_index("Over")  
    st.line_chart(chart_df)  
except Exception:  
    st.info("Path chart unavailable for this situation.")  

st.write("#### Match context")  
crr = runs / (balls / 6.0) if balls > 0 else 0.0  
rrr = None  
if innings_no == 2 and target > 0 and balls < TOTAL_BALLS:  
    rrr = max(0, target - runs) * 6.0 / (TOTAL_BALLS - balls)  
mom = (last_r / last_n * 6.0) if last_n > 0 else None  
m1, m2, m3 = st.columns(3)  
m1.metric("Current run rate", f"{crr:.2f}")  
m2.metric("Required run rate", f"{rrr:.2f}" if rrr is not None else "-")  
m3.metric("Last 2 overs rate", f"{mom:.2f}" if mom is not None else "-")  
wa, wb = result["h2h"]  
if wa + wb:  
    st.caption(f"Head-to-head (this league): {batting_team} {wa} - {wb} {bowling_team}")  
gstats = E["ground"].get(ground or "", None)  
if gstats:  
    st.caption(  
        f"Ground record ({ground}, {gstats.get('n', 0)} matches): typical 1st innings "  
        f"{gstats.get('G1', E['league_first_mean']):.0f}, death-overs scoring "  
        f"{gstats.get('g_d', 0):+.2f} rpo vs league, boundary rate {gstats.get('g_bnd', 0):+.1f} pts, "  
        f"bat-first win-rate {gstats.get('gbias', 0) * 100:+.0f} pts vs league.")  
elif ground:  
    st.caption(f"'{ground}' has no history in this league - ground effects set to neutral.")  

bat_home, bowl_home = result.get("home", (0.0, 0.0))  
if ground:  
    if bat_home:  
        st.caption(f"🏠 {batting_team} is treated as playing at home here (detected from history, not hand-typed).")  
    elif bowl_home:  
        st.caption(f"🏠 {bowling_team} is treated as playing at home here (detected from history, not hand-typed).")  
    else:  
        st.caption("No clear home team detected for this ground (or it's a neutral venue).")  

if squad_info:  
    parts = []  
    if batting_xi:  
        parts.append(f"{batting_team} XI trust: {squad_info['bat_conf'] * 100:.0f}% "  
                    f"(rest comes from the team's season average)")  
    if bowling_xi:  
        parts.append(f"{bowling_team} XI trust: {squad_info['bowl_conf'] * 100:.0f}%")  
    if parts:  
        st.caption("Playing XI - " + " • ".join(parts) +  
                  ". Low % usually means most named players are new/unrecognised in this league's data.")  


if striker_name or non_striker_name or bowler_name:  
    st.write("#### Players")  
    ph = phase_of(E, balls // 6)  
    phase_name = ["Powerplay", "Middle overs", "Death overs"][ph]  
    for nm in (striker_name, non_striker_name):  
        if nm:  
            stt = player_batting_phase(connection, league, nm, E["pp_end"], E["death_over"])  
            r_, b_ = stt["phase"][ph]  
            sr = f"{r_ / b_ * 100:.0f}" if b_ else "-"  
            st.caption(f"{nm}: {phase_name} SR {sr} ({b_} balls in this league)")  
    if bowler_name:  
        stt = player_bowling_phase(connection, league, bowler_name, E["pp_end"], E["death_over"])  
        r_, b_ = stt["phase"][ph]  
        eco = f"{r_ / b_ * 6:.2f}" if b_ else "-"  
        st.caption(f"{bowler_name}: {phase_name} economy {eco} ({b_} balls in this league)")  

st.write("#### Engine report (measured on real history, out-of-sample)")  
mt = E["metrics"]  
st.caption(  
    f"{league}: trained on {mt['n_matches']} full-length matches, seasons "  
    f"{mt['seasons'][0]}-{mt['seasons'][1]} (cross-fitted by match, so these numbers are honest). "  
    f"Trained in {E.get('train_seconds', 0)}s.")  
rep_rows = []  
for k in ("1", "2"):  
    for ball_key, vals in mt.get(f"runs_inn{k}", {}).items():  
        rep_rows.append({"Innings": k, "After over": int(ball_key) // 6, "Samples": vals["n"],  
                         "Model error (runs)": vals["mae_model"], "Naive pace-projection error": vals["mae_naive"]})  
if rep_rows:  
    st.write("Final-score prediction error (lower is better):")  
    st.dataframe(pd.DataFrame(rep_rows), hide_index=True, use_container_width=True)  
w1, w2 = mt["w1"], mt["w2"]  
st.write(  
    f"Win probability, 1st innings: Brier {w1['brier']} (coin-flip baseline {w1['brier_baseline']}); "  
    f"2nd innings: Brier {w2['brier']} (baseline {w2['brier_baseline']}). Lower Brier = better.")  
cal = pd.DataFrame(w2["calibration"], columns=["Predicted", "Actual win rate", "Samples"])  
st.write("2nd-innings calibration (predicted vs what actually happened):")  
st.dataframe(cal, hide_index=True, use_container_width=True)  
st.caption(  
    "Reading it: when the engine says 70%, teams in that bucket should have won about 70% of the time. "  
    "Early in a 1st innings the true win chance is close to 50-50 - a 50-50 there is correct, not a bug.")

st.caption("Historical estimate only. Not a guarantee of the live match result.")
save_persisted_session()
