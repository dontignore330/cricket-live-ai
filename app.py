import streamlit as st
import pandas as pd
import os
import time

st.set_page_config(
    page_title="Isolated Cricket Match Analyzer (Past vs Live)",
    page_icon="📊",
    layout="wide"
)

# --- PASSWORD PROTECTION SYSTEM (Password: Amit4455) ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "Amit4455":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state or not st.session_state["password_correct"]:
        st.markdown("<h2 style='text-align: center;'>🔐 Restricted Access - Private App</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>यह ऐप पूरी तरह प्राइवेट है। उपयोग करने के लिए कृपया पासवर्ड दर्ज करें।</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.text_input("Enter Password", type="password", on_change=password_entered, key="password")
            if "password_correct" in st.session_state and not st.session_state["password_correct"]:
                st.error("😕 गलत पासवर्ड! कृपया सही पासवर्ड डालें।")
        return False
    else:
        return True

if not check_password():
    st.stop()

# --- MAIN APP CODE ---
st.markdown("""
    <style>
    .main { background-color: #0e1117; color: #ffffff; }
    .stButton>button { background-color: #ff4b4b; color: white; font-weight: bold; border-radius: 8px; width: 100%; height: 50px; }
    .metric-card { background-color: #1e2530; padding: 15px; border-radius: 10px; border: 1px solid #30363d; text-align: center; }
    .box-card { background-color: #161b22; padding: 20px; border-radius: 10px; border: 1px solid #30363d; margin-bottom: 15px; }
    .live-analysis-box { background-color: #111c24; padding: 20px; border-radius: 10px; border: 1px solid #0ea5e9; margin-bottom: 15px; }
    .past-data-box { background-color: #1e1b18; padding: 20px; border-radius: 10px; border: 1px solid #f59e0b; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

st.title("📊 Isolated Cricket Match Analyzer (Separate Past Facts & Live Context)")
st.markdown("---")

# --- LOAD HISTORICAL DATA SAFELY ---
@st.cache_data
def load_data():
    csv_file = "match_data.csv"
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file)
        if 'innings' not in df.columns:
            df['innings'] = '1st Inning'
        if 'target_score' not in df.columns:
            df['target_score'] = 0
        return df
    else:
        return pd.DataFrame({
            'league': ['IPL', 'WPL', 'Men BBL', 'Women BBL'],
            'season': [2024, 2024, 2024, 2024],
            'innings': ['1st Inning', '2nd Inning (Target Chasing)', '1st Inning', '2nd Inning (Target Chasing)'],
            'target_score': [0, 180, 0, 165],
            'venue': ['Adelaide Oval', 'Sydney Cricket Ground', 'Adelaide Oval', 'North Sydney Oval'],
            'batting_team': ['Adelaide Strikers', 'Sydney Sixers', 'Adelaide Strikers', 'Sydney Sixers Women'],
            'bowling_team': ['Sydney Sixers', 'Adelaide Strikers', 'Melbourne Stars', 'Adelaide Strikers Women'],
            'current_over': [3.0, 3.0, 3.0, 3.0],
            'current_runs': [30, 35, 25, 28],
            'current_wickets': [0, 1, 0, 0],
            'target_over': [6, 6, 6, 6],
            'final_phase_runs': [60, 65, 52, 55],
            'match_winner_type': ['Batting 1st Won', 'Batting 2nd Won', 'Batting 1st Won', 'Batting 2nd Won']
        })

df_history = load_data()

# --- SIDEBAR & LIVE INPUT CONTROLS ---
st.sidebar.header("🛠️ Live Match Control Center")

selected_league = st.sidebar.selectbox("Select Cricket League / Format", [
    "IPL (Indian Premier League)", 
    "WPL (Women's Premier League)", 
    "Men BBL (Big Bash League)", 
    "Women BBL (WBBL)"
])

if "IPL" in selected_league and "Women" not in selected_league:
    league_key = "IPL"
elif "WPL" in selected_league:
    league_key = "WPL"
elif "Men BBL" in selected_league:
    league_key = "Men BBL"
else:
    league_key = "Women BBL"

match_innings = st.sidebar.selectbox("Select Innings", [
    "1st Inning", 
    "2nd Inning (Target Chasing)"
])

team_batting = st.sidebar.text_input("Batting Team (Live)", "Adelaide Strikers")
team_bowling = st.sidebar.text_input("Bowling Team (Live)", "Sydney Sixers")

st.sidebar.markdown("---")
ground_name = st.sidebar.text_input("Stadium / Ground", "Adelaide Oval")
pitch_behavior = st.sidebar.selectbox("Pitch Condition", [
    "Batting Friendly (High Scoring)", 
    "Balanced Pitch", 
    "Bowling / Seam Friendly", 
    "Spin Friendly (Dry Track)"
])

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Live Match Current Situation")
current_over = st.sidebar.number_input("Current Overs (e.g., 3.0)", min_value=0.0, max_value=20.0, value=3.0, step=0.1)
current_runs = st.sidebar.number_input("Current Runs Scored", min_value=0, max_value=300, value=30)
current_wickets = st.sidebar.number_input("Current Wickets Fallen", min_value=0, max_value=10, value=0)

target_score_input = 0
if match_innings == "2nd Inning (Target Chasing)":
    target_score_input = st.sidebar.number_input("Target Score to Chase", min_value=50, max_value=300, value=180)

target_future_over = st.sidebar.slider("Analyze Past Data At Over:", min_value=1, max_value=20, value=6)

if 'dynamic_matches' not in st.session_state:
    st.session_state['dynamic_matches'] = []

# --- MAIN SCREEN LAYOUT: TWO SEPARATE COLUMNS (LEFT: LIVE CONTEXT, RIGHT: PAST DATA) ---
st.subheader(f"🔴 Live Match [{league_key}] | {match_innings}")
st.markdown(f"**Batting:** {team_batting} vs **Bowling:** {team_bowling} | **Ground:** {ground_name} | **Pitch:** {pitch_behavior}")

# Live Calculations
current_rr = round(current_runs / current_over, 2) if current_over > 0 else 0.0
if match_innings == "2nd Inning (Target Chasing)":
    runs_needed = target_score_input - current_runs
    balls_bowled = int(current_over) * 6 + int(round((current_over % 1) * 10))
    balls_left = max(1, 120 - balls_bowled)
    req_rr = round((runs_needed / balls_left) * 6, 2)
else:
    runs_needed = 0
    req_rr = 0.0

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(f'<div class="metric-card"><h4>Live Over</h4><h2>{current_over}</h2></div>', unsafe_allow_html=True)
with m2:
    st.markdown(f'<div class="metric-card"><h4>Score</h4><h2>{current_runs}/{current_wickets}</h2></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><h4>Current RR</h4><h2>{current_rr}</h2></div>', unsafe_allow_html=True)
with m4:
    if match_innings == "2nd Inning (Target Chasing)":
        st.markdown(f'<div class="metric-card"><h4>Required RR</h4><h2>{req_rr}</h2></div>', unsafe_allow_html=True)
    else:
        proj_1st = int(current_rr * 20)
        st.markdown(f'<div class="metric-card"><h4>Projected Score</h4><h2>{proj_1st}</h2></div>', unsafe_allow_html=True)

st.markdown("---")

# --- TWO SEPARATE COLUMNS FOR INDEPENDENT VIEW ---
col_left, col_right = st.columns(2)

# ================= COL LEFT: LIVE CONTEXT & RUN-RATE SCENARIO (SEPARATE) =================
with col_left:
    st.markdown("### 📈 1. Current Situation & Run-Rate Scenario")
    st.markdown("*(यह केवल वर्तमान रन-रेट, पिच और ओवर के आधार पर संभावित संभावना दिखा रहा है — कोई पास्ट डेटा मिक्स नहीं है)*")
    
    # Independent live projection text
    if match_innings == "1st Inning":
        proj_score = int(current_rr * 20)
        live_scenario_text = f"वर्तमान रन-रेट **{current_rr}** के हिसाब से, यदि यही गति रही तो अनुमानित स्कोर लगभग **{proj_score} रन** तक जा सकता है। पिच का मिजाज **'{pitch_behavior}'** है।"
    else:
        live_scenario_text = f"चेजिंग के दौरान वर्तमान रन-रेट **{current_rr}** है और आवश्यक रन-रेट **{req_rr}** है। लक्ष्य **{target_score_input} रन** का है। पिच **'{pitch_behavior}'** है।"

    st.markdown(f"""
    <div class="live-analysis-box">
        <b>🏟️ ग्राउंड और पिच:</b> {ground_name} ({pitch_behavior})<br><br>
        <b>📊 वर्तमान स्थिति का परिदृश्य (Live Scenario):</b><br>
        {live_scenario_text}
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("💡 *आप अपनी समझ से इस करंट सिनेरियो का उपयोग कर सकते हैं।*")

# ================= COL RIGHT: STRICT PAST 5-YEARS DATA (SEPARATE) =================
with col_right:
    st.markdown("### 🗄️ 2. Strict Past 5-Years Records")
    st.markdown("*(यह पिछले 5 सालों का बिल्कुल शुद्ध और ओरिजिनल डेटा है — बिना किसी बदलाव के)*")

    if st.button("🚀 Load Strict Past Data"):
        if current_over <= 0:
            st.error("कृपया वैध ओवर दर्ज करें।")
        else:
            with st.spinner("पिछले 5 सालों का ओरिजिनल डेटा निकाला जा रहा है..."):
                time.sleep(0.6)
                
                # Combine CSV data and session custom data
                df_dyn = pd.DataFrame(st.session_state['dynamic_matches'])
                if not df_dyn.empty:
                    combined_df = pd.concat([df_history, df_dyn], ignore_index=True)
                else:
                    combined_df = df_history
                
                # Filter strictly by League and Innings
                league_df = combined_df[
                    (combined_df['league'] == league_key) & 
                    (combined_df['innings'] == match_innings)
                ]
                
                if match_innings == "2nd Inning (Target Chasing)":
                    league_df = league_df[
                        (league_df['target_score'] >= target_score_input - 20) & 
                        (league_df['target_score'] <= target_score_input + 20)
                    ]

                # Head-to-Head Record
                h2h_df = league_df[
                    (league_df['batting_team'].str.strip().str.lower() == team_batting.strip().lower()) & 
                    (league_df['bowling_team'].str.strip().str.lower() == team_bowling.strip().lower()) &
                    (league_df['current_over'] == current_over) &
                    (league_df['current_wickets'] == current_wickets)
                ]
                
                # General Record
                general_df = league_df[
                    (league_df['batting_team'].str.strip().str.lower() == team_batting.strip().lower()) &
                    (league_df['current_over'] == current_over) &
                    (league_df['current_wickets'] == current_wickets)
                ]
                
                st.markdown("---")
                # Display H2H Past Facts
                if not h2h_df.empty:
                    h2h_avg_runs = int(h2h_df['final_phase_runs'].mean())
                    h2h_winners = h2h_df['match_winner_type'].value_counts()
                    h2h_b1 = h2h_winners.get('Batting 1st Won', 0)
                    h2h_b2 = h2h_winners.get('Batting 2nd Won', 0)
                    h2h_total = h2h_b1 + h2h_b2
                    h2h_p1_pct = int((h2h_b1 / h2h_total) * 100) if h2h_total > 0 else 0
                    h2h_p2_pct = 100 - h2h_p1_pct
                    
                    st.markdown(f"""
                    <div class="past-data-box">
                        <b>📌 Head-to-Head रिकॉर्ड ({len(h2h_df)} मैच मिले):</b><br>
                        • औसत अंतिम रन: {h2h_avg_runs} Runs<br>
                        • पास्ट रिजल्ट: Batting 1st Won ({h2h_p1_pct}%) | Batting 2nd Won ({h2h_p2_pct}%)
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.warning("⚠️ इस Head-to-Head सिचुएशन का कोई पास्ट रिकॉर्ड नहीं मिला।")

                # Display General Past Facts
                if not general_df.empty:
                    gen_avg_runs = int(general_df['final_phase_runs'].mean())
                    gen_winners = general_df['match_winner_type'].value_counts()
                    gen_b1 = gen_winners.get('Batting 1st Won', 0)
                    gen_b2 = gen_winners.get('Batting 2nd Won', 0)
                    gen_total = gen_b1 + gen_b2
                    gen_p1_pct = int((gen_b1 / gen_total) * 100) if gen_total > 0 else 0
                    gen_p2_pct = 100 - gen_p1_pct
                    
                    st.markdown(f"""
                    <div class="past-data-box">
                        <b>📌 General Batting रिकॉर्ड ({len(h2h_df) if not h2h_df.empty else 'अन्य टीमों के खिलाफ'} {len(general_df)} मैच मिले):</b><br>
                        • इस फेज में औसत रन: {gen_avg_runs} Runs<br>
                        • पास्ट रिजल्ट ट्रेंड: Batting 1st Won ({gen_p1_pct}%) | Batting 2nd Won ({gen_p2_pct}%)
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.expander("📂 पिछले 5 साल के ओरिजिनल मैच रिकॉर्ड्स की पूरी लिस्ट देखें"):
                        st.dataframe(general_df[['season', 'venue', 'innings', 'target_score', 'batting_team', 'bowling_team', 'current_over', 'current_runs', 'current_wickets', 'match_winner_type']])
                else:
                    st.warning("⚠️ पिछले 5 सालों का इस टीम का जनरल डेटा नहीं मिला।")

st.markdown("---")
st.subheader("💾 Save Match Data to Database")
with st.expander("➕ नया पास्ट डेटा सेव करें"):
    saved_target = target_score_input if match_innings == "2nd Inning (Target Chasing)" else 0
    saved_final_runs = st.number_input("Actual Final Phase Runs Scored:", min_value=0, max_value=300, value=50)
    saved_winner = st.selectbox("Actual Match Winner Result:", ["Batting 1st Won", "Batting 2nd Won"])
    
    if st.button("Save to 5-Year Database"):
        new_entry = {
            'league': league_key,
            'season': 2026,
            'innings': match_innings,
            'target_score': saved_target,
            'venue': ground_name,
            'batting_team': team_batting,
            'bowling_team': team_bowling,
            'current_over': current_over,
            'current_runs': current_runs,
            'current_wickets': current_wickets,
            'target_over': target_future_over,
            'final_phase_runs': saved_final_runs,
            'match_winner_type': saved_winner
        }
        st.session_state['dynamic_matches'].append(new_entry)
        st.success("डेटा सफलतापूर्वक सेव हो गया!")

st.markdown("<p style='text-align: center; color: gray;'>Isolated Match Analyzer | Separate Live Scenario & Past Facts</p>", unsafe_allow_html=True)
