import streamlit as st


# =========================================================
# DREAM PROJECT
# =========================================================

st.set_page_config(
    page_title="Dream Project",
    page_icon="🏏",
    layout="wide"
)


# =========================================================
# HEADER
# =========================================================

st.title("🏏 DREAM PROJECT")

st.subheader("Cricket Historical + AI Situation Analyzer")

st.write(
    "Live cricket की current situation डालें। "
    "Dream Project historical data और AI analysis के आधार पर "
    "result calculate करेगा."
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
# EXTRA CURRENT INFORMATION
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
# ANALYZE BUTTON
# =========================================================

st.divider()

analyze = st.button(
    "🔍 ANALYZE CURRENT SITUATION",
    use_container_width=True
)


# =========================================================
# ANALYSIS
# =========================================================

if analyze:

    st.header("🧠 DREAM ANALYSIS")

    # Current situation display

    st.subheader("Current Situation")

    st.write(
        f"**{batting_team or 'Batting Team'}** "
        f"— **{runs}/{wickets}** "
        f"after **{overs} overs**"
    )

    st.write(
        f"League: **{league}**"
    )

    st.write(
        f"Ground: **{ground or 'Not entered'}**"
    )

    st.write(
        f"Bowling Team: **{bowling_team or 'Not entered'}**"
    )

    st.write(
        f"Innings: **{innings}**"
    )

    st.write(
        f"Format: **{match_format}**"
    )

    if target > 0:

        st.write(
            f"Target / Session: **{target}**"
        )

    st.divider()


    # =====================================================
    # YES / NO RESULT
    # =====================================================

    st.subheader("📈 Historical + AI Result")


    result_col1, result_col2 = st.columns(2)


    with result_col1:

        st.metric(
            label="YES",
            value="—"
        )


    with result_col2:

        st.metric(
            label="NO",
            value="—"
        )


    st.info(
        "Historical database और AI calculation engine "
        "अभी connect किया जा रहा है। "
        "इस stage पर कोई अनुमानित percentage नहीं दिखाई जाएगी।"
    )


    # =====================================================
    # HISTORICAL DATA STATUS
    # =====================================================

    st.subheader("📚 Historical Data")

    st.write(
        "Dream Project current situation को historical "
        "matches से compare करेगा."
    )

    st.write(
        "Similar historical situations मिलने के बाद "
        "उनके वास्तविक outcomes से percentage calculate होगी."
    )


    # =====================================================
    # TRANSPARENCY
    # =====================================================

    st.divider()

    st.subheader("🔎 Transparency")

    st.write(
        "Result वही percentage होगी जो available historical "
        "data और model calculation से निकलती है."
    )

    st.write(
        "System percentage को artificially बढ़ाकर या घटाकर "
        "नहीं दिखाएगा."
    )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "DREAM PROJECT • Cricket Data Intelligence System"
)
