import os
import hmac
import json
import math
import sqlite3
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import streamlit as st


st.set_page_config(
    page_title="VasuDev Cricket Historical Analytics",
    page_icon="🏏",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: linear-gradient(180deg, #061426, #081c35);
    color: #f8fafc;
}

.block-container {
    max-width: 1500px;
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
    border-radius: 16px;
    padding: 16px;
    margin: 8px 0;
}

.context-card {
    background: #102844;
    border: 1px solid #3d6690;
    border-radius: 14px;
    padding: 14px;
    text-align: center;
    min-height: 126px;
}

.small {
    color: #bed0e5 !important;
    font-size: 13px;
}

div.stButton > button {
    min-height: 40px;
    border-radius: 9px;
    font-weight: 700;
    background: #12365f;
    color: #ffffff;
    border: 1px solid #3c6795;
}

[data-testid="stHorizontalBlock"] {
    gap: 0.35rem !important;
}

[data-testid="stColumn"] {
    padding-left: 0 !important;
    padding-right: 0 !important;
}
</style>
""", unsafe_allow_html=True)


PASSWORD = os.environ.get("VASUDEV_PASSWORD", "").strip()

if not PASSWORD:
    st.error("Set VASUDEV_PASSWORD in Render Environment Variables.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🏏 VasuDev Cricket Historical Analytics")

    password = st.text_input(
        "Password",
        type="password",
        key="auth_password"
    )

    if st.button("Unlock", use_container_width=True):
        if hmac.compare_digest(password, PASSWORD):
            st.session_state.authenticated = True
            st.session_state.pop("auth_password", None)
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

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip",
}

LEAGUES = list(DATABASES.keys())


def parse_ball(value):
    try:
        over_text, ball_text = str(value).split(".", 1)
        over = int(over_text)
        ball = int(ball_text)

        if over < 0 or ball <= 0:
            return None

        return over * 6 + ball

    except Exception:
        return None


def display_over(balls):
    try:
        balls = int(balls)
    except Exception:
        return "0.0"

    if balls <= 0:
        return "0.0"

    over = (balls - 1) // 6
    ball = ((balls - 1) % 6) + 1

    return f"{over}.{ball}"


def canonical_venue(venue):
    value = (venue or "").strip().lower()
    value = " ".join(value.replace("-", " ").split())

    aliases = {
        "waca ground": "waca ground",
        "waca": "waca ground",
        "perth stadium": "perth stadium",
        "optus stadium": "perth stadium",
        "arun jaitley stadium": "arun jaitley stadium",
        "feroz shah kotla": "arun jaitley stadium",
        "engie stadium": "sydney showground stadium",
        "sydney showground stadium": "sydney showground stadium",
    }

    for alias, key in aliases.items():
        if alias in value:
            return key

    return value or "unknown"


def table_columns(connection, table_name):
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def create_indexes(connection):
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_deliveries_state
        ON deliveries(league, innings_no, ball_pos)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_deliveries_match
        ON deliveries(match_id, innings_no, ball_pos)
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_deliveries_team
        ON deliveries(
            league,
            innings_no,
            batting_team,
            bowling_team,
            ball_pos
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_matches_league
        ON matches(league)
    """)


def migrate_database(database_path):
    if not database_path.exists():
        return

    connection = sqlite3.connect(
        str(database_path),
        timeout=60
    )

    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "deliveries" not in tables or "matches" not in tables:
            return

        columns = table_columns(connection, "deliveries")

        if "ball_pos" not in columns:
            connection.execute("""
                ALTER TABLE deliveries
                ADD COLUMN ball_pos INTEGER
            """)

            rows = connection.execute("""
                SELECT id, ball_no
                FROM deliveries
                WHERE ball_pos IS NULL
            """).fetchall()

            updates = [
                (parse_ball(ball_no), row_id)
                for row_id, ball_no in rows
            ]

            if updates:
                connection.executemany("""
                    UPDATE deliveries
                    SET ball_pos=?
                    WHERE id=?
                """, updates)

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()


