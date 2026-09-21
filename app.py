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
# VasuDev Cricket Live AI - memory-safe version
# ============================================================

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide",
    initial_sidebar_state="expanded",
)

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()
if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()


# No custom header HTML is used in this file.
st.markdown(
    """
    <style>
    .stApp{background:linear-gradient(180deg,#061426 0%,#081c35 100%);color:#f8fafc}
    .block-container{max-width:1500px;padding-top:1.2rem!important}
    .card,.session-box{background:#0f223c;padding:16px;border-radius:16px;border:1px solid #2d4d72}
    .session-box{text-align:center;border:2px solid #4777a8;margin:14px 0}
    .yes{background:#07552f;border:2px solid #20c77a;padding:18px;border-radius:16px;text-align:center}
    .no{background:#651b1b;border:2px solid #ef5350;padding:18px;border-radius:16px;text-align:center}
    .small{color:#bed0e5!important;font-size:13px}
    h1,h2,h3,h4,p,label{color:#f8fafc!important}
    [data-testid="stSidebar"]{background:#071a2e}
    [data-testid="stStatusWidget"],[data-testid="stDecoration"]{display:none!important}
    div.stButton>button{min-height:40px;border-radius:10px;font-weight:700;background:#12365f;color:#fff;border:1px solid #3c6795}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# AUTH - never reset this state during widget reruns
# ============================================================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("VasuDev Cricket AI")
    st.caption("Private access")
    password = st.text_input("Password", type="password", key="auth_password")
    if st.button("Unlock", use_container_width=True, key="unlock_button"):
        if hmac.compare_digest(password, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("auth_password", None)
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


# ============================================================
# DATABASE CONFIG
# ============================================================

BASE = Path(".")
DB_PATHS = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db",
}
DOWNLOAD_URLS = {
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
}
LEAGUES = list(DB_PATHS)


def connect_readonly(path):
    """Open a small read-only connection; never cache a large DataFrame."""
    resolved = Path(path).resolve()
    if not resolved.exists():
        return None
    connection = sqlite3.connect(
        f"file:{resolved}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-8000")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


def parse_ball(value):
    try:
        over, ball = str(value).split(".", 1)
        over = int(over)
        ball = int(ball)
        if over < 0 or ball <= 0:
            raise ValueError
        return over * 6 + ball
    except Exception:
        return None


def build_database(path, league, archive_path):
    """Build SQLite in batches. No complete ZIP is held in memory."""
    temporary = path.with_suffix(".tmp")
    if temporary.exists():
        temporary.unlink()

    connection = sqlite3.connect(str(temporary))
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute(
            "CREATE TABLE matches(match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT)"
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

        match_batch = []
        delivery_batch = []

        def flush_matches():
            if match_batch:
                connection.executemany(
                    "INSERT OR REPLACE INTO matches VALUES (?,?,?,?)",
                    match_batch,
                )
                match_batch.clear()

        def flush_deliveries():
            if delivery_batch:
                connection.executemany(
                    """
                    INSERT INTO deliveries(
                        match_id, innings_no, batting_team, bowling_team,
                        over_no, ball_no, ball_pos, runs, wickets, league
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    delivery_batch,
                )
                delivery_batch.clear()

        with zipfile.ZipFile(archive_path) as archive:
            for filename in archive.namelist():
                if not filename.endswith(".json"):
                    continue
                try:
                    data = json.loads(archive.read(filename))
                    info = data.get("info", {})
                    teams = info.get("teams", [])
                    if len(teams) < 2:
                        continue

                    outcome = info.get("outcome", {}) or {}
                    winner = outcome.get("winner", "") or outcome.get("eliminator", "") or ""
                    match_id = Path(filename).stem
                    match_batch.append((match_id, str(info.get("venue", "") or ""), str(winner), league))

                    for innings_no, innings in enumerate(data.get("innings", []), start=1):
                        if innings.get("super_over"):
                            continue
                        batting_team = innings.get("team", "")
                        bowling_team = next((team for team in teams if team != batting_team), "")

                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))
                            for delivery in over.get("deliveries", []):
                                ball_no = delivery.get("actual_delivery")
                                if not ball_no:
                                    try:
                                        ball_no = f"{over_no}.{int(delivery.get('ball'))}"
                                    except Exception:
                                        continue
                                ball_pos = parse_ball(ball_no)
                                if ball_pos is None:
                                    continue
                                runs = int((delivery.get("runs") or {}).get("total", 0) or 0)
                                wickets = len(delivery.get("wickets") or [])
                                delivery_batch.append(
                                    (
                                        match_id, innings_no, batting_team, bowling_team,
                                        over_no, str(ball_no), ball_pos, runs, wickets, league,
                                    )
                                )

                    if len(match_batch) >= 100:
                        flush_matches()
                    if len(delivery_batch) >= 5000:
                        flush_deliveries()
                except Exception:
                    continue

        flush_matches()
        flush_deliveries()
        connection.execute("CREATE INDEX idx_deliveries_state ON deliveries(league,innings_no,ball_pos)")
        connection.execute("CREATE INDEX idx_deliveries_match ON deliveries(match_id,innings_no,ball_pos)")
        connection.execute("CREATE INDEX idx_matches_league ON matches(league)")
        connection.commit()
    finally:
        connection.close()

    temporary.replace(path)


