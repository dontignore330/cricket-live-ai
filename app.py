import sqlite3
import math
import os
import hmac
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st


# ============================================================
# VASUDEV CRICKET ANALYSIS APP
# ============================================================

BASE_DIR = Path(".")

DB_PATHS = {
    "IPL": BASE_DIR / "cricket_history.db",
    "Men's Big Bash League": BASE_DIR / "bbl_history.db",
    "Women's Big Bash League": BASE_DIR / "wbbl_history.db",
}

BBL_URLS = {
    "Men's Big Bash League":
        "https://cricsheet.org/downloads/bbl_json.zip",

    "Women's Big Bash League":
        "https://cricsheet.org/downloads/wbbl_json.zip",
}


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="VasuDev Cricket Analysis",
    page_icon="🏏",
    layout="wide",
)


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>

    .result_yes {
        background: rgba(0, 180, 80, 0.12);
        border: 1px solid rgba(0, 180, 80, 0.45);
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 12px;
    }

    .result_no {
        background: rgba(220, 40, 40, 0.10);
        border: 1px solid rgba(220, 40, 40, 0.45);
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 12px;
    }

    .result_win {
        background: rgba(0, 180, 80, 0.12);
        border: 1px solid rgba(0, 180, 80, 0.45);
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 12px;
    }

    .result_loss {
        background: rgba(220, 40, 40, 0.10);
        border: 1px solid rgba(220, 40, 40, 0.45);
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 12px;
    }

    .result_avg {
        background: rgba(100, 100, 100, 0.08);
        border: 1px solid rgba(100, 100, 100, 0.25);
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 12px;
    }

    .small {
        font-size: 13px;
        opacity: 0.75;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# PASSWORD
# ============================================================

def password_gate():

    password = os.environ.get("VASUDEV_PASSWORD", "")

    if not password:
        return True

    if "vasudev_auth" not in st.session_state:
        st.session_state.vasudev_auth = False

    if st.session_state.vasudev_auth:
        return True

    st.title("🔐 VasuDev")

    entered = st.text_input(
        "Enter password",
        type="password",
    )

    if st.button("Unlock"):

        if hmac.compare_digest(entered, password):
            st.session_state.vasudev_auth = True
            st.rerun()

        else:
            st.error("Wrong password.")

    return False


if not password_gate():
    st.stop()


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_round(value, digits=0):

    if value is None:
        return 0

    try:
        if pd.isna(value):
            return 0
    except Exception:
        pass

    if digits == 0:
        return int(round(float(value)))

    return round(float(value), digits)


def balls_from_over_ball(value):

    """
    Cricket legal-ball conversion.

    0.1 = 1 ball
    0.6 = 6 balls
    1.1 = 7 balls
    2.3 = 15 balls
    """

    try:

        value = float(value)

        over = int(value)
        ball = int(round((value - over) * 10))

        if ball < 0:
            ball = 0

        if ball > 6:
            raise ValueError("Invalid over.ball")

        return over * 6 + ball

    except Exception:

        return 0


def over_ball_from_balls(balls):

    balls = int(max(0, balls))

    over = balls // 6
    ball = balls % 6

    return f"{over}.{ball}"


def valid_over_ball_options(max_overs=20):

    options = ["0.0"]

    for over in range(0, max_overs + 1):

        start_ball = 1 if over == 0 else 1

        for ball in range(start_ball, 7):

            if over == max_overs and ball > 0:
                continue

            options.append(f"{over}.{ball}")

    return options


def reliability_label(value):

    value = float(value)

    if value >= 100:
        return "Very High"

    if value >= 50:
        return "High"

    if value >= 20:
        return "Good"

    if value >= 10:
        return "Medium"

    return "Low"


# ============================================================
# BIG BASH DATABASE BUILDER
# ============================================================

@st.cache_data(show_spinner=False)
def download_big_bash_zip(url):

    tmp_dir = Path(tempfile.mkdtemp())

    zip_path = tmp_dir / "data.zip"

    urllib.request.urlretrieve(url, zip_path)

    return str(zip_path)


def build_big_bash_database(league):

    db_path = DB_PATHS[league]

    if db_path.exists():
        return True

    url = BBL_URLS.get(league)

    if not url:
        return False

    try:

        zip_path = download_big_bash_zip(url)

        extract_dir = Path(tempfile.mkdtemp())

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

        json_files = list(extract_dir.rglob("*.json"))

        if not json_files:
            return False

        conn = sqlite3.connect(db_path)

        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                match_id TEXT PRIMARY KEY,
                date TEXT,
                venue TEXT,
                team1 TEXT,
                team2 TEXT,
                winner TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS deliveries (
                match_id TEXT,
                innings INTEGER,
                over INTEGER,
                ball INTEGER,
                batting_team TEXT,
                bowling_team TEXT,
                batter TEXT,
                bowler TEXT,
                runs_batter INTEGER,
                runs_total INTEGER,
                wicket INTEGER
            )
            """
        )

        for jf in json_files:

            try:

                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)

                meta = data.get("meta", {})

                info = data.get("info", {})

                dates = info.get("dates", [])

                date_value = str(dates[0]) if dates else ""

                teams = info.get("teams", [])

                if len(teams) >= 2:
                    team1 = teams[0]
                    team2 = teams[1]
                else:
                    team1 = ""
                    team2 = ""

                venue = info.get("venue", "")

                outcome = info.get("outcome", {})

                winner = outcome.get("winner", "")

                match_id = jf.stem

                cur.execute(
                    """
                    INSERT OR REPLACE INTO matches
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        date_value,
                        venue,
                        team1,
                        team2,
                        winner,
                    ),
                )

                innings_list = data.get("innings", [])

                for innings_no, innings in enumerate(innings_list, start=1):

                    batting_team = innings.get("team", "")

                    overs = innings.get("overs", [])

                    for over_data in overs:

                        over_no = over_data.get("over", 0)

                        deliveries_list = over_data.get(
                            "deliveries", []
                        )

                        for ball_no, delivery in enumerate(
                            deliveries_list,
                            start=1,
                        ):

                            batter = delivery.get(
                                "batter",
                                "",
                            )

                            bowler = delivery.get(
                                "bowler",
                                "",
                            )

                            runs = delivery.get(
                                "runs",
                                {},
                            )

                            batter_runs = int(
                                runs.get(
                                    "batter",
                                    0,
                                )
                            )

                            total_runs = int(
                                runs.get(
                                    "total",
                                    0,
                                )
                            )

                            wickets = delivery.get(
                                "wickets",
                                [],
                            )

                            wicket = 1 if wickets else 0

                            bowling_team = ""

                            for t in teams:

                                if t != batting_team:
                                    bowling_team = t
                                    break

                            cur.execute(
                                """
                                INSERT INTO deliveries
                                VALUES (
                                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                                )
                                """,
                                (
                                    match_id,
                                    innings_no,
                                    over_no,
                                    ball_no,
                                    batting_team,
                                    bowling_team,
                                    batter,
                                    bowler,
                                    batter_runs,
                                    total_runs,
                                    wicket,
                                ),
                            )

            except Exception:
                continue

        conn.commit()
        conn.close()

        return True

    except Exception:
        return False


