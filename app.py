import os
import sqlite3
import streamlit as st
import pandas as pd


# =========================================================
# DREAM PROJECT
# =========================================================

st.set_page_config(
    page_title="Dream Project",
    page_icon="🏏",
    layout="wide"
)

DB = "cricket_history.db"


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    if not os.path.exists(DB):
        return None

    return sqlite3.connect(DB)


# =========================================================
# HISTORICAL WIN CALCULATION
# =========================================================

def calculate_win_percentage(
    league,
    batting_team,
    bowling_team,
    innings_no,
    ball_no,
    wickets
):

    connection = get_connection()

    if connection is None:
        return None

    # -----------------------------------------------------
    # First try: same league + same innings + same ball
    # + similar wicket situation
    # -----------------------------------------------------

    query = """
        SELECT won
        FROM win_states
        WHERE league = ?
          AND innings_no = ?
          AND ball_no BETWEEN ? AND ?
          AND wickets BETWEEN ? AND ?
    """

    lower_ball = max(1, ball_no - 1)
    upper_ball = ball_no + 1

    lower_wickets = max(0, wickets - 1)
    upper_wickets = min(10, wickets + 1)

    try:

        data = pd.read_sql_query(
            query,
            connection,
            params=(
                league,
                innings_no,
                lower_ball,
                upper_ball,
                lower_wickets,
                upper_wickets
            )
        )

        # -------------------------------------------------
        # If too few results, widen the search.
        # -------------------------------------------------

        if len(data) < 20:

            query = """
                SELECT won
                FROM win_states
                WHERE league = ?
                  AND innings_no = ?
                  AND ball_no BETWEEN ? AND ?
            """

            lower_ball = max(1, ball_no - 3)
            upper_ball = ball_no + 3

            data = pd.read_sql_query(
                query,
                connection,
                params=(
                    league,
                    innings_no,
                    lower_ball,
                    upper_ball
                )
            )

        # -------------------------------------------------
        # If still too little data, use all leagues
        # with same innings / ball / wickets.
        # -------------------------------------------------

        if len(data) < 20:

            query = """
                SELECT won
                FROM win_states
                WHERE innings_no = ?
                  AND ball_no BETWEEN ? AND ?
                  AND wickets BETWEEN ? AND ?
            """

            data = pd.read_sql_query(
                query,
                connection,
                params=(
                    innings_no,
                    max(1, ball_no - 3),
                    ball_no + 3,
                    lower_wickets,
                    upper_wickets
                )
            )

        connection.close()

        if data.empty:
            return None

        total = len(data)

        yes_count = int(
            data["won"].sum()
        )

        no_count = total - yes_count

        yes_percentage = (
            yes_count / total
        ) * 100

        no_percentage = (
            no_count / total
        ) * 100

        return {
            "yes": yes_percentage,
            "no": no_percentage,
            "total": total,
            "yes_count": yes_count,
            "no_count": no_count
        }

    except Exception:

        connection.close()

        return None


# =========================================================
# HISTORICAL FUTURE-RUN CALCULATION
# =========================================================

def calculate_future_runs(
    league,
    innings_no,
    ball_no,
    target_ball
):

    connection = get_connection()

    if connection is None:
        return None

    query = """
        SELECT future_runs
        FROM samples
        WHERE league = ?
          AND innings_no = ?
          AND ball_no BETWEEN ? AND ?
          AND target_ball = ?
    """

    try:

        data = pd.read_sql_query(
            query,
            connection,
            params=(
                league,
                innings_no,
                max(1, ball_no - 2),
                ball_no + 2,
                target_ball
            )
        )

        connection.close()

        if data.empty:
            return None

        return {
            "average": float(
                data["future_runs"].mean()
            ),
            "median": float(
                data["future_runs"].median()
            ),
            "samples": len(data)
        }

    except Exception:

        connection.close()

        return None


# =========================================================
# HEADER
# =========================================================

st.title("🏏 DREAM PROJECT")

st.subheader(
    "Cricket Historical + AI Situation Analyzer"
)

st.write(
    "Enter the current cricket situation. "
    "The system compares it with real historical match data."
)


# =========================================================
# DATABASE STATUS
# =========================================================

if os.path.exists(DB):

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM matches"
        )

        match_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM deliveries"
        )

        delivery_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM win_states"
        )

        win_count = cursor.fetchone()[0]

        connection.close()

        st.success(
            f"Historical database connected • "
            f"{match_count:,} matches • "
            f"{delivery_count:,} deliveries"
        )

    except Exception:

        if connection:
            connection.close()

        st.warning(
            "Database found, but statistics could not be read."
        )

else:

    st.error(
        "Historical database not found."
    )


# =========================================================
# CURRENT MATCH
# =========================================================

st.divider()

st.header("🏏 Current Match")

col1, col2 = st.columns(2)

with col1:

    league = st.selectbox(
        "League / Tournament",
        [
            "IPL",
            "BBL",
            "WBBL",
            "PSL",
            "BPL",
            "CPL",
            "ILT20",
            "T20 World Cup",
            "ODI",
            "Test",
            "Other"
        ]
    )

    batting_team = st.text_input(
        "Batting Team",
        placeholder="Example: India"
    )

    bowling_team = st.text_input(
        "Bowling Team",
        placeholder="Example: Australia"
    )

    ground = st.text_input(
        "Ground",
        placeholder="Example: Wankhede Stadium"
    )


