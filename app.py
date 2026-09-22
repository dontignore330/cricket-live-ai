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

st.markdown(
    """
    <style>
    .stApp { background: #07192d; color: #f8fafc; }
    .block-container { max-width: 1450px; padding-top: 1rem !important; }
    [data-testid="stSidebar"] { background: #061426; }
    h1,h2,h3,h4,p,label,span { color: #f8fafc !important; }
    .box {
        background: #0f2946;
        border: 1px solid #315b86;
        border-radius: 14px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .small { color: #b9cce2 !important; font-size: 13px; }
    div.stButton > button {
        min-height: 38px;
        border-radius: 8px;
        background: #123d68;
        color: white;
        border: 1px solid #4f7eae;
        font-weight: 700;
    }
    [data-testid="stHorizontalBlock"] { gap: 0.25rem !important; }
    </style>
    """,
    unsafe_allow_html=True
)


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
        type="password"
    )

    if st.button("Unlock", use_container_width=True):
        if hmac.compare_digest(password, PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.stop()


BASE = Path(".")

DATABASES = {
    "IPL": BASE / "cricket_history.db",
    "Men's Big Bash League": BASE / "bbl_history.db",
    "Women's Big Bash League": BASE / "wbbl_history.db"
}

DOWNLOAD_URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "Men's Big Bash League": "https://cricsheet.org/downloads/bbl_json.zip",
    "Women's Big Bash League": "https://cricsheet.org/downloads/wbb_json.zip"
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


def display_over(total_balls):
    try:
        total_balls = int(total_balls)
    except Exception:
        return "0.0"

    if total_balls <= 0:
        return "0.0"

    over = (total_balls - 1) // 6
    ball = ((total_balls - 1) % 6) + 1

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
        "sydney showground stadium": "sydney showground stadium"
    }

    for source, target in aliases.items():
        if source in value:
            return target

    return value or "unknown"


def table_columns(connection, table_name):
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def create_indexes(connection):
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_deliveries_state "
        "ON deliveries(league, innings_no, ball_pos)"
    )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_deliveries_match "
        "ON deliveries(match_id, innings_no, ball_pos)"
    )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_matches_league "
        "ON matches(league)"
    )


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

        if "deliveries" not in tables:
            return

        columns = table_columns(connection, "deliveries")

        if "ball_pos" not in columns:
            connection.execute(
                "ALTER TABLE deliveries ADD COLUMN ball_pos INTEGER"
            )

            rows = connection.execute(
                "SELECT id, ball_no FROM deliveries"
            ).fetchall()

            updates = [
                (parse_ball(ball_no), row_id)
                for row_id, ball_no in rows
            ]

            connection.executemany(
                "UPDATE deliveries SET ball_pos=? WHERE id=?",
                updates
            )

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()


def build_database(database_path, league, archive_path):
    temporary_path = database_path.with_suffix(".tmp")

    if temporary_path.exists():
        temporary_path.unlink()

    connection = sqlite3.connect(
        str(temporary_path),
        timeout=120
    )

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

        connection.execute(
            "CREATE TABLE deliveries("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "match_id TEXT,"
            "innings_no INTEGER,"
            "batting_team TEXT,"
            "bowling_team TEXT,"
            "over_no INTEGER,"
            "ball_no TEXT,"
            "ball_pos INTEGER,"
            "runs INTEGER,"
            "wickets INTEGER,"
            "league TEXT)"
        )

        match_rows = []
        delivery_rows = []

        with zipfile.ZipFile(archive_path) as archive:
            for filename in archive.namelist():
                if not filename.endswith(".json"):
                    continue

                try:
                    data = json.loads(archive.read(filename))
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

                    match_rows.append((
                        match_id,
                        str(info.get("venue", "") or ""),
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

                        for over_data in innings.get("overs", []) or []:
                            over_no = int(
                                over_data.get("over", 0) or 0
                            )

                            for delivery in (
                                over_data.get("deliveries", []) or []
                            ):
                                ball_value = delivery.get(
                                    "actual_delivery"
                                )

                                if not ball_value:
                                    try:
                                        ball_value = (
                                            f"{over_no}."
                                            f"{int(delivery.get('ball'))}"
                                        )
                                    except Exception:
                                        continue

                                ball_pos = parse_ball(ball_value)

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
                                    str(ball_value),
                                    ball_pos,
                                    runs,
                                    wickets,
                                    league
                                ))

                    if len(match_rows) >= 100:
                        connection.executemany(
                            "INSERT OR REPLACE INTO matches "
                            "VALUES(?,?,?,?)",
                            match_rows
                        )
                        match_rows.clear()

                    if len(delivery_rows) >= 5000:
                        connection.executemany(
                            "INSERT INTO deliveries("
                            "match_id, innings_no, batting_team, "
                            "bowling_team, over_no, ball_no, ball_pos, "
                            "runs, wickets, league"
                            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                            delivery_rows
                        )
                        delivery_rows.clear()

                except Exception:
                    continue

        if match_rows:
            connection.executemany(
                "INSERT OR REPLACE INTO matches VALUES(?,?,?,?)",
                match_rows
            )

        if delivery_rows:
            connection.executemany(
                "INSERT INTO deliveries("
                "match_id, innings_no, batting_team, bowling_team, "
                "over_no, ball_no, ball_pos, runs, wickets, league"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                delivery_rows
            )

        create_indexes(connection)
        connection.commit()

    finally:
        connection.close()

    temporary_path.replace(database_path)