# ============================================================
# LOAD HISTORY
# ============================================================

@st.cache_data(show_spinner=False)
def load_history(league):

    db_path = DB_PATHS[league]

    if not db_path.exists():

        if league != "IPL":

            return pd.DataFrame()

        return pd.DataFrame()

    conn = sqlite3.connect(db_path)

    query = """
        SELECT
            d.match_id,
            m.date,
            m.venue,
            m.team1,
            m.team2,
            m.winner,

            d.innings,
            d.over,
            d.ball,

            d.batting_team,
            d.bowling_team,

            d.runs_batter,
            d.runs_total,
            d.wicket

        FROM deliveries d

        LEFT JOIN matches m
            ON d.match_id = m.match_id

        ORDER BY
            d.match_id,
            d.innings,
            d.over,
            d.ball
    """

    try:

        df = pd.read_sql_query(query, conn)

    except Exception:

        conn.close()

        return pd.DataFrame()

    conn.close()

    if df.empty:
        return df

    df["runs_total"] = pd.to_numeric(
        df["runs_total"],
        errors="coerce",
    ).fillna(0)

    df["wicket"] = pd.to_numeric(
        df["wicket"],
        errors="coerce",
    ).fillna(0)

    df["over"] = pd.to_numeric(
        df["over"],
        errors="coerce",
    ).fillna(0)

    df["ball"] = pd.to_numeric(
        df["ball"],
        errors="coerce",
    ).fillna(0)

    df["ball_pos"] = (
        df["over"] * 6
        + df["ball"]
    )

    df["cum_runs"] = (
        df.groupby(
            ["match_id", "innings"]
        )["runs_total"]
        .cumsum()
    )

    df["cum_wk"] = (
        df.groupby(
            ["match_id", "innings"]
        )["wicket"]
        .cumsum()
    )

    return df


