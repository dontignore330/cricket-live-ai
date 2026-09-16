import sqlite3
import math
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("cricket_history.db")

st.set_page_config(page_title="Dream Project", page_icon="🏏", layout="wide")

st.markdown("""
<style>
.main { background: #07111f; }
.block-container { padding-top: 1.5rem; }
.card { background:#0f1b2d; padding:18px; border-radius:14px; border:1px solid #26364d; }
.result_yes { background:#06351f; padding:22px; border-radius:16px; border:2px solid #20c77a; text-align:center; }
.result_no { background:#3d1010; padding:22px; border-radius:16px; border:2px solid #ef5350; text-align:center; }
.muted { color:#94a3b8; }
</style>
""", unsafe_allow_html=True)

# -------------------------
# Database
# -------------------------
@st.cache_resource

def get_conn():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = get_conn()

st.title("🏏 DREAM PROJECT")
st.caption("Cricket Historical + AI Situation Analyzer")
st.write("Enter the current cricket situation. The system compares it with real historical match data.")

if conn is None:
    st.error("Historical database not found.")
    st.info("The app is running, but the historical cricket database has not been connected yet.")
    st.stop()

try:
    match_count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    delivery_count = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
except Exception as e:
    st.error(f"Database could not be read: {e}")
    st.stop()

st.success(f"Historical database connected • {match_count:,} matches • {delivery_count:,} deliveries")

# -------------------------
# Helpers
# -------------------------
def get_values(sql, params=()):
    rows = conn.execute(sql, params).fetchall()
    return [r[0] for r in rows if r[0] not in (None, "")]


def balls_from_over_ball(value):
    """Convert cricket notation 3.3 -> 21 legal-ball position."""
    whole = int(math.floor(float(value) + 1e-9))
    tenth = int(round((float(value) - whole) * 10))
    # Normal cricket notation is 0..5 balls.
    if tenth > 5:
        whole += tenth // 6
        tenth = tenth % 6
    return whole * 6 + tenth


def over_ball_from_balls(balls):
    return f"{balls // 6}.{balls % 6}"


def phase_for_ball(ball_position):
    overs = ball_position / 6.0
    if overs < 6:
        return "Powerplay"
    if overs < 15:
        return "Middle"
    return "Death"


def safe_round(x):
    return int(round(float(x)))


def historical_win_analysis(batting, bowling, venue, innings_no, ball_pos, wickets):
    """Return historical eventual-match-result states with progressive fallback."""
    # Exact match first. Then progressively relax venue/wickets so the app never crashes
    # or silently returns a misleading zero just because an exact combination is rare.
    attempts = [
        ("team + ground + innings + wickets", """SELECT won FROM win_states
         WHERE league='IPL' AND batting_team=? AND bowling_team=? AND innings_no=?
           AND ABS(ball_no-?) < 0.001 AND wickets=?""", (batting, bowling, innings_no, ball_pos, wickets)),
        ("team + ground + innings", """SELECT won FROM win_states
         WHERE league='IPL' AND batting_team=? AND bowling_team=? AND innings_no=?
           AND ABS(ball_no-?) < 0.001""", (batting, bowling, innings_no, ball_pos)),
        ("team + innings + wickets", """SELECT w.won FROM win_states w
         JOIN matches m ON m.match_id=w.match_id
         WHERE w.league='IPL' AND w.batting_team=? AND w.bowling_team=? AND w.innings_no=?
           AND ABS(w.ball_no-?) < 0.001 AND w.wickets=?""", (batting, bowling, innings_no, ball_pos, wickets)),
        ("team + innings", """SELECT won FROM win_states
         WHERE league='IPL' AND batting_team=? AND bowling_team=? AND innings_no=?
           AND ABS(ball_no-?) < 0.001""", (batting, bowling, innings_no, ball_pos)),
    ]

    # First two attempts cannot distinguish venue because win_states intentionally contains
    # the compact state columns. Use match_id to apply venue when requested.
    attempts = [
        ("team + ground + innings + wickets", """SELECT w.won FROM win_states w
         JOIN matches m ON m.match_id=w.match_id
         WHERE w.league='IPL' AND w.batting_team=? AND w.bowling_team=? AND m.venue=?
           AND w.innings_no=? AND ABS(w.ball_no-?) < 0.001 AND w.wickets=?""", (batting, bowling, venue, innings_no, ball_pos, wickets)),
        ("team + ground + innings", """SELECT w.won FROM win_states w
         JOIN matches m ON m.match_id=w.match_id
         WHERE w.league='IPL' AND w.batting_team=? AND w.bowling_team=? AND m.venue=?
           AND w.innings_no=? AND ABS(w.ball_no-?) < 0.001""", (batting, bowling, venue, innings_no, ball_pos)),
        ("team + innings + wickets", """SELECT won FROM win_states
         WHERE league='IPL' AND batting_team=? AND bowling_team=? AND innings_no=?
           AND ABS(ball_no-?) < 0.001 AND wickets=?""", (batting, bowling, innings_no, ball_pos, wickets)),
        ("team + innings", """SELECT won FROM win_states
         WHERE league='IPL' AND batting_team=? AND bowling_team=? AND innings_no=?
           AND ABS(ball_no-?) < 0.001""", (batting, bowling, innings_no, ball_pos)),
    ]

    for label, sql, params in attempts:
        try:
            vals = [int(r[0]) for r in conn.execute(sql, params).fetchall()]
            if vals:
                yes = sum(vals)
                total = len(vals)
                return yes, total - yes, total, label
        except Exception:
            continue
    return 0, 0, 0, "no matching historical states"