def ensure_database(league):
    path = DB_PATHS[league]
    if path.exists():
        return path
    if league == "IPL":
        return path

    building = path.with_suffix(".building")
    try:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "matches.zip"
            urllib.request.urlretrieve(DOWNLOAD_URLS[league], archive)
            build_database(building, league, archive)
        building.replace(path)
        return path
    except Exception:
        if building.exists():
            building.unlink()
        raise


def table_count(connection, table):
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return 0


def distinct_values(connection, sql, league):
    return [row[0] for row in connection.execute(sql, (league,)).fetchall() if row[0]]


def load_match_state(connection, league, innings_no, current_ball, current_runs, current_wickets, session_end):
    """Return only a small candidate list instead of loading all historical deliveries."""
    query = """
        SELECT
            d.match_id,
            d.innings_no,
            d.batting_team,
            d.bowling_team,
            d.ball_pos,
            d.runs,
            d.wickets,
            m.venue,
            m.winner
        FROM deliveries d
        JOIN matches m ON m.match_id=d.match_id
        WHERE d.league=?
          AND d.innings_no=?
          AND d.ball_pos BETWEEN ? AND ?
          AND d.ball_pos <= ?
          AND d.runs BETWEEN 0 AND 20
        LIMIT 3000
    """
    rows = connection.execute(
        query,
        (
            league,
            innings_no,
            max(1, current_ball - 2),
            current_ball + 2,
            session_end,
        ),
    ).fetchall()

    candidates = []
    for row in rows:
        # Query uses scalar values; no Pandas boolean ambiguity is possible.
        score_row = connection.execute(
            """
            SELECT COALESCE(SUM(runs),0), COALESCE(SUM(wickets),0)
            FROM deliveries
            WHERE match_id=? AND innings_no=? AND ball_pos<=?
            """,
            (row["match_id"], row["innings_no"], row["ball_pos"]),
        ).fetchone()
        score = int(score_row[0])
        wickets = int(score_row[1])
        if abs(score - current_runs) > 30 or abs(wickets - current_wickets) > 3:
            continue
        weight = (
            1.0 / (1.0 + abs(score - current_runs))
            * 1.0 / (1.0 + abs(wickets - current_wickets))
            * 1.0 / (1.0 + abs(row["ball_pos"] - current_ball))
        )
        candidates.append((row["match_id"], int(row["innings_no"]), weight))

    candidates.sort(key=lambda item: item[2], reverse=True)
    return candidates[:1000]


def final_score(connection, match_id, innings_no, session_end):
    row = connection.execute(
        """
        SELECT COALESCE(SUM(runs),0)
        FROM deliveries
        WHERE match_id=? AND innings_no=? AND ball_pos<=?
        """,
        (match_id, innings_no, session_end),
    ).fetchone()
    return int(row[0] or 0)


def calculate_line(connection, league, innings_no, current_ball, current_runs, current_wickets, session_over):
    session_end = int(session_over) * 6
    if current_ball >= session_end:
        return current_runs, current_runs + 1, float(current_runs), 0

    candidates = load_match_state(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        session_end,
    )
    if not candidates:
        return current_runs, current_runs + 1, float(current_runs), 0

    scores = []
    weights = []
    for match_id, historical_innings, weight in candidates:
        score = final_score(connection, match_id, historical_innings, session_end)
        scores.append(score)
        weights.append(weight)

    if not scores:
        return current_runs, current_runs + 1, float(current_runs), 0

    expected = sum(score * weight for score, weight in zip(scores, weights)) / sum(weights)
    low = max(current_runs, int(round(expected)))
    return low, low + 1, float(expected), len(scores)