def build_database(database_path, league, archive_path):
    temp_path = database_path.with_suffix(".tmp")

    if temp_path.exists():
        temp_path.unlink()

    connection = sqlite3.connect(
        str(temp_path),
        timeout=120
    )

    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")

        connection.execute("""
            CREATE TABLE matches(
                match_id TEXT PRIMARY KEY,
                venue TEXT,
                winner TEXT,
                league TEXT
            )
        """)

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

        match_rows = []
        delivery_rows = []

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

                    winner = (
                        outcome.get("winner", "")
                        or outcome.get("eliminator", "")
                        or ""
                    )

                    match_id = Path(filename).stem
                    venue = str(info.get("venue", "") or "")

                    match_rows.append((
                        match_id,
                        venue,
                        str(winner),
                        league
                    ))

                    innings_list = data.get("innings", []) or []

                    for innings_no, innings in enumerate(
                        innings_list,
                        start=1
                    ):
                        if innings.get("super_over"):
                            continue

                        batting_team = str(
                            innings.get("team", "") or ""
                        )

                        bowling_team = next(
                            (
                                team
                                for team in teams
                                if team != batting_team
                            ),
                            ""
                        )

                        overs = innings.get("overs", []) or []

                        for over_data in overs:
                            over_no = int(
                                over_data.get("over", 0) or 0
                            )

                            deliveries = (
                                over_data.get("deliveries", []) or []
                            )

                            for delivery in deliveries:
                                actual_delivery = delivery.get(
                                    "actual_delivery"
                                )

                                if not actual_delivery:
                                    try:
                                        actual_delivery = (
                                            f"{over_no}."
                                            f"{int(delivery.get('ball'))}"
                                        )
                                    except Exception:
                                        continue

                                ball_pos = parse_ball(actual_delivery)

                                if ball_pos is None:
                                    continue

                                runs = int(
                                    (
                                        delivery.get("runs", {}) or {}
                                    ).get("total", 0) or 0
                                )

                                wickets = len(
                                    delivery.get("wickets", []) or []
                                )

                                delivery_rows.append((
                                    match_id,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    over_no,
                                    str(actual_delivery),
                                    ball_pos,
                                    runs,
                                    wickets,
                                    league
                                ))

                    if len(match_rows) >= 100:
                        connection.executemany("""
                            INSERT OR REPLACE INTO matches(
                                match_id,
                                venue,
                                winner,
                                league
                            )
                            VALUES(?,?,?,?)
                        """, match_rows)

                        match_rows.clear()

                    if len(delivery_rows) >= 5000:
                        connection.executemany("""
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
                        """, delivery_rows)

                        delivery_rows.clear()

                except Exception:
                    continue

        if match_rows:
            connection.executemany("""
                INSERT OR REPLACE INTO matches(
                    match_id,
                    venue,
                    winner,
                    league
                )
                VALUES(?,?,?,?)
            """, match_rows)

        if delivery_rows:
            connection.executemany("""
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
            """, delivery_rows)

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()

    temp_path.replace(database_path)


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

            urllib.request.urlretrieve(
                DOWNLOAD_URLS[league],
                archive_path
            )

            build_database(
                build_path,
                league,
                archive_path
            )

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
        timeout=60
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA cache_size=-12000")

    return connection


def get_values(connection, query, league):
    rows = connection.execute(query, (league,)).fetchall()

    return [
        row[0]
        for row in rows
        if row[0]
    ]


def build_innings_states(connection, league, innings_no):
    rows = connection.execute("""
        SELECT
            d.match_id,
            d.innings_no,
            d.ball_pos,
            d.runs,
            d.wickets,
            d.batting_team,
            d.bowling_team,
            d.league,
            m.venue
        FROM deliveries d
        JOIN matches m
            ON m.match_id=d.match_id
        WHERE d.league=?
          AND d.innings_no=?
        ORDER BY
            d.match_id,
            d.innings_no,
            d.ball_pos,
            d.id
    """, (
        league,
        innings_no
    )).fetchall()

    totals = defaultdict(int)
    wicket_totals = defaultdict(int)
    by_state = {}

    for row in rows:
        innings_key = (
            row["match_id"],
            int(row["innings_no"])
        )

        totals[innings_key] += int(row["runs"] or 0)
        wicket_totals[innings_key] += int(row["wickets"] or 0)

        state_key = (
            row["match_id"],
            int(row["innings_no"]),
            int(row["ball_pos"])
        )

        by_state[state_key] = {
            "match_id": row["match_id"],
            "innings_no": int(row["innings_no"]),
            "ball_pos": int(row["ball_pos"]),
            "runs": totals[innings_key],
            "wickets": wicket_totals[innings_key],
            "batting": row["batting_team"],
            "bowling": row["bowling_team"],
            "venue": canonical_venue(row["venue"]),
            "venue_raw": row["venue"] or "Unknown"
        }

    return list(by_state.values())


