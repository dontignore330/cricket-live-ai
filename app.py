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
# TEAM DATABASE
# =========================================================

TEAMS = {

    "IPL": [
        "Chennai Super Kings",
        "Delhi Capitals",
        "Gujarat Titans",
        "Kolkata Knight Riders",
        "Lucknow Super Giants",
        "Mumbai Indians",
        "Punjab Kings",
        "Rajasthan Royals",
        "Royal Challengers Bengaluru",
        "Sunrisers Hyderabad"
    ],

    "BBL": [
        "Adelaide Strikers",
        "Brisbane Heat",
        "Hobart Hurricanes",
        "Melbourne Renegades",
        "Melbourne Stars",
        "Perth Scorchers",
        "Sydney Sixers",
        "Sydney Thunder"
    ],

    "WBBL": [
        "Adelaide Strikers",
        "Brisbane Heat",
        "Hobart Hurricanes",
        "Melbourne Renegades",
        "Melbourne Stars",
        "Perth Scorchers",
        "Sydney Sixers",
        "Sydney Thunder"
    ],

    "PSL": [
        "Islamabad United",
        "Karachi Kings",
        "Lahore Qalandars",
        "Multan Sultans",
        "Peshawar Zalmi",
        "Quetta Gladiators"
    ],

    "BPL": [
        "Chattogram Challengers",
        "Comilla Victorians",
        "Dhaka Capitals",
        "Fortune Barishal",
        "Khulna Tigers",
        "Rangpur Riders",
        "Sylhet Strikers"
    ],

    "CPL": [
        "Barbados Royals",
        "Guyana Amazon Warriors",
        "Jamaica Tallawahs",
        "Saint Lucia Kings",
        "St Kitts & Nevis Patriots",
        "Trinbago Knight Riders"
    ],

    "ILT20": [
        "Abu Dhabi Knight Riders",
        "Desert Vipers",
        "Dubai Capitals",
        "Gulf Giants",
        "MI Emirates",
        "Sharjah Warriorz"
    ],

    "T20 World Cup": [
        "India",
        "Australia",
        "England",
        "New Zealand",
        "Pakistan",
        "South Africa",
        "Sri Lanka",
        "Bangladesh",
        "Afghanistan",
        "West Indies",
        "Ireland",
        "Scotland",
        "Zimbabwe",
        "Nepal",
        "Namibia",
        "United States"
    ],

    "ODI": [
        "India",
        "Australia",
        "England",
        "New Zealand",
        "Pakistan",
        "South Africa",
        "Sri Lanka",
        "Bangladesh",
        "Afghanistan",
        "West Indies",
        "Ireland",
        "Zimbabwe"
    ],

    "Test": [
        "India",
        "Australia",
        "England",
        "New Zealand",
        "Pakistan",
        "South Africa",
        "Sri Lanka",
        "Bangladesh",
        "Afghanistan",
        "West Indies"
    ],

    "Other": [
        "India",
        "Australia",
        "England",
        "New Zealand",
        "Pakistan",
        "South Africa",
        "Sri Lanka",
        "Bangladesh"
    ]
}


# =========================================================
# DATABASE
# =========================================================

def get_connection():

    if not os.path.exists(DB):
        return None

    try:
        return sqlite3.connect(DB)
    except Exception:
        return None