# ============================================================
# CANDIDATE MATCHING
# ============================================================

def similarity_candidates(
    df,
    current_runs,
    current_wk,
    current_ball,
    ground,
    batting_team,
    bowling_team,
    max_rows=5000,
):

    if df.empty:
        return pd.DataFrame()

    x = df.copy()

    x = x[
        x["ball_pos"] <= current_ball
    ]

    if x.empty:
        return x

    # score difference
    score_diff = (
        x["cum_runs"]
        - current_runs
    ).abs()

    # wicket difference
    wicket_diff = (
        x["cum_wk"]
        - current_wk
    ).abs()

    # ball difference
    ball_diff = (
        x["ball_pos"]
        - current_ball
    ).abs()

    score_weight = (
        1
        / (1 + score_diff)
    )

    wicket_weight = (
        1
        / (1 + wicket_diff * 4)
    )

    ball_weight = (
        1
        / (1 + ball_diff / 6)
    )

    team_weight = np.where(
        x["batting_team"].eq(
            batting_team
        ),
        1.5,
        0.5,
    )

    if ground:

        ground_weight = np.where(
            x["venue"]
            .fillna("")
            .str.contains(
                str(ground),
                case=False,
                na=False,
            ),
            2.0,
            1.0,
        )

    else:

        ground_weight = 1.0

    x["similarity"] = (
        score_weight
        * wicket_weight
        * ball_weight
        * team_weight
        * ground_weight
    )

    x = x.sort_values(
        "similarity",
        ascending=False,
    )

    return x.head(max_rows)


# ============================================================
# FUTURE SCORE
# ============================================================

def add_future_scores(
    history,
    candidates,
    target_ball,
):

    if candidates.empty:
        return candidates

    keys = candidates[
        [
            "match_id",
            "innings",
        ]
    ].drop_duplicates()

    future = history.merge(
        keys,
        on=[
            "match_id",
            "innings",
        ],
        how="inner",
    )

    future = future[
        future["ball_pos"] <= target_ball
    ]

    if future.empty:
        return candidates

    future = (
        future.sort_values(
            "ball_pos"
        )
        .groupby(
            [
                "match_id",
                "innings",
            ]
        )
        .tail(1)
    )

    future = future[
        [
            "match_id",
            "innings",
            "cum_runs",
            "ball_pos",
        ]
    ].rename(
        columns={
            "cum_runs": "future_score",
            "ball_pos": "future_ball",
        }
    )

    result = candidates.merge(
        future,
        on=[
            "match_id",
            "innings",
        ],
        how="inner",
    )

    return result


# ============================================================
# HISTORICAL WIN SIMILARITY
# ============================================================

def historical_win_similarity(
    history,
    candidates,
    batting_team,
):

    if candidates.empty:
        return None

    match_info = (
        candidates[
            [
                "match_id",
                "innings",
                "similarity",
                "batting_team",
                "winner",
            ]
        ]
        .drop_duplicates(
            [
                "match_id",
                "innings",
            ]
        )
    )

    if match_info.empty:
        return None

    match_info["is_win"] = (
        match_info["winner"]
        == batting_team
    ).astype(int)

    weights = match_info[
        "similarity"
    ].astype(float)

    if weights.sum() <= 0:
        return None

    win_probability = (
        (
            match_info["is_win"]
            * weights
        ).sum()
        / weights.sum()
    ) * 100

    return {
        "win_pct": float(
            win_probability
        ),
        "loss_pct": float(
            100 - win_probability
        ),
        "samples": int(
            len(match_info)
        ),
    }


