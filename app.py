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

    .session-box {
        background: #0f223c;
        border: 1px solid #2d4d72;
        border-radius: 14px;
        padding: 16px;
        min-height: 200px;
    }

    .winning-box {
        background: #0f223c;
        border: 1px solid #2d4d72;
        border-radius: 14px;
        padding: 16px;
        min-height: 200px;
    }

    .yes {
        background: #0d5b34;
        border: 2px solid #20c77a;
        border-radius: 12px;
        padding: 12px;
    }

    .no {
        background: #5d1d1d;
        border: 2px solid #ef5350;
        border-radius: 12px;
        padding: 12px;
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

    return f"{(balls - 1) // 6}.{((balls - 1) % 6) + 1}"


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

    connection = sqlite3.connect(str(path), timeout=60)

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

        columns = table_columns(connection, "deliveries")

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
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-8000")

    return connection


# ============================================================
# DATABASE BUILDER
# ============================================================

def build_database(path, league, archive):
    temporary = path.with_suffix(".tmp")

    if temporary.exists():
        temporary.unlink()

    connection = sqlite3.connect(str(temporary))

    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")

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
                    data = json.loads(raw.decode("utf-8"))

                    info = data.get("info", {})
                    teams = info.get("teams", [])

                    if len(teams) < 2:
                        continue

                    outcome = info.get("outcome", {}) or {}
                    winner = str(
                        outcome.get("winner", "")
                        or outcome.get("eliminator", "")
                        or ""
                    )

                    match_id = Path(filename).stem

                    matches_buffer.append(
                        (
                            match_id,
                            str(info.get("venue", "") or ""),
                            winner,
                            league,
                        )
                    )

                    for innings_no, innings in enumerate(data.get("innings", []), 1):
                        if innings.get("super_over"):
                            continue

                        batting = innings.get("team", "")
                        bowling = next(
                            (team for team in teams if team != batting),
                            "",
                        )

                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))

                            for delivery_index,*

