# VasuDev Cricket AI - "ENGINE v2" app.py        (PART 1 of 2 - paste Part 2 right below this)
#
# What is new vs ENGINE v1 (everything else is the original base, unchanged):
#   * RECENCY BY MATCH DATE: every match is weighted by its real date
#     (Oct 2026 > Sep 2026 > Aug 2026 > ... > 7-10 years ago), same rule
#     for every league/format. Ground, team, player and head-to-head
#     records all use it. (Before, only the season year was used.)
#   * WBBL: T20 Spring Challenge + other recent club matches are pulled in
#     from extra Cricsheet archives (flagged "extra", they never add
#     non-WBBL teams to the team dropdown).
#   * NEW learned factors: toss, venue-specific head-to-head, a
#     confidence indicator and a Monte-Carlo ball-by-ball chase simulation
#     (blended into the chase win %).
#   * Pitch "Auto" (ground record + 1st innings score of this match).
#   * LIVE MODE fixed: teams (correct batting side), ground, toss, Playing
#     XI, batters, bowler, score, target (incl. DLS) now really fill the
#     sidebar widgets; anything the API does not give is shown clearly as
#     "not available - fill manually" (nothing is invented).
#   * T20 ONLY: the ODI league and its data are removed (IPL, BBL, WBBL, T20I).
#   * GRADIENT BOOSTING (pure numpy, no new package): a tree-boosted
#     correction on top of the regression, switched on per innings ONLY if
#     it beats the plain regression out-of-sample (see Engine report).
#   * Strict team matching ("Australia A" never matches "Australia").
#   * Start/Reset widgets always mirror the live score; Quick Catch-Up for
#     live lag; "last synced X sec ago"; smart Projection End Over.

import bisect
import datetime
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
    "projection_end_over", "projection_user_set", "score_prediction",
    "persisted_league", "persisted_batting_team", "persisted_bowling_team",
    "persisted_ground", "persisted_ground_manual", "persisted_innings_label",
    "persisted_batsman_a", "persisted_batsman_a_manual",
    "persisted_batsman_b", "persisted_batsman_b_manual",
    "persisted_current_bowler", "persisted_current_bowler_manual",
    "persisted_pitch_condition", "persisted_dew", "persisted_toss",
    "persisted_batting_xi", "persisted_bowling_xi",
    "on_strike_index", "dismissed_batsmen", "awaiting_new_batsman", "out_slot_index",
    "batter_live", "bowler_live", "partnership_runs", "this_over", "over_history",
    "live_mode_on", "live_matches", "live_selected_id", "live_match_raw",
    "live_ingested_keys", "live_last_fetch_note",
    "live_setup", "live_team_pending", "live_players_pending", "live_status",
    "live_last_sync_ts", "live_warnings", "live_unmapped", "state_version",
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
    "T20 International": BASE / "t20i_history.db",
}

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
    # Direct competition-level archive - every men's T20 international.
    "T20 International": "https://cricsheet.org/downloads/t20s_male_json.zip",
}

# EXTRA archives (optional, a failed download is only a warning). Matches in
# them are stored with comp='extra': they train the engine (recent form!)
# but never add teams to the team dropdown. A match is only taken from an
# extra archive if at least one of its teams is a team of the MAIN archive.
# WBBL: the 8 clubs' own match archives carry the pre-season T20 Spring
# Challenge (ACT Meteors matches included) + any other club match that is
# not in the WBBL archive yet; "recently played" catches the last 30 days.
WBBL_CLUB_SLUGS = [
    "adelaide_strikers", "brisbane_heat", "hobart_hurricanes", "melbourne_renegades",
    "melbourne_stars", "perth_scorchers", "sydney_sixers", "sydney_thunder",
]
EXTRA_DOWNLOAD_URLS = {
    "Women's Big Bash League": (
        ["https://cricsheet.org/downloads/recently_played_30_female_json.zip"]
        + [f"https://cricsheet.org/downloads/{slug}_female_json.zip" for slug in WBBL_CLUB_SLUGS]
    ),
}

RESTRICT_TEAMS = {}

# Women's league -> women's team names only (a "Women" live match is never
# mapped onto a men's league and the other way round).
LEAGUE_GENDER = {"Women's Big Bash League": "female"}

# Format-aware: overs per innings for each league.
LEAGUE_FORMAT_OVERS = {
    "IPL": 20,
    "Men's Big Bash League": 20,
    "Women's Big Bash League": 20,
    "T20 International": 20,
}

# ------------------------------------------------------------
# ROLLING 10-YEAR WINDOW (same rule for every format, every league)
# ------------------------------------------------------------
# Only matches from the last ROLLING_WINDOW_YEARS full years are ever
# downloaded/built into any league's database. Recomputed from TODAY's
# date, so it slides forward by itself every year. Inside this window the
# engine weights every match by how recent it is (see ENGINE_CFG
# half-lives): this month > last month > ... > 7-10 years ago.
ROLLING_WINDOW_YEARS = 10


def current_min_season():
    """Today's year minus the rolling window - recomputed live, never
    hand-typed, so this slides forward automatically every year."""
    return datetime.date.today().year - ROLLING_WINDOW_YEARS


LEAGUES = list(DATABASES.keys())

# How many trailing seasons feed the Batsman/Bowler roster dropdowns.
DEFAULT_ROSTER_LOOKBACK_SEASONS = 2
LEAGUE_ROSTER_LOOKBACK_SEASONS = {
    "T20 International": 5,
}

# ODI was removed (T20 only). Delete its leftover files from older versions.
for _stale in ("odi_history.db", "odi_history.building", "odi_history.tmp",
               "engine_odi_cricket_international.json"):
    try:
        if (BASE / _stale).exists():
            (BASE / _stale).unlink()
    except Exception:
        pass