# ============================================================
# BACKTEST
# ============================================================

def backtest_session_and_win(
    history,
    batting_team,
    current_ball,
    target_ball,
    current_runs,
    current_wk,
    ground,
):

    if history.empty:
        return None

    if target_ball <= current_ball:
        return None

    # Historical sample
    candidates = similarity_candidates(
        history,
        current_runs,
        current_wk,
        current_ball,
        ground,
        batting_team,
        "",
        max_rows=1000,
    )

    if candidates.empty:
        return None

    future = add_future_scores(
        history,
        candidates,
        target_ball,
    )

    if future.empty:
        return None

    future["future_runs"] = (
        future["future_score"]
        - future["cum_runs"]
    )

    average_added = (
        future["future_runs"]
        .mean()
    )

    return {
        "sample": len(future),
        "avg_added": average_added,
    }


# ============================================================
# EXTRA HISTORICAL RESULTS
# ============================================================

def historical_extra_results(
    history,
    candidates,
    current_runs,
    current_ball,
    target_ball,
):

    if candidates.empty:
        return {
            "avg_added": 0,
            "projected_score": current_runs,
            "reached": 0,
            "below": 0,
            "sample": 0,
            "trend": None,
        }

    future = add_future_scores(
        history,
        candidates,
        target_ball,
    )

    if future.empty:

        return {
            "avg_added": 0,
            "projected_score": current_runs,
            "reached": 0,
            "below": 0,
            "sample": 0,
            "trend": None,
        }

    future["future_runs"] = (
        future["future_score"]
        - future["cum_runs"]
    )

    future["future_runs"] = pd.to_numeric(
        future["future_runs"],
        errors="coerce",
    )

    future = future.dropna(
        subset=["future_runs"]
    )

    if future.empty:

        return {
            "avg_added": 0,
            "projected_score": current_runs,
            "reached": 0,
            "below": 0,
            "sample": 0,
            "trend": None,
        }

    avg_added = float(
        future["future_runs"].mean()
    )

    projected_score = (
        current_runs
        + avg_added
    )

    # --------------------------------------------------------
    # Historical threshold
    # --------------------------------------------------------

    avg_threshold = round(
        avg_added
    )

    reached = int(
        (
            future["future_runs"]
            >= avg_threshold
        ).sum()
    )

    below = int(
        len(future)
        - reached
    )

    # --------------------------------------------------------
    # Trend calculation
    # --------------------------------------------------------

    trend = history[
        [
            "match_id",
            "innings",
            "ball_pos",
            "runs_total",
        ]
    ].copy()

    trend = trend[
        trend["ball_pos"]
        >= current_ball + 1
    ]

    trend = trend[
        trend["ball_pos"]
        <= target_ball
    ]

    if trend.empty:

        trend_summary = None

    else:

        # Average runs in every legal-ball position
        ball_avg = (
            trend.groupby(
                "ball_pos"
            )["runs_total"]
            .mean()
            .reset_index()
            .sort_values(
                "ball_pos"
            )
        )

        if len(ball_avg) >= 2:

            ball_avg["change"] = (
                ball_avg["runs_total"]
                .diff()
            )

            # Remove first NaN row
            trend = ball_avg.dropna(
                subset=["change"]
            ).copy()

            if not trend.empty:

                if len(trend) > 1:

                    biggest_up = trend.loc[
                        trend["change"].idxmax()
                    ]

                    biggest_down = trend.loc[
                        trend["change"].idxmin()
                    ]

                else:

                    biggest_up = trend.iloc[0]
                    biggest_down = trend.iloc[0]

                up_change = float(
                    biggest_up["change"]
                )

                down_change = float(
                    biggest_down["change"]
                )

                if abs(up_change) >= abs(
                    down_change
                ):

                    change_ball = int(
                        biggest_up[
                            "ball_pos"
                        ]
                    )

                    change_value = (
                        up_change
                    )

                    direction = "increase"

                else:

                    change_ball = int(
                        biggest_down[
                            "ball_pos"
                        ]
                    )

                    change_value = (
                        down_change
                    )

                    direction = "decrease"

                trend_summary = {
                    "change_ball": change_ball,
                    "change_value": change_value,
                    "direction": direction,
                }

            else:

                trend_summary = None

        else:

            trend_summary = None

    return {
        "avg_added": avg_added,
        "projected_score": projected_score,
        "reached": reached,
        "below": below,
        "sample": len(future),
        "trend": trend_summary,
    }