@st.cache_data(show_spinner=False)
def cached_states(database_path_text, league, innings_no):
    connection = get_connection(database_path_text)

    return build_innings_states(
        connection,
        league,
        innings_no
    )


def make_state_index(states):
    index = {}

    for state in states:
        index[(
            state["match_id"],
            state["innings_no"],
            state["ball_pos"]
        )] = state

    return index


def select_comparable_states(
    states,
    current_ball,
    current_runs,
    current_wickets,
    end_ball,
    batting_team=None,
    bowling_team=None,
    venue=None,
    run_tolerance=3,
    ball_tolerance=1,
    exact_wickets=True
):
    candidates = []

    for state in states:
        if state["ball_pos"] > end_ball:
            continue

        if abs(state["ball_pos"] - current_ball) > ball_tolerance:
            continue

        if abs(state["runs"] - current_runs) > run_tolerance:
            continue

        if exact_wickets:
            if state["wickets"] != current_wickets:
                continue
        else:
            if abs(state["wickets"] - current_wickets) > 1:
                continue

        if batting_team and state["batting"] != batting_team:
            continue

        if bowling_team and state["bowling"] != bowling_team:
            continue

        if venue and state["venue"] != venue:
            continue

        candidates.append(state)

    best_states = {}

    for item in candidates:
        key = (
            item["match_id"],
            item["innings_no"]
        )

        distance = (
            abs(item["ball_pos"] - current_ball) * 3
            + abs(item["runs"] - current_runs)
            + abs(item["wickets"] - current_wickets) * 8
        )

        candidate = dict(item)
        candidate["distance"] = distance

        if key not in best_states:
            best_states[key] = candidate

        elif candidate["distance"] < best_states[key]["distance"]:
            best_states[key] = candidate

    return list(best_states.values())


def endpoint_outcomes(states, state_lookup, end_ball):
    outcomes = []

    for state in states:
        match_id = state["match_id"]
        innings_no = state["innings_no"]

        endpoint = state_lookup.get((
            match_id,
            innings_no,
            end_ball
        ))

        if endpoint is None:
            available = [
                item
                for item in state_lookup.values()
                if item["match_id"] == match_id
                and item["innings_no"] == innings_no
                and item["ball_pos"] <= end_ball
            ]

            if not available:
                continue

            endpoint = max(
                available,
                key=lambda item: item["ball_pos"]
            )

        outcomes.append({
            "endpoint_runs": endpoint["runs"],
            "start_runs": state["runs"],
            "start_wickets": state["wickets"],
            "start_ball": state["ball_pos"]
        })

    return outcomes


def percentile(values, quantile):
    if not values:
        return None

    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile

    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return float(ordered[lower])

    return (
        ordered[lower]
        + (ordered[upper] - ordered[lower])
        * (position - lower)
    )


def summarize_outcomes(outcomes, benchmark):
    scores = [
        item["endpoint_runs"]
        for item in outcomes
    ]

    if not scores:
        return {
            "n": 0,
            "mean": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "above": 0,
            "below": 0,
            "above_rate": None,
            "scores": []
        }

    above = sum(
        score >= benchmark
        for score in scores
    )

    below = len(scores) - above

    return {
        "n": len(scores),
        "mean": sum(scores) / len(scores),
        "p10": percentile(scores, 0.10),
        "p25": percentile(scores, 0.25),
        "median": percentile(scores, 0.50),
        "p75": percentile(scores, 0.75),
        "p90": percentile(scores, 0.90),
        "above": above,
        "below": below,
        "above_rate": above / len(scores) * 100,
        "scores": scores
    }


def confidence_label(sample_size):
    if sample_size >= 100:
        return "High"

    if sample_size >= 35:
        return "Medium"

    if sample_size >= 10:
        return "Low"

    return "Very low"


def weighted_context(layers):
    base_weights = {
        "Matchup + venue": 0.35,
        "Matchup": 0.20,
        "Venue": 0.20,
        "Batting team": 0.15,
        "Bowling team": 0.10,
        "League baseline": 0.10
    }

    total_weight = 0.0
    weighted_mean = 0.0
    weighted_rate = 0.0

    for name, summary in layers.items():
        if not summary["n"]:
            continue

        reliability = min(summary["n"] / 50, 1.0)
        weight = base_weights.get(name, 0.10) * reliability

        total_weight += weight
        weighted_mean += summary["mean"] * weight
        weighted_rate += summary["above_rate"] * weight

    if total_weight <= 0:
        return None

    return {
        "mean": weighted_mean / total_weight,
        "rate": weighted_rate / total_weight
    }


