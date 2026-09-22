import os
import hmac
import json
import sqlite3
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="VasuDev Cricket AI",
    page_icon="🐎",
    layout="wide"
)

PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

st.markdown("""
<style>
.stApp{
    background:linear-gradient(180deg,#061426,#081c35);
    color:#f8fafc
}
.block-container{
    max-width:1500px;
    padding-top:1.2rem!important
}
.card,.session-box{
    background:#0f223c;
    padding:16px;
    border-radius:16px;
    border:1px solid #2d4d72
}
.session-box{
    text-align:center;
    border:2px solid #4777a8;
    margin:14px 0
}
.yes{
    background:#07552f;
    border:2px solid #20c77a;
    padding:18px;
    border-radius:16px;
    text-align:center
}
.no{
    background:#651b1b;
    border:2px solid #ef5350;
    padding:18px;
    border-radius:16px;
    text-align:center
}
.small{
    color:#bed0e5!important;
    font-size:13px
}
h1,h2,h3,h4,p,label{
    color:#f8fafc!important
}
[data-testid="stSidebar"]{
    background:#071a2e
}
div.stButton>button{
    min-height:40px;
    border-radius:10px;
    font-weight:700;
    background:#12365f;
    color:#fff;
    border:1px solid #3c6795
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# AUTH
# ============================================================

if not st.session_state.authenticated:

    st.title("VasuDev Cricket AI")

    password = st.text_input(
        "Password",
        type="password",
        key="auth_password"
    )

    if st.button(
        "Unlock",
        use_container_width=True,
        key="unlock"
    ):
        if hmac.compare_digest(password, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("auth_password", None)
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

LEAGUES = list(DBS)


# ============================================================
# BALL PARSING
# ============================================================

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


def display_over(balls):
    balls = int(balls)

    if balls <= 0:
        return "0.0"

    return f"{(balls - 1)//6}.{((balls - 1)%6)+1}"


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
    """
    Permanently repair databases created by previous app versions.
    """

    if not path.exists():
        return

    connection = sqlite3.connect(
        str(path),
        timeout=60
    )

    try:

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        if "deliveries" not in tables:
            return

        columns = table_columns(
            connection,
            "deliveries"
        )

        if "ball_pos" not in columns:

            connection.execute(
                "ALTER TABLE deliveries ADD COLUMN ball_pos INTEGER"
            )

            rows = connection.execute(
                "SELECT id, ball_no FROM deliveries WHERE ball_pos IS NULL"
            ).fetchall()

            updates = [
                (parse_ball(ball_no), row_id)
                for row_id, ball_no in rows
            ]

            connection.executemany(
                "UPDATE deliveries SET ball_pos=? WHERE id=?",
                updates
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
        timeout=60
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA query_only=ON"
    )

    connection.execute(
        "PRAGMA cache_size=-8000"
    )

    return connection


# ============================================================
# DATABASE BUILDER
# ============================================================

def build_database(path, league, archive):

    temporary = path.with_suffix(".tmp")

    if temporary.exists():
        temporary.unlink()

    connection = sqlite3.connect(
        str(temporary)
    )

    try:

        connection.execute(
            "PRAGMA journal_mode=OFF"
        )

        connection.execute(
            "PRAGMA synchronous=OFF"
        )

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

        matches = []
        deliveries = []

        with zipfile.ZipFile(archive) as source:

            for filename in source.namelist():

                if not filename.endswith(".json"):
                    continue

                try:

                    data = json.loads(
                        source.read(filename)
                    )

                    info = data.get(
                        "info",
                        {}
                    )

                    teams = info.get(
                        "teams",
                        []
                    )

                    if len(teams) < 2:
                        continue

                    outcome = info.get(
                        "outcome",
                        {}
                    ) or {}

                    winner = (
                        outcome.get("winner", "")
                        or outcome.get("eliminator", "")
                        or ""
                    )

                    match_id = Path(
                        filename
                    ).stem

                    matches.append(
                        (
                            match_id,
                            str(
                                info.get(
                                    "venue",
                                    ""
                                ) or ""
                            ),
                            str(winner),
                            league
                        )
                    )

                    for innings_no, innings in enumerate(
                        data.get("innings", []),
                        1
                    ):

                        if innings.get("super_over"):
                            continue

                        batting = innings.get(
                            "team",
                            ""
                        )

                        bowling = next(
                            (
                                team
                                for team in teams
                                if team != batting
                            ),
                            ""
                        )

                        for over in innings.get(
                            "overs",
                            []
                        ):

                            over_no = int(
                                over.get(
                                    "over",
                                    0
                                )
                            )

                            for delivery in over.get(
                                "deliveries",
                                []
                            ):

                                value = delivery.get(
                                    "actual_delivery"
                                )

                                if not value:

                                    try:

                                        value = (
                                            f"{over_no}."
                                            f"{int(delivery.get('ball'))}"
                                        )

                                    except Exception:
                                        continue

                                position = parse_ball(
                                    value
                                )

                                if position is None:
                                    continue

                                runs = int(
                                    (
                                        delivery.get(
                                            "runs"
                                        ) or {}
                                    ).get(
                                        "total",
                                        0
                                    ) or 0
                                )

                                wickets = len(
                                    delivery.get(
                                        "wickets"
                                    ) or []
                                )

                                deliveries.append(
                                    (
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
                                    )
                                )

                    if len(matches) >= 100:

                        connection.executemany(
                            """
                            INSERT OR REPLACE INTO matches
                            VALUES(?,?,?,?)
                            """,
                            matches
                        )

                        matches.clear()

                    if len(deliveries) >= 5000:

                        connection.executemany(
                            """
                            INSERT INTO deliveries(
                                match_id,
                                innings_no,
                                batting_team,
                                bowling_team,
                                over_no,
                                ball_no,
                                ball_pos,
                                runs,
                                wickets,
                                league
                            )
                            VALUES(?,?,?,?,?,?,?,?,?,?)
                            """,
                            deliveries
                        )

                        deliveries.clear()

                except Exception:
                    continue

        if matches:

            connection.executemany(
                """
                INSERT OR REPLACE INTO matches
                VALUES(?,?,?,?)
                """,
                matches
            )

        if deliveries:

            connection.executemany(
                """
                INSERT INTO deliveries(
                    match_id,
                    innings_no,
                    batting_team,
                    bowling_team,
                    over_no,
                    ball_no,
                    ball_pos,
                    runs,
                    wickets,
                    league
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                deliveries
            )

        connection.execute(
            """
            CREATE INDEX idx_deliveries_state
            ON deliveries(league, innings_no, ball_pos)
            """
        )

        connection.execute(
            """
            CREATE INDEX idx_deliveries_match
            ON deliveries(match_id, innings_no, ball_pos)
            """
        )

        connection.commit()

    finally:
        connection.close()

    temporary.replace(path)


# ============================================================
# ENSURE DATABASE
# ============================================================

def ensure_database(league):

    path = DBS[league]

    if path.exists():

        migrate_database(path)

        return path

    if league == "IPL":
        return path

    building = path.with_suffix(
        ".building"
    )

    try:

        with tempfile.TemporaryDirectory() as directory:

            archive = Path(
                directory
            ) / "matches.zip"

            urllib.request.urlretrieve(
                URLS[league],
                archive
            )

            build_database(
                building,
                league,
                archive
            )

        building.replace(path)

        return path

    except Exception:

        if building.exists():
            building.unlink()

        raise


# ============================================================
# VALUES HELPER
# ============================================================

def values(connection, sql, league):
    return [
        row[0]
        for row in connection.execute(
            sql,
            (league,)
        ).fetchall()
        if row[0]
    ]


# ============================================================
# SCORE
# ============================================================

def score_at(
    connection,
    match_id,
    innings_no,
    end_ball
):

    row = connection.execute(
        """
        SELECT
            COALESCE(SUM(runs),0),
            COALESCE(SUM(wickets),0)
        FROM deliveries
        WHERE match_id=?
        AND innings_no=?
        AND ball_pos<=?
        """,
        (
            match_id,
            innings_no,
            end_ball
        )
    ).fetchone()

    return (
        int(row[0] or 0),
        int(row[1] or 0)
    )


# ============================================================
# SIMILAR HISTORICAL MATCHES
# ============================================================

def similar_matches(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    end_ball
):

    rows = connection.execute(
        """
        SELECT DISTINCT
            match_id,
            innings_no,
            ball_pos
        FROM deliveries
        WHERE league=?
        AND innings_no=?
        AND ball_pos BETWEEN ? AND ?
        AND ball_pos<=?
        LIMIT 2500
        """,
        (
            league,
            innings_no,
            max(1, current_ball - 2),
            current_ball + 2,
            end_ball
        )
    ).fetchall()

    result = []

    for row in rows:

        score, wickets = score_at(
            connection,
            row["match_id"],
            row["innings_no"],
            row["ball_pos"]
        )

        if (
            abs(score - current_runs) <= 30
            and
            abs(wickets - current_wickets) <= 3
        ):

            weight = (
                1
                /
                (
                    1
                    + abs(score - current_runs)
                )
                /
                (
                    1
                    + abs(wickets - current_wickets)
                )
                /
                (
                    1
                    + abs(
                        row["ball_pos"]
                        - current_ball
                    )
                )
            )

            result.append(
                (
                    row["match_id"],
                    int(row["innings_no"]),
                    weight
                )
            )

    result.sort(
        key=lambda item: item[2],
        reverse=True
    )

    return result[:800]


# ============================================================
# SESSION CALCULATION
# ============================================================

def calculate_line(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over
):

    end_ball = int(session_over) * 6

    if current_ball >= end_ball:

        return (
            current_runs,
            current_runs + 1,
            float(current_runs),
            0
        )

    matches = similar_matches(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        end_ball
    )

    if not matches:

        return (
            current_runs,
            current_runs + 1,
            float(current_runs),
            0
        )

    scores = []
    weights = []

    for match_id, inn, weight in matches:

        scores.append(
            score_at(
                connection,
                match_id,
                inn,
                end_ball
            )[0]
        )

        weights.append(weight)

    expected = (
        sum(
            score * weight
            for score, weight
            in zip(scores, weights)
        )
        /
        sum(weights)
    )

    low = max(
        current_runs,
        int(round(expected))
    )

    return (
        low,
        low + 1,
        expected,
        len(scores)
    )


# ============================================================
# RESULT CALCULATION
# ============================================================

def calculate_result(
    connection,
    league,
    innings_no,
    current_ball,
    current_runs,
    current_wickets,
    session_over,
    threshold
):

    end_ball = int(session_over) * 6

    matches = similar_matches(
        connection,
        league,
        innings_no,
        current_ball,
        current_runs,
        current_wickets,
        end_ball
    )

    if not matches:
        return None

    scores = [
        score_at(
            connection,
            match_id,
            inn,
            end_ball
        )[0]
        for match_id, inn, _
        in matches
    ]

    yes = (
        sum(
            score >= threshold
            for score in scores
        )
        /
        len(scores)
        *
        100
    )

    ordered = sorted(scores)

    return {
        "yes": yes,
        "no": 100 - yes,
        "samples": len(scores),
        "expected": sum(scores) / len(scores),
        "low": ordered[
            max(
                0,
                int(len(ordered) * 0.1) - 1
            )
        ],
        "high": ordered[
            max(
                0,
                int(len(ordered) * 0.9) - 1
            )
        ]
    }


# ============================================================
# SESSION STATE
# ============================================================

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
    "manual": False,
    "analysis": None
}.items():

    st.session_state.setdefault(
        key,
        value
    )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    league = st.selectbox(
        "League",
        LEAGUES,
        key="league_choice"
    )

    try:

        database_path = ensure_database(
            league
        )

        connection = readonly(
            database_path
        )

    except Exception as error:

        st.error(
            f"Historical database could not be prepared: {error}"
        )

        st.stop()

    # FIXED:
    # league argument is passed correctly.

    teams = values(
        connection,
        """
        SELECT DISTINCT batting_team
        FROM deliveries
        WHERE league=?
        ORDER BY batting_team
        """,
        league
    )

    # FIXED:
    # Previously league argument was missing here.

    venues = values(
        connection,
        """
        SELECT DISTINCT venue
        FROM matches
        WHERE league=?
        AND venue<>''
        ORDER BY venue
        """,
        league
    ) or ["Unknown"]

    if not teams:

        st.error(
            "No teams found in database."
        )

        st.stop()

    batting = st.selectbox(
        "Batting Team",
        teams,
        key="batting_team"
    )

    bowling = st.selectbox(
        "Bowling Team",
        [
            x
            for x in teams
            if x != batting
        ],
        key="bowling_team"
    )

    venue = st.selectbox(
        "Ground",
        venues,
        key="ground"
    )

    innings_label = st.selectbox(
        "Innings",
        [
            "1st Innings",
            "2nd Innings"
        ],
        key="innings"
    )

    innings_no = (
        1
        if innings_label.startswith("1")
        else 2
    )

    session_over = st.number_input(
        "Session Over",
        1,
        20,
        int(
            st.session_state.session_over
        ),
        1,
        key="session_over_input"
    )

    target = st.number_input(
        "Target Runs",
        0,
        400,
        int(
            st.session_state.target
        ),
        1,
        key="target_input"
    )

    st.session_state.session_over = int(
        session_over
    )

    st.session_state.target = int(
        target
    )

    points = (
        ["0.0"]
        +
        [
            f"{o}.{b}"
            for o in range(20)
            for b in range(1, 7)
        ]
    )

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

        st.session_state.runs = int(
            start_runs
        )

        st.session_state.wickets = int(
            start_wickets
        )

        st.session_state.balls = (
            parse_ball(start_over)
            or 0
        )

        st.session_state.undo = []

        st.session_state.last = (
            "Starting situation set"
        )

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


