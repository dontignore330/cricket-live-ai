import os
import hmac
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="VasuDev Cricket AI", page_icon="🐎", layout="wide")

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()
if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

st.markdown("""
<style>
.stApp{background:linear-gradient(180deg,#061426,#081c35);color:#f8fafc}
.block-container{max-width:1500px;padding-top:1rem!important}
.card,.session-box,.win-box{background:#0f223c;padding:14px;border-radius:16px;border:1px solid #2d4d72}
.session-box{text-align:center;border:2px solid #4777a8;margin:10px 0}
.win-box{text-align:center;border:2px solid #8256c8;margin:10px 0}
.yes{background:#07552f;border:2px solid #20c77a;padding:16px;border-radius:16px;text-align:center}
.no{background:#651b1b;border:2px solid #ef5350;padding:16px;border-radius:16px;text-align:center}
.small{color:#bed0e5!important;font-size:13px}
h1,h2,h3,h4,p,label{color:#f8fafc!important}
[data-testid="stSidebar"]{background:#071a2e}
div.stButton>button{min-height:38px;border-radius:8px;font-weight:700;background:#12365f;color:#fff;border:1px solid #3c6795}
[data-testid="stHorizontalBlock"]{gap:0.15rem!important}
[data-testid="stColumn"]{padding:0!important}
div.stButton>button{width:100%!important}
</style>
""", unsafe_allow_html=True)

if not st.session_state.authenticated:
    st.title("VasuDev Cricket AI")
    password = st.text_input("Password", type="password", key="auth_password")
    if st.button("Unlock", use_container_width=True, key="unlock"):
        if hmac.compare_digest(password, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("auth_password", None)
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

BASE = Path(".")
DBS = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db",
}
URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbbl_json.zip",
}
LEAGUES = list(DBS)
MAX_HISTORY = 5000


def parse_ball(value):
    try:
        over, ball = str(value).split(".", 1)
        over, ball = int(over), int(ball)
        if over < 0 or ball <= 0:
            raise ValueError
        return over * 6 + ball
    except Exception:
        return None


def display_over(balls):
    balls = int(balls)
    if balls <= 0:
        return "0.0"
    return f"{(balls - 1)//6}.{((balls - 1)%6)+1}"


def table_columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def rebuild_ball_state(connection, league):
    connection.execute("DELETE FROM ball_state WHERE league=?", (league,))
    connection.execute("""
        INSERT INTO ball_state(
            match_id, innings_no, ball_pos, cum_runs, cum_wickets,
            final_runs, batting_team, bowling_team, batting_win, league
        )
        WITH ball_agg AS (
            SELECT match_id, innings_no, ball_pos,
                   SUM(runs) AS ball_runs,
                   SUM(wickets) AS ball_wickets
            FROM deliveries
            WHERE league=?
            GROUP BY match_id, innings_no, ball_pos
        ),
        running AS (
            SELECT match_id, innings_no, ball_pos,
                   SUM(ball_runs) OVER (
                       PARTITION BY match_id, innings_no ORDER BY ball_pos
                   ) AS cum_runs,
                   SUM(ball_wickets) OVER (
                       PARTITION BY match_id, innings_no ORDER BY ball_pos
                   ) AS cum_wickets
            FROM ball_agg
        ),
        totals AS (
            SELECT match_id, innings_no, SUM(ball_runs) AS final_runs
            FROM ball_agg
            GROUP BY match_id, innings_no
        ),
        teams AS (
            SELECT match_id, innings_no, ball_pos,
                   MIN(batting_team) AS batting_team,
                   MIN(bowling_team) AS bowling_team,
                   MIN(league) AS league
            FROM deliveries
            WHERE league=?
            GROUP BY match_id, innings_no, ball_pos
        )
        SELECT
            r.match_id,
            r.innings_no,
            r.ball_pos,
            r.cum_runs,
            r.cum_wickets,
            t.final_runs,
            x.batting_team,
            x.bowling_team,
            CASE WHEN m.winner=x.batting_team THEN 1 ELSE 0 END,
            x.league
        FROM running r
        JOIN totals t
          ON t.match_id=r.match_id AND t.innings_no=r.innings_no
        JOIN teams x
          ON x.match_id=r.match_id
         AND x.innings_no=r.innings_no
         AND x.ball_pos=r.ball_pos
        JOIN matches m
          ON m.match_id=r.match_id
        WHERE x.league=?
    """, (league, league, league))
    connection.commit()


