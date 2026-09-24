import os
import hmac
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="VasuDev Cricket AI", page_icon="🏏", layout="wide")

st.markdown("""
<style>
.stApp { background: linear-gradient(180deg,#061426,#081c35); color:#f8fafc; }
.block-container { max-width:1450px; padding-top:1rem!important; padding-bottom:2rem!important; }
[data-testid="stSidebar"] { background:#071a2e; }
h1,h2,h3,h4,p,label,span { color:#f8fafc!important; }
.card { background:#0f223c; border:1px solid #2d4d72; border-radius:15px; padding:14px 18px; margin-bottom:10px; }
.session-box { background:#0f223c; border:2px solid #4777a8; border-radius:16px; padding:15px; text-align:center; }
.win-box { background:#151132; border:2px solid #8256c8; border-radius:16px; padding:15px; text-align:center; }
.yes { background:#07552f; border:2px solid #20c77a; padding:16px; border-radius:16px; text-align:center; margin-top:12px; }
.no { background:#651b1b; border:2px solid #ef5350; padding:16px; border-radius:16px; text-align:center; margin-top:12px; }
.small { color:#bed0e5!important; font-size:13px; }
div.stButton > button { min-height:40px; border-radius:8px; font-weight:700; background:#12365f; color:#fff; border:1px solid #3c6795; }
[data-testid="stHorizontalBlock"] { gap:.15rem!important; }
[data-testid="stColumn"] { padding-left:0!important; padding-right:0!important; }
[data-testid="stMetric"] { background:#0f223c; border:1px solid #2d4d72; border-radius:14px; padding:10px; }
</style>
""", unsafe_allow_html=True)

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()
if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🏏 VasuDev Cricket AI")
    entered_password = st.text_input("Password", type="password", key="auth_password")
    if st.button("Unlock", use_container_width=True):
        if hmac.compare_digest(entered_password, PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

BASE = Path(".")
DATABASES = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db",
}

# Working WBBL URL from your old code
DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
}
LEAGUES = list(DATABASES)


def parse_ball(value):
    try:
        over_text, ball_text = str(value).split(".", 1)
        over, ball = int(over_text), int(ball_text)
        return over * 6 + ball if over >= 0 and ball > 0 else None
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


def table_columns(connection, table_name):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def create_indexes(connection):
    connection.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_state ON deliveries(league, innings_no, ball_pos)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_match ON deliveries(match_id, innings_no, ball_pos)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_teams ON deliveries(league, innings_no, batting_team, bowling_team)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)")


def migrate_database(database_path):
    if not database_path.exists():
        return
    connection = sqlite3.connect(str(database_path), timeout=60)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "deliveries" not in tables or "matches" not in tables:
            return
        columns = table_columns(connection, "deliveries")
        if "ball_pos" not in columns:
            connection.execute("ALTER TABLE deliveries ADD COLUMN ball_pos INTEGER")
            rows = connection.execute("SELECT id, ball_no FROM deliveries WHERE ball_pos IS NULL").fetchall()
            connection.executemany(
                "UPDATE deliveries SET ball_pos=? WHERE id=?",
                [(parse_ball(ball_no), row_id) for row_id, ball_no in rows],
            )
        create_indexes(connection)
        connection.commit()
    finally:
        connection.close()