# ============================================================
# CURRENT STATE
# ============================================================

runs = int(
    st.session_state.runs
)

wickets = int(
    st.session_state.wickets
)

balls = int(
    st.session_state.balls
)


low, high, expected, samples = calculate_line(
    connection,
    league,
    innings_no,
    balls,
    runs,
    wickets,
    session_over
)

if not st.session_state.manual:

    st.session_state.low = low
    st.session_state.high = high
    st.session_state.expected = expected


# ============================================================
# LIVE SCORE
# ============================================================

st.markdown(
    f"""
    <div class='card'>
        <h3>Current Live Score</h3>
        <h2>{runs}/{wickets}</h2>
        <p class='small'>
            Over/Ball: {display_over(balls)}
            • Target: {target or 'Not set'}
            • Session over: {session_over}
            • Last: {st.session_state.last or '—'}
        </p>
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# BALL BY BALL
# ============================================================

st.subheader(
    "Ball-by-Ball Update"
)

buttons = [
    ("Dot", 0, False),
    ("1 Run", 1, False),
    ("2 Runs", 2, False),
    ("3 Runs", 3, False),
    ("4 Runs", 4, False),
    ("6 Runs", 6, False),
    ("Wicket", 0, True),
    ("Undo", None, False)
]

for index, (
    label,
    run_value,
    wicket
) in enumerate(buttons):

    with st.columns(4)[index % 4]:

        if st.button(
            label,
            use_container_width=True,
            key=f"ball_{index}"
        ):

            if (
                label == "Undo"
                and st.session_state.undo
            ):

                (
                    st.session_state.runs,
                    st.session_state.wickets,
                    st.session_state.balls,
                    _
                ) = st.session_state.undo.pop()

                st.session_state.last = "Undo"

            elif label != "Undo":

                st.session_state.undo.append(
                    (
                        runs,
                        wickets,
                        balls,
                        st.session_state.last
                    )
                )

                st.session_state.runs += int(
                    run_value
                )

                st.session_state.wickets = min(
                    10,
                    wickets + int(wicket)
                )

                st.session_state.balls += 1

                st.session_state.last = label

            st.session_state.analysis = None

            st.rerun()


# ============================================================
# MATCH DETAIL
# ============================================================

st.subheader(
    "Match Detail"
)

detail = st.columns(4)

detail[0].metric(
    "Batting",
    batting
)

detail[1].metric(
    "Bowling",
    bowling
)

detail[2].metric(
    "Ground",
    venue
)

detail[3].metric(
    "Innings",
    innings_label
)


# ============================================================
# SESSION
# ============================================================

st.markdown(
    f"""
    <div class='session-box'>
        <h3>Session</h3>
        <h2>
            {int(st.session_state.low)}
            -
            {int(st.session_state.high)}
        </h2>
        <p class='small'>
            Expected:
            {float(st.session_state.expected):.1f}
            • Over:
            {session_over}
            • Target:
            {target or 'Not set'}
            • Samples:
            {samples}
        </p>
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# MANUAL SESSION
# ============================================================

manual = st.columns(2)

with manual[0]:

    manual_low = st.number_input(
        "Manual Session Low",
        0,
        400,
        int(st.session_state.low),
        1,
        key="manual_low"
    )

with manual[1]:

    manual_high = st.number_input(
        "Manual Session High",
        0,
        400,
        int(st.session_state.high),
        1,
        key="manual_high"
    )


a, b = st.columns(2)

with a:

    if st.button(
        "Apply Manual Session",
        use_container_width=True,
        key="apply_manual"
    ):

        st.session_state.manual = True

        st.session_state.low = int(
            manual_low
        )

        st.session_state.high = max(
            int(manual_low) + 1,
            int(manual_high)
        )

        st.session_state.analysis = None

        st.rerun()


with b:

    if st.button(
        "Use Auto Session",
        use_container_width=True,
        key="auto"
    ):

        st.session_state.manual = False
        st.session_state.analysis = None

        st.rerun()


# ============================================================
# ANALYZE
# ============================================================

if st.button(
    "Analyze Current Situation",
    use_container_width=True,
    key="analyze"
):

    st.session_state.analysis = calculate_result(
        connection,
        league,
        innings_no,
        balls,
        runs,
        wickets,
        session_over,
        int(st.session_state.high)
    )

    st.rerun()


# ============================================================
# RESULT
# ============================================================

if st.session_state.analysis is None:

    st.info(
        "Enter the match situation and press Analyze Current Situation."
    )

else:

    data = st.session_state.analysis

    yes = float(
        data["yes"]
    )

    no = float(
        data["no"]
    )

    label = (
        "YES"
        if yes >= no
        else "NO"
    )

    css = (
        "yes"
        if label == "YES"
        else "no"
    )

    st.subheader(
        "VasuDev Result"
    )

    st.markdown(
        f"""
        <div class='{css}'>
            <h1>
                {label} — {max(yes, no):.1f}%
            </h1>

            <p>
                Session line:
                <b>
                    {int(st.session_state.low)}
                    -
                    {int(st.session_state.high)}
                </b>
                •
                {data['samples']}
                similar states
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.caption(
        "Historical estimate only; it is not a guarantee."
    )

    with st.expander(
        "Details"
    ):

        st.write(
            f"Expected score: **{data['expected']:.1f}**"
        )

        st.write(
            f"Historical range: **{int(data['low'])}–{int(data['high'])}**"
        )

        st.write(
            f"YES: **{yes:.1f}%** • NO: **{no:.1f}%**"
        )