with col2:

    overs = st.number_input(
        "Current Over",
        min_value=0.0,
        max_value=50.0,
        value=0.0,
        step=0.1
    )

    runs = st.number_input(
        "Current Runs",
        min_value=0,
        value=0,
        step=1
    )

    wickets = st.number_input(
        "Wickets",
        min_value=0,
        max_value=10,
        value=0,
        step=1
    )

    target = st.number_input(
        "Target / Session Number",
        min_value=0,
        value=0,
        step=1
    )


# =========================================================
# EXTRA INFORMATION
# =========================================================

st.divider()

st.header("📊 Additional Current Information")

col3, col4 = st.columns(2)

with col3:

    last_over_runs = st.number_input(
        "Last Over Runs",
        min_value=0,
        max_value=36,
        value=0,
        step=1
    )

    balls_remaining = st.number_input(
        "Balls Remaining",
        min_value=0,
        max_value=300,
        value=120,
        step=1
    )


with col4:

    innings = st.selectbox(
        "Innings",
        [
            "1st Innings",
            "2nd Innings"
        ]
    )

    match_format = st.selectbox(
        "Match Format",
        [
            "T20",
            "ODI",
            "Test"
        ]
    )


# =========================================================
# ANALYZE
# =========================================================

st.divider()

analyze = st.button(
    "🔍 ANALYZE CURRENT SITUATION",
    use_container_width=True
)


# =========================================================
# RESULT
# =========================================================

if analyze:

    innings_no = (
        1
        if innings == "1st Innings"
        else 2
    )

    # Convert 2.3 style cricket over
    # into approximate legal-ball number.
    over_number = int(overs)

    decimal_part = round(
        overs - over_number,
        1
    )

    ball_in_over = int(
        round(decimal_part * 10)
    )

    if ball_in_over > 6:
        ball_in_over = 6

    current_ball = (
        over_number * 6
        + ball_in_over
    )

    st.header("🧠 DREAM ANALYSIS")

    st.write(
        f"**{batting_team or 'Batting Team'}** "
        f"— **{runs}/{wickets}** "
        f"after **{overs} overs**"
    )

    st.write(
        f"League: **{league}**"
    )

    st.write(
        f"Bowling Team: **{bowling_team or 'Not entered'}**"
    )

    st.write(
        f"Ground: **{ground or 'Not entered'}**"
    )

    st.write(
        f"Innings: **{innings}**"
    )

    st.write(
        f"Format: **{match_format}**"
    )

    st.write(
        f"Historical ball position: **{current_ball}**"
    )

    st.divider()

    st.subheader(
        "📈 Historical Result"
    )

    result = calculate_win_percentage(
        league=league,
        batting_team=batting_team,
        bowling_team=bowling_team,
        innings_no=innings_no,
        ball_no=current_ball,
        wickets=wickets
    )

    if result is None:

        st.warning(
            "इस situation के लिए पर्याप्त historical data नहीं मिला। "
            "इसलिए percentage नहीं बनाई गई।"
        )

    else:

        result_col1, result_col2 = st.columns(2)

        with result_col1:

            st.metric(
                "YES",
                f"{result['yes']:.1f}%"
            )

        with result_col2:

            st.metric(
                "NO",
                f"{result['no']:.1f}%"
            )

        st.info(
            f"Calculation based on "
            f"{result['total']:,} historical states."
        )

        st.write(
            f"Historical YES: **{result['yes_count']:,}**"
        )

        st.write(
            f"Historical NO: **{result['no_count']:,}**"
        )


    # =====================================================
    # FUTURE RUN ANALYSIS
    # =====================================================

    if target > 0 and current_ball > 0:

        st.divider()

        st.subheader(
            "🎯 Historical Future-Run Analysis"
        )

        target_ball = int(target)

        if target_ball > current_ball:

            future_result = calculate_future_runs(
                league=league,
                innings_no=innings_no,
                ball_no=current_ball,
                target_ball=target_ball
            )

            if future_result:

                st.write(
                    f"Historical sample size: "
                    f"**{future_result['samples']:,}**"
                )

                st.write(
                    f"Average future runs: "
                    f"**{future_result['average']:.2f}**"
                )

                st.write(
                    f"Median future runs: "
                    f"**{future_result['median']:.2f}**"
                )

            else:

                st.info(
                    "इस target के लिए पर्याप्त historical "
                    "future-run data नहीं मिला।"
                )

        else:

            st.info(
                "Target / Session number current ball से "
                "आगे होना चाहिए।"
            )


    # =====================================================
    # TRANSPARENCY
    # =====================================================

    st.divider()

    st.subheader(
        "🔎 Transparency"
    )

    st.write(
        "Percentage historical match outcomes से calculate "
        "की जाती है। कोई artificial percentage नहीं बनाई जाती।"
    )

    st.write(
        "Historical sample कम होने पर system percentage "
        "दिखाने के बजाय insufficient data बताएगा।"
    )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "DREAM PROJECT • Cricket Data Intelligence System"
)