def table_columns(connection, table_name):

    try:

        cursor = connection.cursor()

        cursor.execute(
            f"PRAGMA table_info({table_name})"
        )

        rows = cursor.fetchall()

        return [row[1] for row in rows]

    except Exception:

        return []


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

    try:

        columns = table_columns(
            connection,
            "win_states"
        )

        if "league" not in columns:
            connection.close()
            return None

        # -------------------------------------------------
        # TEAM-AWARE SEARCH
        # -------------------------------------------------

        team_columns_available = (
            "batting_team" in columns
            and "bowling_team" in columns
        )

        if team_columns_available:

            query = """
                SELECT won
                FROM win_states
                WHERE league = ?
                  AND batting_team = ?
                  AND bowling_team = ?
                  AND innings_no = ?
                  AND ball_no BETWEEN ? AND ?
                  AND wickets BETWEEN ? AND ?
            """

            data = pd.read_sql_query(
                query,
                connection,
                params=(
                    league,
                    batting_team,
                    bowling_team,
                    innings_no,
                    max(1, ball_no - 1),
                    ball_no + 1,
                    max(0, wickets - 1),
                    min(10, wickets + 1)
                )
            )

        else:

            # -------------------------------------------------
            # OLD DATABASE COMPATIBILITY
            # -------------------------------------------------

            query = """
                SELECT won
                FROM win_states
                WHERE league = ?
                  AND innings_no = ?
                  AND ball_no BETWEEN ? AND ?
                  AND wickets BETWEEN ? AND ?
            """

            data = pd.read_sql_query(
                query,
                connection,
                params=(
                    league,
                    innings_no,
                    max(1, ball_no - 1),
                    ball_no + 1,
                    max(0, wickets - 1),
                    min(10, wickets + 1)
                )
            )


        # -------------------------------------------------
        # WIDER SEARCH
        # -------------------------------------------------

        if len(data) < 20:

            if team_columns_available:

                query = """
                    SELECT won
                    FROM win_states
                    WHERE league = ?
                      AND batting_team = ?
                      AND bowling_team = ?
                      AND innings_no = ?
                      AND ball_no BETWEEN ? AND ?
                """

                data = pd.read_sql_query(
                    query,
                    connection,
                    params=(
                        league,
                        batting_team,
                        bowling_team,
                        innings_no,
                        max(1, ball_no - 3),
                        ball_no + 3
                    )
                )

            else:

                query = """
                    SELECT won
                    FROM win_states
                    WHERE league = ?
                      AND innings_no = ?
                      AND ball_no BETWEEN ? AND ?
                """

                data = pd.read_sql_query(
                    query,
                    connection,
                    params=(
                        league,
                        innings_no,
                        max(1, ball_no - 3),
                        ball_no + 3
                    )
                )


        # -------------------------------------------------
        # FINAL FALLBACK
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
                    max(0, wickets - 1),
                    min(10, wickets + 1)
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

        try:
            connection.close()
        except Exception:
            pass

        return None


# =========================================================
# FUTURE RUN CALCULATION
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

    try:

        query = """
            SELECT future_runs
            FROM samples
            WHERE league = ?
              AND innings_no = ?
              AND ball_no BETWEEN ? AND ?
              AND target_ball = ?
        """

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

        try:
            connection.close()
        except Exception:
            pass

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

        try:
            connection.close()
        except Exception:
            pass

        st.warning(
            "Database found, but statistics could not be read."
        )

else:

    st.error(
        "Historical database not found."
    )

    st.info(
        "The app is running, but the historical cricket "
        "database has not been connected yet."
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
        ],
        key="league"
    )


    teams = TEAMS.get(
        league,
        TEAMS["Other"]
    )


    batting_team = st.selectbox(
        "Batting Team",
        teams,
        index=None,
        placeholder="Select batting team",
        key="batting_team"
    )


    bowling_options = [
        team
        for team in teams
        if team != batting_team
    ]


    bowling_team = st.selectbox(
        "Bowling Team",
        bowling_options,
        index=None,
        placeholder="Select bowling team",
        key="bowling_team"
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
        "Target / Future Ball",
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

    if batting_team is None or bowling_team is None:

        st.error(
            "Please select both Batting Team and Bowling Team."
        )

        st.stop()


    if batting_team == bowling_team:

        st.error(
            "Batting Team and Bowling Team cannot be the same."
        )

        st.stop()


    if not os.path.exists(DB):

        st.error(
            "Historical database not found. "
            "The app cannot calculate a real historical percentage "
            "until the database is connected."
        )

        st.stop()


    innings_no = (
        1
        if innings == "1st Innings"
        else 2
    )


    # -----------------------------------------------------
    # CONVERT CRICKET OVER
    # -----------------------------------------------------

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

    if ball_in_over < 0:
        ball_in_over = 0

    current_ball = (
        over_number * 6
        + ball_in_over
    )


    # -----------------------------------------------------
    # ANALYSIS HEADER
    # -----------------------------------------------------

    st.header("🧠 DREAM ANALYSIS")


    st.write(
        f"**{batting_team}** "
        f"vs "
        f"**{bowling_team}**"
    )


    st.write(
        f"Score: **{runs}/{wickets}** "
        f"after **{overs} overs**"
    )


    st.write(
        f"League: **{league}**"
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


    # =====================================================
    # HISTORICAL RESULT
    # =====================================================

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
            "इस situation के लिए पर्याप्त historical "
            "data नहीं मिला। Percentage नहीं बनाई गई।"
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
            f"Historical YES: "
            f"**{result['yes_count']:,}**"
        )


        st.write(
            f"Historical NO: "
            f"**{result['no_count']:,}**"
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
                "Future Ball current ball से आगे होना चाहिए."
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