DEFAULTS = {
    "runs": 16,
    "wickets": 1,
    "balls": 18,
    "last": "Starting state",
    "undo": []
}

for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


with st.sidebar:
    st.header("Historical Analysis Setup")

    league = st.selectbox(
        "League",
        LEAGUES,
        key="league_select"
    )

    try:
        database_path = ensure_database(league)

        connection = get_connection(
            str(database_path.resolve())
        )

    except Exception as error:
        st.error("Historical database could not be prepared.")
        st.exception(error)
        st.stop()

    teams = get_values(
        connection,
        """
        SELECT DISTINCT batting_team
        FROM deliveries
        WHERE league=?
          AND batting_team<>''
        ORDER BY batting_team
        """,
        league
    )

    if not teams:
        st.error("No teams found in database.")
        st.stop()

    batting_team = st.selectbox(
        "Batting team",
        teams,
        key="batting_team_select"
    )

    bowling_team = st.selectbox(
        "Bowling team",
        [
            team
            for team in teams
            if team != batting_team
        ],
        key="bowling_team_select"
    )

    innings_label = st.selectbox(
        "Innings",
        ["1st innings", "2nd innings"],
        key="innings_select"
    )

    innings_no = 1 if innings_label.startswith("1") else 2

    venues = get_values(
        connection,
        """
        SELECT DISTINCT venue
        FROM matches
        WHERE league=?
          AND venue<>''
        ORDER BY venue
        """,
        league
    )

    venue_choice = st.selectbox(
        "Exact ground",
        ["All grounds"] + venues,
        key="venue_select"
    )

    session_over = st.number_input(
        "Analysis end over",
        min_value=1,
        max_value=20,
        value=6,
        step=1,
        key="session_over_input"
    )

    benchmark = st.number_input(
        "Score benchmark at end over",
        min_value=0,
        max_value=400,
        value=35,
        step=1,
        key="benchmark_input"
    )

    st.caption(
        "This dashboard reports historical distributions and context."
    )

    st.divider()

    st.subheader("Current state")

    points = ["0.0"] + [
        f"{over}.{ball}"
        for over in range(20)
        for ball in range(1, 7)
    ]

    start_over = st.selectbox(
        "Over / ball",
        points,
        index=18,
        key="start_over_select"
    )

    start_runs = st.number_input(
        "Runs",
        min_value=0,
        max_value=400,
        value=int(st.session_state.runs),
        step=1,
        key="start_runs_input"
    )

    start_wickets = st.number_input(
        "Wickets",
        min_value=0,
        max_value=10,
        value=int(st.session_state.wickets),
        step=1,
        key="start_wickets_input"
    )

    if st.button(
        "Set state",
        use_container_width=True,
        key="set_state_button"
    ):
        st.session_state.runs = int(start_runs)
        st.session_state.wickets = int(start_wickets)
        st.session_state.balls = parse_ball(start_over) or 0
        st.session_state.undo = []
        st.session_state.last = "State set"
        st.rerun()


runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

end_ball = int(session_over) * 6

if venue_choice == "All grounds":
    selected_venue = None
else:
    selected_venue = canonical_venue(venue_choice)


left_header, right_header = st.columns([8, 2])

with left_header:
    st.markdown(
        f"""
        <div class="card">
            <h2 style="margin:0">
                {batting_team} {runs}/{wickets}
            </h2>
            <p class="small" style="margin:4px 0 0">
                {display_over(balls)} ov
                • vs {bowling_team}
                • {venue_choice}
                • Historical endpoint: {session_over}.0 ov
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

with right_header:
    required_runs = max(0, int(benchmark) - runs)
    remaining_balls = max(0, end_ball - balls)

    if remaining_balls > 0:
        required_rate = (
            required_runs / remaining_balls
        ) * 6
    else:
        required_rate = 0.0

    st.markdown(
        f"""
        <div class="context-card">
            <h4 style="margin:0">Benchmark context</h4>
            <h2 style="margin:8px 0">
                {benchmark} at {session_over}.0
            </h2>
            <p class="small" style="margin:0">
                Need: {required_runs} from {remaining_balls} balls<br>
                Required rate: {required_rate:.2f}
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )


st.subheader("Ball-by-ball state entry")

actions = [
    ("Dot", 0, False),
    ("1", 1, False),
    ("2", 2, False),
    ("3", 3, False),
    ("4", 4, False),
    ("6", 6, False),
    ("Wicket", 0, True),
    ("Undo", None, False)
]