# ============================================================
# MAIN TITLE
# ============================================================

st.title("🏏 VasuDev Cricket Analysis")

st.caption(
    "Historical cricket situation analysis using ball-by-ball data."
)


# ============================================================
# LEAGUE
# ============================================================

league = st.selectbox(
    "League",
    [
        "IPL",
        "Men's Big Bash League",
        "Women's Big Bash League",
    ],
)


# ============================================================
# BUILD BBL DB IF NEEDED
# ============================================================

if league != "IPL":

    if not DB_PATHS[league].exists():

        with st.spinner(
            f"Preparing {league} historical database..."
        ):

            success = build_big_bash_database(
                league
            )

        if success:

            st.success(
                f"{league} database ready."
            )

        else:

            st.error(
                f"Could not prepare {league} database."
            )

            st.stop()


# ============================================================
# LOAD DATA
# ============================================================

history = load_history(
    league
)

if history.empty:

    st.error(
        "Historical database/data could not be loaded."
    )

    st.stop()


# ============================================================
# DATABASE INFO
# ============================================================

match_count = history[
    "match_id"
].nunique()

delivery_count = len(history)

c1, c2 = st.columns(2)

with c1:

    st.metric(
        "Historical Matches",
        f"{match_count:,}",
    )

with c2:

    st.metric(
        "Historical Deliveries",
        f"{delivery_count:,}",
    )


# ============================================================
# INPUT SECTION
# ============================================================

st.subheader("📊 Current Match Situation")


col1, col2, col3 = st.columns(3)


with col1:

    teams = sorted(
        [
            x for x in history[
                "batting_team"
            ].dropna().unique()
            if str(x).strip()
        ]
    )

    batting_team = st.selectbox(
        "Batting Team",
        teams,
    )


with col2:

    bowling_teams = sorted(
        [
            x for x in history[
                "bowling_team"
            ].dropna().unique()
            if str(x).strip()
        ]
    )

    if batting_team in bowling_teams:
        bowling_teams = [
            x
            for x in bowling_teams
            if x != batting_team
        ]

    bowling_team = st.selectbox(
        "Bowling Team",
        bowling_teams,
    )


with col3:

    grounds = sorted(
        [
            x for x in history[
                "venue"
            ].dropna().unique()
            if str(x).strip()
        ]
    )

    ground = st.selectbox(
        "Ground",
        ["All Grounds"] + grounds,
    )

    if ground == "All Grounds":
        ground = ""


col4, col5, col6 = st.columns(3)


with col4:

    innings = st.selectbox(
        "Innings",
        [1, 2],
    )


with col5:

    over_options = valid_over_ball_options(
        20
    )

    current_over_ball = st.selectbox(
        "Current Over.Ball",
        over_options,
        index=min(
            len(over_options) - 1,
            over_options.index("3.1")
            if "3.1" in over_options
            else 0,
        ),
    )


with col6:

    current_runs = st.number_input(
        "Current Score",
        min_value=0,
        max_value=500,
        value=16,
        step=1,
    )


col7, col8, col9 = st.columns(3)


with col7:

    current_wk = st.number_input(
        "Current Wickets",
        min_value=0,
        max_value=10,
        value=1,
        step=1,
    )


with col8:

    target_over_ball = st.selectbox(
        "Future Over.Ball",
        over_options,
        index=min(
            len(over_options) - 1,
            over_options.index("7.1")
            if "7.1" in over_options
            else 0,
        ),
    )


with col9:

    target_score = st.number_input(
        "Session Target Runs",
        min_value=1,
        max_value=500,
        value=50,
        step=1,
    )


# ============================================================
# CONVERT BALLS
# ============================================================