# Manual pitch-behaviour multiplier on the projected remaining runs.
# "Auto" estimates it (ground record + this match's 1st-innings score);
# the others are judgement values (Cricsheet has no pitch-type data).
PITCH_AUTO_LABEL = "Auto (ground + 1st innings)"
PITCH_CONDITIONS = {
    PITCH_AUTO_LABEL: 1.00,
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

# Per-league training settings: recency half-life (years, applied on the
# real match DATE), the season from which a rule change lifted scoring
# (IPL Impact Player, 2023), ELO between-season carry-over, and a cap on
# how many of the most recent matches are used.
ENGINE_CFG = {
    "IPL": {"half_life": 4.0, "era_start": 2023, "elo_keep": 0.75, "cap": 900},
    "Men's Big Bash League": {"half_life": 5.0, "era_start": None, "elo_keep": 0.75, "cap": 700},
    "Women's Big Bash League": {"half_life": 5.0, "era_start": None, "elo_keep": 0.75, "cap": 700},
    "T20 International": {"half_life": 4.0, "era_start": None, "elo_keep": 0.90, "cap": 700},
}

# Team / player form uses a SHORTER half-life than the league-wide one
# (squads change): TEAM_HL_FACTOR * half_life.
TEAM_HL_FACTOR = 0.5

# Venue-specific head-to-head: the pair's record at THIS ground is blended
# with their league-wide record, H2H_VENUE_K pseudo-matches of the latter.
H2H_VENUE_K = 4.0

# Monte-Carlo chase simulation: share of the final chase win % and size.
MC_BLEND = 0.4
MC_PATHS = 1200

# Gradient boosting (pure numpy histogram trees) on top of the ridge
# regression. It is only switched on for an innings if it lowers the
# out-of-sample squared error by at least GB_MIN_GAIN (1%).
GB_ROUNDS = 60
GB_DEPTH = 3
GB_LR = 0.08
GB_BINS = 32
GB_MIN_GAIN = 0.01
GB_MAX_ROWS = 70000

# Real, format-specific Powerplay/Death boundaries where they're known.
KNOWN_PHASE_BOUNDARIES = {
    20: (6, 15),
    10: (3, 8),
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

SCHEMA_VERSION = "5"


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


REBUILD_AFTER_DAYS = 3


def database_is_valid(database_path, league):
    """Valid = right tables, right columns, current schema_version, AND
    built recently enough (so newly completed real matches flow in)."""
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

        built_row = connection.execute(
            "SELECT value FROM meta WHERE key='built_at'"
        ).fetchone()
        try:
            built_at = float(built_row[0]) if built_row else 0.0
        except (TypeError, ValueError):
            built_at = 0.0
        if (time.time() - built_at) > REBUILD_AFTER_DAYS * 86400:
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
            "match_date", "comp", "toss_winner",
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
# DATABASE BUILDER (v5: match dates, main/extra archives, canonical names)
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
        "CREATE INDEX IF NOT EXISTS idx_matches_comp ON matches(league, comp)",
    ):
        connection.execute(statement)


def _team_key(name):
    """'Sydney Sixers Women' and 'Sydney Sixers' -> same key. Used so a
    club that is spelled slightly differently in an extra archive is
    folded onto the main archive's spelling (one team, not two)."""
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    tokens = [t for t in text.split() if t not in ("women", "womens", "w")]
    return "".join(tokens)


def build_database(database_path, league, archives, restrict_teams=None, min_season=None):
    """archives: list of (zip_path, is_main). Main archives define the
    league (and its teams); extra archives only add matches that involve
    at least one main-archive team (stored with comp='extra')."""
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
                match_overs INTEGER, dls INTEGER, match_date TEXT, comp TEXT)"""
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
        main_canon = {}          # team key -> main-archive spelling

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
                    toss_winner, toss_decision, match_overs, dls, match_date, comp)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                match_rows,
            )
            match_rows.clear()

        ordered = sorted(archives, key=lambda item: 0 if item[1] else 1)
        for archive_path, is_main in ordered:
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
                        raw_teams = [str(t).strip() for t in (info.get("teams", []) or [])]
                        if len(raw_teams) < 2:
                            continue
                        keys = [_team_key(t) for t in raw_teams]
                        if is_main:
                            if restrict_teams is not None:
                                names = {t.lower() for t in raw_teams}
                                if not names.issubset(restrict_teams):
                                    continue
                            for t, k in zip(raw_teams, keys):
                                main_canon.setdefault(k, t)
                            teams = raw_teams
                        else:
                            if not (set(keys) & set(main_canon)):
                                continue
                            teams = [main_canon.get(k, t) for t, k in zip(raw_teams, keys)]
                        canon = dict(zip(raw_teams, teams))
                        seen_match_ids.add(match_id)

                        outcome = info.get("outcome", {}) or {}
                        winner = str(outcome.get("winner", "") or "").strip()
                        winner = canon.get(winner, winner)
                        dls = 1 if outcome.get("method") else 0
                        venue = str(info.get("venue", "") or "")
                        toss = info.get("toss", {}) or {}
                        toss_winner = str(toss.get("winner", "") or "").strip()
                        toss_winner = canon.get(toss_winner, toss_winner)

                        dates = info.get("dates") or []
                        match_date = str(dates[0])[:10] if dates else ""

                        season_year = None
                        digits = "".join(ch for ch in str(info.get("season", "") or "") if ch.isdigit())
                        if len(digits) >= 4:
                            season_year = int(digits[:4])
                        if season_year is None and match_date:
                            try:
                                season_year = int(match_date[:4])
                            except (ValueError, TypeError):
                                season_year = None

                        if min_season is not None and (season_year is None or season_year < min_season):
                            # Skip entirely - before touching any innings data.
                            seen_match_ids.discard(match_id)
                            continue

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
                            raw_bt = str(innings.get("team", "") or "").strip()
                            batting_team = canon.get(raw_bt, raw_bt)
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
                            toss_winner,
                            str(toss.get("decision", "") or "").lower(),
                            match_overs, dls, match_date, "main" if is_main else "extra",
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
        connection.execute("INSERT OR REPLACE INTO meta VALUES('built_at', ?)", (str(time.time()),))
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
    main_urls = list(urls) if isinstance(urls, (list, tuple)) else [urls]
    extra_urls = list(EXTRA_DOWNLOAD_URLS.get(league, []))
    restrict_teams = RESTRICT_TEAMS.get(league)

    try:
        if building_path.exists():
            building_path.unlink()

        with tempfile.TemporaryDirectory() as temp_directory:
            archives, failed_sources = [], []
            main_errors = []
            for index, url in enumerate(main_urls):
                archive_path = Path(temp_directory) / f"main_{index}.zip"
                try:
                    download_archive(url, archive_path)
                    archives.append((archive_path, True))
                except Exception as download_error:
                    failed_sources.append(url)
                    main_errors.append((url, str(download_error)))
            if not archives:
                raise RuntimeError(
                    f"Could not download the main archive for {league}. Failures: {main_errors}"
                )
            for index, url in enumerate(extra_urls):
                archive_path = Path(temp_directory) / f"extra_{index}.zip"
                try:
                    download_archive(url, archive_path)
                    archives.append((archive_path, False))
                except Exception:
                    failed_sources.append(url)

            build_database(building_path, league, archives, restrict_teams=restrict_teams,
                           min_season=current_min_season())

            if failed_sources:
                st.session_state.setdefault("league_build_warnings", {})
                st.session_state["league_build_warnings"][league] = failed_sources

        if not database_is_valid(building_path, league):
            raise RuntimeError(f"{league} database build completed but validation failed.")

        building_path.replace(database_path)
        # The old read-only connection / cached lookups / engine still point
        # at the previous file - drop them so the fresh data is really used.
        try:
            get_connection.clear()
            st.cache_data.clear()
            get_engine.clear()
        except Exception:
            pass
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
# VASUDEV ENGINE v2  (no streamlit dependency below this line,
# up to prepare_engine)
# ============================================================
#
#  RUNS MODEL (per innings): weighted ridge regression that predicts the
#  runs still to come over ANY horizon H (next over, next 6 overs, rest
#  of innings) from: league phase par, pace vs par, last 2 overs
#  momentum, wickets lost, new-batter effect, ground scoring / death /
#  boundary record, batting-team and bowling-attack strength (death and
#  non-death), ELO gap and era (Impact Player). A GRADIENT-BOOSTED tree
#  correction is added on top for an innings only if it wins the
#  out-of-sample test. The spread comes from out-of-fold residual
#  quantiles (real, not assumed-normal).
#
#  RECENCY: every match is weighted by 0.5 ** (age_in_days / half_life),
#  so this month counts more than last month, more than last year, ...
#  down to the 10-year window edge. Team strength / player form use a
#  shorter half-life (TEAM_HL_FACTOR).
#
#  WIN MODELS (logistic regression, IRLS):
#   1st innings: P(bat-first wins | final score) fitted on real results
#     (score vs ground par, ELO gap, venue-aware head-to-head, ground
#     chase bias, home side, toss), integrated over the predicted
#     final-score distribution.
#   2nd innings: P(chase wins) from (predicted remaining runs - needed)
#     / spread, ELO gap, head-to-head, wickets, required rate, home, toss
#     - blended with a Monte-Carlo ball-by-ball simulation.
#
#  ELO: chronological (by date), with between-season regression to the
#  mean. Everything is cross-fitted by match (3 folds) so the reported
#  Brier / MAE numbers are out-of-sample.

import math

ENGINE_VERSION = 2
N_FOLDS = 3
Q_GRID = np.arange(1, 100) / 100.0
H_BIN_EDGES = [6, 12, 24, 36, 60, 84, 120]
WB_MAP = np.array([0, 0, 0, 1, 1, 1, 2, 2, 3, 3, 3])   # wickets lost -> bucket

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
# gradient boosting (histogram trees, squared loss, pure numpy)
# ------------------------------------------------------------

def gb_fit(X, y, w, rounds=GB_ROUNDS, depth=GB_DEPTH, lr=GB_LR, bins=GB_BINS,
           lam=10.0, min_w=60.0, seed=3, max_rows=GB_MAX_ROWS):
    """Fits y (here: the residual of the ridge model) with `rounds` small
    trees. Weighted. Returns a model dict usable by gb_predict."""
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)
    n, k = X.shape
    if n > max_rows:
        sel = np.random.default_rng(seed).choice(n, max_rows, replace=False)
        X, y, w = X[sel], y[sel], w[sel]
        n = max_rows
    w = w / w.mean()
    qs = np.linspace(0, 1, bins + 1)[1:-1]
    edges = [np.unique(np.quantile(X[:, j], qs)) for j in range(k)]
    Xb = np.empty((n, k), dtype=np.int64)
    for j in range(k):
        Xb[:, j] = np.searchsorted(edges[j], X[:, j], side="right")
    nb = bins
    base = float((w * y).sum() / w.sum())
    pred = np.full(n, base)
    ar = np.arange(n)
    trees = []
    for _ in range(rounds):
        res = y - pred
        wr = w * res
        nid = np.zeros(n, dtype=np.int64)
        feats, thrs = [], []
        for level in range(depth):
            nn = 1 << level
            best_gain = np.zeros(nn)
            best_f = np.zeros(nn, dtype=np.int64)
            best_t = np.full(nn, nb, dtype=np.int64)       # nb = "no split: all go left"
            tot_w = np.bincount(nid, weights=w, minlength=nn)
            tot_wr = np.bincount(nid, weights=wr, minlength=nn)
            parent = tot_wr ** 2 / (tot_w + lam)
            for j in range(k):
                idx = nid * nb + Xb[:, j]
                hw = np.bincount(idx, weights=w, minlength=nn * nb).reshape(nn, nb)
                hwr = np.bincount(idx, weights=wr, minlength=nn * nb).reshape(nn, nb)
                lw = np.cumsum(hw, axis=1)[:, :-1]
                lwr = np.cumsum(hwr, axis=1)[:, :-1]
                rw = tot_w[:, None] - lw
                rwr = tot_wr[:, None] - lwr
                gain = lwr ** 2 / (lw + lam) + rwr ** 2 / (rw + lam) - parent[:, None]
                gain = np.where((lw >= min_w) & (rw >= min_w), gain, -1.0)
                jb = gain.argmax(axis=1)
                jg = gain[np.arange(nn), jb]
                better = jg > best_gain
                best_gain = np.where(better, jg, best_gain)
                best_f = np.where(better, j, best_f)
                best_t = np.where(better, jb, best_t)
            feats.append(best_f)
            thrs.append(best_t)
            nid = nid * 2 + (Xb[ar, best_f[nid]] > best_t[nid]).astype(np.int64)
        nleaf = 1 << depth
        lw_ = np.bincount(nid, weights=w, minlength=nleaf)
        lwr_ = np.bincount(nid, weights=wr, minlength=nleaf)
        leaf = lwr_ / (lw_ + lam)
        pred = pred + lr * leaf[nid]
        trees.append((feats, thrs, leaf))
    return {"base": base, "lr": lr, "depth": depth, "bins": nb,
            "edges_np": edges, "trees_np": trees}


def gb_predict(G, X):
    X = np.asarray(X, dtype=np.float64)
    m = X.shape[0]
    if G is None:
        return np.zeros(m)
    Xb = np.empty((m, X.shape[1]), dtype=np.int64)
    for j, e in enumerate(G["edges_np"]):
        Xb[:, j] = np.searchsorted(e, X[:, j], side="right")
    pred = np.full(m, G["base"], dtype=np.float64)
    ar = np.arange(m)
    for feats, thrs, leaf in G["trees_np"]:
        nid = np.zeros(m, dtype=np.int64)
        for f, t in zip(feats, thrs):
            nid = nid * 2 + (Xb[ar, f[nid]] > t[nid]).astype(np.int64)
        pred += G["lr"] * leaf[nid]
    return pred


def gb_to_json(G):
    if G is None:
        return None
    return {
        "base": float(G["base"]), "lr": float(G["lr"]), "depth": int(G["depth"]), "bins": int(G["bins"]),
        "edges": [e.tolist() for e in G["edges_np"]],
        "trees": [([f.tolist() for f in fs], [t.tolist() for t in ts], lf.tolist())
                  for fs, ts, lf in G["trees_np"]],
    }


def gb_from_json(raw):
    if not raw:
        return None
    return {
        "base": float(raw["base"]), "lr": float(raw["lr"]), "depth": int(raw["depth"]), "bins": int(raw["bins"]),
        "edges_np": [np.array(e, dtype=np.float64) for e in raw["edges"]],
        "trees_np": [([np.array(f, dtype=np.int64) for f in fs], [np.array(t, dtype=np.int64) for t in ts],
                      np.array(lf, dtype=np.float64)) for fs, ts, lf in raw["trees"]],
    }


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
    """Checkpoint spacing (balls) and the horizons (balls) trained on."""
    return 8, [6, 12, 18, 24, 30, 36, 48, 60, 72, 90, 108]


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
        "SELECT rowid AS mid, match_id, venue, winner, season, match_overs, dls, "
        "match_date, toss_winner FROM matches WHERE league=?", con, params=(league,))
    m = m[(m.match_overs == T_overs) & (m.dls == 0) & m.season.notna()].copy()
    m["idnum"] = pd.to_numeric(m.match_id, errors="coerce").fillna(0)
    m["toss_winner"] = m["toss_winner"].fillna("")
    m["date"] = pd.to_datetime(m["match_date"], format="%Y-%m-%d", errors="coerce")
    fallback = pd.to_datetime(m["season"].astype(int).astype(str) + "-07-01", format="%Y-%m-%d", errors="coerce")
    m["date"] = m["date"].fillna(fallback)
    m = m.sort_values(["date", "idnum"])
    if cap:
        m = m.tail(int(cap))
    m = m.reset_index(drop=True)
    if len(m) < 60:
        con.close()
        raise RuntimeError(f"Only {len(m)} usable full-length matches found for {league}; need at least 60.")

    def _query_by_match_batches(sql_template, match_ids, extra_params=()):
        """Only matches actually kept in `m` are ever pulled into pandas
        (chunked to stay under SQLite's bound-variable limit)."""
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

    # ---- recency weights from the REAL match date ----
    latest = int(m.season.max())
    latest_date = m["date"].max()
    age_days = (latest_date - m["date"]).dt.days.clip(lower=0).astype(float)
    team_hl = max(1.0, half_life * TEAM_HL_FACTOR)
    m["w"] = 0.5 ** (age_days / (half_life * 365.25))
    m["wt"] = 0.5 ** (age_days / (team_hl * 365.25))
    if era_start:
        m["w"] = m["w"] * np.where(m["season"] < era_start, 0.6, 1.0)

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
    inn = inn.merge(m[["mid", "season", "venue", "winner", "w", "wt", "date"]], on="mid", how="left")
    inn["one"] = 1.0
    inn = inn[inn.bat.notna()].reset_index(drop=True)

    # league baselines (recency weighted, per ball)
    W = inn.w
    L_nd = (W * inn.nd_runs).sum() / (W * inn.nd_balls).sum()
    L_d = (W * inn.d_runs).sum() / max(1.0, (W * inn.d_balls).sum())
    L_b = (W * inn.bnd).sum() / (W * inn.balls_tot).sum()

    # ---- per-over league par curve, per innings ----
    par_cum = {}
    par_rate_over = {}
    w_row = d.mid.map(m.set_index("mid")["w"]).values
    for k in (1, 2):
        mk = d.inn.values == k
        ov = np.minimum(d.ov.values[mk], T_overs - 1)
        num = np.bincount(ov, weights=runs_v[mk] * w_row[mk], minlength=T_overs)
        den = np.bincount(ov, weights=legal[mk] * w_row[mk], minlength=T_overs)
        rate = np.where(den > 0, num / np.maximum(den, 1e-9), num.sum() / max(den.sum(), 1e-9))
        par_rate_over[k] = rate
        per_ball = np.repeat(rate, 6)[:T]
        par_cum[k] = np.concatenate([[0.0], np.cumsum(per_ball)])

    # ---- ground stats (LOO for training rows, recency weighted) ----
    K_G_ND, K_G_D, K_G_B = 600.0, 150.0, 600.0
    inn["g_nd"] = (_loo(inn, "venue", "nd_runs", "nd_balls", L_nd, K_G_ND) - L_nd) * 6.0
    inn["g_d"] = (_loo(inn, "venue", "d_runs", "d_balls", L_d, K_G_D) - L_d) * 6.0
    inn["g_bnd"] = (_loo(inn, "venue", "bnd", "balls_tot", L_b, K_G_B) - L_b) * 100.0

    # ---- team strength (LOO, recency weighted over the whole window) ----
    K_T_ND, K_T_D = 300.0, 90.0
    inn["bkey"] = inn.bat.astype(str)
    inn["wkey"] = inn.bowl.astype(str)
    inn["bat_nd"] = (_loo(inn, "bkey", "nd_runs", "nd_balls", L_nd, K_T_ND, "wt") - L_nd) * 6.0
    inn["bat_d"] = (_loo(inn, "bkey", "d_runs", "d_balls", L_d, K_T_D, "wt") - L_d) * 6.0
    inn["bowl_nd"] = (_loo(inn, "wkey", "nd_runs", "nd_balls", L_nd, K_T_ND, "wt") - L_nd) * 6.0
    inn["bowl_d"] = (_loo(inn, "wkey", "d_runs", "d_balls", L_d, K_T_D, "wt") - L_d) * 6.0

    # ---- match level frame (bat first / second) ----
    i1 = inn[inn.inn == 1].set_index("mid")
    i2 = inn[inn.inn == 2].set_index("mid")
    mm = m.set_index("mid").join(i1[["bat", "bowl", "runs_tot"]].rename(
        columns={"bat": "bat1", "bowl": "bat2x", "runs_tot": "F1"}), how="inner")
    mm = mm.join(i2[["bat", "runs_tot"]].rename(columns={"bat": "bat2", "runs_tot": "F2"}), how="left")
    mm = mm.reset_index().sort_values(["date", "idnum"]).reset_index(drop=True)
    mm["bat2"] = mm.bat2.fillna(mm.bat2x)

    # ---- ELO + head-to-head (chronological by DATE, point-in-time) ----
    # h2h feature = pair's record at THIS venue blended with their league
    # record (venue-specific head-to-head).
    ratings, h2h, h2h_v, pre = {}, {}, {}, {}
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
        h2h_lg = (wa - wb) / (wa + wb + 4.0)
        vk = (k_, row.venue)
        vw = h2h_v.get(vk, [0, 0])
        v_wa = vw[0] if a == k_[0] else vw[1]
        v_wb = vw[1] if a == k_[0] else vw[0]
        h2h_eff = (v_wa - v_wb + H2H_VENUE_K * h2h_lg) / (v_wa + v_wb + H2H_VENUE_K)
        pre[row.mid] = (ra - rb, h2h_eff)
        if row.winner in (a, b_):
            exp_a = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
            s_a = 1.0 if row.winner == a else 0.0
            ratings[a] = ra + 20.0 * (s_a - exp_a)
            ratings[b_] = rb - 20.0 * (s_a - exp_a)
            idx = 0 if row.winner == k_[0] else 1
            wins = list(wins); wins[idx] += 1
            h2h[k_] = wins
            vw = list(vw); vw[idx] += 1
            h2h_v[vk] = vw
        else:
            h2h.setdefault(k_, wins)

    mm["elo1"] = mm.mid.map(lambda x: pre[x][0])
    mm["h2h1"] = mm.mid.map(lambda x: pre[x][1])
    mm["toss1"] = np.where(mm.toss_winner == mm.bat1, 1.0, np.where(mm.toss_winner == mm.bat2, -1.0, 0.0))

    # ---- home venue detection (purely from data - no hand-typed mapping) ----
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
    inn = inn[inn.mid.isin(mm.mid)].reset_index(drop=True)
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
    toss_map = dict(zip(m.mid.values, m.toss_winner.values))
    toss_w = inn.mid.map(toss_map).fillna("").values
    toss_i = np.where(toss_w == inn.bat.values, 1.0, np.where(toss_w == inn.bowl.values, -1.0, 0.0))
    era_i = (inn.season.values >= era_start).astype(float) if era_start else np.zeros(n_inn2)
    fold_i = (inn.mid.values % N_FOLDS).astype(int)
    w_i = inn.w.values
    T_i = inn.balls_tot.values.astype(np.int64)
    fin_i = inn.runs_tot.values
    inn_no = inn.inn.values
    winner_i = inn.winner.values
    bat_i = inn.bat.values
    chase_won_i = (inn_no == 2) & (winner_i == bat_i)
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

    # ---- ball-outcome table for the Monte-Carlo chase simulation ----
    # outcome per legal ball (extras bowled before it are folded in):
    # 0..6 runs, 7 = wicket. Cells: innings x phase x wickets-bucket.
    prev_cr = np.where(same, np.roll(cr_l, 1), 0.0)
    ball_runs = cr_l - prev_cr
    ball_wk = cw_l - prev_cw
    ov_idx = (lb_l - 1) // 6
    ph_l = np.where(ov_idx < pp_end, 0, np.where(ov_idx < death_over, 1, 2))
    wb_l = WB_MAP[np.minimum(np.maximum(cw_l - ball_wk, 0), 10)]
    out_l = np.where(ball_wk > 0, 7, np.clip(np.rint(ball_runs), 0, 6)).astype(np.int64)
    inn_l = np.clip(inn_no[iid_l] - 1, 0, 1)
    flat = (((inn_l * 3 + ph_l) * 4 + wb_l) * 8 + out_l).astype(np.int64)
    tab = np.bincount(flat, weights=w_i[iid_l], minlength=2 * 3 * 4 * 8).reshape(2, 3, 4, 8)
    pool = tab.sum(axis=2)
    pool_p = (pool + 1e-6) / (pool.sum(axis=-1, keepdims=True) + 8e-6)
    ball_probs = (tab + 30.0 * pool_p[:, :, None, :]) / (tab.sum(axis=-1, keepdims=True) + 30.0)

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
    models, gb_models, resid_tab, oof_store = {}, {}, {}, {}
    metrics = {"n_matches": int(len(mm)), "seasons": [int(m.season.min()), int(m.season.max())],
               "dates": [str(m["date"].min().date()), str(latest_date.date())]}
    rep_balls = (36, 60, 84, 102) if T == 120 else tuple(int(T * f) // 6 * 6 for f in (0.3, 0.5, 0.7, 0.85))

    for k in (1, 2):
        idx, Hv = expand(k)
        if len(idx) > 130000:
            sub = rng.choice(len(idx), 130000, replace=False)
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
        oof_gb = np.zeros(len(y))
        fold_models, gb_folds = [], []
        for f in range(N_FOLDS):
            tr = fo != f
            Mf = fit_ridge(X[tr], y[tr], wts[tr])
            fold_models.append(Mf)
            oof[~tr] = ridge_predict(Mf, X[~tr])
            Gf = gb_fit(X[tr], y[tr] - ridge_predict(Mf, X[tr]), wts[tr], seed=11 + f)
            gb_folds.append(Gf)
            oof_gb[~tr] = gb_predict(Gf, X[~tr])
        Mall = fit_ridge(X, y, wts)

        # gradient boosting is used for this innings only if it wins OUT-OF-SAMPLE
        mse_r = float(np.average((y - oof) ** 2, weights=wts))
        mse_g = float(np.average((y - oof - oof_gb) ** 2, weights=wts))
        use_gb = mse_g < (1.0 - GB_MIN_GAIN) * mse_r
        gb_models[k] = gb_fit(X, y - ridge_predict(Mall, X), wts, seed=5) if use_gb else None
        pred_oof = oof + (oof_gb if use_gb else 0.0)
        metrics[f"gb_inn{k}"] = {
            "used": bool(use_gb), "mse_ridge": round(mse_r, 2), "mse_gb": round(mse_g, 2),
            "gain_pct": round(100.0 * (mse_r - mse_g) / max(mse_r, 1e-9), 2),
        }

        res = y - pred_oof
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
        oof_store[k] = (fold_models, gb_folds if use_gb else None)

        end_m = (b_ + Hv) == T
        rep = {}
        for bb in rep_balls:
            mk = end_m & (b_ == bb)
            if mk.sum() >= 50:
                naive = r_[mk] * T / bb - r_[mk]
                rep[str(bb)] = {
                    "n": int(mk.sum()),
                    "mae_model": round(float(np.mean(np.abs(res[mk]))), 2),
                    "mae_naive": round(float(np.mean(np.abs(y[mk] - naive))), 2),
                }
        metrics[f"runs_inn{k}"] = rep
        log(f"innings {k} runs model: {len(y)} rows, gb={'on' if use_gb else 'off'}, {time.time()-t0:.1f}s")

    # ---- W1: first innings win (match level logistic on true F) ----
    d1 = mm[mm.decided].copy()
    X1 = np.column_stack([
        (d1.F1.values - d1.G1.values) / 10.0,
        d1.elo1.values / 100.0,
        d1.h2h1.values,
        d1.gbias.values * 10.0,
        d1.home_adv.values,
        d1.toss1.values,
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
    win_ok = (winner_i[ii] == bat_i[ii]) | (winner_i[ii] == inn.bowl.values[ii])
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
            if oof_store[2][1] is not None:
                mu_end[mk] += gb_predict(oof_store[2][1][f], Xe[mk])
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
        toss_i[ii],
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
    for bb in (0,) + rep_balls:
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
    cutoff_recent = latest_date - pd.Timedelta(days=365)
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
    for t in set(inn_all.bat.unique()) | set(inn_all.bowl.unique()):
        sb = inn_all[inn_all.bat == t]
        sw = inn_all[inn_all.bowl == t]
        wb_, ww_ = sb.wt, sw.wt
        dates = pd.concat([sb["date"], sw["date"]])
        team[str(t)] = {
            "bat_nd": float((_shrunk((wb_ * sb.nd_runs).sum(), (wb_ * sb.nd_balls).sum(), L_nd, K_T_ND) - L_nd) * 6.0),
            "bat_d": float((_shrunk((wb_ * sb.d_runs).sum(), (wb_ * sb.d_balls).sum(), L_d, K_T_D) - L_d) * 6.0),
            "bowl_nd": float((_shrunk((ww_ * sw.nd_runs).sum(), (ww_ * sw.nd_balls).sum(), L_nd, K_T_ND) - L_nd) * 6.0),
            "bowl_d": float((_shrunk((ww_ * sw.d_runs).sum(), (ww_ * sw.d_balls).sum(), L_d, K_T_D) - L_d) * 6.0),
            "n_bat": int(len(sb)), "n_bowl": int(len(sw)),
            "n_recent": int(((sb["date"] >= cutoff_recent).sum() + (sw["date"] >= cutoff_recent).sum()) // 2),
            "last_date": str(dates.max().date()) if len(dates) else "",
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
        "latest_date": str(latest_date.date()), "latest_ord": int(latest_date.toordinal()),
        "hl_days": float(half_life * 365.25), "team_hl_days": float(team_hl * 365.25),
        "par_cum": {str(k): par_cum[k].tolist() for k in par_cum},
        "par_rate_over": {str(k): par_rate_over[k].tolist() for k in par_rate_over},
        "models": {str(k): {kk: (v.tolist() if hasattr(v, "tolist") else v) for kk, v in models[k].items()} for k in models},
        "gb": {str(k): gb_to_json(gb_models[k]) for k in gb_models},
        "resid": {str(k): resid_tab[k].tolist() for k in resid_tab},
        "w1": beta1.tolist(), "w2": beta2.tolist(),
        "ground": gnd, "team": team,
        "elo": {str(k): float(v) for k, v in ratings.items()},
        "h2h": {f"{a}|{b}": v for (a, b), v in h2h.items()},
        "h2h_v": {f"{a}|{b}|{v}": w for ((a, b), v), w in h2h_v.items()},
        "team_home": team_home,
        "league_first_mean": float(LF), "bat_first_win_rate": float(Lbf),
        "lg_bat_ball": lg_bat, "lg_bowl_ball": lg_bowl,
        "ball_tab": ball_probs.tolist(),
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
    E["gb_np"] = {int(k): gb_from_json(v) for k, v in raw.get("gb", {}).items()}
    E["resid_np"] = {int(k): np.array(v) for k, v in raw["resid"].items()}
    E["w1_np"] = np.array(raw["w1"]); E["w2_np"] = np.array(raw["w2"])
    E["ball_np"] = np.array(raw["ball_tab"], dtype=np.float64)
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


def h2h_effective(E, a, b_, ground):
    """Head-to-head from batting team a's view: their record at THIS ground
    blended with their league-wide record (venue-specific head-to-head).
    Returns (blended value, (league wins a, wins b), (venue wins a, wins b))."""
    k_ = (a, b_) if a < b_ else (b_, a)
    wins = E["h2h"].get(f"{k_[0]}|{k_[1]}", [0, 0])
    wa = wins[0] if a == k_[0] else wins[1]
    wb = wins[1] if a == k_[0] else wins[0]
    h2h_lg = (wa - wb) / (wa + wb + 4.0)
    vw = E.get("h2h_v", {}).get(f"{k_[0]}|{k_[1]}|{ground or ''}", [0, 0])
    v_wa = vw[0] if a == k_[0] else vw[1]
    v_wb = vw[1] if a == k_[0] else vw[0]
    eff = (v_wa - v_wb + H2H_VENUE_K * h2h_lg) / (v_wa + v_wb + H2H_VENUE_K)
    return eff, (wa, wb), (v_wa, v_wb)


def team_ctx(E, batting_team, bowling_team, ground, innings, squad=None):
    """squad (optional): {"bat_nd","bat_d","bat_conf","bowl_nd","bowl_d","bowl_conf"} -
    computed from the announced Playing XI. Blended with the team's own
    recency-weighted average by confidence (0 = no XI data, use team
    average; 1 = fully trust the named XI)."""
    g = E["ground"].get(ground or "", {})
    tb = E["team"].get(batting_team, {})
    tw = E["team"].get(bowling_team, {})
    eb = E["elo"].get(batting_team, 1500.0)
    ew = E["elo"].get(bowling_team, 1500.0)
    era = 1.0 if (E.get("era_start") and E["latest_season"] >= E["era_start"]) else 0.0
    h2h, (wa, wb), (v_wa, v_wb) = h2h_effective(E, batting_team, bowling_team, ground)

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
    }, h2h, (wa, wb), home_adv, (bat_home, bowl_home), (v_wa, v_wb)


def mean_runs(E, inn, b, r, w, last_r, last_n, bsw, H, ctx):
    """Expected runs over the next H balls = ridge regression + (if it won
    the out-of-sample test for this innings) the gradient-boosting
    correction. Returns (mean, ridge contributions, gb correction)."""
    T = E["T"]
    X = make_features(np.array([b]), np.array([r]), np.array([w]), np.array([last_r]),
                      np.array([last_n]), np.array([bsw]), np.array([H]), T,
                      E["par_cum_np"][inn], E["d_start"], {k: np.array([v]) for k, v in ctx.items()})
    M = E["models_np"][inn]
    mu_ridge = float(ridge_predict(M, X)[0])
    gbd = float(gb_predict(E["gb_np"].get(inn), X)[0])
    contrib = (M["coef"] * X[0] / M["sd"])
    return max(mu_ridge + gbd, 0.0), contrib, gbd


def phase_of(E, over_idx):
    if over_idx < E["pp_end"]:
        return 0
    if over_idx < E["death_over"]:
        return 1
    return 2


def player_delta(E, b, mu_h, H_eff, bat_info, bowl_info, match_info):
    """Bounded, shrunk player effect on the projection (heuristic weights).
    bat_info: list of (weight, runs, balls) per batter for the CURRENT phase;
    bowl_info: (runs_conceded, balls); match_info: list of (weight, runs, balls) striker-vs-bowler.
    (runs/balls are recency-weighted sums.)"""
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


# ------------------------------------------------------------
# Monte-Carlo simulation (ball by ball, history-based outcome table)
# ------------------------------------------------------------

_MC_MEMO = {}


def mc_paths(E, inn, b, w, ratio, win_steps, n=MC_PATHS, seed=20260101):
    """Simulates the rest of the innings `n` times, ball by ball, from the
    league's real per-ball outcome table (innings x phase x wickets lost;
    wickets end an innings at 10, so all-out and running-out-of-balls limits
    are built in). `ratio` = this match's context-adjusted expectation / the
    neutral one (ground, teams, ELO, pitch, dew, players ...): the table is
    tilted (exponentially, in runs) until the simulated mean matches it.
    Returns {"win": runs scored up to the projection end over, "end": runs
    scored to the end of the innings} (arrays) or None. Fixed seed -> the
    numbers do not flicker between reruns."""
    T = E["T"]
    steps = T - int(b)
    if steps <= 0 or int(w) >= 10:
        return None
    win_steps = int(min(max(int(win_steps), 0), steps))
    ratio = float(min(1.5, max(0.6, ratio)))
    key = (id(E), int(inn), int(b), int(w), round(ratio, 3), win_steps)
    hit = _MC_MEMO.get(key)
    if hit is not None:
        return hit
    tab = E["ball_np"][int(inn) - 1]
    ov = (int(b) + np.arange(steps)) // 6
    ph = np.where(ov < E["pp_end"], 0, np.where(ov < E["death_over"], 1, 2))
    U = np.random.default_rng(seed).random((steps, n))

    def simulate(lam):
        tilt = np.concatenate([np.exp(lam * np.arange(7)), [1.0]])
        P = tab * tilt
        P = P / P.sum(axis=-1, keepdims=True)
        C = np.cumsum(P, axis=-1)
        runs = np.zeros(n)
        win_runs = np.zeros(n) if win_steps == 0 else None
        wk = np.full(n, int(w), dtype=np.int64)
        alive = wk < 10
        for t in range(steps):
            cdf = C[ph[t], WB_MAP[wk]]
            out = np.minimum((U[t][:, None] > cdf).sum(axis=1), 7)
            runs += np.where(alive & (out < 7), out, 0)
            wk = wk + (alive & (out == 7))
            alive = wk < 10
            if t + 1 == win_steps:
                win_runs = runs.copy()
            if not alive.any():
                break
        if win_runs is None:
            win_runs = runs.copy()
        return win_runs, runs

    win_runs, end_runs = simulate(0.0)
    base_mean = float(end_runs.mean())
    if abs(ratio - 1.0) > 0.004 and base_mean > 1.0:
        goal = base_mean * ratio
        lo, hi = -0.9, 0.9
        for _ in range(6):
            mid = (lo + hi) / 2.0
            if float(simulate(mid)[1].mean()) < goal:
                lo = mid
            else:
                hi = mid
        win_runs, end_runs = simulate((lo + hi) / 2.0)
    res = {"win": win_runs, "end": end_runs}
    if len(_MC_MEMO) > 300:
        _MC_MEMO.clear()
    _MC_MEMO[key] = res
    return res


def auto_pitch(E, ground, innings, target):
    """'Auto' pitch factor. 1st innings: the ground record and the live pace
    are already inside the model, so no extra factor. 2nd innings: how the
    1st-innings total compares with this ground's typical 1st-innings score
    (quarter weight, capped +-6%) - a high total says a good batting surface."""
    if int(innings) != 2 or float(target or 0) <= 0:
        return 1.0, "1st innings: ground record + live pace are already in the model (no extra factor)"
    g = E["ground"].get(ground or "", {})
    G1 = float(g.get("G1", E["league_first_mean"]))
    ratio = (float(target) - 1.0) / max(G1, 1.0)
    mult = min(1.06, max(0.94, 1.0 + 0.25 * (ratio - 1.0)))
    return mult, f"1st innings {int(target) - 1} vs typical {G1:.0f} at this ground"


def predict(E, s):
    """s keys: innings, b, r, w, last_r, last_n, bsw, window_over, line,
    batting_team, bowling_team, ground, target, pitch_mult, dew_level,
    toss (+1 batting team won the toss, -1 bowling team, 0 unknown),
    mc (True -> Monte-Carlo shapes the score spread and joins the chase win %),
    player (dict or None), squad (dict or None, from Playing XI)."""
    T = E["T"]
    inn = int(s["innings"])
    b = min(int(s["b"]), T); r = float(s["r"]); w = min(int(s["w"]), 10)
    ctx, h2h, (wa, wb), home_adv, (bat_home, bowl_home), (v_wa, v_wb) = team_ctx(
        E, s["batting_team"], s["bowling_team"], s.get("ground", ""), inn, squad=s.get("squad")
    )
    toss = float(s.get("toss", 0.0))
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
            results[tag] = {"mu": 0.0, "H": 0}
            continue
        mu, contrib, gbd = mean_runs(*common, H, ctx)
        adj_pitch = mu * (mult - 1.0)
        mu_adj = mu * mult
        pl_delta, notes = 0.0, []
        if s.get("player"):
            pi = s["player"]
            pl_delta, notes = player_delta(E, b, mu_adj, H, pi.get("bat"), pi.get("bowl"), pi.get("match"))
        mu_final = max(0.0, mu_adj + pl_delta)
        results[tag] = {"mu": mu_final, "mu_raw": mu, "pitch_dew": adj_pitch, "player": pl_delta,
                        "notes": notes, "contrib": contrib, "H": H, "gb": gbd,
                        "q": _resid_row(E, inn, H)}
        if tag == "end":
            contribs = contrib
    end = results["end"]

    # ---- Monte-Carlo: the regression sets the MEAN (it is the backtested
    # part), the simulation reshapes the SPREAD (all-out / out-of-balls
    # limits, wicket-dependent scoring) and gives a chase win probability.
    mc = None
    if s.get("mc") and H_end > 0:
        ctx0 = {k: 0.0 for k in ctx}
        mu_ref = mean_runs(*common, H_end, ctx0)[0]
        mc = mc_paths(E, inn, b, w, end["mu"] / max(mu_ref, 1.0), H_win)

    for tag in ("end", "win"):
        res = results[tag]
        if res["H"] <= 0:
            res["grid"] = np.zeros(len(Q_GRID))
            continue
        q = res["q"]
        if mc is not None:
            sm = mc["end"] if tag == "end" else mc["win"]
            q = (1.0 - MC_BLEND) * q + MC_BLEND * (np.percentile(sm, Q_GRID * 100.0) - float(sm.mean()))
        res["grid"] = np.maximum(0.0, res["mu"] + q)

    win = results["win"]
    out["window_over"] = win_end // 6 if win_end % 6 == 0 else win_end / 6.0
    out["window_expected"] = r + win["mu"]
    out["window_p10"] = r + float(np.percentile(win["grid"], 25))
    out["window_p90"] = r + float(np.percentile(win["grid"], 75))
    out["window_p05"] = r + float(np.percentile(win["grid"], 10))
    out["window_p95"] = r + float(np.percentile(win["grid"], 90))
    line = float(s.get("line", 0))
    if H_win > 0:
        need = line - r
        g = np.sort(win["grid"])
        p_reach = float(1.0 - np.interp(need - 0.5, g, Q_GRID, left=0.0, right=1.0))
        out["p_reach"] = min(0.995, max(0.005, p_reach))
    else:
        out["p_reach"] = 1.0 if r >= line else 0.0

    out["final_expected"] = r + end["mu"]
    out["final_p10"] = r + float(np.percentile(end["grid"], 25))
    out["final_p90"] = r + float(np.percentile(end["grid"], 75))
    out["final_p05"] = r + float(np.percentile(end["grid"], 10))
    out["final_p95"] = r + float(np.percentile(end["grid"], 90))

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
                             np.full(len(F), home_adv), np.full(len(F), toss)])
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
                               (10 - w) / 10.0, (rrr - par_rpo) / 4.0, home_adv, toss]])
                wp = float(logistic_predict(E["w2_np"], x)[0])
                out["win_logistic"] = wp
                if mc is not None:
                    out["mc_p_win"] = float((mc["end"] >= need).mean())
                    wp = (1.0 - MC_BLEND) * wp + MC_BLEND * out["mc_p_win"]
            out["needed"] = need
    out["win_prob"] = None if wp is None else min(0.995, max(0.005, wp))
    out["mc"] = None if mc is None else {
        "mean": float(r + mc["end"].mean()), "p10": float(r + np.percentile(mc["end"], 10)),
        "p90": float(r + np.percentile(mc["end"], 90)), "n": int(len(mc["end"])),
    }
    out["h2h"] = (wa, wb)
    out["h2h_venue"] = (v_wa, v_wb)
    out["h2h_blend"] = h2h
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
        if abs(end.get("gb", 0.0)) > 0.005:
            rows.append(("Gradient-boosting correction (non-linear)", float(end["gb"])))
        if end.get("pitch_dew"):
            rows.append(("Pitch condition + dew", float(end["pitch_dew"])))
        for nm, v in end.get("notes", []):
            rows.append((nm, float(v)))
    out["factors"] = sorted(rows, key=lambda x: -abs(x[1]))
    out["end_mu_raw"] = end.get("mu_raw", 0.0)
    return out