button_columns = st.columns(8)

for index, (label, run_value, wicket_value) in enumerate(actions):
    with button_columns[index]:
        if st.button(
            label,
            use_container_width=True,
            key=f"action_{index}"
        ):
            if label == "Undo":
                if st.session_state.undo:
                    (
                        st.session_state.runs,
                        st.session_state.wickets,
                        st.session_state.balls,
                        st.session_state.last
                    ) = st.session_state.undo.pop()

            else:
                st.session_state.undo.append((
                    runs,
                    wickets,
                    balls,
                    st.session_state.last
                ))

                st.session_state.runs += int(run_value)
                st.session_state.wickets = min(
                    10,
                    wickets + int(wicket_value)
                )
                st.session_state.balls += 1
                st.session_state.last = label

            st.rerun()


if balls >= end_ball:
    st.warning(
        "Current ball selected analysis endpoint ke equal ya usse "
        "aage hai. Earlier state ya later endpoint select karein."
    )
    st.stop()


with st.spinner("Preparing comparable historical states..."):
    states = cached_states(
        str(database_path.resolve()),
        league,
        innings_no
    )

    state_lookup = make_state_index(states)

    layer_specs = {
        "Matchup + venue": {
            "batting": batting_team,
            "bowling": bowling_team,
            "venue": selected_venue
        },
        "Matchup": {
            "batting": batting_team,
            "bowling": bowling_team,
            "venue": None
        },
        "Venue": {
            "batting": None,
            "bowling": None,
            "venue": selected_venue
        },
        "Batting team": {
            "batting": batting_team,
            "bowling": None,
            "venue": None
        },
        "Bowling team": {
            "batting": None,
            "bowling": bowling_team,
            "venue": None
        },
        "League baseline": {
            "batting": None,
            "bowling": None,
            "venue": None
        }
    }

    layers = {}

    for layer_name, filters in layer_specs.items():
        if selected_venue is None and layer_name in [
            "Matchup + venue",
            "Venue"
        ]:
            layers[layer_name] = summarize_outcomes(
                [],
                int(benchmark)
            )
            continue

        comparable_states = select_comparable_states(
            states=states,
            current_ball=balls,
            current_runs=runs,
            current_wickets=wickets,
            end_ball=end_ball,
            batting_team=filters["batting"],
            bowling_team=filters["bowling"],
            venue=filters["venue"]
        )

        outcomes = endpoint_outcomes(
            comparable_states,
            state_lookup,
            end_ball
        )

        layers[layer_name] = summarize_outcomes(
            outcomes,
            int(benchmark)
        )

    blended = weighted_context(layers)


st.subheader("Historical score distribution")

main_layer = layers["Matchup + venue"]

if main_layer["n"] == 0:
    main_layer = layers["League baseline"]

if main_layer["n"] > 0:
    metric_columns = st.columns(5)

    metrics = [
        ("Comparable innings", main_layer["n"]),
        ("10th percentile", f"{main_layer['p10']:.0f}"),
        ("Median", f"{main_layer['median']:.0f}"),
        ("75th percentile", f"{main_layer['p75']:.0f}"),
        ("90th percentile", f"{main_layer['p90']:.0f}")
    ]

    for column, (label, value) in zip(metric_columns, metrics):
        column.metric(label, value)

else:
    st.info(
        "No comparable historical innings matched the selected state."
    )


st.subheader("Historical context layers")

table_rows = []

for layer_name, summary in layers.items():
    if summary["n"] > 0:
        table_rows.append({
            "Context": layer_name,
            "Comparable innings": summary["n"],
            f"At least {benchmark}": (
                f"{summary['above']} "
                f"({summary['above_rate']:.1f}%)"
            ),
            f"Below {benchmark}": summary["below"],
            "Average endpoint score": f"{summary['mean']:.1f}",
            "Median endpoint score": f"{summary['median']:.1f}",
            "Confidence": confidence_label(summary["n"])
        })

    else:
        table_rows.append({
            "Context": layer_name,
            "Comparable innings": 0,
            f"At least {benchmark}": "No matching data",
            f"Below {benchmark}": "—",
            "Average endpoint score": "—",
            "Median endpoint score": "—",
            "Confidence": "No data"
        })

st.dataframe(
    table_rows,
    use_container_width=True,
    hide_index=True
)


st.subheader("Blended historical context")

if blended:
    st.markdown(
        f"""
        <div class="card">
            <h3 style="margin-top:0">
                Context-weighted historical summary
            </h3>
            <p>
                Available