current_ball = balls_from_over_ball(
    current_over_ball
)

target_ball = balls_from_over_ball(
    target_over_ball
)


# ============================================================
# VALIDATION
# ============================================================

if target_ball <= current_ball:

    st.warning(
        "Future Over.Ball must be after Current Over.Ball."
    )

    st.stop()


balls_remaining = (
    target_ball
    - current_ball
)


# ============================================================
# ANALYSE BUTTON
# ============================================================

analyse = st.button(
    "🔍 ANALYSE",
    type="primary",
    use_container_width=True,
)


if analyse:

    # --------------------------------------------------------
    # Similar candidates
    # --------------------------------------------------------

    candidates = similarity_candidates(
        history,
        current_runs,
        current_wk,
        current_ball,
        ground,
        batting_team,
        bowling_team,
        max_rows=3000,
    )

    # --------------------------------------------------------
    # WINNING
    # --------------------------------------------------------

    win_result = historical_win_similarity(
        history,
        candidates,
        batting_team,
    )

    if win_result is None:

        win_pct = 0
        loss_pct = 0
        win_samples = 0

    else:

        win_pct = win_result[
            "win_pct"
        ]

        loss_pct = win_result[
            "loss_pct"
        ]

        win_samples = win_result[
            "samples"
        ]

    st.subheader("🏆 WINNING")

    if win_pct >= loss_pct:

        win_class = "result_win"

        win_title = (
            f"{batting_team} WIN"
        )

    else:

        win_class = "result_loss"

        win_title = (
            f"{batting_team} LOSS"
        )

    c1, c2 = st.columns(2)

    with c1:

        st.markdown(
            f"""
            <div class="{win_class}">
                <h2>{win_title}</h2>
                <h1>{safe_round(
                    win_pct,
                    1
                )}%</h1>
                <p>Historical WIN probability</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:

        st.markdown(
            f"""
            <div class="result_loss">
                <h2>LOSS</h2>
                <h1>{safe_round(
                    loss_pct,
                    1
                )}%</h1>
                <p>Historical LOSS probability</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        f"{win_samples:,} similar historical match states • "
        f"Reliability: {reliability_label(win_samples)}"
    )


    # --------------------------------------------------------
    # SESSION
    # --------------------------------------------------------

    st.subheader("🎯 SESSION")

    future = add_future_scores(
        history,
        candidates,
        target_ball,
    )

    if future.empty:

        yes_pct = 0
        no_pct = 0
        session_samples = 0

    else:

        future["future_runs"] = (
            future["future_score"]
            - future["cum_runs"]
        )

        session_samples = len(
            future
        )

        yes_count = int(
            (
                future["future_runs"]
                >= target_score
            ).sum()
        )

        yes_pct = (
            yes_count
            / session_samples
            * 100
        )

        no_pct = (
            100
            - yes_pct
        )

    s1, s2 = st.columns(2)

    with s1:

        if yes_pct >= no_pct:

            session_class = (
                "result_yes"
            )

        else:

            session_class = (
                "result_no"
            )

        st.markdown(
            f"""
            <div class="{session_class}">
                <h2>YES</h2>
                <h1>{safe_round(
                    yes_pct,
                    1
                )}%</h1>
                <p>
                    Target {target_score} runs by
                    {target_over_ball}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with s2:

        st.markdown(
            f"""
            <div class="result_no">
                <h2>NO</h2>
                <h1>{safe_round(
                    no_pct,
                    1
                )}%</h1>
                <p>
                    Historical probability
                    of not reaching target
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        f"{session_samples:,} similar historical situations • "
        f"{balls_remaining} legal balls remaining • "
        f"Reliability: {reliability_label(session_samples)}"
    )


    # --------------------------------------------------------
    # HISTORICAL EXTRA RESULTS
    # --------------------------------------------------------

    extra = historical_extra_results(
        history,
        candidates,
        current_runs,
        current_ball,
        target_ball,
    )


    # --------------------------------------------------------
    # HISTORICAL AVERAGE
    # --------------------------------------------------------

    st.subheader(
        "📈 Historical Average"
    )

    avg_added = extra[
        "avg_added"
    ]

    projected_score = extra[
        "projected_score"
    ]

    reached = extra[
        "reached"
    ]

    below = extra[
        "below"
    ]

    sample = extra[
        "sample"
    ]

    c1, c2, c3, c4 = st.columns(4)

    with c1:

        st.markdown(
            f"""
            <div class="result_avg">
                <h3>AVERAGE ADD</h3>
                <h2>+{safe_round(
                    avg_added
                )} runs</h2>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:

        st.markdown(
            f"""
            <div class="result_avg">
                <h3>PROJECTED SCORE</h3>
                <h2>{safe_round(
                    projected_score
                )}</h2>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:

        st.markdown(
            f"""
            <div class="result_avg">
                <h3>REACHED</h3>
                <h2>{reached}</h2>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c4:

        st.markdown(
            f"""
            <div class="result_avg">
                <h3>BELOW</h3>
                <h2>{below}</h2>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        f"{sample:,} similar innings • "
        f"Current score {current_runs} → "
        f"projected {safe_round(projected_score)}"
    )


    # --------------------------------------------------------
    # AVG SCORING CHANGE
    # --------------------------------------------------------

    c1, c2 = st.columns(2)

    with c1:

        st.markdown(
            f"""
            <div class="result_avg">
                <h3>⏱️ BALLS REMAINING</h3>
                <h2>{balls_remaining}</h2>
                <p class="small">
                    Legal balls from
                    {current_over_ball}
                    to
                    {target_over_ball}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


    with c2:

        tr = extra["trend"]

        if tr is None:

            trend_text = (
                "Not enough ball-by-ball data"
            )

        else:

            change_ball = (
                over_ball_from_balls(
                    tr["change_ball"]
                )
            )

            change_value = safe_round(
                abs(
                    tr["change_value"]
                )
            )

            if tr["direction"] == "increase":

                change_word = "Increased"
                sign = "+"

            else:

                change_word = "Decreased"
                sign = "-"

            trend_text = (
                f'<p><b>Biggest scoring change:</b> '
                f'after <b>{change_ball}</b></p>'
                f'<h2>{change_word} by '
                f'{sign}{change_value} runs / 6 balls</h2>'
            )

        st.markdown(
            f"""
            <div class="result_avg">
                <h3>🔄 AVG SCORING CHANGE</h3>
                {trend_text}
                <p class="small">
                    Checked at every legal ball from
                    {over_ball_from_balls(
                        current_ball + 1
                    )}
                    to
                    {over_ball_from_balls(
                        target_ball
                    )}.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


    # ========================================================
    # DETAILS
    # ========================================================

    with st.expander(
        "🔽 Details (optional)"
    ):

        st.markdown(
            f"""
            ### Analysis Details

            **League:** {league}

            **Batting Team:** {batting_team}

            **Bowling Team:** {bowling_team}

            **Ground:** {ground if ground else "All Grounds"}

            **Innings:** {innings}

            **Current:** {current_over_ball} — 
            {current_runs}/{current_wk}

            **Future Point:** {target_over_ball}

            **Session Target:** {target_score}

            **Legal Balls Remaining:** {balls_remaining}

            **Historical Similar Situations:** {sample:,}

            **Average Added Runs:** 
            +{safe_round(avg_added)}

            **Projected Score:** 
            {safe_round(projected_score)}

            **Historical WIN:** 
            {safe_round(win_pct, 1)}%

            **Historical LOSS:** 
            {safe_round(loss_pct, 1)}%

            **Session YES:** 
            {safe_round(yes_pct, 1)}%

            **Session NO:** 
            {safe_round(no_pct, 1)}%

            ---

            ### How the result is calculated

            The app compares the current match situation with
            historical ball-by-ball situations.

            It considers factors such as:

            - Current score
            - Current wickets
            - Current legal-ball position
            - Batting team
            - Ground, when selected
            - Historical match outcome
            - Historical score progression

            The displayed percentage is based on the
            historical sample found by the analysis.

            The app does not force the percentage to
            80% or 90%. If the historical data gives a
            lower percentage, the lower percentage is shown.
            """
        )


# ============================================================
# FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "VasuDev • Historical Cricket Situation Analysis"
)
