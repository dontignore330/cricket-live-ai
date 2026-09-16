import os
import sqlite3
import streamlit as st
import pandas as pd
import numpy as np


DB = "cricket_history.db"


# -----------------------------
# PAGE
# -----------------------------

st.set_page_config(
    page_title="Apex Quant Cricket AI",
    page_icon="🏏",
    layout="wide"
)


# -----------------------------
# PASSWORD
# -----------------------------

APP_PASSWORD = os.getenv("APP_PASSWORD", "")

if APP_PASSWORD:

    password = st.text_input(
        "Enter Password",
        type="password"
    )

    if password != APP_PASSWORD:
        st.warning("🔒 Private testing mode")
        st.stop()


# -----------------------------
# TITLE
# -----------------------------

st.title("🏏 Apex Quant Cricket AI")

st.caption(
    "Historical cricket analytics • IPL • BBL • WBBL"
)


# -----------------------------
# DATABASE
# -----------------------------

@st.cache_resource
def get_connection():

    if not os.path.exists(DB):
        return None

    return sqlite3.connect(
        DB,
        check_same_thread=False
    )


conn = get_connection()


if conn is None:

    st.error(
        "Historical database is not available yet."
    )

    st.info(
        "Render ko build_model.py run karke database banana hoga."
    )

    st.stop()


# -----------------------------
# HELPERS
# -----------------------------

def valid_ball(value):

    try:

        over, ball = value.split(".")

        over = int(over)
        ball = int(ball)

        if over < 0:
            return False

        if ball < 0 or ball > 5:
            return False

        if over > 19:
            return False

        return True

    except:

        return False


def ball_to_number(value):

    over, ball = value.split(".")

    return int(over) * 6 + int(ball)


def number_to_ball(number):

    over = number // 6
    ball = number % 6

    return f"{over}.{ball}"


# -----------------------------
# SIDEBAR
# -----------------------------

st.sidebar.header("Match Information")


league = st.sidebar.selectbox(
    "League",
    [
        "IPL",
        "BBL",
        "WBBL"
    ]
)


innings = st.sidebar.selectbox(
    "Innings",
    [
        1,
        2
    ]
)


# -----------------------------
# TEAM LIST
# -----------------------------

@st.cache_data
def get_teams(league_name):

    query = """
        SELECT DISTINCT batting_team
        FROM samples
        WHERE league = ?
        ORDER BY batting_team
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(league_name,)
    )

    return df["batting_team"].tolist()


teams = get_teams(league)


if not teams:

    st.error(
        "Team data nahi mili."
    )

    st.stop()


batting_team = st.sidebar.selectbox(
    "Batting Team",
    teams
)


# -----------------------------
# BOWLING TEAMS
# -----------------------------

@st.cache_data
def get_bowling_teams(
    league_name,
    batting
):

    query = """
        SELECT DISTINCT bowling_team
        FROM samples
        WHERE league = ?
        AND batting_team = ?
        ORDER BY bowling_team
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(
            league_name,
            batting
        )
    )

    return df["bowling_team"].tolist()


bowling_teams = get_bowling_teams(
    league,
    batting_team
)


if bowling_teams:

    bowling_team = st.sidebar.selectbox(
        "Bowling Team",
        bowling_teams
    )

else:

    bowling_team = st.sidebar.text_input(
        "Bowling Team"
    )


# -----------------------------
# VENUE
# -----------------------------