def build_database(database_path, league, archive_path):
    temp_path = database_path.with_suffix(".tmp")
    if temp_path.exists():
        temp_path.unlink()
    connection = sqlite3.connect(str(temp_path), timeout=120)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            "CREATE TABLE matches(match_id TEXT PRIMARY KEY, venue TEXT, winner TEXT, league TEXT)"
        )
        connection.execute("""
            CREATE TABLE deliveries(
                id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, innings_no INTEGER,
                batting_team TEXT, bowling_team TEXT, over_no INTEGER, ball_no TEXT,
                ball_pos INTEGER, runs INTEGER, wickets INTEGER, league TEXT
            )
        """)
        match_rows, delivery_rows = [], []
        with zipfile.ZipFile(archive_path) as source_zip:
            for filename in source_zip.namelist():
                if not filename.endswith(".json"):
                    continue
                try:
                    data = json.loads(source_zip.read(filename))
                    info = data.get("info", {}) or {}
                    teams = info.get("teams", []) or []
                    if len(teams) < 2:
                        continue
                    outcome = info.get("outcome", {}) or {}
                    winner = outcome.get("winner", "") or outcome.get("eliminator", "") or ""
                    match_id = Path(filename).stem
                    match_rows.append((match_id, str(info.get("venue", "") or ""), str(winner), league))
                    for innings_no, innings in enumerate(data.get("innings", []) or [], start=1):
                        if innings.get("super_over"):
                            continue
                        batting_team = str(innings.get("team", "") or "")
                        bowling_team = next((team for team in teams if team != batting_team), "")
                        for over_data in innings.get("overs", []) or []:
                            over_no = int(over_data.get("over", 0) or 0)
                            for delivery in over_data.get("deliveries", []) or []:
                                actual_delivery = delivery.get("actual_delivery")
                                if not actual_delivery:
                                    try:
                                        actual_delivery = f"{over_no}.{int(delivery.get('ball'))}"
                                    except Exception:
                                        continue
                                ball_pos = parse_ball(actual_delivery)
                                if ball_pos is None:
                                    continue
                                runs = int((delivery.get("runs", {}) or {}).get("total", 0) or 0)
                                wickets = len(delivery.get("wickets", []) or [])
                                delivery_rows.append(
                                    (match_id, innings_no, batting_team, bowling_team, over_no, str(actual_delivery), ball_pos, runs, wickets, league)
                                )
                    if len(match_rows) >= 100:
                        connection.executemany("INSERT OR REPLACE INTO matches VALUES(?,?,?,?)", match_rows)
                        match_rows.clear()
                    if len(delivery_rows) >= 5000:
                        connection.executemany(
                            "INSERT INTO deliveries(match_id,innings_no,batting_team,bowling_team,over_no,ball_no,ball_pos,runs,wickets,league) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            delivery_rows,
                        )
                        delivery_rows.clear()
                except Exception:
                    continue
        if match_rows:
            connection.executemany("INSERT OR REPLACE INTO matches VALUES(?,?,?,?)", match_rows)
        if delivery_rows:
            connection.executemany(
                "INSERT INTO deliveries(match_id,innings_no,batting_team,bowling_team,over_no,ball_no,ball_pos,runs,wickets,league) VALUES(?,?,?,?,?,?,?,?,?,?)",
                delivery_rows,
            )
        create_indexes(connection)
        connection.commit()
    finally:
        connection.close()
    temp_path.replace(database_path)


def delete_database_files(league):
    database_path = DATABASES[league]
    for suffix in ["", ".building", ".tmp"]:
        file_path = Path(str(database_path) + suffix)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass


