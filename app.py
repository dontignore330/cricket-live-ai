import streamlit as st
import pandas as pd
import math, os

st.set_page_config(
    page_title="Apex Quant Pro",
    page_icon="🦅",
    layout="wide"
)

st.title("🦅 Apex Quant Pro — Multi-League Cricket Analytics")
st.caption("IPL • BBL • WBBL | Statistical projection & historical benchmarking")

LEAGUES = {
    "IPL": {
        "file": "ipl_features.csv",
        "full": "Indian Premier League"
    },
    "BBL": {
        "file": "bbl_features.csv",
        "full": "Big Bash League"
    },
    "WBBL": {
        "file": "wbbl_features.csv",
        "full": "Women's Big Bash League"
    },
}


@st.cache_data
def load_data(path):
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame()


league = st.sidebar.selectbox(
    "1. League / Series",
    list(LEAGUES)
)

df = load_data(LEAGUES[league]["file"])

teams = sorted(
    set(df.get("batting_team", pd.Series(dtype=str)).dropna())
    |
    set(df.get("bowling_team", pd.Series(dtype=str)).dropna())
)

venues = sorted(
    df.get("venue", pd.Series(dtype=str)).dropna().unique()
)

bat = st.sidebar.selectbox(
    "2. Batting Team",
    teams if teams else ["No data"]
)

bowl = st.sidebar.selectbox(
    "3. Bowling Team",
    [x for x in teams if x != bat] or ["No data"]
)

venue = st.sidebar.selectbox(
    "4. Ground",
    venues if venues else ["No data"]
)

innings = st.sidebar.radio(
    "5. Innings",
    ["1st innings", "2nd innings"]
)

over_raw = st.sidebar.number_input(
    "Current over.ball (e.g. 8.2)",
    min_value=0.0,
    max_value=20.5,
    value=3.0,
    step=0.1
)

runs = st.sidebar.number_input(
    "Current runs",
    min_value=0,
    max_value=350,
    value=20
)

wickets = st.sidebar.number_input(
    "Wickets down",
    min_value=0,
    max_value=10,
    value=1
)

target = st.sidebar.number_input(
    "Target (2nd innings only)",
    min_value=0,
    max_value=400,
    value=0
)

window = st.sidebar.slider(
    "Future session length (overs)",
    1,
    10,
    5
)

market = st.sidebar.number_input(
    "Market/session line (optional)",
    min_value=0.0,
    value=0.0
)


def ball_to_decimal(x):
    whole = int(x)
    ball = round((x - whole) * 10)
    ball = max(0, min(5, ball))
    return whole + ball / 6


ov = ball_to_decimal(over_raw)

phase = (
    "Powerplay"
    if ov < 6
    else ("Middle" if ov < 15 else "Death")
)

remaining = max(0, 20 - ov)

crr = runs / ov if ov else 0


st.markdown(
    f"### {bat} vs {bowl}  |  {league}  |  {venue}"
)

a, b, c, d = st.columns(4)

a.metric(
    "Over",
    f"{int(ov)}.{round((ov - int(ov)) * 6):.0f}"
)

b.metric(
    "Score",
    f"{runs}/{wickets}"
)

c.metric(
    "CRR",
    f"{crr:.2f}"
)

d.metric(
    "Phase",
    phase
)


if st.button("🚀 ANALYSE"):

    subset = df.copy()

    # Historical similarity filters,
    # progressively relaxed if data is sparse.

    if "venue" in subset:
        v = subset[
            subset.venue.astype(str).str.lower()
            == str(venue).lower()
        ]

        if len(v) >= 30:
            subset = v

    if "batting_team" in subset:
        t = subset[
            (subset.batting_team.astype(str) == bat)
            &
            (subset.bowling_team.astype(str) == bowl)
        ]

        if len(t) >= 20:
            subset = t

    if "phase" in subset:
        p = subset[
            subset.phase == phase
        ]

        if len(p) >= 20:
            subset = p

    if len(subset) == 0:
        st.warning(
            "Historical data is not available for this exact combination. "
            "Use a broader sample."
        )
        st.stop()

    # Session target is the additional runs
    # in the selected future window.

    if "future_runs" in subset:
        hist = subset["future_runs"].dropna()
    else:
        hist = pd.Series(dtype=float)

    if len(hist):

        q10, q25, q50, q75, q90 = hist.quantile(
            [.10, .25, .50, .75, .90]
        )

        projection = float(q50)
        low = float(q25)
        high = float(q75)

    else:

        # Transparent fallback.
        # No fake confidence percentage.

        phase_rate = {
            "Powerplay": 7.8,
            "Middle": 8.0,
            "Death": 9.5
        }.get(phase, 8.0)

        projection = phase_rate * window
        low = projection * 0.75
        high = projection * 1.25

    # Adjust current scoring rate modestly.

    if crr > 0:

        baseline_rate = projection / window

        adjusted_rate = (
            0.65 * baseline_rate
            +
            0.35 * crr
        )

        projection = adjusted_rate * window

    # Wicket adjustment.

    if wickets >= 6:
        projection *= 0.82

    elif wickets >= 4:
        projection *= 0.91

    st.subheader(
        "📊 Statistical Projection"
    )

    x, y, z = st.columns(3)

    x.metric(
        "Projected next session",
        f"{projection:.1f} runs"
    )

    y.metric(
        "Likely range",
        f"{max(0, low):.0f} – {high:.0f}"
    )

    z.metric(
        "Historical samples",
        f"{len(subset):,}"
    )

    if market > 0:

        edge = projection - market

        st.info(
            f"Market benchmark: {market:.1f} | "
            f"Model median: {projection:.1f} | "
            f"Difference: {edge:+.1f}"
        )

        st.caption(
            "The market line is shown separately; "
            "it is not used to manufacture a confidence percentage."
        )

    if innings == "2nd innings" and target > 0:

        need = target - runs

        rrr = (
            need / (20 - ov)
            if 20 > ov
            else math.inf
        )

        st.write(
            f"Chase requirement: **{need} runs** "
            f"from **{max(0, 20 - ov):.2f} overs** | "
            f"RRR: **{rrr:.2f}**"
        )


st.sidebar.markdown("---")

st.sidebar.caption(
    "No guaranteed win rate. "
    "Probabilities should only be shown after "
    "out-of-sample validation."
)