def historical_future_samples(batting, bowling, venue, innings_no, current_ball, current_wickets, target_ball):
    """Build historical current-score -> target-score samples directly from deliveries."""
    if target_ball <= current_ball:
        return [], "Target/Future point must be after the current ball."

    # Pull only the selected team matchup. This is small compared with the full database.
    sql = """SELECT d.match_id, d.innings_no, d.batting_team, d.bowling_team,
                    d.over_no, d.ball_no, d.runs, d.wickets
             FROM deliveries d
             JOIN matches m ON m.match_id=d.match_id
             WHERE d.league='IPL'
               AND d.batting_team=? AND d.bowling_team=?
               AND d.innings_no=? AND m.venue=?
             ORDER BY d.match_id, d.innings_no, d.id"""

    params = (batting, bowling, innings_no, venue)
    df = pd.read_sql_query(sql, conn, params=params)

    # If the exact ground has no usable samples, retry matchup without ground.
    source_label = "team + ground + innings"
    if df.empty:
        sql2 = """SELECT match_id, innings_no, batting_team, bowling_team,
                         over_no, ball_no, runs, wickets
                  FROM deliveries
                  WHERE league='IPL' AND batting_team=? AND bowling_team=? AND innings_no=?
                  ORDER BY match_id, innings_no, id"""
        df = pd.read_sql_query(sql2, conn, params=(batting, bowling, innings_no))
        source_label = "team + innings"

    if df.empty:
        return [], "No historical deliveries found for this team combination."

    samples = []

    # Match by the same current ball position. Current score is checked against the
    # historical score with a small tolerance because exact scores are often sparse.
    for (match_id, inn), g in df.groupby(["match_id", "innings_no"], sort=False):
        g = g.sort_values("id" if "id" in g.columns else ["over_no", "ball_no"]).copy()
        # Reconstruct cumulative score and wickets after each recorded delivery.
        g["cum_runs"] = g["runs"].cumsum()
        g["cum_wk"] = g["wickets"].cumsum()
        # Convert stored cricket notation (e.g. 3.3) to a simple ball position.
        g["position"] = g["ball_no"].apply(balls_from_over_ball)

        current_rows = g[g["position"] == int(current_ball)]
        if current_rows.empty:
            continue

        cur = current_rows.iloc[-1]
        hist_score = float(cur["cum_runs"])
        hist_wk = int(cur["cum_wk"])

        # Match current wickets exactly; this keeps the comparison genuinely situation-based.
        if hist_wk != int(current_wickets):
            continue

        # Current live score is not stored in this function's arguments, so caller will
        # apply score filtering after receiving the raw sample tuple.
        target_rows = g[g["position"] <= int(target_ball)]
        if target_rows.empty:
            continue
        target_row = target_rows.iloc[-1]
        target_score = float(target_row["cum_runs"])
        future_runs = target_score - hist_score
        samples.append((hist_score, target_score, future_runs, match_id))

    return samples, source_label