def calculate_result(connection, league, innings_no, current_ball, current_runs, current_wickets, session_over, threshold):
    session_end = int(session_over) * 6
    candidates = load_match_state(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        session_end,
    )
    if not candidates:
        return None

    scores = [final_score(connection, match_id, historical_innings, session_end) for match_id, historical_innings, _ in candidates]
    if not scores:
        return None

    yes = sum(score >= threshold for score in scores) / len(scores) * 100.0
    return {
        "yes": yes,
        "no": 100.0 - yes,
        "samples": len(scores),
        "expected": sum(scores) / len(scores),
        "low": sorted(scores)[max(0, int(len(scores) * 0.10) - 1)],
        "high": sorted(scores)[max(0, int(len(scores) * 0.90) - 1)],
    }


# ============================================================
# STATE
# ============================================================

state_defaults = {
    "runs": 16,
    "wickets": 1,
    "balls": 19,
    "last_action": "Starting situation",
    "undo": [],
    "session_over": 6,
    "target": 0,
    "session_low": 0,
    "session_high": 1,
    "session_expected": 0.0,
    "manual_session": False,
    "analysis": None,
}
for key, value in state_defaults.items():
    st.session_state.setdefault(key, value)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    league = st.selectbox("League", LEAGUES, key="league_choice")
    try:
        database_path = ensure_database(league)
    except Exception as error:
        st.error(f"Historical database could not be prepared: {error}")
        st.stop()

    connection = connect_readonly(database_path)
    if connection is None:
        st.error(f"Database not found: {database_path.name}")
        st.stop()

    matches = table_count(connection, "matches")
    deliveries = table_count(connection, "deliveries")
    st.caption(f"{matches:,} matches • {deliveries:,} deliveries")

    teams = distinct_values(
        connection,
        "SELECT DISTINCT batting_team FROM deliveries WHERE league=? ORDER BY batting_team",
        league,
    )
    venues = distinct_values(
        connection,
        "SELECT DISTINCT venue FROM matches WHERE league=? AND venue<>'' ORDER BY venue",
        league,
    ) or ["Unknown"]

    if not teams:
        st.error("No teams found in the selected database.")
        st.stop()

    batting = st.selectbox("Batting Team", teams, key="batting_team")
    bowling = st.selectbox(
        "Bowling Team",
        [team for team in teams if team != batting],
        key="bowling_team",
    )
    venue = st.selectbox("Ground", venues, key="ground")
    innings_label = st.selectbox("Innings", ["1st Innings", "2nd Innings"], key="innings")
    innings_no = 1 if innings_label.startswith("1") else 2

    session_over = st.number_input(
        "Session Over",
        min_value=1,
        max_value=20,
        value=int(st.session_state.session_over),
        step=1,
        key="session_over_input",
    )
    target = st.number_input(
        "Target Runs",
        min_value=0,
        max_value=400,
        value=int(st.session_state.target),
        step=1,
        key="target_input",
    )
    st.session_state.session_over = int(session_over)
    st.session_state.target = int(target)

    points = ["0.0"] + [f"{over}.{ball}" for over in range(20) for ball in range(1, 7)]
    start_over = st.selectbox("Start Over / Ball", points, index=19, key="start_over")
    start_runs = st.number_input("Start Runs", 0, 400, 16, 1, key="start_runs")
    start_wickets = st.number_input("Start Wickets", 0, 10, 1, 1, key="start_wickets")

    if st.button("Set Current Match Situation", use_container_width=True, key="set_situation"):
        st.session_state.runs = int(start_runs)
        st.session_state.wickets = int(start_wickets)
        st.session_state.balls = parse_ball(start_over) or 0
        st.session_state.undo = []
        st.session_state.last_action = "Starting situation set"
        st.session_state.analysis = None
        st.rerun()

    if st.button("Reset Live Situation", use_container_width=True, key="reset_live"):
        st.session_state.runs = 0
        st.session_state.wickets = 0
        st.session_state.balls = 0
        st.session_state.undo = []
        st.session_state.last_action = ""
        st.session_state.analysis = None
        st.rerun()


# ============================================================
# LIVE SCORE AND SESSION
# ============================================================

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

low, high, expected, samples = calculate_line(
    connection,
    league,
    innings_no,
    balls,
    runs,
    wickets,
    int(session_over),
)