def predict_path(E, s):
    """Expected score + 10/90 range at the end of every remaining over."""
    T = E["T"]
    inn = int(s["innings"]); b = min(int(s["b"]), T); r = float(s["r"]); w = min(int(s["w"]), 10)
    ctx = team_ctx(E, s["batting_team"], s["bowling_team"], s.get("ground", ""), inn)[0]
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
    mu = np.maximum(ridge_predict(E["models_np"][inn], X) + gb_predict(E["gb_np"].get(inn), X), 0.0)
    dew = {"none": 1.0, "some": 1.03, "heavy": 1.06}.get(s.get("dew_level", "none"), 1.0) if inn == 2 else 1.0
    mu = mu * float(s.get("pitch_mult", 1.0)) * dew
    rows = []
    for e, m_, H in zip(ends, mu, Hs):
        q = _resid_row(E, inn, int(H))
        rows.append((e // 6, r + m_, r + max(0.0, m_ + q[9]), r + max(0.0, m_ + q[89])))
    return rows


def confidence_info(E, batting_team, bowling_team, ground, h2h_counts, venue_counts, squad_info):
    """How much real history backs THIS situation (ground, both teams, their
    head-to-head, the named XI). Returns {"score" 0-1, "label", "lines"}."""
    g = E["ground"].get(ground or "", {})
    n_g = int(g.get("n", 0))
    tb = E["team"].get(batting_team, {})
    tw = E["team"].get(bowling_team, {})
    rec_b = int(tb.get("n_recent", 0)); rec_w = int(tw.get("n_recent", 0))
    wa, wb = h2h_counts
    v_wa, v_wb = venue_counts
    s_g = min(1.0, n_g / 12.0)
    s_t = min(1.0, min(rec_b, rec_w) / 12.0)
    s_h = min(1.0, (wa + wb) / 8.0)
    score = 0.4 * s_g + 0.4 * s_t + 0.2 * s_h
    label = "High" if score >= 0.7 else ("Medium" if score >= 0.45 else "Low")
    lines = [
        f"Ground: {n_g} matches on record" if n_g else "Ground: no history (neutral)",
        f"Matches in last 12 months: {batting_team} {rec_b}, {bowling_team} {rec_w}",
        f"Head-to-head: {wa + wb} meetings ({v_wa + v_wb} at this ground)",
    ]
    if squad_info:
        parts = []
        if squad_info.get("bat_conf") is not None and squad_info.get("bat_n", 0):
            parts.append(f"batting XI {squad_info['bat_conf'] * 100:.0f}%")
        if squad_info.get("bowl_conf") is not None and squad_info.get("bowl_n", 0):
            parts.append(f"bowling XI {squad_info['bowl_conf'] * 100:.0f}%")
        if parts:
            lines.append("Playing XI data trust: " + ", ".join(parts))
    return {"score": score, "label": label, "lines": lines}


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
    """Teams of the league itself (main archive only) - extra-archive
    opponents (e.g. ACT Meteors in the Spring Challenge) never show up."""
    latest = get_latest_season(_connection, league)

    def teams_for(seasons):
        ph = ",".join("?" for _ in seasons)
        rows = _connection.execute(
            f"SELECT DISTINCT d.batting_team FROM deliveries d JOIN matches m "
            f"ON m.match_id=d.match_id AND m.league=d.league WHERE d.league=? AND m.comp='main' "
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
        "SELECT DISTINCT d.batting_team FROM deliveries d JOIN matches m "
        "ON m.match_id=d.match_id AND m.league=d.league WHERE d.league=? AND m.comp='main' "
        "AND d.batting_team<>'' ORDER BY d.batting_team", (league,)).fetchall()
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


def _recency(date_text, ref_ord, hl_days):
    """0.5 ** (age_in_days / half_life_days) for a match date (ISO text)."""
    try:
        age = max(0, int(ref_ord) - datetime.date.fromisoformat(str(date_text)[:10]).toordinal())
    except Exception:
        age = float(hl_days)
    return 0.5 ** (age / float(hl_days))


@st.cache_data(show_spinner=False)
def player_batting_phase(_connection, league, name, pp_end, death_over, ref_ord, hl_days):
    """Recency-weighted {phase: (batter_runs, legal_balls)} for the model,
    raw {phase: (runs, balls)} for display/trust, and dismissals."""
    rows = _connection.execute(
        "SELECT m.match_date, CASE WHEN d.over_no < ? THEN 0 WHEN d.over_no < ? THEN 1 ELSE 2 END AS ph, "
        "SUM(d.batter_runs), SUM(d.legal), SUM(CASE WHEN d.player_out=d.batter THEN 1 ELSE 0 END) "
        "FROM deliveries d JOIN matches m ON m.match_id=d.match_id AND m.league=d.league "
        "WHERE d.league=? AND d.batter=? GROUP BY d.match_id, ph",
        (pp_end, death_over, league, name)).fetchall()
    wph = {0: [0.0, 0.0], 1: [0.0, 0.0], 2: [0.0, 0.0]}
    raw = {0: [0, 0], 1: [0, 0], 2: [0, 0]}
    dis = 0
    for match_date, ph, runs, balls, d_ in rows:
        wgt = _recency(match_date, ref_ord, hl_days)
        ph = int(ph)
        wph[ph][0] += wgt * int(runs or 0); wph[ph][1] += wgt * int(balls or 0)
        raw[ph][0] += int(runs or 0); raw[ph][1] += int(balls or 0)
        dis += int(d_ or 0)
    return {"phase": {p: tuple(v) for p, v in wph.items()},
            "raw": {p: tuple(v) for p, v in raw.items()}, "dismissals": dis}


@st.cache_data(show_spinner=False)
def player_bowling_phase(_connection, league, name, pp_end, death_over, ref_ord, hl_days):
    rows = _connection.execute(
        "SELECT m.match_date, CASE WHEN d.over_no < ? THEN 0 WHEN d.over_no < ? THEN 1 ELSE 2 END AS ph, "
        "SUM(d.bowler_runs), SUM(d.legal), SUM(d.bowler_wkts) "
        "FROM deliveries d JOIN matches m ON m.match_id=d.match_id AND m.league=d.league "
        "WHERE d.league=? AND d.bowler=? GROUP BY d.match_id, ph",
        (pp_end, death_over, league, name)).fetchall()
    wph = {0: [0.0, 0.0], 1: [0.0, 0.0], 2: [0.0, 0.0]}
    raw = {0: [0, 0], 1: [0, 0], 2: [0, 0]}
    wk = 0
    for match_date, ph, runs, balls, w_ in rows:
        wgt = _recency(match_date, ref_ord, hl_days)
        ph = int(ph)
        wph[ph][0] += wgt * int(runs or 0); wph[ph][1] += wgt * int(balls or 0)
        raw[ph][0] += int(runs or 0); raw[ph][1] += int(balls or 0)
        wk += int(w_ or 0)
    return {"phase": {p: tuple(v) for p, v in wph.items()},
            "raw": {p: tuple(v) for p, v in raw.items()}, "wickets": wk}


@st.cache_data(show_spinner=False)
def matchup_stats(_connection, league, batter, bowler, ref_ord, hl_days):
    """Recency-weighted (runs, balls) of batter vs bowler + raw balls."""
    rows = _connection.execute(
        "SELECT m.match_date, SUM(d.batter_runs), SUM(d.legal), "
        "SUM(CASE WHEN d.player_out=d.batter THEN 1 ELSE 0 END) "
        "FROM deliveries d JOIN matches m ON m.match_id=d.match_id AND m.league=d.league "
        "WHERE d.league=? AND d.batter=? AND d.bowler=? GROUP BY d.match_id",
        (league, batter, bowler)).fetchall()
    wr = wb = 0.0
    raw_balls = outs = 0
    for match_date, runs, balls, dismissed in rows:
        wgt = _recency(match_date, ref_ord, hl_days)
        wr += wgt * int(runs or 0); wb += wgt * int(balls or 0)
        raw_balls += int(balls or 0); outs += int(dismissed or 0)
    return (wr, wb, raw_balls, outs)


@st.cache_data(show_spinner=False)
def squad_batting_strength(_connection, league, names, pp_end, death_over, lg_bat_ball, ref_ord, hl_days):
    """Average, shrunk, phase-split batting strength of a named XI, in the
    SAME units as the team-level bat_nd/bat_d features (runs/over vs
    league), recency weighted. Confidence (0-1) reflects how much real ball
    data backs the named players - an unknown name contributes nothing, so
    an XI of mostly-unknown names safely falls back to the team average."""
    if not names:
        return 0.0, 0.0, 0.0
    l_nd = (lg_bat_ball[0] + lg_bat_ball[1]) / 2.0
    l_d = lg_bat_ball[2]
    nd_vals, d_vals, confs = [], [], []
    for name in names:
        stats = player_batting_phase(_connection, league, name, pp_end, death_over, ref_ord, hl_days)
        ph, raw = stats["phase"], stats["raw"]
        nd_runs, nd_balls = ph[0][0] + ph[1][0], ph[0][1] + ph[1][1]
        d_runs, d_balls = ph[2]
        nd_vals.append((nd_runs + 150.0 * l_nd) / (nd_balls + 150.0))
        d_vals.append((d_runs + 40.0 * l_d) / (d_balls + 40.0))
        confs.append(min(1.0, (raw[0][1] + raw[1][1] + raw[2][1]) / 220.0))
    conf = sum(confs) / len(confs)
    return (sum(nd_vals) / len(nd_vals) - l_nd) * 6.0, (sum(d_vals) / len(d_vals) - l_d) * 6.0, conf


@st.cache_data(show_spinner=False)
def squad_bowling_strength(_connection, league, names, pp_end, death_over, lg_bowl_ball, ref_ord, hl_days):
    if not names:
        return 0.0, 0.0, 0.0
    l_nd = (lg_bowl_ball[0] + lg_bowl_ball[1]) / 2.0
    l_d = lg_bowl_ball[2]
    nd_vals, d_vals, confs = [], [], []
    for name in names:
        stats = player_bowling_phase(_connection, league, name, pp_end, death_over, ref_ord, hl_days)
        ph, raw = stats["phase"], stats["raw"]
        nd_runs, nd_balls = ph[0][0] + ph[1][0], ph[0][1] + ph[1][1]
        d_runs, d_balls = ph[2]
        nd_vals.append((nd_runs + 150.0 * l_nd) / (nd_balls + 150.0))
        d_vals.append((d_runs + 40.0 * l_d) / (d_balls + 40.0))
        confs.append(min(1.0, (raw[0][1] + raw[1][1] + raw[2][1]) / 220.0))
    conf = sum(confs) / len(confs)
    return (sum(nd_vals) / len(nd_vals) - l_nd) * 6.0, (sum(d_vals) / len(d_vals) - l_d) * 6.0, conf


def build_player_info(connection, E, league, striker, non_striker, bowler, b):
    """Turns the selected players into the phase-specific numbers the
    engine's bounded player adjustment needs (recency weighted). Manual /
    unknown names have no history, so they come out neutral (zero balls)."""
    if not (striker or non_striker or bowler):
        return None
    ph = phase_of(E, b // 6)
    pp, dv = E["pp_end"], E["death_over"]
    ref, hl = E["latest_ord"], E["team_hl_days"]
    bat = []
    for weight, name in ((0.6, striker), (0.4, non_striker)):
        if name:
            stats = player_batting_phase(connection, league, name, pp, dv, ref, hl)
            bat.append((weight, *stats["phase"][ph]))
    bowl = None
    match = []
    if bowler:
        stats = player_bowling_phase(connection, league, bowler, pp, dv, ref, hl)
        bowl = stats["phase"][ph]
        for weight, name in ((0.6, striker), (0.4, non_striker)):
            if name:
                runs, balls, _raw, _outs = matchup_stats(connection, league, name, bowler, ref, hl)
                match.append((weight, runs, balls))
    return {"bat": bat or None, "bowl": bowl, "match": match or None}


@st.cache_data(show_spinner=False)
def data_freshness(_connection, league, db_sig):
    """What the database actually contains right now (so you can SEE that
    the latest matches - e.g. the Spring Challenge - made it in)."""
    total, last_date, n_extra = _connection.execute(
        "SELECT COUNT(*), MAX(match_date), SUM(CASE WHEN comp='extra' THEN 1 ELSE 0 END) "
        "FROM matches WHERE league=?", (league,)).fetchone()
    last_extra = _connection.execute(
        "SELECT MAX(match_date) FROM matches WHERE league=? AND comp='extra'", (league,)).fetchone()[0]
    recent = _connection.execute(
        "SELECT COUNT(*) FROM matches WHERE league=? AND match_date >= date('now','-30 day')",
        (league,)).fetchone()[0]
    return {"total": int(total or 0), "last_date": last_date or "-", "extra": int(n_extra or 0),
            "last_extra": last_extra or "-", "last30": int(recent or 0)}


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
# VasuDev Cricket AI - ENGINE v2          (PART 2 of 2)
# Paste this file RIGHT BELOW Part 1 (same app.py). Part 1 + Part 2 = the complete app.


# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "runs": 0, "wickets": 0, "balls": 0, "last": "New innings",
    "undo_stack": [], "target": 0,
    "recent_balls": [], "pending_extras": 0.0, "bsw": 99,
    "projection_end_over": 6, "projection_user_set": False, "score_prediction": 0,
    "on_strike_index": 0, "dismissed_batsmen": [],
    "awaiting_new_batsman": False, "out_slot_index": None,
    "batter_live": {}, "bowler_live": {}, "partnership_runs": 0,
    "this_over": [], "over_history": [],
    "state_version": 0, "live_status": {}, "live_warnings": [], "live_setup": {},
    "live_unmapped": False, "live_team_pending": False, "live_players_pending": False,
    "live_xi_pending": False,
}
for _key, _value in DEFAULTS.items():
    st.session_state.setdefault(_key, _value)


def bump_state_version():
    """Every change of the scoreboard that does NOT come from a widget
    (ball button, live sync, catch-up, reset ...) bumps this; the sidebar
    widgets re-read the live state when they see a new version, so header
    and sidebar always show the same score."""
    st.session_state["state_version"] = int(st.session_state.get("state_version", 0)) + 1


def queue_widget_value(key, value):
    """Streamlit forbids changing a widget's value after the widget was
    drawn in this run. Anything queued here is applied at the very top of
    the NEXT run, before any widget exists."""
    st.session_state.setdefault("pending_widget_values", {})[key] = value


_pending_values = st.session_state.pop("pending_widget_values", None)
if _pending_values:
    for _k, _v in _pending_values.items():
        st.session_state[_k] = _v


MANUAL_OPTION_LABEL = "Other / Type manually"

# Widget keys / remembered selections that belong to ONE match: wiped when
# another match is loaded so nothing of the old match can leak into the new.
MATCH_WIDGET_KEYS = [
    "batting_team_select", "bowling_team_select", "ground_select", "ground_manual",
    "batsman_a_select", "batsman_a_manual", "batsman_b_select", "batsman_b_manual",
    "current_bowler_select", "current_bowler_manual", "batting_xi_select", "bowling_xi_select",
    "toss_select", "innings_select", "target_runs_widget", "incoming_batsman_select",
]
MATCH_PERSISTED_KEYS = [
    "persisted_batting_team", "persisted_bowling_team", "persisted_ground", "persisted_ground_manual",
    "persisted_innings_label", "persisted_batsman_a", "persisted_batsman_a_manual",
    "persisted_batsman_b", "persisted_batsman_b_manual", "persisted_current_bowler",
    "persisted_current_bowler_manual", "persisted_toss", "persisted_batting_xi", "persisted_bowling_xi",
]


def reset_match_state(clear_selections=True):
    ss = st.session_state
    for k in ("runs", "wickets", "balls"):
        ss[k] = 0
    ss.recent_balls = []
    ss.pending_extras = 0.0
    ss.bsw = 99
    ss.undo_stack = []
    ss.last = "New match" if clear_selections else "New innings"
    ss.on_strike_index = 0
    ss.dismissed_batsmen = []
    ss.awaiting_new_batsman = False
    ss.out_slot_index = None
    ss.batter_live = {}
    ss.bowler_live = {}
    ss.partnership_runs = 0
    ss.this_over = []
    ss.over_history = []
    if clear_selections:
        ss.target = 0
        for k in MATCH_WIDGET_KEYS:
            ss.pop(k, None)
        for k in MATCH_PERSISTED_KEYS:
            ss.pop(k, None)
        ss["live_ingested_keys"] = {}
        ss["live_status"] = {}
        ss["live_warnings"] = []
        ss["live_unmapped"] = False
        ss["live_setup"] = {}
        ss["projection_user_set"] = False
    bump_state_version()


def restored_index(options, persisted_key):
    value = st.session_state.get(persisted_key)
    return options.index(value) if value in options else 0


def idx_kw(widget_key, options, persisted_key):
    """`index=` only while the widget has no value yet. (A widget whose value
    was also written through st.session_state - the live fill does that -
    must not get a default too, or Streamlit shows a yellow warning.)"""
    return {} if widget_key in st.session_state else {"index": restored_index(options, persisted_key)}


def select_with_manual_option(label, options, persisted_select_key, persisted_manual_key, widget_key):
    """Selectbox with an 'Other / Type manually' entry for names that are
    not in Cricsheet yet (debutants, new grounds)."""
    combined = list(options) + [MANUAL_OPTION_LABEL]
    sel_key = f"{widget_key}_select"
    choice = st.selectbox(label, combined, key=sel_key, **idx_kw(sel_key, combined, persisted_select_key))
    st.session_state[persisted_select_key] = choice
    if choice == MANUAL_OPTION_LABEL:
        man_key = f"{widget_key}_manual"
        kw = {} if man_key in st.session_state else {"value": st.session_state.get(persisted_manual_key, "")}
        typed = st.text_input(f"Type {label}", key=man_key, **kw).strip()
        st.session_state[persisted_manual_key] = typed
        return typed if typed else "Not Selected"
    st.session_state[persisted_manual_key] = ""
    return choice


def set_select_value(widget_key, persisted_key, value, options):
    """Write a value into a selectbox widget (only if it is a valid option)."""
    if value in options:
        st.session_state[widget_key] = value
        st.session_state[persisted_key] = value
        return True
    return False


def set_manual_value(base, persisted_select_key, persisted_manual_key, typed):
    st.session_state[f"{base}_select"] = MANUAL_OPTION_LABEL
    st.session_state[f"{base}_manual"] = typed
    st.session_state[persisted_select_key] = MANUAL_OPTION_LABEL
    st.session_state[persisted_manual_key] = typed


# ============================================================
# LIVE CRICKET API MODE (additive - manual mode is untouched)
# ============================================================
#
# Provider: CricketData.org / CricAPI (https://cricapi.com). All API-specific
# code is isolated in this section so another provider could be swapped in
# without touching the prediction engine. The API NEVER supplies a
# prediction - only raw match facts.
#
# Field names below follow the provider's documented shape; they are parsed
# defensively (several key names tried, a missing field never crashes). The
# sidebar shows the raw JSON (match + scorecard + ball-by-ball) in an
# expander so a mismatch is easy to spot. Whatever the API does NOT give is
# listed in "Live data status" as "not available - fill manually": nothing
# is invented. Each FETCH may use up to 3 API hits (match, scorecard,
# ball-by-ball); an endpoint that fails twice in a row is skipped.

LIVE_API_BASE = "https://api.cricapi.com/v1"


def _live_api_get(path, params):
    """One HTTP GET to the live provider. Never raises - returns
    (data_or_None, error_message_or_None). This is the ONLY function that
    talks to the network for live data."""
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


def _cap_ok(name):
    return int(st.session_state.setdefault("api_caps", {}).get(name, 0)) < 2


def _cap_result(name, ok):
    caps = st.session_state.setdefault("api_caps", {})
    caps[name] = 0 if ok else int(caps.get(name, 0)) + 1


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
    """Teams, venue, toss, score array (per-innings r/w/o), status.
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


def fetch_match_scorecard(match_id):
    """Batting + bowling figures per innings (current batters, bowlers)."""
    if not match_id or not _cap_ok("scorecard"):
        return None, "skipped"
    data, error = _live_api_get("match_scorecard", {"id": match_id})
    info = data.get("data") if isinstance(data, dict) else None
    ok = bool(not error and isinstance(info, dict))
    _cap_result("scorecard", ok)
    return (info, None) if ok else (None, error or "Scorecard response had no usable data.")


def fetch_match_squad(match_id):
    """Squads / Playing XI per team, if the provider has them."""
    if not match_id or not _cap_ok("squad"):
        return None, "skipped"
    data, error = _live_api_get("match_squad", {"id": match_id})
    info = data.get("data") if isinstance(data, dict) else None
    ok = bool(not error and isinstance(info, list) and info)
    _cap_result("squad", ok)
    return (info, None) if ok else (None, error or "Squad response had no usable data.")


def fetch_ball_by_ball(match_id):
    """Best-effort ball-by-ball. Many plans do not expose it - then this
    returns (None, note) and the caller falls back to the cumulative score."""
    if not match_id or not _cap_ok("bbb"):
        return None, "skipped"
    data, error = _live_api_get("match_bbb", {"id": match_id})
    info = data.get("data") if isinstance(data, dict) else None
    ok = bool(not error and isinstance(info, dict))
    _cap_result("bbb", ok)
    return (info, None) if ok else (None, "Ball-by-ball not available from this API plan/endpoint.")


# ------------------------------------------------------------
# name matching (strict: a wrong match is worse than "pick manually")
# ------------------------------------------------------------

IGNORABLE_TEAM_TOKENS = {"women", "womens", "w", "men", "mens", "cricket", "team", "club"}
WOMEN_TOKENS = {"women", "womens", "w"}
TEAM_ALIASES = {
    "usa": "united states of america", "united states": "united states of america",
    "uae": "united arab emirates", "png": "papua new guinea",
}


def _normalize_name(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _team_tokens(name):
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    toks = [t for t in text.split() if t]
    joined = " ".join(toks)
    if joined in TEAM_ALIASES:
        toks = TEAM_ALIASES[joined].split()
    return toks


def match_team_name(api_name, roster_options, league_gender="male"):
    """Exact match after removing gender words only. 'Australia A' (extra
    token 'a') NEVER matches 'Australia'; 'India Women' never matches a
    men's league. Prefix abbreviations ('Melb' -> 'Melbourne', >=4 letters)
    are accepted only if they identify exactly one team. None = not found."""
    api_toks = _team_tokens(api_name)
    if not api_toks:
        return None
    if any(t in WOMEN_TOKENS for t in api_toks) and league_gender != "female":
        return None
    api_core = [t for t in api_toks if t not in IGNORABLE_TEAM_TOKENS]
    if not api_core:
        return None
    for option in roster_options:
        if [t for t in _team_tokens(option) if t not in IGNORABLE_TEAM_TOKENS] == api_core:
            return option
    cands = []
    for option in roster_options:
        opt_core = [t for t in _team_tokens(option) if t not in IGNORABLE_TEAM_TOKENS]
        if len(opt_core) == len(api_core) and all(
                o == a or (len(a) >= 4 and o.startswith(a)) for a, o in zip(api_core, opt_core)):
            cands.append(option)
    return cands[0] if len(cands) == 1 else None


GENERIC_VENUE_WORDS = {
    "stadium", "ground", "oval", "cricket", "international", "the", "park", "sports", "complex",
    "club", "and", "of", "association", "arena", "centre", "center",
}


def _venue_tokens(name):
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    return [t for t in text.split() if t and t not in GENERIC_VENUE_WORDS]


def match_ground_name(api_venue, grounds):
    """Best token-overlap venue (>= 0.5) that clearly beats the runner-up."""
    a = set(_venue_tokens(api_venue))
    if not a:
        return None
    scored = []
    for g in grounds:
        gt = set(_venue_tokens(g))
        if gt:
            scored.append((len(a & gt) / len(a | gt), g))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.5 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.1):
        return scored[0][1]
    return None


def _name_tokens(name):
    text = re.sub(r"[^a-z ]+", " ", str(name or "").lower().replace("-", " "))
    return [t for t in text.split() if t]


def match_player_name(api_name, roster_options):
    """'Virat Kohli' -> Cricsheet 'V Kohli'. Same surname + same first
    initial, and only if exactly one roster name fits. None = not sure."""
    if not api_name or not roster_options:
        return None
    norm = _normalize_name(api_name)
    for o in roster_options:
        if _normalize_name(o) == norm:
            return o
    toks = _name_tokens(api_name)
    if len(toks) < 2:
        return None
    first = toks[0]
    sur_variants = {toks[-1], "".join(toks[1:])}
    cands = []
    for o in roster_options:
        otoks = _name_tokens(o)
        if len(otoks) < 2:
            continue
        o_init, o_sur_last, o_sur = otoks[0], otoks[-1], "".join(otoks[1:])
        if o_init[0] != first[0]:
            continue
        if o_sur in sur_variants or o_sur_last in sur_variants:
            cands.append(o)
    return cands[0] if len(cands) == 1 else None


# ------------------------------------------------------------
# parsing
# ------------------------------------------------------------

def _name_of(x):
    if isinstance(x, dict):
        return str(x.get("name") or x.get("fullname") or x.get("player") or "").strip()
    return str(x or "").strip()


def _to_int(x, default=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def parse_over_ball(overs_value):
    """CricAPI reports overs as a float like 14.2 (14 overs, 2 balls) -
    already the same 'over.ball' convention this app uses."""
    try:
        text = f"{float(overs_value):.1f}"
        return over_to_balls(text)
    except (TypeError, ValueError):
        return None


def team_in_label(label, teams):
    """Longest team name contained in an innings label ('India A Inning 1')."""
    label_l = str(label or "").lower()
    best = None
    for t in teams:
        if str(t).lower() in label_l and (best is None or len(str(t)) > len(str(best))):
            best = t
    return best


def parse_revised_target(status_text):
    """DLS / revised target written into the status line, if any."""
    text = str(status_text or "")
    if not re.search(r"dls|d/l|duckworth|revised|reduced", text, re.I):
        return None
    mt = re.search(r"target[^0-9]{0,15}(\d{2,3})", text, re.I)
    return int(mt.group(1)) if mt else None


def parse_live_match(raw):
    """CricAPI match_info -> plain fields. Every value defaults to
    None/[] rather than a guess if the provider didn't include it."""
    if not isinstance(raw, dict):
        return {}
    teams = [str(t) for t in (raw.get("teams") or [])]
    toss_info = raw.get("toss") if isinstance(raw.get("toss"), dict) else {}
    score_list = [x for x in (raw.get("score") or []) if isinstance(x, dict)] \
        if isinstance(raw.get("score"), list) else []

    players_by_team = {}
    for block in (raw.get("players") or []):
        if not isinstance(block, dict):
            continue
        team_name = block.get("team") or block.get("teamName") or block.get("shortname") or ""
        names = []
        for player in (block.get("playing11") or block.get("players") or block.get("squad") or []):
            nm = _name_of(player)
            if nm:
                names.append(nm)
        if team_name and names:
            players_by_team[str(team_name)] = names

    return {
        "teams": teams,
        "venue": str(raw.get("venue") or raw.get("venueName") or ""),
        "status": str(raw.get("status") or ""),
        "match_type": str(raw.get("matchType") or ""),
        "series_name": str(raw.get("series") or ""),
        "match_name": str(raw.get("name") or ""),
        "toss_winner": raw.get("tossWinner") or toss_info.get("winner"),
        "toss_choice": raw.get("tossChoice") or toss_info.get("decision"),
        "score_list": score_list,
        "players_by_team": players_by_team,
    }


def interpret_innings(parsed):
    """Which innings is on, which side bats, current score, target.
    The batting side comes from the innings label of the score entry
    ('West Indies Inning 1') - NOT from the order of the two team names."""
    out = {"innings_no": None, "batting": None, "bowling": None, "runs": None, "wickets": None,
           "balls": None, "target": None, "target_src": "", "label": "", "break": False}
    teams = parsed.get("teams") or []
    real = [x for x in (parsed.get("score_list") or []) if "super" not in str(x.get("inning", "")).lower()]
    if not real:
        return out

    def other(team):
        rest = [t for t in teams if t != team]
        return rest[0] if team and len(rest) == 1 else None

    status_l = str(parsed.get("status", "")).lower()
    if len(real) == 1 and ("innings break" in status_l or "inning break" in status_l):
        bat1 = team_in_label(real[0].get("inning"), teams)
        out.update(innings_no=2, batting=other(bat1), bowling=bat1, runs=0, wickets=0, balls=0, label="",
                   target=_to_int(real[0].get("r")) + 1, target_src="1st innings + 1", **{"break": True})
        return out

    cur = real[-1]
    n = len(real)
    batting = team_in_label(cur.get("inning"), teams)
    if batting is None and n == 1:
        tw, tc = parsed.get("toss_winner"), str(parsed.get("toss_choice") or "").lower()
        if tw and tc:
            batting = tw if "bat" in tc else other(tw)
    out.update(
        innings_no=n if n in (1, 2) else None, batting=batting, bowling=other(batting),
        runs=_to_int(cur.get("r"), None) if cur.get("r") is not None else None,
        wickets=_to_int(cur.get("w")), balls=parse_over_ball(cur.get("o")),
        label=str(cur.get("inning") or ""),
    )
    if n >= 2:
        out["target"] = _to_int(real[0].get("r")) + 1
        out["target_src"] = "1st innings + 1"
    revised = parse_revised_target(parsed.get("status"))
    if revised and n >= 2:
        out["target"] = revised
        out["target_src"] = "revised (DLS) target from the match status"
    return out


def _is_not_out(item):
    txt = str(item.get("dismissal-text") or item.get("dismissal-info") or item.get("dismissal") or "").strip().lower()
    return txt in ("batting", "not out", "notout", "not-out") or txt.startswith("not out")


def _is_dismissed(item):
    txt = str(item.get("dismissal-text") or item.get("dismissal-info") or item.get("dismissal") or "").strip().lower()
    return bool(txt) and not _is_not_out(item) and "did not bat" not in txt and txt not in ("dnb", "yet to bat")


def parse_scorecard(sc_raw, batting_team, innings_label):
    """Current batters (not out), last bowler, dismissed batters from the
    scorecard of the innings in progress."""
    out = {"ok": False, "batters": [], "bowler": None, "dismissed": [], "last_out": None,
           "new_batter_balls": None}
    if not isinstance(sc_raw, dict):
        return out
    cards = sc_raw.get("scorecard") or sc_raw.get("scoreCard") or []
    if not isinstance(cards, list) or not cards:
        return out
    cards = [c for c in cards if isinstance(c, dict)]
    chosen = None
    label_l = str(innings_label or "").strip().lower()
    if label_l:
        for c in cards:
            if str(c.get("inning", "")).strip().lower() == label_l:
                chosen = c
    if chosen is None and batting_team:
        for c in cards:
            if str(batting_team).lower() in str(c.get("inning", "")).lower():
                chosen = c
    if chosen is None and cards:
        chosen = cards[-1]
    if chosen is None:
        return out

    batting = [x for x in (chosen.get("batting") or []) if isinstance(x, dict)]
    rows = []
    for it in batting:
        nm = _name_of(it.get("batsman") or it.get("batter") or it.get("name"))
        if not nm:
            continue
        rows.append({"name": nm, "r": _to_int(it.get("r")), "b": _to_int(it.get("b")),
                     "4s": _to_int(it.get("4s")), "6s": _to_int(it.get("6s")),
                     "out": _is_dismissed(it), "not_out": _is_not_out(it)})
    at_crease = [x for x in rows if x["not_out"]]
    dismissed = [x for x in rows if x["out"]]
    out["batters"] = at_crease[-2:] if len(at_crease) > 2 else at_crease
    out["dismissed"] = [x["name"] for x in dismissed]
    out["last_out"] = dismissed[-1] if dismissed else None
    if len(out["batters"]) == 2:
        out["new_batter_balls"] = out["batters"][1]["b"]       # later arrival = the new batter

    bowling = [x for x in (chosen.get("bowling") or []) if isinstance(x, dict)]
    if bowling:
        last = bowling[-1]
        nm = _name_of(last.get("bowler") or last.get("name"))
        if nm:
            out["bowler"] = {"name": nm, "balls": parse_over_ball(last.get("o")) or 0,
                             "r": _to_int(last.get("r")), "w": _to_int(last.get("w"))}
    out["ok"] = bool(out["batters"] or out["bowler"])
    return out


def parse_ball_by_ball_deliveries(bbb_raw):
    """Flatten a ball-by-ball payload into an ordered list of
    {runs, is_wicket, legal, batter, bowler} dicts, trying a few plausible
    provider shapes defensively. Returns [] (not an error) if nothing
    recognisable is found."""
    if not isinstance(bbb_raw, dict):
        return []
    raw_overs = None
    for key in ("overs", "over", "ballByBall", "data"):
        value = bbb_raw.get(key)
        if isinstance(value, list) and value:
            raw_overs = value
            break
    if raw_overs is None:
        return []

    out = []
    for over_block in raw_overs:
        if not isinstance(over_block, dict):
            continue
        over_no = over_block.get("over")
        if over_no is None:
            over_no = over_block.get("overNumber")
        deliveries = over_block.get("balls") or over_block.get("deliveries") or []
        if not isinstance(deliveries, list):
            continue
        try:
            ov = int(over_no)
        except (TypeError, ValueError):
            continue
        for i, ball in enumerate(deliveries, start=1):
            if not isinstance(ball, dict):
                continue
            runs = ball.get("runs")
            if runs is None:
                runs = ball.get("r", 0)
            extra_type = str(ball.get("type") or ball.get("extraType") or "").lower()
            out.append({
                "runs": _to_int(runs),
                "is_wicket": bool(ball.get("wicket") or ball.get("isWicket") or ball.get("out")),
                "legal": extra_type not in ("wide", "wd", "noball", "nb", "no ball"),
                "batter": _name_of(ball.get("batsman") or ball.get("batter") or ball.get("striker")),
                "bowler": _name_of(ball.get("bowler")),
                "sort_key": (ov, i),
            })
    out.sort(key=lambda d: d["sort_key"])
    return out


def legal_ball_values(deliveries):
    """Per-LEGAL-ball runs (extras bowled before a legal ball are folded
    into it, exactly like the app's own ball buttons), wicket positions."""
    vals, wk_idx, pending = [], [], 0.0
    last_legal = None
    for d in deliveries:
        if d["legal"]:
            vals.append(float(d["runs"]) + pending)
            pending = 0.0
            if d["is_wicket"]:
                wk_idx.append(len(vals) - 1)
            last_legal = d
        else:
            pending += float(d["runs"])
    return {"vals": vals, "wk_idx": wk_idx, "n": len(vals), "last": last_legal}


def guess_league_for_match(match_type, series_name, match_name, teams):
    """Returns (league or None, note). T20 only (IPL, BBL, WBBL, T20I)."""
    mt = str(match_type or "").lower()
    series = str(series_name or "").lower()
    name = str(match_name or "").lower()
    blob = " ".join([series, name] + [str(t).lower() for t in teams])
    is_women = bool(re.search(r"\bwomen\b|\bwomens\b|women's|\bwbbl\b", blob))
    if "t20" not in mt and "twenty20" not in mt:
        return None, f"This match is '{match_type or 'unknown format'}' - the app is T20 only (IPL, BBL, WBBL, T20I)."
    if "ipl" in blob or "indian premier league" in blob:
        return "IPL", ""
    if "big bash" in blob or "bbl" in blob or "spring challenge" in blob:
        return ("Women's Big Bash League" if (is_women or "spring challenge" in blob) else "Men's Big Bash League"), ""
    if is_women:
        return None, "Women's international / other women's T20 is not one of the app's leagues."
    return "T20 International", ""


# ------------------------------------------------------------
# live match: load once, sync on every FETCH, fill the sidebar
# ------------------------------------------------------------

def live_sync(match_id, detail, sc_raw=None, bbb_raw=None):
    """Pull everything the API gave into VasuDev's state: score, innings,
    target (revised/DLS if given), recent balls, balls since last wicket,
    batters / bowler / toss / teams for the sidebar. Whatever the API did
    NOT give is marked "missing" in live_status - never invented. Returns a
    human-readable note."""
    ss = st.session_state
    parsed = parse_live_match(detail)
    ss["live_match_raw"] = detail
    live = interpret_innings(parsed)
    setup = dict(ss.get("live_setup") or {})
    status = dict(ss.get("live_status") or {})
    warnings = [w for w in (ss.get("live_warnings") or []) if not str(w).startswith("[sync]")]

    # ---- teams / toss / ground bookkeeping ----
    if live["batting"] and live["bowling"]:
        if live["batting"] != setup.get("batting_api"):
            ss["live_team_pending"] = True
            ss["live_xi_pending"] = True
        setup["batting_api"], setup["bowling_api"] = live["batting"], live["bowling"]
        status["Teams"] = ["live", f"{live['batting']} batting vs {live['bowling']} (from the innings label)"]
    else:
        status["Teams"] = ["missing", "Batting side not clear from the API yet - pick the teams manually"]
    setup["toss_winner"] = parsed.get("toss_winner") or setup.get("toss_winner")
    setup["toss_choice"] = parsed.get("toss_choice") or setup.get("toss_choice")
    setup["venue"] = parsed.get("venue") or setup.get("venue")
    if parsed.get("players_by_team"):
        setup["players_by_team"] = parsed["players_by_team"]

    status_text = parsed.get("status", "")
    if re.search(r"dls|d/l|duckworth|reduced|revised", status_text, re.I):
        warnings.append("[sync] DLS / reduced-overs match: the engine assumes the full 20 overs - use with care.")

    sc = parse_scorecard(sc_raw, live["batting"], live["label"]) if sc_raw else None
    deliveries = parse_ball_by_ball_deliveries(bbb_raw) if bbb_raw else []
    lbv = legal_ball_values(deliveries)

    if live["balls"] is None or live["runs"] is None:
        note = "Live API did not return a usable current score for this match right now."
        status["Score"] = ["missing", note]
    else:
        new_balls, new_runs, new_w = int(live["balls"]), int(live["runs"]), int(live["wickets"] or 0)
        ingested = ss.setdefault("live_ingested_keys", {})
        inn_key = f"{match_id}|{live['innings_no']}|{live['batting']}"
        prev = ingested.get(inn_key)
        gained = (new_balls - prev["balls"]) if prev else None

        bbb_ok = lbv["n"] >= 1 and new_balls > 0 and abs(lbv["n"] - new_balls) <= 3
        hint = None
        if bbb_ok:
            ss.recent_balls = lbv["vals"][-18:]
            ss.pending_extras = 0.0
            status["Last 2 overs"] = ["live", "exact, from ball-by-ball"]
            last = lbv["last"]
            if last and last.get("batter") and not last["is_wicket"]:
                hint = {"name": last["batter"], "swap": bool((int(last["runs"]) % 2 == 1) != (lbv["n"] % 6 == 0))}
            if lbv["wk_idx"]:
                ss.bsw = max(0, lbv["n"] - 1 - lbv["wk_idx"][-1])
                status["Last wicket"] = ["live", f"{ss.bsw} balls ago (ball-by-ball)"]
            elif new_w == 0:
                ss.bsw = 99
                status["Last wicket"] = ["live", "no wicket yet"]
        else:
            if new_balls == 0:
                ss.recent_balls = []
                status["Last 2 overs"] = ["live", "innings not started"]
            elif prev is None or new_balls < prev["balls"]:
                ss.recent_balls = [new_runs / new_balls] * min(12, new_balls)
                status["Last 2 overs"] = ["est", "ball-by-ball not available: average run rate used - type the real "
                                                 "'Runs in last 2 overs' in Start/Reset if you know it"]
            elif gained and gained > 0:
                avg = (new_runs - prev["runs"]) / gained
                ss.recent_balls = (list(ss.recent_balls) + [avg] * min(gained, 18))[-18:]
                status["Last 2 overs"] = ["est", "ball-by-ball not available: the new balls are covered by their "
                                                 "average rate (not invented deliveries)"]
        # balls since the last wicket when the ball-by-ball did not settle it
        if not (bbb_ok and (lbv["wk_idx"] or new_w == 0)):
            if new_w == 0:
                ss.bsw = 99
                status["Last wicket"] = ["live", "no wicket yet"]
            elif sc and sc["ok"] and sc["new_batter_balls"] is not None:
                ss.bsw = int(min(new_balls, 2 * sc["new_batter_balls"]))
                status["Last wicket"] = ["est", f"about {ss.bsw} balls ago (estimated from the new batter's balls)"]
            elif prev and new_w > prev["wickets"]:
                ss.bsw = int(max(0, (new_balls - prev["balls"]) // 2))
                status["Last wicket"] = ["est", "wicket fell since the last fetch - time estimated"]
            elif prev and ss.bsw < 99:
                ss.bsw = int(min(99, ss.bsw + max(0, new_balls - prev["balls"])))
                status["Last wicket"] = ["est", "carried forward from the last fetch"]
            else:
                ss.bsw = 99
                status["Last wicket"] = ["missing", "balls since the last wicket unknown - type it in Start/Reset"]
        if sc and sc.get("last_out") and status.get("Last wicket"):
            lo = sc["last_out"]
            status["Last wicket"][1] += f" | last out (approx.): {lo['name']} {lo['r']}({lo['b']})"
        setup["striker_hint"] = hint

        ingested[inn_key] = {"balls": new_balls, "runs": new_runs, "wickets": new_w}
        ss.runs, ss.wickets, ss.balls = new_runs, new_w, new_balls
        ss.last = "Live sync"
        status["Score"] = ["live", f"{new_runs}/{new_w} after {display_over(new_balls)} overs"]
        note = f"Synced {live['batting'] or 'innings'}: {new_runs}/{new_w} at {display_over(new_balls)}."

    # ---- innings number + target (revised/DLS if the API says so) ----
    if live["innings_no"] in (1, 2):
        label = "1st Innings" if live["innings_no"] == 1 else "2nd Innings"
        queue_widget_value("innings_select", label)
        ss["persisted_innings_label"] = label
        if live["innings_no"] == 2 and live["target"]:
            ss.target = int(live["target"])
            queue_widget_value("target_runs_widget", int(live["target"]))
            status["Innings & target"] = ["live", f"2nd innings, target {int(live['target'])} ({live['target_src']})"]
        elif live["innings_no"] == 1:
            ss.target = 0
            status["Innings & target"] = ["live", "1st innings"]
        else:
            status["Innings & target"] = ["missing", "target not available - type it in Target Runs"]
    else:
        status["Innings & target"] = ["missing", "innings not clear (super over / not started) - set it manually"]
    status["Pitch"] = ["est", "API gives no pitch data - 'Auto' estimate (ground + 1st innings) is used unless you pick one"]

    # ---- batters / bowler from the scorecard ----
    if sc and sc["ok"]:
        setup["batters"], setup["bowler"], setup["dismissed"] = sc["batters"], sc["bowler"], sc["dismissed"]
    else:
        setup["batters"], setup["bowler"], setup["dismissed"] = [], None, []
    ss["live_players_pending"] = True

    ss["live_setup"] = setup
    ss["live_status"] = status
    ss["live_warnings"] = warnings
    ss["live_last_sync_ts"] = time.time()
    ss["live_last_fetch_note"] = note
    bump_state_version()
    return note


def live_fetch_and_sync(match_id, detail=None):
    """match_info (+ scorecard + ball-by-ball when the plan has them) -> state."""
    ss = st.session_state
    if detail is None:
        detail, error = fetch_match_details(match_id)
        if error:
            ss["live_last_fetch_note"] = error
            return error
    sc_raw, _sc_err = fetch_match_scorecard(match_id)
    bbb_raw, _bbb_err = fetch_ball_by_ball(match_id)
    ss["live_scorecard_raw"] = sc_raw
    ss["live_bbb_raw"] = bbb_raw
    return live_sync(match_id, detail, sc_raw, bbb_raw)


def live_load_match(match_id):
    """A freshly chosen match: everything of the previous match is wiped
    first (done by the caller), then teams / ground / toss / XI / score are
    fetched and queued for the sidebar. Returns True if the match loaded."""
    ss = st.session_state
    detail, error = fetch_match_details(match_id)
    if error:
        ss["live_last_fetch_note"] = error
        return False
    parsed = parse_live_match(detail)
    league_guess, league_note = guess_league_for_match(
        parsed.get("match_type"), parsed.get("series_name"), parsed.get("match_name"), parsed.get("teams") or [])
    warnings = []
    if league_guess:
        queue_widget_value("league_select", league_guess)
        ss["persisted_league"] = league_guess
    elif league_note:
        warnings.append(league_note)

    setup = {
        "match_id": match_id, "players_by_team": dict(parsed.get("players_by_team") or {}),
        "batters": [], "bowler": None, "dismissed": [], "striker_hint": None,
        "venue": parsed.get("venue"), "toss_winner": parsed.get("toss_winner"),
        "toss_choice": parsed.get("toss_choice"), "match_name": parsed.get("match_name"),
        "batting_api": None, "bowling_api": None,
    }
    if not setup["players_by_team"]:
        squad_raw, _err = fetch_match_squad(match_id)
        for block in (squad_raw or []):
            if not isinstance(block, dict):
                continue
            team_name = block.get("teamName") or block.get("team") or block.get("shortname") or ""
            names = [_name_of(p) for p in (block.get("players") or []) if _name_of(p)]
            if team_name and names:
                setup["players_by_team"][str(team_name)] = names
    ss["live_setup"] = setup
    ss["live_team_pending"] = True
    ss["live_xi_pending"] = True
    ss["live_players_pending"] = True
    ss["live_warnings"] = warnings
    live_fetch_and_sync(match_id, detail=detail)
    return True


def apply_live_teams_and_ground(teams, grounds_list, gender):
    """BEFORE the team/ground widgets are drawn: map the live match's teams
    and ground onto this league's names and write them into the widget
    keys (setting only the 'persisted' keys never moves an existing widget).
    A team that cannot be matched is reported loudly - the old selection is
    never kept silently."""
    ss = st.session_state
    if not (ss.get("live_mode_on") and ss.get("live_team_pending")):
        return
    ss["live_team_pending"] = False
    setup = ss.get("live_setup") or {}
    status = dict(ss.get("live_status") or {})
    warnings = [w for w in (ss.get("live_warnings") or []) if not str(w).startswith("[map]")]
    bat_api, bowl_api = setup.get("batting_api"), setup.get("bowling_api")
    bat = match_team_name(bat_api, teams, gender) if bat_api else None
    bowl = match_team_name(bowl_api, teams, gender) if bowl_api else None
    if bat and bowl and bat != bowl:
        ss["batting_team_select"] = bat
        ss["persisted_batting_team"] = bat
        ss["bowling_team_select"] = bowl
        ss["persisted_bowling_team"] = bowl
        status["Teams"] = ["live", f"{bat} (batting) vs {bowl}"]
        ss["live_unmapped"] = False
    else:
        ss["live_unmapped"] = True
        missing = [n for n, got in ((bat_api, bat), (bowl_api, bowl)) if n and not got]
        if missing:
            warnings.append(
                "[map] These teams are not in this league's database: " + ", ".join(missing)
                + ". Select teams manually or skip this match (A-teams / Under-19 / unknown sides are never "
                  "mapped onto the senior team).")
        else:
            warnings.append("[map] The batting side of this match is not clear yet - select the teams manually.")
        status["Teams"] = ["missing", "teams could not be mapped - the sidebar is NOT the live match"]

    venue = setup.get("venue")
    if venue:
        g = match_ground_name(venue, grounds_list)
        if g:
            ss["ground_select"] = g
            ss["persisted_ground"] = g
            ss["ground_manual"] = ""
            ss["persisted_ground_manual"] = ""
            status["Ground"] = ["live", g]
        else:
            set_manual_value("ground", "persisted_ground", "persisted_ground_manual", venue)
            status["Ground"] = ["est", f"'{venue}' has no history in this league - typed manually, ground effects neutral"]
    else:
        status["Ground"] = ["missing", "API has no venue - pick the ground manually"]
    ss["live_status"] = status
    ss["live_warnings"] = warnings


def apply_live_xi_and_toss(batting_team, bowling_team, batting_roster, bowling_roster, gender):
    """AFTER the rosters are known, BEFORE the XI / toss widgets are drawn."""
    ss = st.session_state
    if not (ss.get("live_mode_on") and ss.get("live_xi_pending")):
        return
    ss["live_xi_pending"] = False
    if ss.get("live_unmapped"):
        return
    setup = ss.get("live_setup") or {}
    status = dict(ss.get("live_status") or {})
    msgs, got_any = [], False
    for api_team, names in (setup.get("players_by_team") or {}).items():
        if match_team_name(api_team, [batting_team], gender):
            roster, key, persist, label = batting_roster, "batting_xi_select", "persisted_batting_xi", batting_team
        elif match_team_name(api_team, [bowling_team], gender):
            roster, key, persist, label = bowling_roster, "bowling_xi_select", "persisted_bowling_xi", bowling_team
        else:
            continue
        good = []
        for nm in names:
            mapped = match_player_name(nm, roster)
            if mapped and mapped not in good:
                good.append(mapped)
        if good:
            ss[key] = good
            ss[persist] = good
            got_any = True
        if roster is bowling_roster:
            msgs.append(f"{label}: {len(good)} bowlers matched (of {len(names)} named - non-bowlers are skipped)")
        else:
            msgs.append(f"{label}: {len(good)}/{len(names)} names matched")
    if got_any:
        status["Playing XI"] = ["live", " | ".join(msgs)]
    else:
        status["Playing XI"] = ["missing", "API has no Playing XI for this match (or names did not match) - "
                                           "choose the XI manually"]
    tw = setup.get("toss_winner")
    if tw:
        mt = match_team_name(tw, [batting_team, bowling_team], gender)
        if mt:
            ss["toss_select"] = mt
            ss["persisted_toss"] = mt
            status["Toss"] = ["live", f"{mt} won the toss"]
        else:
            status["Toss"] = ["missing", f"toss winner '{tw}' not matched - choose it manually"]
    else:
        status["Toss"] = ["missing", "API has no toss info yet - choose it manually"]
    ss["live_status"] = status


def apply_live_players(batting_roster, bowling_roster):
    """BEFORE the Batsman 1/2 and Current Bowler widgets are drawn: put the
    scorecard's not-out batters and the bowler of the over into them."""
    ss = st.session_state
    if not (ss.get("live_mode_on") and ss.get("live_players_pending")):
        return
    ss["live_players_pending"] = False
    if ss.get("live_unmapped"):
        return
    setup = ss.get("live_setup") or {}
    status = dict(ss.get("live_status") or {})
    batters = list(setup.get("batters") or [])[:2]
    bat_options = ["Not Selected"] + list(batting_roster) + [MANUAL_OPTION_LABEL]

    def map_slot(slot, name):
        mapped = match_player_name(name, batting_roster)
        if mapped:
            set_select_value(f"batsman_{slot}_select", f"persisted_batsman_{slot}", mapped, bat_options)
            ss[f"batsman_{slot}_manual"] = ""
            ss[f"persisted_batsman_{slot}_manual"] = ""
            return mapped, True
        set_manual_value(f"batsman_{slot}", f"persisted_batsman_{slot}", f"persisted_batsman_{slot}_manual", name)
        return name, False

    if batters:
        shown, all_mapped = [], True
        live_cards = dict(ss.get("batter_live") or {})
        for slot, bt in zip(("a", "b"), batters):
            display, ok = map_slot(slot, bt["name"])
            all_mapped = all_mapped and ok
            shown.append(display)
            live_cards[display] = {"runs": bt["r"], "balls": bt["b"], "fours": bt["4s"], "sixes": bt["6s"]}
        ss["batter_live"] = live_cards
        status["Batters"] = ["live" if all_mapped else "est",
                             " & ".join(shown) + ("" if all_mapped else " (some names typed manually - no history for them)")]
        idx = 0
        hint = setup.get("striker_hint")
        if hint and hint.get("name") and len(batters) == 2:
            pos = [i for i, bt in enumerate(batters) if _normalize_name(bt["name"]) == _normalize_name(hint["name"])]
            if pos:
                idx = (1 - pos[0]) if hint.get("swap") else pos[0]
                status["Striker"] = ["live", f"{shown[idx]} on strike (from the last ball)"]
            else:
                status["Striker"] = ["est", "last-ball batter not among the two not-out batters - Batsman 1 assumed"]
        else:
            status["Striker"] = ["est", "API does not say who is on strike - Batsman 1 assumed; tap Swap Strike if wrong"]
        ss["on_strike_index"] = idx
        ss["dismissed_batsmen"] = [match_player_name(n, batting_roster) or n for n in (setup.get("dismissed") or [])]
    else:
        status["Batters"] = ["missing", "scorecard not available on this API plan - choose Batsman 1 / 2 manually"]
        status["Striker"] = ["missing", "not available - use Swap Strike manually"]

    bw = setup.get("bowler")
    bowl_options = ["Not Selected"] + list(bowling_roster) + [MANUAL_OPTION_LABEL]
    if bw and int(ss.get("balls", 0)) % 6 != 0:
        mapped = match_player_name(bw["name"], bowling_roster)
        if mapped:
            set_select_value("current_bowler_select", "persisted_current_bowler", mapped, bowl_options)
            ss["current_bowler_manual"] = ""
            ss["persisted_current_bowler_manual"] = ""
            display = mapped
        else:
            set_manual_value("current_bowler", "persisted_current_bowler", "persisted_current_bowler_manual", bw["name"])
            display = bw["name"]
        ss["bowler_live"] = {**(ss.get("bowler_live") or {}),
                             display: {"runs": bw["r"], "balls": bw["balls"], "wickets": bw["w"]}}
        status["Bowler"] = ["live" if mapped else "est", f"{display} (bowling now)"]
    elif bw:
        status["Bowler"] = ["missing", f"over just finished (last: {bw['name']}) - pick the next bowler manually"]
    else:
        status["Bowler"] = ["missing", "scorecard not available - choose Current Bowler manually"]
    ss["live_status"] = status


# ------------------------------------------------------------
# SIDEBAR - STAGE A: pick a live match (before the league's own
# team/ground lists are available)
# ------------------------------------------------------------

LIVE_STATUS_ORDER = ["Teams", "Ground", "Toss", "Playing XI", "Score", "Innings & target",
                     "Batters", "Striker", "Bowler", "Last 2 overs", "Last wicket", "Pitch"]
LIVE_STATUS_ICON = {"live": "✅", "est": "⚠️", "missing": "❌"}

st.sidebar.markdown("---")
live_mode_on = st.sidebar.checkbox(
    "🔴 LIVE MODE", value=bool(st.session_state.get("live_mode_on", False)), key="live_mode_checkbox",
)
st.session_state["live_mode_on"] = live_mode_on

if live_mode_on:
    with st.sidebar:
        st.caption(
            "Loads today's match facts (teams, ground, toss, Playing XI, batters, bowler, score, target) from a "
            "live provider. The prediction itself always comes from VasuDev's own historical engine, "
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
                st.session_state["api_caps"] = {}
                st.session_state["live_last_fetch_note"] = error or f"{len(matches)} match(es) found."
                st.rerun()

            note = st.session_state.get("live_last_fetch_note")
            if note:
                st.caption(note)

            live_matches = st.session_state.get("live_matches") or []
            if live_matches:
                def _match_label(m):
                    teams_ = m.get("teams") or []
                    vs = " vs ".join(teams_) if teams_ else m.get("name", "Match")
                    return f"{vs} ({m.get('status', '')})" if m.get("status") else vs

                labels = [_match_label(m) for m in live_matches]
                chosen_idx = st.selectbox(
                    "Select a live match", list(range(len(live_matches))),
                    format_func=lambda i: labels[i], key="live_match_select",
                )
                if st.button("📥 Load Selected Match", use_container_width=True, key="load_live_match_button"):
                    chosen = live_matches[chosen_idx]
                    # a new match: forget EVERYTHING of the old one first
                    reset_match_state(clear_selections=True)
                    st.session_state["live_selected_id"] = chosen.get("id")
                    st.session_state["api_caps"] = {}
                    live_load_match(chosen.get("id"))
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

    league = st.selectbox("League", LEAGUES, key="league_select",
                          **idx_kw("league_select", LEAGUES, "persisted_league"))
    st.session_state["persisted_league"] = league
    FULL_OVERS = LEAGUE_FORMAT_OVERS.get(league, 20)
    TOTAL_BALLS = FULL_OVERS * 6
    league_gender = LEAGUE_GENDER.get(league, "male")

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

    db_stat = database_path.stat()
    db_sig = f"{db_stat.st_size}-{int(db_stat.st_mtime)}"
    try:
        with st.spinner(f"Training the {league} engine (one-time, uses full history)..."):
            E = get_engine(league, db_sig)
    except Exception as error:
        st.error("Engine training failed.")
        st.exception(error)
        st.stop()

    try:
        _fr = data_freshness(connection, league, db_sig)
        st.caption(
            f"Data: {_fr['total']} matches • latest {_fr['last_date']} • last 30 days: {_fr['last30']}"
            + (f" • {_fr['extra']} from extra sources (latest {_fr['last_extra']})" if _fr["extra"] else "")
        )
    except Exception:
        pass

    warn = st.session_state.get("league_build_warnings", {}).get(league)
    if warn:
        st.warning(f"{len(warn)} extra archive(s) could not be downloaded for this league (main data is fine).")

    teams = get_current_teams(connection, league)
    if not teams:
        st.error("Database me team data nahi mila.")
        st.stop()

    grounds_list = get_grounds(connection, league)

    # --- Live Mode: write the live match's teams + ground into the widgets
    # (before they are drawn). Unmatched teams are reported, never silently
    # replaced by the old selection. ---
    apply_live_teams_and_ground(teams, grounds_list, league_gender)

    def _guard_select(widget_key, options):
        """A stored value that is no longer a valid option would break the
        widget - drop it so the widget falls back to its default."""
        cur = st.session_state.get(widget_key)
        if cur is not None and cur not in options:
            st.session_state.pop(widget_key, None)

    _guard_select("batting_team_select", teams)
    batting_team = st.selectbox("Batting Team", teams, key="batting_team_select",
                                **idx_kw("batting_team_select", teams, "persisted_batting_team"))
    st.session_state["persisted_batting_team"] = batting_team
    bowling_options = [t for t in teams if t != batting_team] or ["Unknown"]
    _guard_select("bowling_team_select", bowling_options)
    bowling_team = st.selectbox("Bowling Team", bowling_options, key="bowling_team_select",
                                **idx_kw("bowling_team_select", bowling_options, "persisted_bowling_team"))
    st.session_state["persisted_bowling_team"] = bowling_team

    _guard_select("ground_select", list(grounds_list) + [MANUAL_OPTION_LABEL])
    ground = select_with_manual_option("Ground / Venue", grounds_list,
                                       "persisted_ground", "persisted_ground_manual", "ground")
    if ground == "Not Selected":
        ground = ""

    innings_options = ["1st Innings", "2nd Innings"]
    _guard_select("innings_select", innings_options)
    innings_label = st.selectbox("Innings", innings_options, key="innings_select",
                                 **idx_kw("innings_select", innings_options, "persisted_innings_label"))
    st.session_state["persisted_innings_label"] = innings_label
    innings_no = 1 if innings_label == "1st Innings" else 2

    if innings_no == 2:
        if (st.session_state.get("_sync_target") != st.session_state.state_version
                or "target_runs_widget" not in st.session_state):
            st.session_state["target_runs_widget"] = int(min(600, max(0, int(st.session_state.target))))
            st.session_state["_sync_target"] = st.session_state.state_version
        target = st.number_input("Target Runs", min_value=0, max_value=600, step=1, key="target_runs_widget")
        st.session_state.target = int(target)
    else:
        target = 0
        st.session_state.target = 0

    # rosters are needed by the live fill of XI / players, so build them here
    batting_roster = get_team_roster(connection, league, batting_team, "batting")
    bowling_roster_full = get_team_roster(connection, league, bowling_team, "bowling")
    apply_live_xi_and_toss(batting_team, bowling_team, batting_roster, bowling_roster_full, league_gender)
    apply_live_players(batting_roster, bowling_roster_full)

    st.markdown("---")
    st.subheader("Conditions")
    pitch_options = list(PITCH_CONDITIONS.keys())
    _guard_select("pitch_condition_select", pitch_options)
    pitch_choice = st.selectbox("Pitch", pitch_options, key="pitch_condition_select",
                                **idx_kw("pitch_condition_select", pitch_options, "persisted_pitch_condition"))
    st.session_state["persisted_pitch_condition"] = pitch_choice
    if pitch_choice == PITCH_AUTO_LABEL:
        pitch_mult, _pitch_note = auto_pitch(E, ground, innings_no, target)
        st.caption(f"Auto pitch factor x{pitch_mult:.3f}: {_pitch_note}")
    else:
        pitch_mult = PITCH_CONDITIONS[pitch_choice]
    dew_options = list(DEW_OPTIONS.keys())
    _guard_select("dew_select", dew_options)
    dew_choice = st.selectbox("Dew", dew_options, key="dew_select",
                              **idx_kw("dew_select", dew_options, "persisted_dew"))
    st.session_state["persisted_dew"] = dew_choice
    toss_options = ["Not known", batting_team, bowling_team]
    _guard_select("toss_select", toss_options)
    toss_choice = st.selectbox("Toss won by", toss_options, key="toss_select",
                               **idx_kw("toss_select", toss_options, "persisted_toss"))
    st.session_state["persisted_toss"] = toss_choice
    toss_rel = 1.0 if toss_choice == batting_team else (-1.0 if toss_choice == bowling_team else 0.0)

    st.markdown("---")
    st.subheader("Players (optional)")
    st.caption("Set once. Strike rotates automatically; a wicket asks for the next batter.")
    batsman_options = ["Not Selected"] + batting_roster
    _guard_select("batsman_a_select", batsman_options + [MANUAL_OPTION_LABEL])
    batsman_a = select_with_manual_option("Batsman 1", batsman_options, "persisted_batsman_a",
                                          "persisted_batsman_a_manual", "batsman_a")
    _guard_select("batsman_b_select", batsman_options + [MANUAL_OPTION_LABEL])
    batsman_b = select_with_manual_option("Batsman 2", batsman_options, "persisted_batsman_b",
                                          "persisted_batsman_b_manual", "batsman_b")
    strike_idx = int(st.session_state.get("on_strike_index", 0))
    on_strike_name = batsman_a if strike_idx == 0 else batsman_b
    st.caption(f"On strike: **{on_strike_name if on_strike_name != 'Not Selected' else '-'}**")
    if st.button("Swap Strike", use_container_width=True, key="swap_strike_button"):
        st.session_state.on_strike_index = 1 - strike_idx
        st.rerun()
    bowler_options = ["Not Selected"] + bowling_roster_full
    _guard_select("current_bowler_select", bowler_options + [MANUAL_OPTION_LABEL])
    bowler_choice = select_with_manual_option("Current Bowler", bowler_options, "persisted_current_bowler",
                                              "persisted_current_bowler_manual", "current_bowler")

    st.markdown("---")
    st.subheader("Playing XI (optional)")
    st.caption(
        "If today's actual XI differs from the team's recent average (injuries, "
        "rotation, a strong/weak XI), naming them here shifts the "
        "prediction toward THIS XI's real record instead of the team's "
        "average. Leave empty to just use the team average."
    )
    for _xi_key, _roster in (("batting_xi_select", batting_roster), ("bowling_xi_select", bowling_roster_full)):
        if _xi_key in st.session_state:
            st.session_state[_xi_key] = [n for n in (st.session_state[_xi_key] or []) if n in _roster]
    batting_xi = st.multiselect(
        f"{batting_team} Playing XI (batters)", batting_roster, key="batting_xi_select",
        **({} if "batting_xi_select" in st.session_state else
           {"default": [n for n in st.session_state.get("persisted_batting_xi", []) if n in batting_roster]}),
    )
    st.session_state["persisted_batting_xi"] = batting_xi
    bowling_xi = st.multiselect(
        f"{bowling_team} Playing XI (bowlers)", bowling_roster_full, key="bowling_xi_select",
        **({} if "bowling_xi_select" in st.session_state else
           {"default": [n for n in st.session_state.get("persisted_bowling_xi", []) if n in bowling_roster_full]}),
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
                live_fetch_and_sync(st.session_state["live_selected_id"])
                st.rerun()

            _ts = st.session_state.get("live_last_sync_ts")
            if _ts:
                st.caption(f"Last synced {int(max(0, time.time() - float(_ts)))} sec ago "
                           f"(refreshes on every tap; press FETCH for new data)")
            live_note = st.session_state.get("live_last_fetch_note")
            if live_note:
                st.caption(live_note)
            _status = st.session_state.get("live_status") or {}
            if _status:
                with st.expander("Live data status (what the API gave / what to fill manually)", expanded=True):
                    for _item in LIVE_STATUS_ORDER:
                        if _item in _status:
                            level, text = _status[_item][0], _status[_item][1]
                            st.caption(f"{LIVE_STATUS_ICON.get(level, '•')} **{_item}**: {text}")
            with st.expander("Raw live JSON (for checking field names)", expanded=False):
                st.write("match_info")
                st.write(st.session_state.get("live_match_raw") or {})
                st.write("match_scorecard")
                st.write(st.session_state.get("live_scorecard_raw") or {})
                st.write("match_bbb")
                st.write(st.session_state.get("live_bbb_raw") or {})

    st.markdown("---")
    st.subheader("Start / Reset")
    over_points = ["0.0"] + [f"{o}.{k}" for o in range(FULL_OVERS) for k in range(1, 7)] + [f"{FULL_OVERS}.0"]
    # These widgets ALWAYS mirror the live scoreboard: whenever the score
    # changed since they were last drawn (ball button, live sync, catch-up...)
    # they are re-filled from it - header and sidebar can never disagree.
    if (st.session_state.get("_sync_start") != st.session_state.state_version
            or "start_over_select" not in st.session_state):
        _b = int(st.session_state.balls)
        _lab = "0.0" if _b <= 0 else f"{(_b - 1) // 6}.{(_b - 1) % 6 + 1}"
        st.session_state["start_over_select"] = _lab if _lab in over_points else "0.0"
        st.session_state["start_runs_widget"] = int(min(600, max(0, int(st.session_state.runs))))
        st.session_state["start_wickets_widget"] = int(min(10, max(0, int(st.session_state.wickets))))
        _rb = list(st.session_state.recent_balls)[-12:]
        st.session_state["start_last12_widget"] = int(min(80, round(sum(_rb)))) if len(_rb) >= 12 else -1
        st.session_state["start_bsw_widget"] = int(min(99, max(0, int(st.session_state.bsw))))
        st.session_state["_sync_start"] = st.session_state.state_version
    start_over = st.selectbox("Over / Ball now", over_points, key="start_over_select")
    start_runs = st.number_input("Runs now", 0, 600, step=1, key="start_runs_widget")
    start_wickets = st.number_input("Wickets now", 0, 10, step=1, key="start_wickets_widget")
    start_last12 = st.number_input(
        "Runs in last 2 overs (optional)", -1, 80, step=1, key="start_last12_widget",
        help="Auto-filled from the live feed / ball buttons once 12 balls are known. -1 = unknown "
             "(that signal is simply skipped).",
    )
    start_bsw = st.number_input(
        "Balls since last wicket (optional)", 0, 99, step=1, key="start_bsw_widget",
        help="Auto-filled when known. 99 = no recent wicket / unknown.",
    )

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
            bump_state_version()
            st.rerun()

    if st.button("Reset (new innings)", use_container_width=True, key="reset_live_button"):
        reset_match_state(clear_selections=False)
        st.rerun()

    st.caption(
        "Retrain below throws away the saved model for this league and rebuilds it from the "
        "database again. You will not normally need this - only if you suspect something is "
        "stale after a database rebuild."
    )
    if st.button("Retrain engine from scratch", use_container_width=True, key="retrain_button"):
        try:
            engine_path_for(league).unlink()
        except Exception:
            pass
        get_engine.clear()
        st.rerun()
    st.caption("Refresh downloads the latest matches (e.g. the newest WBBL games) and rebuilds the database "
               "and engine for this league (takes a few minutes). It also happens by itself when the app "
               f"starts fresh and the data is more than {REBUILD_AFTER_DAYS} days old.")
    if st.button("Refresh match data now", use_container_width=True, key="refresh_data_button"):
        for _path in (DATABASES[league], engine_path_for(league)):
            try:
                _path.unlink()
            except Exception:
                pass
        ready.pop(league, None)
        try:
            get_connection.clear()
            get_engine.clear()
            st.cache_data.clear()
        except Exception:
            pass
        st.rerun()


# ============================================================
# CURRENT STATE
# ============================================================

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


# ============================================================
# TOP SCORE (the only place the live score is shown) - scoreboard-style
# header: score bar, CRR/RRR/target row, ball-by-over dots, current
# batsmen and bowler figures.
# ============================================================

_crr = (runs / (balls / 6.0)) if balls > 0 else 0.0
_rrr = None
_need_line = ""
if innings_no == 2 and target > 0:
    _remaining_balls = max(0, TOTAL_BALLS - balls)
    _remaining_runs = max(0, target - runs)
    if runs >= target:
        _need_line = '<p style="margin:6px 0 0;color:#8fe3a0">Target achieved</p>'
    elif _remaining_balls > 0 and wickets < 10:
        _rrr = _remaining_runs * 6.0 / _remaining_balls
        _need_line = f'<p style="margin:6px 0 0;color:#ffd166">Need {_remaining_runs} runs in {_remaining_balls} balls</p>'
    elif wickets >= 10:
        _need_line = '<p style="margin:6px 0 0;color:#ffd166">All out</p>'

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

# --- Live Mode banners: never let a wrong/unmapped match pass silently ---
if st.session_state.get("live_mode_on"):
    _ts_main = st.session_state.get("live_last_sync_ts")
    if st.session_state.get("live_selected_id") and _ts_main:
        st.caption(f"🔴 Live • last synced {int(max(0, time.time() - float(_ts_main)))} sec ago "
                   f"(tap FETCH LIVE UPDATE in the sidebar for fresh data)")
    if st.session_state.get("live_unmapped"):
        st.error("The live match's teams are NOT in this league's database - the sidebar shows your own "
                 "selection, not the live match. Select teams manually or skip this match.")
    for _w in (st.session_state.get("live_warnings") or []):
        st.warning(str(_w).replace("[sync] ", "").replace("[map] ", ""))

# --- Ball-by-over dots (recent overs + the one in progress) ---
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

# --- Partnership + current batsmen + bowler ---
_slot_a_name = batsman_a if batsman_a != "Not Selected" else "Batsman 1"
_slot_b_name = batsman_b if batsman_b != "Not Selected" else "Batsman 2"
_bat_rows = ""
for _nm in (_slot_a_name, _slot_b_name):
    _st_ = st.session_state.get("batter_live", {}).get(_nm)
    if _st_:
        _sr = (_st_["runs"] / _st_["balls"] * 100) if _st_["balls"] else 0.0
        _mark = " *" if _nm == (batsman_a if strike_idx == 0 else batsman_b) else ""
        _bat_rows += (
            f"<tr><td>{_nm}{_mark}</td><td>{_st_['runs']}</td><td>{_st_['balls']}</td>"
            f"<td>{_st_['fours']}</td><td>{_st_['sixes']}</td><td>{_sr:.1f}</td></tr>"
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


# ============================================================
# BALL CONTROLS
# ============================================================

SNAPSHOT_KEYS = ("runs", "wickets", "balls", "recent_balls", "pending_extras", "bsw",
                 "on_strike_index", "dismissed_batsmen", "awaiting_new_batsman", "out_slot_index",
                 "batter_live", "bowler_live", "partnership_runs", "this_over", "over_history")


def push_undo_snapshot():
    ss = st.session_state
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


def apply_ball(label, add_runs, add_wicket, legal_ball):
    ss = st.session_state
    if label != "Undo" and (ss.wickets >= 10 or ss.balls >= TOTAL_BALLS):
        ss.last = "Innings already complete - use Reset for a new innings"
        return
    if label == "Undo":
        if ss.undo_stack:
            old = ss.undo_stack.pop()
            for k in SNAPSHOT_KEYS:
                ss[k] = old[k]
            ss.last = "Undo"
            bump_state_version()
        return
    push_undo_snapshot()
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
    bump_state_version()


def quick_catch_up(add_runs, add_balls, add_wickets):
    """Live feed is behind? Add what you missed in one go: '+runs in +balls'
    (+ wickets). The missed balls are covered by their average rate (they
    are not invented deliveries); strike is left as it is - use Swap Strike
    if needed."""
    ss = st.session_state
    add_runs, add_balls, add_wickets = int(add_runs), int(add_balls), int(add_wickets)
    if add_runs == 0 and add_balls == 0 and add_wickets == 0:
        return
    if ss.wickets >= 10 or ss.balls >= TOTAL_BALLS:
        ss.last = "Innings already complete - use Reset for a new innings"
        return
    push_undo_snapshot()
    add_balls = min(add_balls, TOTAL_BALLS - ss.balls)
    ss.runs += add_runs
    ss.balls += add_balls
    ss.wickets = min(10, ss.wickets + add_wickets)
    ss.partnership_runs = 0 if add_wickets else ss.partnership_runs + add_runs
    if add_balls > 0:
        rate = add_runs / add_balls
        ss.recent_balls = (list(ss.recent_balls) + [rate] * min(add_balls, 18))[-18:]
    if add_wickets:
        ss.bsw = max(0, add_balls // 2)
    elif ss.bsw < 99:
        ss.bsw = min(99, ss.bsw + add_balls)
    ss.last = f"Catch-up +{add_runs} in {add_balls} balls"
    bump_state_version()


st.subheader("Ball-by-Ball Update")
actions = [
    ("Dot", 0, 0, True), ("1", 1, 0, True), ("2", 2, 0, True), ("3", 3, 0, True),
    ("4", 4, 0, True), ("6", 6, 0, True), ("Wicket", 0, 1, True),
    ("Wide", 1, 0, False), ("No Ball", 1, 0, False), ("Undo", 0, 0, False),
]
action_columns = st.columns(len(actions), gap="small")
for _i, (_label, _r, _w, _legal) in enumerate(actions):
    with action_columns[_i]:
        if st.button(_label, use_container_width=True, key=f"live_action_button_{_i}"):
            apply_ball(_label, _r, _w, _legal)
            st.rerun()

with st.expander("⚡ Quick Catch-Up (live feed behind? add what you missed)", expanded=False):
    cu1, cu2, cu3 = st.columns(3, gap="small")
    cu_runs = cu1.number_input("+ Runs", 0, 120, step=1, key="catchup_runs")
    cu_balls = cu2.number_input("+ Balls", 0, 60, step=1, key="catchup_balls")
    cu_wkts = cu3.number_input("+ Wkts", 0, 10, step=1, key="catchup_wkts")
    if st.button("Apply catch-up", use_container_width=True, key="catchup_apply_button"):
        quick_catch_up(cu_runs, cu_balls, cu_wkts)
        for _ck in ("catchup_runs", "catchup_balls", "catchup_wkts"):
            queue_widget_value(_ck, 0)
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
        _slot = "a" if out_slot == 0 else "b"
        st.session_state[f"persisted_batsman_{_slot}"] = incoming
        st.session_state[f"persisted_batsman_{_slot}_manual"] = ""
        queue_widget_value(f"batsman_{_slot}_select", incoming)
        queue_widget_value(f"batsman_{_slot}_manual", "")
        st.session_state.awaiting_new_batsman = False
        st.session_state.out_slot_index = None
        st.rerun()


# ============================================================
# PROJECTION INPUTS (the only two things typed during the match)
# ============================================================

def smart_projection_over(balls_now, full_overs, pp_end, death_over):
    """Default 'Projection End Over': the end of the phase we are in
    (Powerplay -> middle -> death -> end of innings)."""
    for boundary in (pp_end, death_over, full_overs):
        if boundary * 6 > balls_now:
            return int(min(boundary, full_overs))
    return int(full_overs)


def _projection_changed():
    st.session_state.projection_end_over = int(st.session_state.projection_end_over_widget)
    st.session_state.projection_user_set = True


st.subheader("Projection")
_smart_over = smart_projection_over(balls, FULL_OVERS, E["pp_end"], E["death_over"])
_cur_over = int(st.session_state.projection_end_over)
_stale = (_cur_over * 6 <= balls) and balls < TOTAL_BALLS
if _stale and st.session_state.get("projection_user_set"):
    st.info(f"Projection End Over {_cur_over} is already over - reset to over {_smart_over}.")
if (not st.session_state.get("projection_user_set")) or _stale or _cur_over < 1 or _cur_over > FULL_OVERS:
    st.session_state.projection_end_over = _smart_over
    st.session_state.projection_user_set = False
    st.session_state["projection_end_over_widget"] = _smart_over
elif st.session_state.get("projection_end_over_widget") != _cur_over:
    st.session_state["projection_end_over_widget"] = _cur_over

c1, c2 = st.columns(2, gap="small")
with c1:
    proj_over = st.number_input("Projection End Over", min_value=1, max_value=FULL_OVERS, step=1,
                                key="projection_end_over_widget", on_change=_projection_changed)
    if not st.session_state.get("projection_user_set"):
        st.caption("Auto = end of the current phase. Type another over to override.")
st.session_state.projection_end_over = int(proj_over)

player_info = build_player_info(connection, E, league, striker_name, non_striker_name, bowler_name, balls)

squad_info = None
if batting_xi or bowling_xi:
    b_nd, b_d, b_conf = squad_batting_strength(
        connection, league, tuple(batting_xi), E["pp_end"], E["death_over"], tuple(E["lg_bat_ball"]),
        E["latest_ord"], E["team_hl_days"])
    w_nd, w_d, w_conf = squad_bowling_strength(
        connection, league, tuple(bowling_xi), E["pp_end"], E["death_over"], tuple(E["lg_bowl_ball"]),
        E["latest_ord"], E["team_hl_days"])
    squad_info = {
        "bat_nd": b_nd, "bat_d": b_d, "bat_conf": b_conf, "bat_n": len(batting_xi),
        "bowl_nd": w_nd, "bowl_d": w_d, "bowl_conf": w_conf, "bowl_n": len(bowling_xi),
    }

state = {
    "innings": innings_no, "b": balls, "r": runs, "w": wickets,
    "last_r": last_r, "last_n": last_n, "bsw": int(st.session_state.bsw),
    "window_over": int(proj_over), "line": 0,
    "batting_team": batting_team, "bowling_team": bowling_team, "ground": ground,
    "target": int(target), "pitch_mult": pitch_mult,
    "dew_level": DEW_OPTIONS[dew_choice], "player": player_info, "squad": squad_info,
    "toss": toss_rel, "mc": False,
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
state["mc"] = True
result = predict(E, state)


# ============================================================
# RESULT BOX 1 - SCORE
# ============================================================

p_reach = result["p_reach"] * 100
box_class = "positive" if p_reach >= 50 else "negative"
over_label = int(proj_over)
ahead = runs - result["par_now"]
st.html(
    f"""
    <div class="{box_class}">
        <h1 style="margin:0">Expected {result['window_expected']:.0f} by over {over_label}</h1>
        <p style="margin:6px 0 0">Likely range: <b>{result['window_p10']:.0f} - {result['window_p90']:.0f}</b></p>
        <p style="margin:8px 0 0;font-size:20px">
            {int(line)} or more: <b>{p_reach:.0f}%</b> &nbsp;•&nbsp;
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
st.caption(
    f"'Likely range' is the middle 50% of outcomes (25th-75th percentile) - tighter and more "
    f"decisive than the full spread. The wider 10-90 range "
    f"({result['window_p05']:.0f}-{result['window_p95']:.0f}) is in 'More Insights & Details' below "
    f"for anyone who wants the fuller picture - cricket genuinely has this much ball-to-ball variance; "
    f"showing a fake single number would just hide it, not remove it."
)


# ============================================================
# RESULT BOX 2 - WIN
# ============================================================

wp = result["win_prob"]
if wp is not None:
    bat_win = wp * 100
    bowl_win = 100 - bat_win
    if bat_win >= bowl_win:
        w_name, w_pct, w_class = batting_team, bat_win, "positive"
    else:
        w_name, w_pct, w_class = bowling_team, bowl_win, "negative"
    basis = ("Based on projected final score vs ground par, team rating, venue head-to-head, toss"
             if innings_no == 1 else
             f"Target {int(target)} • needs {result.get('needed', 0):.0f} more • regression + Monte-Carlo simulation")
    st.html(
        f"""
        <div class="{w_class}">
            <h1 style="margin:0">{w_name.upper()} WIN - {w_pct:.0f}%</h1>
            <p style="margin:8px 0 0">
                {batting_team}: <b>{bat_win:.1f}%</b> &nbsp;•&nbsp; {bowling_team}: <b>{bowl_win:.1f}%</b>
            </p>
            <p class="small" style="margin:5px 0 0">{basis}</p>
        </div>
        """
    )
else:
    st.info("2nd innings win % ke liye sidebar me Target Runs set karein.")


# ============================================================
# CONFIDENCE (how much real history backs THIS situation)
# ============================================================

_conf = confidence_info(E, batting_team, bowling_team, ground, result["h2h"], result["h2h_venue"], squad_info)
st.html(
    f"""
    <div class="card">
        <b>Confidence: {_conf['label']}</b> <span class="small">({_conf['score'] * 100:.0f}% historical backing)</span>
        <p class="small" style="margin:5px 0 0">{' • '.join(_conf['lines'])}</p>
    </div>
    """
)


# ============================================================
# DETAILS
# ============================================================

with st.expander("More Insights & Details", expanded=False):
    st.caption(
        f"Fuller 10-90 range by over {over_label}: "
        f"{result['window_p05']:.0f} - {result['window_p95']:.0f} runs. "
        f"Full innings 10-90 range: {result['final_p05']:.0f} - {result['final_p95']:.0f} runs."
    )
    if result.get("mc"):
        _m = result["mc"]
        st.caption(
            f"Monte-Carlo ({_m['n']} simulated finishes): mean {_m['mean']:.0f}, 10-90 range "
            f"{_m['p10']:.0f}-{_m['p90']:.0f}. The regression sets the mean; the simulation reshapes the spread."
        )
    if result.get("mc_p_win") is not None:
        st.caption(
            f"Chase win %: regression model {result['win_logistic'] * 100:.1f}% • Monte-Carlo "
            f"{result['mc_p_win'] * 100:.1f}% • shown = {int((1 - MC_BLEND) * 100)}/{int(MC_BLEND * 100)} blend."
        )
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
    v_wa, v_wb = result["h2h_venue"]
    if wa + wb:
        st.caption(
            f"Head-to-head (this league): {batting_team} {wa} - {wb} {bowling_team}"
            + (f" • at this ground: {v_wa} - {v_wb}" if (v_wa + v_wb) else " • no meeting at this ground")
            + f" • blended value used: {result['h2h_blend']:+.2f}")
    if toss_rel:
        st.caption(f"Toss: {toss_choice} won it (small learned factor).")
    gstats = E["ground"].get(ground or "", None)
    if gstats:
        st.caption(
            f"Ground record ({ground}, {gstats.get('n', 0)} matches): typical 1st innings "
            f"{gstats.get('G1', E['league_first_mean']):.0f}, death-overs scoring "
            f"{gstats.get('g_d', 0):+.2f} rpo vs league, boundary rate {gstats.get('g_bnd', 0):+.1f} pts, "
            f"bat-first win-rate {gstats.get('gbias', 0) * 100:+.0f} pts vs league. "
            f"Recent matches count more (half-life {E.get('hl_days', 0) / 365.25:.1f} years, by match date).")
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
                        f"(rest comes from the team's recent average)")
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
                stt = player_batting_phase(connection, league, nm, E["pp_end"], E["death_over"],
                                           E["latest_ord"], E["team_hl_days"])
                r_, b_ = stt["raw"][ph]
                sr = f"{r_ / b_ * 100:.0f}" if b_ else "-"
                st.caption(f"{nm}: {phase_name} SR {sr} ({b_} balls in this league)")
        if bowler_name:
            stt = player_bowling_phase(connection, league, bowler_name, E["pp_end"], E["death_over"],
                                       E["latest_ord"], E["team_hl_days"])
            r_, b_ = stt["raw"][ph]
            eco = f"{r_ / b_ * 6:.2f}" if b_ else "-"
            st.caption(f"{bowler_name}: {phase_name} economy {eco} ({b_} balls in this league)")

    st.write("#### Engine report (measured on real history, out-of-sample)")
    mt = E["metrics"]
    _dates = mt.get("dates")
    st.caption(
        f"{league}: trained on {mt['n_matches']} full-length matches, seasons "
        f"{mt['seasons'][0]}-{mt['seasons'][1]}"
        + (f", match dates {_dates[0]} to {_dates[1]}" if _dates else "")
        + f" (cross-fitted by match, so these numbers are honest). Trained in {E.get('train_seconds', 0)}s.")
    for _k in ("1", "2"):
        _g = mt.get(f"gb_inn{_k}")
        if _g:
            st.caption(
                f"Gradient boosting, innings {_k}: {'ON' if _g['used'] else 'off'} - squared error "
                f"{_g['mse_ridge']} (regression) vs {_g['mse_gb']} (with boosting), gain {_g['gain_pct']}%. "
                f"It is switched on only when it wins out-of-sample.")
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