def build_future_samples(batting, bowling, venue, innings_no, current_ball, current_runs, current_wickets, target_ball):
    raw, source_label = historical_future_samples(
        batting, bowling, venue, innings_no, current_ball, current_wickets, target_ball
    )

    # Prefer situations close to the live score. If exact ground gives too few, progressively
    # broaden the search so an ordinary live state still receives a useful historical sample.
    for tolerance in (2, 4, 6, 10, 15):
        selected = [x for x in raw if abs(x[0] - current_runs) <= tolerance]
        if len(selected) >= 20:
            return selected, source_label + f" • current-score tolerance ±{tolerance}"

    # If ground is too restrictive, redo without ground.
    if source_label.startswith("team + ground"):
        sql = """SELECT match_id, innings_no, batting_team, bowling_team,
                         over_no, ball_no, runs, wickets, id
                  FROM deliveries
                  WHERE league='IPL' AND batting_team=? AND bowling_team=? AND innings_no=?
                  ORDER BY match_id, innings_no, id"""
        df = pd.read_sql_query(sql, conn, params=(batting, bowling, innings_no))
        raw2 = []
        for (match_id, inn), g in df.groupby(["match_id", "innings_no"], sort=False):
            g = g.sort_values("id").copy()
            g["cum_runs"] = g["runs"].cumsum()
            g["cum_wk"] = g["wickets"].cumsum()
            g["position"] = g["ball_no"].apply(balls_from_over_ball)
            cr = g[g["position"] == int(current_ball)]
            if cr.empty:
                continue
            cur = cr.iloc[-1]
            if int(cur["cum_wk"]) != int(current_wickets):
                continue
            tr = g[g["position"] <= int(target_ball)]
            if tr.empty:
                continue
            tar = tr.iloc[-1]
            raw2.append((float(cur["cum_runs"]), float(tar["cum_runs"]), float(tar["cum_runs"]-cur["cum_runs"]), match_id))
        raw = raw2
        source_label = "team + innings"

    if not raw:
        return [], source_label

    # Best available tolerance if fewer than 20 samples.
    selected = [x for x in raw if abs(x[0] - current_runs) <= 15]
    return (selected if selected else raw), source_label + (" • broad historical match" if not selected else " • current-score tolerance ±15")

# -------------------------
# IPL-only dynamic lists
# -------------------------
league = st.selectbox("League / Tournament", ["IPL"])

try:
    teams = get_values("""SELECT DISTINCT batting_team FROM deliveries
                           WHERE league='IPL' ORDER BY batting_team""")
    venues = get_values("""SELECT DISTINCT venue FROM matches
                            WHERE league='IPL' AND venue IS NOT NULL AND venue<>''
                            ORDER BY venue""")
except Exception:
    teams, venues = [], []

# Fallback IPL teams only if database query ever fails.
if not teams:
    teams = [
        "Chennai Super Kings", "Delhi Capitals", "Gujarat Titans",
        "Kolkata Knight Riders", "Lucknow Super Giants", "Mumbai Indians",
        "Punjab Kings", "Rajasthan Royals", "Royal Challengers Bengaluru",
        "Sunrisers Hyderabad"
    ]
if not venues:
    venues = ["Rajiv Gandhi International Stadium, Hyderabad"]

st.subheader("🏏 Current Match")
col1, col2 = st.columns(2)
with col1:
    batting = st.selectbox("Batting Team", teams, index=teams.index("Sunrisers Hyderabad") if "Sunrisers Hyderabad" in teams else 0)
    bowling_options = [t for t in teams if t != batting]
    bowling = st.selectbox("Bowling Team", bowling_options, index=bowling_options.index("Rajasthan Royals") if "Rajasthan Royals" in bowling_options else 0)
with col2:
    venue = st.selectbox("Ground", venues, index=venues.index("Rajiv Gandhi International Stadium, Hyderabad") if "Rajiv Gandhi International Stadium, Hyderabad" in venues else 0)
    innings_label = st.selectbox("Innings", ["1st Innings", "2nd Innings"])

col3, col4, col5 = st.columns(3)
with col3:
    current_over = st.number_input("Current Over / Ball", min_value=0.0, max_value=19.5, value=3.0, step=0.1, format="%.1f")
with col4:
    current_runs = st.number_input("Current Runs", min_value=0, max_value=400, value=16, step=1)
with col5:
    wickets = st.number_input("Wickets", min_value=0, max_value=10, value=1, step=1)

st.subheader("🎯 Target & Future Point")
st.caption("Dono alag hain: Future Point = kis over/ball tak dekhna hai. Target Runs = us point tak kitne runs chahiye.")

col6, col7, col8 = st.columns(3)
with col6:
    future_over = st.number_input("Future Ball / Over", min_value=0.1, max_value=20.0, value=6.0, step=0.1, format="%.1f")
with col7:
    target_runs = st.number_input("Target Runs", min_value=0, max_value=400, value=50, step=1)
with col8:
    match_format = st.selectbox("Match Format", ["T20"])

current_ball = balls_from_over_ball(current_over)
target_ball = balls_from_over_ball(future_over)
innings_no = 1 if innings_label == "1st Innings" else 2
remaining_to_future = max(0, target_ball - current_ball)