def ensure_database(league):
    database_path = DATABASES[league]

    if database_path.exists():
        migrate_database(database_path)
        return database_path

    building_path = database_path.with_suffix(".building")

    try:
        with tempfile.TemporaryDirectory() as temp_directory:
            archive_path = Path(temp_directory) / "matches.zip"

            urllib.request.urlretrieve(
                DOWNLOAD_URLS[league],
                archive_path
            )

            build_database(
                building_path,
                league,
                archive_path
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
        timeout=60
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")

    return connection


def get_values(connection, query, league):
    return [
        row[0]
        for row in connection.execute(
            query,
            (league,)
        ).fetchall()
        if row[0]
    ]


def get_all_states(connection, league, innings_no):
    rows = connection.execute(
        """
        SELECT
            d.match_id,
            d.innings_no,
            d.ball_pos,
            d.runs,
            d.wickets,
            d.batting_team,
            d.bowling_team,
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
        """,
        (league, innings_no)
    ).fetchall()

    total_runs = defaultdict(int)
    total_wickets = defaultdict(int)
    states_by_ball = {}

    for row in rows:
        innings_key = (
            row["match_id"],
            int(row["innings_no"])
        )

        total_runs[innings_key] += int(row["runs"] or 0)
        total_wickets[innings_key] += int(row["wickets"] or 0)

        state_key = (
            row["match_id"],
            int(row["innings_no"]),
            int(row["ball_pos"])
        )

        states_by_ball[state_key] = {
            "match_id": row["match_id"],
            "innings_no": int(row["innings_no"]),
            "ball_pos": int(row["ball_pos"]),
            "runs": total_runs[innings_key],
            "wickets": total_wickets[innings_key],
            "batting_team": row["batting_team"],
            "bowling_team": row["bowling_team"],
            "venue": canonical_venue(row["venue"])
        }

    return list(states_by_ball.values())


@st.cache_data(show_spinner=False)
def cached_states(database_path_text, league, innings_no):
    connection = get_connection(database_path_text)

    return get_all_states(
        connection,
        league,
        innings_no
    )


def make_lookup(states):
    return {
        (
            item["match_id"],
            item["innings_no"],
            item["ball_pos"]
        ): item
        for item in states
    }


def comparable_states(
    states,
    current_ball,
    current_runs,
    current_wickets,
    end_ball,
    batting_team=None,
    bowling_team=None,
    venue=None
):
    possible = []

    for item in states:
        if item["ball_pos"] > end_ball:
            continue

        if abs(item["ball_pos"] - current_ball) > 1:
            continue

        if abs(item["runs"] - current_runs) > 3:
            continue

        if item["wickets"] != current_wickets:
            continue

        if batting_team and item["batting_team"] != batting_team:
            continue

        if bowling_team and item["bowling_team"] != bowling_team:
            continue

        if venue and item["venue"] != venue:
            continue

        possible.append(item)

    best_per_innings = {}

    for item in possible:
        key = (
            item["match_id"],
            item["innings_no"]
        )

        distance = (
            abs(item["ball_pos"] - current_ball) * 3
            + abs(item["runs"] - current_runs)
        )

        candidate = dict(item)
        candidate["distance"] = distance

        if key not in best_per_innings:
            best_per_innings[key] = candidate

        elif candidate["distance"] < best_per_innings[key]["distance"]:
            best_per_innings[key] = candidate

    return list(best_per_innings.values())


def get_endpoint_scores(states, lookup, end_ball):
    scores = []

    for item in states:
        exact_key = (
            item["match_id"],
            item["innings_no"],
            end_ball
        )

        endpoint = lookup.get(exact_key)

        if endpoint is None:
            options = [
                row
                for row in lookup.values()
                if row["match_id"] == item["match_id"]
                and row["innings_no"] == item["innings_no"]
                and row["ball_pos"] <= end_ball
            ]

            if not options:
                continue

            endpoint = max(
                options,
                key=lambda row: row["ball_pos"]
            )

        scores.append(endpoint["runs"])

    return scores


def percentile(values, quantile):
    if not values:
        return None

    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile

    low = math.floor(position)
    high = math.ceil(position)

    if low == high:
        return float(ordered[low])

    return (
        ordered[low]
        + (ordered[high] - ordered[low])
        * (position - low)
    )


def make_summary(scores, benchmark):
    if not scores:
        return {
            "count": 0,
            "mean": None,
            "p10": None,
            "median": None,
            "p75": None,
            "p90": None,
            "at_least": 0,
            "below": 0,
            "rate": None
        }

    at_least = sum(
        score >= benchmark
        for score in scores
    )

    return {
        "count": len(scores),
        "mean": sum(scores) / len(scores),
        "p10": percentile(scores, 0.10),
        "median": percentile(scores, 0.50),
        "p75": percentile(scores, 0.75),
        "p90": percentile(scores, 0.90),
        "at_least": at_least,
        "below": len(scores) - at_least,
        "rate": at_least / len(scores) * 100
    }


def confidence(sample_count):
    if sample_count >= 100:
        return "High"

    if sample_count >= 35:
        return "Medium"

    if sample_count >= 10:
        return "Low"

    return "Very low"


def calculate_blend(summaries):
    base_weights = {
        "Matchup + venue": 0.35,
        "Matchup": 0.20,
        "Venue": 0.20,
        "Batting team": 0.15,
        "Bowling team": 0.10,
        "League baseline": 0.10
    }

    total_weight = 0.0
    score_sum = 0.0
    rate_sum = 0.0

    for name, summary in summaries.items():
        if summary["count"] == 0:
            continue

        reliability = min(
            summary["count"] / 50,
            1.0
        )

        weight = base_weights[name] * reliability

        total_weight += weight
        score_sum += summary["mean"] * weight
        rate_sum += summary["rate"] * weight

    if total_weight == 0:
        return None

    return {
        "mean": score_sum / total_weight,
        "rate": rate_sum / total_weight
    }


for key, value in {
    "runs": 16,
    "wickets": 1,
    "balls": 18,
    "last": "Starting state",
    "undo": []
}.items():
    st.session_state.setdefault(key, value)


with st.sidebar:
    st.header("Historical Analysis Setup")

    league = st.selectbox(
        "League",
        LEAGUES
    )

    try:
        db_path = ensure_database(league)
        connection = get_connection(
            str(db_path.resolve())
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
        st.error("No teams available in the database.")
        st.stop()

    batting_team = st.selectbox(
        "Batting team",
        teams
    )

    bowling_team = st.selectbox(
        "Bowling team",
        [
            team
            for team in teams
            if team != batting_team
        ]
    )

    innings_label = st.selectbox(
        "Innings",
        [
            "1st innings",
            "2nd innings"
        ]
    )

    innings_no = (
        1
        if innings_label == "1st innings"
        else 2
    )

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
        ["All grounds"] + venues
    )

    endpoint_over = st.number_input(
        "Analysis end over",
        min_value=1,
        max_value=20,
        value=6,
        step=1
    )

    benchmark = st.number_input(
        "Score benchmark at end over",
        min_value=0,
        max_value=400,
        value=35,
        step=1
    )

    st.divider()
    st.subheader("Current state")

    points = ["0.0"] + [
        f"{over}.{ball}"
        for over in range(20)
        for ball in range(1, 7)
    ]

    selected_ball = st.selectbox(
        "Over / ball",
        points,
        index=18
    )

    entered_runs = st.number_input(
        "Runs",
        min_value=0,
        max_value=400,
        value=int(st.session_state.runs),
        step=1
    )

    entered_wickets = st.number_input(
        "Wickets",
        min_value=0,
        max_value=10,
        value=int(st.session_state.wickets),
        step=1
    )

    if st.button("Set state", use_container_width=True):
        st.session_state.runs = int(entered_runs)
        st.session_state.wickets = int(entered_wickets)
        st.session_state.balls = parse_ball(selected_ball) or 0
        st.session_state.undo = []
        st.session_state.last = "State set"
        st.rerun()


runs = int(st.session_state.runs)
wickets = int(st.session_state.wickets)
balls = int(st.session_state.balls)

end_ball = int(endpoint_over) * 6

selected_venue = (
    None
    if venue_choice == "All grounds"
    else canonical_venue(venue_choice)
)

left, right = st.columns([8, 2])

with left:
    score_html = (
        "<div class='box'>"
        "<h2 style='margin:0'>"
        + batting_team
        + " "
        + str(runs)
        + "/"
        + str(wickets)
        + "</h2>"
        "<p class='small' style='margin:4px 0 0'>"
        + display_over(balls)
        + " ov • vs "
        + bowling_team
        + " • "
        + venue_choice
        + " • Endpoint: "
        + str(endpoint_over)
        + ".0 ov"
        + "</p>"
        "</div>"
    )

    st.markdown(
        score_html,
        unsafe_allow_html=True
    )

with right:
    needed_runs = max(
        0,
        int(benchmark) - runs
    )

    remaining_balls = max(
        0,
        end_ball - balls
    )

    if remaining_balls > 0:
        required_rate = (
            needed_runs / remaining_balls
        ) * 6
    else:
        required_rate = 0.0

    benchmark_html = (
        "<div class='box'>"
        "<h4 style='margin:0'>Benchmark</h4>"
        "<h2 style='margin:8px 0'>"
        + str(benchmark)
        + " at "
        + str(endpoint_over)
        + ".0"
        + "</h2>"
        "<p class='small' style='margin:0'>Need: "
        + str(needed_runs)
        + " from "
        + str(remaining_balls)
        + " balls<br>Required rate: "
        + format(required_rate, ".2f")
        + "</p>"
        "</div>"
    )

    st.markdown(
        benchmark_html,
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

action_columns = st.columns(8)

for index, action in enumerate(actions):
    label, add_runs, add_wicket = action

    with action_columns[index]:
        if st.button(
            label,
            use_container_width=True,
            key="live_action_" + str(index)
        ):
            if label == "Undo":
                if st.session_state.undo:
                    previous = st.session_state.undo.pop()

                    st.session_state.runs = previous[0]
                    st.session_state.wickets = previous[1]
                    st.session_state.balls = previous[2]
                    st.session_state.last = previous[3]

            else:
                st.session_state.undo.append((
                    runs,
                    wickets,
                    balls,
                    st.session_state.last
                ))

                st.session_state.runs = (
                    runs + int(add_runs)
                )

                st.session_state.wickets = min(
                    10,
                    wickets + int(add_wicket)
                )

                st.session_state.balls = balls + 1
                st.session_state.last = label

            st.rerun()


if balls >= end_ball:
    st.warning(
        "Current ball analysis endpoint ke equal ya usse aage hai. "
        "Earlier score state ya later endpoint select karein."
    )
    st.stop()


with st.spinner("Preparing historical comparisons..."):
    states = cached_states(
        str(db_path.resolve()),
        league,
        innings_no
    )

    lookup = make_lookup(states)

    filters = {
        "Matchup + venue": (
            batting_team,
            bowling_team,
            selected_venue
        ),
        "Matchup": (
            batting_team,
            bowling_team,
            None
        ),
        "Venue": (
            None,
            None,
            selected_venue
        ),
        "Batting team": (
            batting_team,
            None,
            None
        ),
        "Bowling team": (
            None,
            bowling_team,
            None
        ),
        "League baseline": (
            None,
            None,
            None
        )
    }

    summaries = {}

    for context_name, context_filter in filters.items():
        filter_batting = context_filter[0]
        filter_bowling = context_filter[1]
        filter_venue = context_filter[2]

        if (
            selected_venue is None
            and context_name in [
                "Matchup + venue",
                "Venue"
            ]
        ):
            summaries[context_name] = make_summary(
                [],
                int(benchmark)
            )
            continue

        matched_states = comparable_states(
            states,
            balls,
            runs,
            wickets,
            end_ball,
            batting_team=filter_batting,
            bowling_team=filter_bowling,
            venue=filter_venue
        )

        scores = get_endpoint_scores(
            matched_states,
            lookup,
            end_ball
        )

        summaries[context_name] = make_summary(
            scores,
            int(benchmark)
        )

    blend = calculate_blend(summaries)


st.subheader("Historical endpoint distribution")

primary = summaries["Matchup + venue"]

if primary["count"] == 0:
    primary = summaries["League baseline"]

if primary["count"] > 0:
    metric_columns = st.columns(5)

    metric_columns[0].metric(
        "Comparable innings",
        primary["count"]
    )

    metric_columns[1].metric(
        "10th percentile",
        str(round(primary["p10"]))
    )

    metric_columns[2].metric(
        "Median",
        str(round(primary["median"]))
    )

    metric_columns[3].metric(
        "75th percentile",
        str(round(primary["p75"]))
    )

    metric_columns[4].metric(
        "90th percentile",
        str(round(primary["p90"]))
    )

else:
    st.info(
        "Selected current state ke liye comparable historical innings "
        "nahi mile."
    )


st.subheader("Historical context layers")

table_rows = []

for context_name, summary in summaries.items():
    if summary["count"] > 0:
        table_rows.append({
            "Context": context_name,
            "Comparable innings": summary["count"],
            "Reached benchmark": (
                str(summary["at_least"])
                + " ("
                + format(summary["rate"], ".1f")
                + "%)"
            ),
            "Below benchmark": summary["below"],
            "Average endpoint score": format(
                summary["mean"],
                ".1f"
            ),
            "Median endpoint score": format(
                summary["median"],
                ".1f"
            ),
            "Confidence": confidence(
                summary["count"]
            )
        })

    else:
        table_rows.append({
            "Context": context_name,
            "Comparable innings": 0,
            "Reached benchmark": "No matching data",
            "Below benchmark": "—",
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

if blend:
    st.markdown(
        "### Context-weighted historical summary"
    )

    st.write(
        "Available historical context layers ka weighted endpoint "
        "estimate: "
        + "**"
        + format(blend["mean"], ".1f")
        + "** runs at "
        + str(endpoint_over)
        + ".0 overs."
    )

    st.write(
        "Available comparable historical innings me "
        + "**"
        + format(blend["rate"], ".1f")
        + "%** cases me score "
        + str(benchmark)
        + " ya usse zyada tha."
    )

    st.caption(
        "This is historical descriptive analysis. "
        "It is not a guarantee, official odds, or a recommendation."
    )

else:
    st.info(
        "Blended historical context ke liye sufficient data nahi mila."
    )


with st.expander("Method and data transparency"):
    st.write(
        "Dashboard entered runs, wickets aur legal-ball position ko "
        "recorded historical innings ke saath compare karta hai."
    )

    st.write(
        "Matchup, venue, batting team, bowling team aur league baseline "
        "ke separate historical context layers calculate hote hain."
    )

    st.write(
        "Har matching historical innings ka actual recorded cumulative "
        "score endpoint over tak use kiya jata hai. "
        "No random score or invented historical outcome is generated."
    )

    st.write(
        "Venue aliases normalize kiye gaye hain. WACA Ground aur Perth "
        "Stadium ko alag grounds treat kiya jata hai."
    )