def migrate_database(path):
    if not path.exists():
        return

    connection = sqlite3.connect(str(path), timeout=60)
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "deliveries" not in tables or "matches" not in tables:
            return

        columns = table_columns(connection, "deliveries")
        if "ball_pos" not in columns:
            connection.execute("ALTER TABLE deliveries ADD COLUMN ball_pos INTEGER")
            rows = connection.execute(
                "SELECT id, ball_no FROM deliveries WHERE ball_pos IS NULL"
            ).fetchall()
            updates = [(parse_ball(ball_no), row_id) for row_id, ball_no in rows]
            connection.executemany(
                "UPDATE deliveries SET ball_pos=? WHERE id=?", updates
            )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_deliveries_state "
            "ON deliveries(league, innings_no, ball_pos)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_deliveries_match "
            "ON deliveries(match_id, innings_no, ball_pos)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)"
        )

        if "ball_state" not in tables:
            connection.execute("""
                CREATE TABLE ball_state(
                    match_id TEXT,
                    innings_no INTEGER,
                    ball_pos INTEGER,
                    cum_runs INTEGER,
                    cum_wickets INTEGER,
                    final_runs INTEGER,
                    batting_team TEXT,
                    bowling_team TEXT,
                    batting_win INTEGER,
                    league TEXT,
                    PRIMARY KEY(match_id, innings_no, ball_pos)
                )
                WITHOUT ROWID
            """)

        state_count = connection.execute(
            "SELECT COUNT(*) FROM ball_state"
        ).fetchone()[0]
        delivery_count = connection.execute(
            "SELECT COUNT(*) FROM deliveries"
        ).fetchone()[0]

        if state_count == 0 or state_count < delivery_count:
            leagues = [
                row[0] for row in connection.execute(
                    "SELECT DISTINCT league FROM deliveries WHERE league IS NOT NULL"
                )
            ]
            for league in leagues:
                rebuild_ball_state(connection, league)

        connection.commit()
    finally:
        connection.close()