if not st.session_state.manual_session:
    st.session_state.session_low = low
    st.session_state.session_high = high
    st.session_state.session_expected = expected

st.markdown(
    f"""
    <div class="card">
        <h3>Current Live Score</h3>
        <h2>{runs}/{wickets}</h2>
        <p class="small">Over/Ball: {over_ball(balls)} • Target: {target or 'Not set'} • Session over: {session_over} • Last: {st.session_state.last_action or '—'}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.subheader("Ball-by-Ball Update")

buttons = [
    ("Dot", 0, False),
    ("1 Run", 1, False),
    ("2 Runs", 2, False),
    ("3 Runs", 3, False),
    ("4 Runs", 4, False),
    ("6 Runs", 6, False),
    ("Wicket", 0, True),
    ("Undo", None, False),
]
button_columns = st.columns(4)
for index, (label, run_value, wicket) in enumerate(buttons):
    with button_columns[index % 4]:
        if st.button(label, use_container_width=True, key=f"ball_{index}"):
            if label == "Undo":
                if st.session_state.undo:
                    previous = st.session_state.undo.pop()
                    st.session_state.runs, st.session_state.wickets, st.session_state.balls, _ = previous
                    st.session_state.last_action = "Undo"
            else:
                st.session_state.undo.append((runs, wickets, balls, st.session_state.last_action))
                st.session_state.runs += int(run_value)
                st.session_state.wickets = min(10, wickets + int(wicket))
                st.session_state.balls += 1
                st.session_state.last_action = label
            st.session_state.analysis = None
            st.rerun()

st.subheader("Match Detail")
detail = st.columns(4)
detail[0].metric("Batting", batting)
detail[1].metric("Bowling", bowling)
detail[2].metric("Ground", venue)
detail[3].metric("Innings", innings_label)

st.markdown(
    f"""
    <div class="session-box">
        <h3>Session</h3>
        <h2>{int(st.session_state.session_low)}-{int(st.session_state.session_high)}</h2>
        <p class="small">Expected: {float(st.session_state.session_expected):.1f} • Over: {session_over} • Target: {target or 'Not set'} • Samples: {samples}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

manual_columns = st.columns(2)
with manual_columns[0]:
    manual_low = st.number_input("Manual Session Low", 0, 400, int(st.session_state.session_low), 1, key="manual_low")
with manual_columns[1]:
    manual_high = st.number_input("Manual Session High", 0, 400, int(st.session_state.session_high), 1, key="manual_high")

manual_actions = st.columns(2)
with manual_actions[0]:
    if st.button("Apply Manual Session", use_container_width=True, key="apply_manual"):
        st.session_state.manual_session = True
        st.session_state.session_low = int(manual_low)
        st.session_state.session_high = max(int(manual_low) + 1, int(manual_high))
        st.session_state.analysis = None
        st.rerun()
with manual_actions[1]:
    if st.button("Use Auto Session", use_container_width=True, key="use_auto"):
        st.session_state.manual_session = False
        st.session_state.analysis = None
        st.rerun()


# ============================================================
# RESULT
# ============================================================

if st.button("Analyze Current Situation", use_container_width=True, key="analyze"):
    threshold = int(st.session_state.session_high)
    st.session_state.analysis = calculate_result(
        connection,
        league,
        innings_no,
        balls,
        runs,
        wickets,
        int(session_over),
        threshold,
    )
    st.rerun()

analysis = st.session_state.analysis
if analysis is None:
    st.info("Enter the match situation and press Analyze Current Situation.")
else:
    yes = float(analysis["yes"])
    no = float(analysis["no"])
    label = "YES" if yes >= no else "NO"
    css_class = "yes" if label == "YES" else "no"

    st.subheader("VasuDev Result")
    st.markdown(
        f"""
        <div class="{css_class}">
            <h1>{label} — {max(yes, no):.1f}%</h1>
            <p>Session line: <b>{int(st.session_state.session_low)}-{int(st.session_state.session_high)}</b> • {analysis['samples']} similar states</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Historical estimate only; it is not a guarantee.")
    with st.expander("Details", expanded=False):
        st.write(f"Expected score: **{analysis['expected']:.1f}**")
        st.write(f"Historical range: **{int(analysis['low'])}–{int(analysis['high'])}**")
        st.write(f"YES: **{yes:.1f}%** • NO: **{no:.1f}%**")