st.info(
    f"**Live situation:** {current_runs}/{wickets} at {over_ball_from_balls(current_ball)}  •  "
    f"**Future point:** {over_ball_from_balls(target_ball)}  •  "
    f"**Balls remaining:** {remaining_to_future}  •  **Target:** {target_runs} runs"
)

if target_ball <= current_ball:
    st.warning("Future Ball / Over must be later than the current Over / Ball.")

if st.button("🔎 ANALYZE HISTORICAL SITUATION", use_container_width=True, disabled=(target_ball <= current_ball)):
    st.subheader("🧠 DREAM ANALYSIS")
    st.markdown(
        f"**{batting}** vs **{bowling}**  \n"
        f"Score: **{current_runs}/{wickets}** after **{over_ball_from_balls(current_ball)} overs**  \n"
        f"League: **IPL**  \n"
        f"Ground: **{venue}**  \n"
        f"Innings: **{innings_label}**  \n"
        f"Format: **{match_format}**  \n"
        f"Historical ball position: **{current_ball}**"
    )

    # 1) Existing-style historical YES/NO match-result state analysis.
    yes, no, total, method = historical_win_analysis(
        batting, bowling, venue, innings_no, current_ball, wickets
    )

    st.markdown("### 📈 Historical Result")
    if total:
        yes_pct = yes / total * 100
        no_pct = no / total * 100
        a, b = st.columns(2)
        a.metric("YES", f"{yes_pct:.1f}%")
        b.metric("NO", f"{no_pct:.1f}%")
        st.write(f"Calculation based on **{total} historical states**.")
        st.write(f"Historical YES: **{yes}**  •  Historical NO: **{no}**")
        st.caption(f"Historical state filter: {method}")
    else:
        st.info("No matching historical result states were found for this exact situation. Try another ground, over/ball, or team combination.")

    # 2) Target-at-future-point analysis.
    st.markdown("### 🎯 Historical Target Analysis")
    samples, source = build_future_samples(
        batting, bowling, venue, innings_no,
        current_ball, current_runs, wickets, target_ball
    )

    if samples:
        target_yes = sum(1 for x in samples if x[1] >= target_runs)
        target_no = len(samples) - target_yes
        target_pct = target_yes / len(samples) * 100
        no_pct2 = target_no / len(samples) * 100

        st.write(
            f"**Question:** Historical situations similar to **{current_runs}/{wickets} at {over_ball_from_balls(current_ball)}** — "
            f"did the batting team reach **{target_runs} runs by {over_ball_from_balls(target_ball)}**?"
        )

        if target_yes >= target_no:
            box_class = "result_yes"
            label = "YES"
            pct = target_pct
        else:
            box_class = "result_no"
            label = "NO"
            pct = no_pct2

        st.markdown(f"""
        <div class="{box_class}">
            <h1>{label}</h1>
            <h2>{pct:.1f}% historical frequency</h2>
            <p>Target: <b>{target_runs} runs</b> by <b>{over_ball_from_balls(target_ball)}</b></p>
            <p>{remaining_to_future} balls between current point and future point</p>
        </div>
        """, unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Historical YES", target_yes)
        c2.metric("Historical NO", target_no)
        c3.metric("Samples", len(samples))
        c4.metric("Avg Future Runs", safe_round(pd.Series([x[2] for x in samples]).mean()))

        future_runs = pd.Series([x[2] for x in samples])
        target_scores = pd.Series([x[1] for x in samples])
        st.write(
            f"Historical future runs: **{safe_round(future_runs.mean())} average**  •  "
            f"**{safe_round(future_runs.median())} median**  •  "
            f"10–90% range: **{safe_round(future_runs.quantile(.10))} – {safe_round(future_runs.quantile(.90))} runs**"
        )
        st.write(
            f"Historical score at future point: **{safe_round(target_scores.mean())} average**  •  "
            f"10–90% range: **{safe_round(target_scores.quantile(.10))} – {safe_round(target_scores.quantile(.90))}**"
        )
        st.caption(f"Future-target calculation source: {source}. Historical frequency, not a guarantee.")
    else:
        st.info("इस target के लिए पर्याप्त historical future-run data नहीं मिला।")

    # 3) Clear interpretation so YES is never ambiguous.
    st.markdown("### 🧾 What YES means")
    st.write(
        f"YES/NO above is **not** asking whether the current 16/{wickets} situation itself is YES. "
        f"It specifically asks whether similar historical situations reached **{target_runs} runs by {over_ball_from_balls(target_ball)}**."
    )