@st.cache_data
def get_venues(league_name):

    query = """
        SELECT DISTINCT venue
        FROM samples
        WHERE league = ?
        AND venue != ''
        ORDER BY venue
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(league_name,)
    )

    return df["venue"].tolist()


venues = get_venues(league)


venue_options = [
    "Any Venue"
] + venues


venue = st.sidebar.selectbox(
    "Venue",
    venue_options
)


# -----------------------------
# CURRENT STATE
# -----------------------------

st.subheader("📍 Current Match State")


col1, col2, col3, col4 = st.columns(4)


with col1:

    current_ball_text = st.text_input(
        "Current Over.Ball",
        value="2.3"
    )


with col2:

    current_runs = st.number_input(
        "Current Runs",
        min_value=0,
        max_value=400,
        value=20
    )


with col3:

    current_wickets = st.number_input(
        "Wickets",
        min_value=0,
        max_value=10,
        value=1
    )


with col4:

    target_ball_text = st.text_input(
        "Target Over.Ball",
        value="5.2"
    )


# -----------------------------
# VALIDATION
# -----------------------------

if not valid_ball(current_ball_text):

    st.error(
        "Current Over.Ball invalid hai. Example: 2.3, 7.1, 15.5"
    )

    st.stop()


if not valid_ball(target_ball_text):

    st.error(
        "Target Over.Ball invalid hai. Example: 5.2, 11.4, 19.2"
    )

    st.stop()


current_ball = ball_to_number(
    current_ball_text
)

target_ball = ball_to_number(
    target_ball_text
)


if target_ball <= current_ball:

    st.error(
        "Target ball current ball se aage honi chahiye."
    )

    st.stop()


if current_wickets >= 10:

    st.warning(
        "10 wickets gir chuke hain."
    )

    st.stop()


# -----------------------------
# EXACT LEGAL BALL DIFFERENCE
# -----------------------------

remaining_legal_balls = (
    target_ball - current_ball
)


st.info(
    f"🎯 Analysis window: "
    f"{current_ball_text} → {target_ball_text}  "
    f"= **{remaining_legal_balls} legal balls**"
)


# -----------------------------
# OPTIONAL MARKET LINE
# -----------------------------

st.subheader("📊 Optional Market Signal")


market_line = st.number_input(
    "Current session / market line (optional)",
    min_value=0,
    max_value=250,
    value=0,
    help="Agar available ho to enter karo. Nahi ho to 0 rehne do."
)


# -----------------------------
# HISTORICAL QUERY
# -----------------------------

def get_historical_data():

    conditions = [
        "league = ?",
        "target_ball = ?"
    ]

    params = [
        league,
        target_ball
    ]

    # Similar wicket states
    conditions.append(
        "wickets BETWEEN ? AND ?"
    )

    low_wickets = max(
        0,
        int(current_wickets) - 1
    )

    high_wickets = min(
        9,
        int(current_wickets) + 1
    )

    params.extend([
        low_wickets,
        high_wickets
    ])

    # Team match
    conditions.append(
        "batting_team = ?"
    )

    params.append(
        batting_team
    )

    # Bowling team
    if bowling_team:

        conditions.append(
            "bowling_team = ?"
        )

        params.append(
            bowling_team
        )

    # Venue
    if venue != "Any Venue":

        conditions.append(
            "venue = ?"
        )

        params.append(
            venue
        )

    where = " AND ".join(
        conditions
    )

    query = f"""
        SELECT
            runs_to_target,
            current_runs,
            wickets
        FROM samples
        WHERE {where}
    """

    return pd.read_sql_query(
        query,
        conn,
        params=params
    )


data = get_historical_data()


# -----------------------------
# FALLBACK QUERY
# -----------------------------

if len(data) < 20:

    conditions = [
        "league = ?",
        "target_ball = ?",
        "wickets BETWEEN ? AND ?"
    ]

    params = [
        league,
        target_ball,
        low_wickets,
        high_wickets
    ]

    query = """
        SELECT
            runs_to_target,
            current_runs,
            wickets
        FROM samples
        WHERE league = ?
        AND target_ball = ?
        AND wickets BETWEEN ? AND ?
    """

    data = pd.read_sql_query(
        query,
        conn,
        params=params
    )


# -----------------------------
# VERY BROAD FALLBACK
# -----------------------------

if len(data) < 20:

    query = """
        SELECT
            runs_to_target,
            current_runs,
            wickets
        FROM samples
        WHERE league = ?
        AND target_ball = ?
    """

    data = pd.read_sql_query(
        query,
        conn,
        params=(
            league,
            target_ball
        )
    )


# -----------------------------
# MODEL
# -----------------------------

if len(data) == 0:

    st.warning(
        "Is exact target ball ke liye historical sample nahi mila."
    )

    st.stop()


runs = pd.to_numeric(
    data["runs_to_target"],
    errors="coerce"
).dropna()


# Remove impossible negative values
runs = runs[runs >= 0]


if len(runs) == 0:

    st.warning(
        "Us state ke liye valid historical data nahi mila."
    )

    st.stop()


# Historical statistics
median_runs = float(
    runs.median()
)

q25 = float(
    runs.quantile(0.25)
)

q75 = float(
    runs.quantile(0.75)
)

q10 = float(
    runs.quantile(0.10)
)

q90 = float(
    runs.quantile(0.90)
)


# -----------------------------
# CURRENT SCORE ADJUSTMENT
# -----------------------------

# Historical sample ka average current score
historical_current_score = float(
    data["current_runs"].median()
)


score_adjustment = (
    float(current_runs)
    - historical_current_score
)


# Conservative adjustment.
# Current score ko full future runs me directly
# add nahi karte.
adjustment = score_adjustment * 0.08


model_estimate = (
    median_runs + adjustment
)


# -----------------------------
# MARKET BLEND
# -----------------------------

if market_line > 0:

    # Market ko blind truth nahi maana ja raha.
    # Sirf small signal ke roop me blend.
    model_estimate = (
        model_estimate * 0.75
        +
        market_line * 0.25
    )


# -----------------------------
# WHOLE RUN
# -----------------------------

estimate = int(
    round(model_estimate)
)


# Compact 2-3 run display zone
display_low = max(
    0,
    estimate - 1
)

display_high = (
    estimate + 1
)


# -----------------------------
# OUTPUT
# -----------------------------

st.subheader("🎯 Projection")


c1, c2, c3 = st.columns(3)


with c1:

    st.metric(
        "Estimated Runs",
        f"{estimate}"
    )


with c2:

    st.metric(
        "Compact Zone",
        f"{display_low} – {display_high}"
    )


with c3:

    st.metric(
        "Historical Samples",
        f"{len(runs):,}"
    )


# -----------------------------
# HISTORICAL DISTRIBUTION
# -----------------------------

st.subheader(
    "📚 Historical Distribution"
)


h1, h2, h3 = st.columns(3)


with h1:

    st.write(
        f"Middle 50%: "
        f"**{round(q25)} – {round(q75)}**"
    )


with h2:

    st.write(
        f"10–90% range: "
        f"**{round(q10)} – {round(q90)}**"
    )


with h3:

    st.write(
        f"Historical median: "
        f"**{round(median_runs)} runs**"
    )


# -----------------------------
# MATCH STATE
# -----------------------------

st.subheader(
    "🏏 Match State"
)


run_rate = (
    current_runs / current_ball
    if current_ball > 0
    else 0
)


required_info = (
    f"Current score: **{current_runs}/{current_wickets}**  \n"
    f"Current position: **{current_ball_text}**  \n"
    f"Current legal-ball run rate: **{run_rate:.2f}**"
)


st.markdown(
    required_info
)


# -----------------------------
# WIN PROBABILITY
# -----------------------------

def get_win_probability():

    query = """
        SELECT
            won
        FROM win_states
        WHERE league = ?
        AND innings_no = ?
        AND ball_no BETWEEN ? AND ?
        AND wickets BETWEEN ? AND ?
    """

    low_ball = max(
        1,
        current_ball - 6
    )

    high_ball = current_ball + 6

    df = pd.read_sql_query(
        query,
        conn,
        params=(
            league,
            innings,
            low_ball,
            high_ball,
            low_wickets,
            high_wickets
        )
    )

    if len(df) < 20:

        query = """
            SELECT won
            FROM win_states
            WHERE league = ?
            AND innings_no = ?
            AND ball_no = ?
        """

        df = pd.read_sql_query(
            query,
            conn,
            params=(
                league,
                innings,
                current_ball
            )
        )

    if len(df) == 0:

        return None, 0

    probability = (
        float(df["won"].mean())
        * 100
    )

    return probability, len(df)


win_probability, win_samples = (
    get_win_probability()
)


if win_probability is not None:

    st.subheader(
        "📈 Historical Match-State Probability"
    )

    st.metric(
        "Historical batting-team win rate",
        f"{win_probability:.1f}%"
    )

    st.caption(
        f"Based on {win_samples:,} historical states. "
        "This is a historical statistic, not a guarantee."
    )

else:

    st.info(
        "Is match state ke liye sufficient historical "
        "win-state data nahi mila."
    )


# -----------------------------
# DEBUG / DATA QUALITY
# -----------------------------

with st.expander(
    "🔎 Data & Model Details"
):

    st.write(
        "League:",
        league
    )

    st.write(
        "Batting team:",
        batting_team
    )

    st.write(
        "Bowling team:",
        bowling_team
    )

    st.write(
        "Venue:",
        venue
    )

    st.write(
        "Current legal ball:",
        current_ball
    )

    st.write(
        "Target legal ball:",
        target_ball
    )

    st.write(
        "Legal balls analysed:",
        remaining_legal_balls
    )

    st.write(
        "Historical observations:",
        len(runs)
    )

    st.write(
        "Historical median future runs:",
        round(median_runs, 2)
    )

    st.write(
        "Model estimate before market:",
        round(
            median_runs + adjustment,
            2
        )
    )

    if market_line > 0:

        st.write(
            "Market signal used:",
            market_line
        )

st.caption(
    "Apex Quant is a statistical analytics tool. "
    "Historical patterns do not guarantee future results."
)