def readonly(path):
    migrate_database(path)
    connection = sqlite3.connect(
        f"file:{path.resolve()}?mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=60
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-12000")
    return connection


def build_database(path, league, archive):
    temporary = path.with_suffix(".tmp")
    if temporary.exists():
        temporary.unlink()

    connection = sqlite3.connect(str(temporary))
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")

        connection.execute(
            "CREATE TABLE matches("
            "match_id TEXT PRIMARY KEY,"
            "venue TEXT,"
            "winner TEXT,"
            "league TEXT)"
        )
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
        connection.execute("""
            CREATE TABLE ball_state(
                match_id TEXT,
                innings_no INTEGER,
                ball_pos INTEGER,
                cum_runs INTEGER,
                cum_wickets INTEGER,
                final_runs INTEGER,
                batting_team TEXT,
                bowling_team TEXT,
                batting_win INTEGER,
                league TEXT,
                PRIMARY KEY(match_id, innings_no, ball_pos)
            )
            WITHOUT ROWID
        """)

        matches, deliveries = [], []

        with zipfile.ZipFile(archive) as source:
            for filename in source.namelist():
                if not filename.endswith(".json"):
                    continue

                try:
                    data = json.loads(source.read(filename))
                    info = data.get("info", {})
                    teams = info.get("teams", [])

                    if len(teams) < 2:
                        continue

                    outcome = info.get("outcome", {}) or {}
                    winner = (
                        outcome.get("winner", "")
                        or outcome.get("eliminator", "")
                        or ""
                    )
                    match_id = Path(filename).stem

                    matches.append((
                        match_id,
                        str(info.get("venue", "") or ""),
                        str(winner),
                        league
                    ))

                    for innings_no, innings in enumerate(data.get("innings", []), 1):
                        if innings.get("super_over"):
                            continue

                        batting = innings.get("team", "")
                        bowling = next(
                            (team for team in teams if team != batting),
                            ""
                        )

                        for over in innings.get("overs", []):
                            over_no = int(over.get("over", 0))

                            for delivery in over.get("deliveries", []):
                                value = delivery.get("actual_delivery")
                                if not value:
                                    try:
                                        value = f"{over_no}.{int(delivery.get('ball'))}"
                                    except Exception:
                                        continue

                                position = parse_ball(value)
                                if position is None:
                                    continue

                                runs = int(
                                    (delivery.get("runs") or {}).get("total", 0) or 0
                                )
                                wickets = len(delivery.get("wickets") or [])

                                deliveries.append((
                                    match_id,
                                    innings_no,
                                    batting,
                                    bowling,
                                    over_no,
                                    str(value),
                                    position,
                                    runs,
                                    wickets,
                                    league
                                ))

                    if len(matches) >= 100:
                        connection.executemany(
                            "INSERT OR REPLACE INTO matches VALUES(?,?,?,?)",
                            matches
                        )
                        matches.clear()

                    if len(deliveries) >= 5000:
                        connection.executemany("""
                            INSERT INTO deliveries(
                                match_id,innings_no,batting_team,bowling_team,
                                over_no,ball_no,ball_pos,runs,wickets,league
                            ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """, deliveries)
                        deliveries.clear()

                except Exception:
                    continue

        if matches:
            connection.executemany(
                "INSERT OR REPLACE INTO matches VALUES(?,?,?,?)", matches
            )

        if deliveries:
            connection.executemany("""
                INSERT INTO deliveries(
                    match_id,innings_no,batting_team,bowling_team,
                    over_no,ball_no,ball_pos,runs,wickets,league
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """, deliveries)

        connection.execute(
            "CREATE INDEX idx_deliveries_state "
            "ON deliveries(league,innings_no,ball_pos)"
        )
        connection.execute(
            "CREATE INDEX idx_deliveries_match "
            "ON deliveries(match_id,innings_no,ball_pos)"
        )

        rebuild_ball_state(connection, league)
        connection.commit()

    finally:
        connection.close()

    temporary.replace(path)


def ensure_database(league):
    path = DBS[league]

    if path.exists():
        migrate_database(path)
        return path

    building = path.with_suffix(".building")
    try:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "matches.zip"
            urllib.request.urlretrieve(URLS[league], archive)
            build_database(building, league, archive)

        building.replace(path)
        return path

    except Exception:
        if building.exists():
            building.unlink()
        raise


@st.cache_resource
def get_connection(path_string):
    return readonly(Path(path_string))


def values(connection, sql, league):
    return [
        row[0]
        for row in connection.execute(sql, (league,)).fetchall()
        if row[0]
    ]


def similar_states(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    end_ball,
    batting_team=None,
    bowling_team=None
):
    low_ball = max(1, current_ball - 2)
    high_ball = min(current_ball + 2, end_ball)

    base_filters = """
        WHERE league=:league
          AND innings_no=:innings_no
          AND ball_pos BETWEEN :low_ball AND :high_ball
          AND ball_pos <= :end_ball
          AND ABS(cum_runs - :runs) <= 30
          AND ABS(cum_wickets - :wickets) <= 3
    """

    params = {
        "league": league,
        "innings_no": innings_no,
        "low_ball": low_ball,
        "high_ball": high_ball,
        "end_ball": end_ball,
        "runs": current_runs,
        "wickets": current_wickets,
        "batting": batting_team,
        "bowling": bowling_team
    }

    team_filter = ""
    if batting_team and bowling_team:
        team_filter = (
            " AND batting_team=:batting AND bowling_team=:bowling"
        )
    elif batting_team:
        team_filter = " AND batting_team=:batting"

    sql = f"""
        WITH candidates AS (
            SELECT *,
                   (
                       ABS(cum_runs - :runs) / 30.0
                     + ABS(cum_wickets - :wickets) / 3.0
                     + ABS(ball_pos - :current_ball) / 12.0
                   ) AS distance
            FROM ball_state
            {base_filters}
            {team_filter}
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY match_id, innings_no
                       ORDER BY distance, ball_pos
                   ) AS rank_no
            FROM candidates
        )
        SELECT
            match_id,
            innings_no,
            ball_pos,
            cum_runs,
            cum_wickets,
            final_runs,
            batting_team,
            bowling_team,
            batting_win,
            distance
        FROM ranked
        WHERE rank_no=1
        ORDER BY distance
        LIMIT {MAX_HISTORY}
    """

    final_params = dict(params)
    final_params["current_ball"] = current_ball

    return connection.execute(sql, final_params).fetchall()


def calculate_model(
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
    end_ball = int(session_over) * 6

    if current_ball >= end_ball:
        return {
            "low": current_runs,
            "high": current_runs + 1,
            "expected": float(current_runs),
            "session_yes": 100.0 if current_runs >= current_runs + 1 else 0.0,
            "session_no": 0.0 if current_runs >= current_runs + 1 else 100.0,
            "win": None,
            "states": 0
        }

    rows = similar_states(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        end_ball,
        batting_team,
        bowling_team
    )

    if not rows:
        rows = similar_states(
            connection,
            league,
            innings_no,
            current_ball,
            current_runs,
            current_wickets,
            end_ball,
            batting_team,
            None
        )

    if not rows:
        rows = similar_states(
            connection,
            league,
            innings_no,
            current_ball,
            current_runs,
            current_wickets,
            end_ball,
            None,
            None
        )

    if not rows:
        return {
            "low": current_runs,
            "high": current_runs + 1,
            "expected": float(current_runs),
            "session_yes": 0.0,
            "session_no": 100.0,
            "win": None,
            "states": 0
        }

    weights = [1 / (1 + row["distance"]) for row in rows]
    total_weight = sum(weights)

    expected = sum(
        row["final_runs"] * weight
        for row, weight in zip(rows, weights)
    ) / total_weight

    low = max(current_runs, int(round(expected)))
    high = low + 1

    session_yes = sum(
        weight
        for row, weight in zip(rows, weights)
        if row["final_runs"] >= high
    ) / total_weight * 100

    win = None
    if innings_no == 2 and target > 0:
        win = sum(
            weight
            for row, weight in zip(rows, weights)
            if row["final_runs"] >= target
        ) / total_weight * 100
    elif innings_no == 1:
        win = sum(
            weight * row["batting_win"]
            for row, weight in zip(rows, weights)
        ) / total_weight * 100

    return {
        "low": low,
        "high": high,
        "expected": expected,
        "session_yes": session_yes,
        "session_no": 100 - session_yes,
        "win": win,
        "states": len(rows)
    }


for key, value in {
    "runs": 16,
    "wickets": 1,
    "balls": 19,
    "last": "Starting situation",
    "undo": [],
    "session_over": 6,
    "target": 0,
    "low": 0,
    "high": 1,
    "expected": 0.0,
    "win": None,
    "manual": False,
    "analysis": None
}.items():
    st.session_state.setdefault(key, value)

with st.sidebar:
    league = st.selectbox("League", LEAGUES, key="league_choice")

    try:
        database_path = ensure_database(league)
        connection = get_connection(str(database_path.resolve()))
    except Exception as error:
        st.error(f"Historical database could not be prepared: {error}")
        st.stop()

    teams = values(
        connection,
        "SELECT DISTINCT batting_team FROM ball_state WHERE league=? ORDER BY batting_team",
        league
    )

    venues = values(
        connection,
        "SELECT DISTINCT venue FROM matches WHERE league=? AND venue<>'' ORDER BY venue",
        league
    ) or ["Unknown"]

    if not teams:
        st.error("No teams found in database.")
        st.stop()

    batting = st.selectbox("Batting Team", teams, key="batting_team")
    bowling = st.selectbox(
        "Bowling Team",
        [team for team in teams if team != batting],
        key="bowling_team"
    )
    venue = st.selectbox("Ground", venues, key="ground")

    innings_label = st.selectbox(
        "Innings",
        ["1st Innings", "2nd Innings"],
        key="innings"
    )
    innings_no = 1 if innings_label.startswith("1") else 2

    session_over = st.number_input(
        "Session Over",
        1,
        20,
        int(st.session_state.session_over),
        1,
        key="session_over_input"
    )

    target = st.number_input(
        "Target Runs",
        0,
        400,
        int(st.session_state.target),
        1,
        key="target_input"
    )

    st.session_state.session_over = int(session_over)
    st.session_state.target = int(target)

    points = ["0.0"] + [
        f"{over}.{ball}"
        for over in range(20)
        for ball in range(1, 7)
    ]

    start_over = st.selectbox(
        "Start Over / Ball",
        points,
        index=19,
        key="start_over"
    )

    start_runs = st.number_input(
        "Start Runs",
        0,
        400,
        16,
        1,
        key="start_runs"
    )

    start_wickets = st.number_input(
        "Start Wickets",
        0,
        10,
        1,
        1,
        key="start_wickets"
    )

    if st.button(
        "Set Current Match Situation",
        use_container_width=True,
        key="set_situation"
    ):
        st.session_state.runs = int(start_runs)
        st.session_state.wickets = int(start_wickets)
        st.session_state.balls = parse_ball(start_over) or 0
        st.session_state.undo = []
        st.session_state.last = "Starting situation set"
        st.session_state.analysis = None
        st.rerun()

    if st.button(
        "Reset Live Situation",
        use_container_width=True,
        key="reset_live"
    ):
        st.session_state.runs = 0
        st.session_state.wickets = 0
        st.session_state.balls = 0
        st.session_state.undo = []
        st.session_state.last = ""
        st.session_state.analysis = None
        st.rerun()

runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

model = calculate_model(
    connection,
    league,
    innings_no,
    balls,
    runs,
    wickets,
    session_over,
    batting,
    bowling,
    int(st.session_state.target)
)

if not st.session_state.manual:
    st.session_state.low = model["low"]
    st.session_state.high = model["high"]
    st.session_state.expected = model["expected"]
    st.session_state.win = model["win"]

top = st.columns([7, 2])

with top[0]:
    st.markdown(
        f"""
        <div class='card'>
            <h2 style='margin:0'>{batting} {runs}/{wickets}</h2>
            <p class='small' style='margin:4px 0 0'>
                {display_over(balls)} ov • Target: {st.session_state.target or 'Not set'} •
                Session over: {session_over} • Last: {st.session_state.last or '—'}
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

with top[1]:
    mode = st.radio(
        "Mode",
        ["AUTO", "MANUAL"],
        index=0 if not st.session_state.manual else 1,
        horizontal=True,
        key="mode_selector"
    )
    st.session_state.manual = mode == "MANUAL"

st.subheader("Ball-by-Ball Update")

actions = [
    ("Dot", 0, False),
    ("1 Run", 1, False),
    ("2 Runs", 2, False),
    ("3 Runs", 3, False),
    ("4 Runs", 4, False),
    ("6 Runs", 6, False),
    ("Wicket", 0, True),
    ("Undo", None, False)
]

button_columns = st.columns(len(actions))

for index, (label, run_value, is_wicket) in enumerate(actions):
    with button_columns[index]:
        if st.button(label, use_container_width=True, key=f"ball_{index}"):

            if label == "Undo" and st.session_state.undo:
                (
                    st.session_state.runs,
                    st.session_state.wickets,
                    st.session_state.balls,
                    _
                ) = st.session_state.undo.pop()
                st.session_state.last = "Undo"

            elif label != "Undo":
                st.session_state.undo.append((
                    runs,
                    wickets,
                    balls,
                    st.session_state.last
                ))
                st.session_state.runs += int(run_value)
                st.session_state.wickets = min(
                    10,
                    wickets + int(is_wicket)
                )
                st.session_state.balls += 1
                st.session_state.last = label

            st.session_state.analysis = None
            st.rerun()

boxes = st.columns(2)

with boxes[0]:
    st.markdown(
        f"""
        <div class='session-box'>
            <h3>Session</h3>
            <h2>{int(st.session_state.low)}-{int(st.session_state.high)}</h2>
            <p class='small'>
                Expected: {float(st.session_state.expected):.1f} •
                Over: {session_over}
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

with boxes[1]:
    win_value = st.session_state.win
    win_text = f"{float(win_value):.1f}%" if win_value is not None else "—"
    win_label = f"{batting} Win"

    st.markdown(
        f"""
        <div class='win-box'>
            <h3>{win_label}</h3>
            <h2>{win_text}</h2>
            <p class='small'>
                Historical situations + current match state
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

manual_columns = st.columns(2)

with manual_columns[0]:
    manual_low = st.number_input(
        "Manual Session Low",
        0,
        400,
        int(st.session_state.low),
        1,
        key="manual_low"
    )

with manual_columns[1]:
    manual_high = st.number_input(
        "Manual Session High",
        0,
        400,
        int(st.session_state.high),
        1,
        key="manual_high"
    )

action_columns = st.columns(3)

with action_columns[0]:
    if st.button(
        "Apply Manual Session",
        use_container_width=True,
        key="apply_manual"
    ):
        st.session_state.manual = True
        st.session_state.low = int(manual_low)
        st.session_state.high = max(
            int(manual_low) + 1,
            int(manual_high)
        )
        st.session_state.analysis = None
        st.rerun()

with action_columns[1]:
    if st.button(
        "Use Auto Session",
        use_container_width=True,
        key="auto"
    ):
        st.session_state.manual = False
        st.session_state.analysis = None
        st.rerun()

with action_columns[2]:
    if st.button(
        "Analyze Current Situation",
        use_container_width=True,
        key="analyze"
    ):
        st.session_state.analysis = calculate_model(
            connection,
            league,
            innings_no,
            balls,
            runs,
            wickets,
            session_over,
            batting,
            bowling,
            int(st.session_state.target)
        )
        st.rerun()

if st.session_state.analysis is None:
    st.info(
        "AUTO mode me session aur winning har ball par update hoga. "
        "Manual line ke liye Apply Manual Session use karein."
    )
else:
    data = st.session_state.analysis
    session_yes = float(data["session_yes"])
    session_no = float(data["session_no"])
    session_label = "YES" if session_yes >= session_no else "NO"
    session_css = "yes" if session_label == "YES" else "no"

    st.subheader("VasuDev Result")

    st.markdown(
        f"""
        <div class='{session_css}'>
            <h1>SESSION {session_label} — {max(session_yes, session_no):.1f}%</h1>
            <p>
                Session line: <b>{int(st.session_state.low)}-{int(st.session_state.high)}</b>
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    win = data["win"]
    if win is not None:
        win_yes = float(win)
        win_no = 100 - win_yes
        win_side = batting if win_yes >= win_no else bowling
        win_css = "yes" if win_yes >= win_no else "no"

        st.markdown(
            f"""
            <div class='{win_css}'>
                <h1>{win_side.upper()} WIN — {max(win_yes, win_no):.1f}%</h1>
                <p>
                    {batting}: <b>{win_yes:.1f}%</b> •
                    {bowling}: <b>{win_no:.1f}%</b>
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.warning(
            "Winning estimate ke liye target set karein ya 1st innings ke liye "
            "historical batting-team outcome available hona chahiye."
        )

    st.caption(
        "Original historical-ball-state model. No random or artificial adjustment."
    )

    with st.expander("Model Details"):
        st.write(
            f"Expected session-end score: **{data['expected']:.1f}**"
        )
        st.write(
            f"Session YES: **{data['session_yes']:.1f}%** • "
            f"Session NO: **{data['session_no']:.1f}%**"
        )

        if data["win"] is not None:
            st.write(
                f"{batting} win probability: **{data['win']:.1f}%**"
            )

        st.write(
            "Every historical innings contributes only its closest matching state, "
            "so repeated balls from the same innings do not inflate the result."
        )