def ensure_database(league):
    database_path = DATABASES[league]
    if database_path.exists():
        migrate_database(database_path)
        return database_path
    build_path = database_path.with_suffix(".building")
    try:
        if build_path.exists():
            build_path.unlink()
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "matches.zip"
            request = urllib.request.Request(
                DOWNLOAD_URLS[league],
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(request, timeout=120) as response, open(archive_path, "wb") as output_file:
                output_file.write(response.read())
            build_database(build_path, league, archive_path)
        build_path.replace(database_path)
        return database_path
    except Exception:
        if build_path.exists():
            build_path.unlink()
        raise


@st.cache_resource
def get_connection(database_path_text):
    database_path = Path(database_path_text)
    migrate_database(database_path)
    connection = sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=60,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-10000")
    return connection


def get_values(connection, query, league):
    return [row[0] for row in connection.execute(query, (league,)).fetchall() if row[0]]


def score_at(connection, match_id, innings_no, end_ball):
    row = connection.execute(
        """SELECT COALESCE(SUM(runs),0) AS total_runs,
        COALESCE(SUM(wickets),0) AS total_wickets FROM deliveries
        WHERE match_id=? AND innings_no=? AND ball_pos<=?""",
        (match_id, innings_no, end_ball),
    ).fetchone()
    return int(row["total_runs"] or 0), int(row["total_wickets"] or 0)


def session_runs_between(connection, match_id, innings_no, start_ball, end_ball):
    row = connection.execute(
        """SELECT COALESCE(SUM(runs),0) AS total_runs FROM deliveries
        WHERE match_id=? AND innings_no=? AND ball_pos>? AND ball_pos<=?""",
        (match_id, innings_no, start_ball, end_ball),
    ).fetchone()
    return int(row["total_runs"] or 0)


def final_score(connection, match_id, innings_no):
    row = connection.execute(
        "SELECT COALESCE(SUM(runs),0) AS final_runs FROM deliveries WHERE match_id=? AND innings_no=?",
        (match_id, innings_no),
    ).fetchone()
    return int(row["final_runs"] or 0)


def historical_batting_win(connection, match_id, batting_team):
    row = connection.execute("SELECT winner FROM matches WHERE match_id=?", (match_id,)).fetchone()
    return 1 if row and str(row["winner"] or "") == batting_team else 0


def find_similar_states(connection, league, innings_no, current_ball, current_runs, current_wickets, end_ball, batting_team, bowling_team):
    current_rr = (current_runs / current_ball) * 6 if current_ball > 0 else 0.0
    low_ball = max(1, int(current_ball) - 2)
    high_ball = min(int(end_ball), int(current_ball) + 2)

    def get_candidates(mode):
        where_sql = "league=? AND innings_no=? AND ball_pos BETWEEN ? AND ?"
        params = [league, innings_no, low_ball, high_ball]
        if mode == "both":
            where_sql += " AND batting_team=? AND bowling_team=?"
            params += [batting_team, bowling_team]
        elif mode == "batting":
            where_sql += " AND batting_team=?"
            params.append(batting_team)
        query = f"""SELECT match_id, innings_no, ball_pos, batting_team, bowling_team
            FROM deliveries WHERE {where_sql}
            GROUP BY match_id, innings_no, ball_pos, batting_team, bowling_team
            LIMIT 6000"""
        return connection.execute(query, params).fetchall()

    candidates = get_candidates("both")
    if len(candidates) < 40:
        candidates = get_candidates("batting")
    if len(candidates) < 40:
        candidates = get_candidates("all")

    best_states = {}
    for row in candidates:
        match_id = row["match_id"]
        historical_innings = int(row["innings_no"])
        historical_ball = int(row["ball_pos"])
        historical_runs, historical_wickets = score_at(connection, match_id, historical_innings, historical_ball)
        historical_rr = (historical_runs / historical_ball) * 6 if historical_ball > 0 else 0.0
        run_gap = abs(historical_runs - int(current_runs))
        wicket_gap = abs(historical_wickets - int(current_wickets))
        ball_gap = abs(historical_ball - int(current_ball))
        rr_gap = abs(historical_rr - current_rr)
        if run_gap > 35 or wicket_gap > 4:
            continue
        distance = run_gap + wicket_gap * 8 + ball_gap * 2 + rr_gap * 4
        key = (match_id, historical_innings)
        state = {
            "match_id": match_id,
            "innings_no": historical_innings,
            "ball_pos": historical_ball,
            "runs": historical_runs,
            "batting_team": row["batting_team"],
            "distance": float(distance),
        }
        if key not in best_states or state["distance"] < best_states[key]["distance"]:
            best_states[key] = state
    return sorted(best_states.values(), key=lambda item: item["distance"])[:800]


@st.cache_data(ttl=300, show_spinner=False)
def calculate_auto_model_cached(
    database_path_text,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    batting_team,
    bowling_team,
    match_target,
):
    connection = get_connection(database_path_text)
    end_ball = int(session_over) * 6

    empty_result = {
        "low": int(current_runs),
        "high": int(current_runs) + 1,
        "expected": float(current_runs),
        "session_yes": 0.0,
        "session_no": 100.0,
        "win_probability": None,
    }

    if int(current_ball) >= end_ball:
        return empty_result

    states = find_similar_states(
        connection, league, innings_no, current_ball, current_runs,
        current_wickets, end_ball, batting_team, bowling_team,
    )
    if not states:
        return empty_result

    projected_totals, weights, win_results = [], [], []
    for state in states:
        historical_session_runs = session_runs_between(
            connection,
            state["match_id"],
            state["innings_no"],
            state["ball_pos"],
            end_ball,
        )
        projected_total = int(current_runs) + historical_session_runs
        weight = 1.0 / (1.0 + state["distance"])
        projected_totals.append(projected_total)
        weights.append(float(weight))

        if int(innings_no) == 1:
            win_results.append(
                historical_batting_win(connection, state["match_id"], state["batting_team"])
            )
        elif int(innings_no) == 2 and int(match_target) > 0:
            match_final = final_score(connection, state["match_id"], state["innings_no"])
            win_results.append(1 if match_final >= int(match_target) else 0)

    total_weight = sum(weights)
    expected = (
        sum(score * weight for score, weight in zip(projected_totals, weights)) / total_weight
        if total_weight else float(current_runs)
    )
    low = max(int(current_runs), int(round(expected)))
    high = low + 1
    yes_weight = sum(
        weight for score, weight in zip(projected_totals, weights) if score >= high
    )
    session_yes = yes_weight / total_weight * 100 if total_weight else 0.0

    win_probability = None
    if win_results and len(win_results) == len(weights) and total_weight:
        win_probability = (
            sum(result * weight for result, weight in zip(win_results, weights))
            / total_weight * 100
        )

    return {
        "low": int(low),
        "high": int(high),
        "expected": float(expected),
        "session_yes": float(session_yes),
        "session_no": float(100.0 - session_yes),
        "win_probability": win_probability,
    }


@st.cache_data(ttl=60, show_spinner=False)
def calculate_manual_probability_cached(
    database_path_text,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    batting_team,
    bowling_team,
    line_high,
):
    connection = get_connection(database_path_text)
    end_ball = int(session_over) * 6
    states = find_similar_states(
        connection, league, innings_no, current_ball, current_runs,
        current_wickets, end_ball, batting_team, bowling_team,
    )
    if not states:
        return {"yes": 0.0, "no": 100.0}

    total_weight, yes_weight = 0.0, 0.0
    for state in states:
        historical_session_runs = session_runs_between(
            connection,
            state["match_id"],
            state["innings_no"],
            state["ball_pos"],
            end_ball,
        )
        projected_total = int(current_runs) + historical_session_runs
        weight = 1.0 / (1.0 + state["distance"])
        total_weight += weight
        if projected_total >= int(line_high):
            yes_weight += weight

    yes_probability = yes_weight / total_weight * 100 if total_weight else 0.0
    return {"yes": float(yes_probability), "no": float(100.0 - yes_probability)}


DEFAULTS = {
    "runs": 8,
    "wickets": 0,
    "balls": 6,
    "last": "Starting situation",
    "undo_stack": [],
    "session_over": 6,
    "match_target": 0,
    "manual_mode": False,
    "session_low": 0,
    "session_high": 1,
    "expected_score": 0.0,
    "win_probability": None,
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)

with st.sidebar:
    st.header("Match Setup")
    league = st.selectbox("League", LEAGUES, key="league_select")

    if league == "Women's Big Bash League":
        if st.button("Delete & Rebuild WBBL Database", use_container_width=True, key="rebuild_wbbl_button"):
            delete_database_files(league)
            st.cache_resource.clear()
            st.cache_data.clear()
            st.success("WBBL database delete ho gayi. Fresh data download hoga.")
            st.rerun()

    try:
        db_path = ensure_database(league)
        connection = get_connection(str(db_path.resolve()))
    except Exception as error:
        st.error("Database start nahi ho saka.")
        st.exception(error)
        st.stop()

    database_path_text = str(db_path.resolve())

    venues = ["All Grounds"] + get_values(
        connection,
        "SELECT DISTINCT venue FROM matches WHERE league=? AND venue<>'' ORDER BY venue",
        league,
    )
    selected_venue = st.selectbox("Ground / Venue", venues, key="venue_select")

    teams = get_values(
        connection,
        "SELECT DISTINCT batting_team FROM deliveries WHERE league=? AND batting_team<>'' ORDER BY batting_team",
        league,
    )
    if not teams:
        st.error("Database me team data nahi mila.")
        st.stop()

    batting_team = st.selectbox("Batting Team", teams, key="batting_team_select")
    bowling_options = [team for team in teams if team != batting_team] or ["Unknown"]
    bowling_team = st.selectbox("Bowling Team", bowling_options, key="bowling_team_select")

    innings_label = st.selectbox("Innings", ["1st Innings", "2nd Innings"], key="innings_select")
    innings_no = 1 if innings_label == "1st Innings" else 2

    session_over = st.number_input(
        "Session Over", 1, 20, int(st.session_state.session_over), 1, key="session_over_widget"
    )

    starting_session_line = st.number_input(
        "Starting Session Line",
        1, 400, 62, 1,
        help="Example: 62 means Session 61-62",
        key="starting_session_line_widget",
    )

    match_target = 0
    if innings_no == 2:
        match_target = st.number_input(
            "Match Target Runs",
            0, 400, int(st.session_state.match_target), 1,
            key="match_target_widget",
        )

    st.session_state.session_over = int(session_over)
    st.session_state.match_target = int(match_target)

    over_points = ["0.0"] + [f"{over}.{ball}" for over in range(20) for ball in range(1, 7)]
    start_over = st.selectbox("Start Over / Ball", over_points, index=6, key="start_over_select")
    start_runs = st.number_input("Start Runs", 0, 400, 8, 1, key="start_runs_widget")
    start_wickets = st.number_input("Start Wickets", 0, 10, 0, 1, key="start_wickets_widget")

    if st.button("Set Current Match Situation", use_container_width=True, key="set_situation_button"):
        st.session_state.runs = int(start_runs)
        st.session_state.wickets = int(start_wickets)
        st.session_state.balls = parse_ball(start_over) or 0
        st.session_state.undo_stack = []
        st.session_state.last = "Starting situation set"
        st.rerun()

    if st.button("Reset Live Situation", use_container_width=True, key="reset_button"):
        st.session_state.runs = 0
        st.session_state.wickets = 0
        st.session_state.balls = 0
        st.session_state.undo_stack = []
        st.session_state.last = ""
        st.rerun()

    st.divider()
    st.subheader("Live Match")

    sidebar_rr = (st.session_state.runs / st.session_state.balls) * 6 if st.session_state.balls > 0 else 0.0

    st.metric("Score", f"{st.session_state.runs}/{st.session_state.wickets}")
    st.metric("Overs", display_over(st.session_state.balls))
    st.metric("Run Rate", f"{sidebar_rr:.2f}")
    st.metric(
        "Session",
        f"{st.session_state.session_low}-{st.session_state.session_high}",
    )
    st.metric("Session End", f"{st.session_state.session_over} ov")

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

try:
    auto_model = calculate_auto_model_cached(
        database_path_text,
        league,
        innings_no,
        balls,
        runs,
        wickets,
        int(session_over),
        batting_team,
        bowling_team,
        int(match_target),
    )
except Exception as error:
    st.error("Model calculation failed.")
    st.exception(error)
    st.stop()

# Historical average always updates independently of manual session line.
st.session_state.expected_score = float(auto_model["expected"])
st.session_state.win_probability = auto_model["win_probability"]

# AUTO session line updates after every ball.
if not st.session_state.manual_mode:
    st.session_state.session_low = int(auto_model["low"])
    st.session_state.session_high = int(auto_model["high"])

score_column, mode_column = st.columns([8, 2])
with score_column:
    st.markdown(
        f"""<div class="card"><h2 style="margin:0">{batting_team} {runs}/{wickets}</h2>
        <p class="small" style="margin:4px 0 0">{display_over(balls)} ov • Session End: {session_over} ov •
        Ground: {selected_venue} • Last: {st.session_state.last or '—'}</p></div>""",
        unsafe_allow_html=True,
    )

with mode_column:
    mode = st.radio(
        "Mode",
        ["AUTO", "MANUAL"],
        index=1 if st.session_state.manual_mode else 0,
        horizontal=True,
        key="mode_selector",
    )
    st.session_state.manual_mode = mode == "MANUAL"

st.subheader("Ball-by-Ball Update")
buttons = [
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
button_columns = st.columns(len(buttons))

for index, (label, add_runs, add_wicket, legal_ball) in enumerate(buttons):
    with button_columns[index]:
        if st.button(label, use_container_width=True, key=f"ball_action_{index}"):
            if label == "Undo":
                if st.session_state.undo_stack:
                    old_data = st.session_state.undo_stack.pop()
                    st.session_state.runs = old_data["runs"]
                    st.session_state.wickets = old_data["wickets"]
                    st.session_state.balls = old_data["balls"]
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

session_column, winning_column = st.columns(2)
with session_column:
    st.markdown(
        f"""<div class="session-box"><h3 style="margin:0">Session</h3>
        <h1 style="margin:8px 0">{int(st.session_state.session_low)}-{int(st.session_state.session_high)}</h1>
        <p class="small" style="margin:0">Expected: {float(st.session_state.expected_score):.1f} • End: {session_over} ov</p></div>""",
        unsafe_allow_html=True,
    )

with winning_column:
    probability = st.session_state.win_probability
    win_text = f"{float(probability):.1f}%" if probability is not None else "—"
    st.markdown(
        f"""<div class="win-box"><h3 style="margin:0">{batting_team} Win</h3>
        <h1 style="margin:8px 0">{win_text}</h1>
        <p class="small" style="margin:0">Historical situations + current score</p></div>""",
        unsafe_allow_html=True,
    )

manual_state_key = f"{balls}_{runs}_{wickets}"
manual_low_column, manual_high_column = st.columns(2)

with manual_low_column:
    manual_low = st.number_input(
        "Manual Session Low",
        0, 400,
        int(st.session_state.session_low),
        1,
        key=f"manual_low_widget_{manual_state_key}",
    )

with manual_high_column:
    manual_high = st.number_input(
        "Manual Session High",
        0, 400,
        int(st.session_state.session_high),
        1,
        key=f"manual_high_widget_{manual_state_key}",
    )

manual_button, auto_button = st.columns(2)
with manual_button:
    if st.button("Apply Manual Session", use_container_width=True, key="apply_manual_button"):
        st.session_state.manual_mode = True
        st.session_state.session_low = int(manual_low)
        st.session_state.session_high = max(int(manual_low) + 1, int(manual_high))
        st.rerun()

with auto_button:
    if st.button("Use Auto Session", use_container_width=True, key="use_auto_button"):
        st.session_state.manual_mode = False
        st.rerun()

if st.session_state.manual_mode:
    try:
        manual_result = calculate_manual_probability_cached(
            database_path_text,
            league,
            innings_no,
            balls,
            runs,
            wickets,
            int(session_over),
            batting_team,
            bowling_team,
            int(st.session_state.session_high),
        )
        session_yes = float(manual_result["yes"])
        session_no = float(manual_result["no"])
    except Exception as error:
        st.error("Manual session calculation failed.")
        st.exception(error)
        session_yes, session_no = 0.0, 100.0
else:
    session_yes = float(auto_model["session_yes"])
    session_no = float(auto_model["session_no"])

result_label = "YES" if session_yes >= session_no else "NO"
result_class = "yes" if result_label == "YES" else "no"
result_percent = max(session_yes, session_no)

st.subheader("VasuDev Result")
st.markdown(
    f"""<div class="{result_class}"><h1 style="margin:0">SESSION {result_label} — {result_percent:.1f}%</h1>
    <p style="margin:8px 0 0">Session line: <b>{int(st.session_state.session_low)}-{int(st.session_state.session_high)}</b></p>
    <p style="margin:5px 0 0">Avg Score: <b>{float(st.session_state.expected_score):.1f}</b></p></div>""",
    unsafe_allow_html=True,
)

final_win_probability = st.session_state.win_probability
if final_win_probability is not None:
    batting_win = float(final_win_probability)
    bowling_win = 100.0 - batting_win
    if batting_win >= bowling_win:
        winner_name, winner_percent, winner_class = batting_team, batting_win, "yes"
    else:
        winner_name, winner_percent, winner_class = bowling_team, bowling_win, "no"

    st.markdown(
        f"""<div class="{winner_class}"><h1 style="margin:0">{winner_name.upper()} WIN — {winner_percent:.1f}%</h1>
        <p style="margin:8px 0 0">{batting_team}: <b>{batting_win:.1f}%</b> • {bowling_team}: <b>{bowling_win:.1f}%</b></p></div>""",
        unsafe_allow_html=True,
    )
elif innings_no == 2 and int(match_target) <= 0:
    st.info("2nd innings win probability ke liye Match Target Runs set karein.")
else:
    st.info("Winning probability ke liye historical data insufficient hai.")

st.caption("Historical estimate only. This is not a guarantee of the live match result.")

with st.expander("Details"):
    st.write(f"Expected session-end score: **{auto_model['expected']:.1f}**")
    st.write(f"YES: **{session_yes:.1f}%** • NO: **{session_no:.1f}%**")
    st.write(f"Session line: **{int(st.session_state.session_low)}-{int(st.session_state.session_high)}**")
    if final_win_probability is not None:
        st.write(f"{batting_team} win probability: **{float(final_win_probability):.1f}%**")
