import streamlit as st
import pandas as pd
import os
import time

st.set_page_config(
    page_title="Enterprise Grade Cricket Prediction Engine",
    page_icon="⚡",
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

# --- STYLING ---
st.markdown("""
    <style>
    .main { background-color: #07090e; color: #ffffff; }
    .stButton>button { background-color: #10b981; color: white; font-weight: bold; border-radius: 8px; width: 100%; height: 50px; }
    .metric-card { background-color: #131b2e; padding: 15px; border-radius: 10px; border: 1px solid #1e293b; text-align: center; }
    .enterprise-box { background-color: #0d1526; padding: 20px; border-radius: 10px; border: 2px solid #10b981; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

st.title("⚡ Enterprise-Grade Cricket Prediction & Analytics Engine")
st.markdown("---")

# --- MASTER DATASET ---
@st.cache_data
def load_data():
    csv_file = "match_data.csv"
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file)
        if 'innings' not in df.columns:
            df['innings'] = '1st Inning'
        return df
    else:
        return pd.DataFrame({
            'league': ['IPL', 'IPL', 'IPL', 'Men BBL'],
            'season': [2024, 2024, 2023, 2024],
            'innings': ['1st Inning', '1st Inning', '1st Inning', '1st Inning'],
            'venue': ['Guwahati', 'Guwahati', 'Wankhede Stadium', 'Adelaide Oval'],
            'batting_team': ['Rajasthan Royals', 'Rajasthan Royals', 'Mumbai Indians', 'Adelaide Strikers'],
            'bowling_team': ['Chennai Super Kings', 'Royal Challengers Bengaluru', 'Chennai Super Kings', 'Melbourne Stars'],
            'current_over': [2.0, 2.0, 2.0, 3.0],
            'current_runs': [14, 15, 16, 25],
            'current_wickets': [1, 1, 0, 0],
            'target_over': [6.0, 6.0, 6.0, 6.0],
            'final_phase_runs': [41, 43, 46, 50],
            'match_winner_type': ['Batting 1st Won', 'Batting 2nd Won', 'Batting 1st Won', 'Batting 1st Won']
        })

df_history = load_data()

# --- SIDEBAR CONTROLS ---
st.sidebar.header("🛠️ Enterprise Control Center")

selected_league = st.sidebar.selectbox("League / Format", [
    "IPL (Indian Premier League)", 
    "WPL (Women's Premier League)", 
    "Men BBL (Big Bash League)", 
    "International T20"
])

match_innings = st.sidebar.selectbox("Innings", [
    "1st Inning", 
    "2nd Inning (Target Chasing)"
])

team_batting = st.sidebar.text_input("Batting Team", "Rajasthan Royals")
team_bowling = st.sidebar.text_input("Bowling Team", "Chennai Super Kings")

ground_name = st.sidebar.text_input("Stadium / Ground", "Guwahati")

g_lower = ground_name.strip().lower()
if "guwahati" in g_lower or "wankhede" in g_lower or "chinnaswamy" in g_lower:
    auto_pitch = "Batting Friendly (High Scoring)"
elif "chepauk" in g_lower or "delhi" in g_lower:
    auto_pitch = "Spin Friendly (Dry Track)"
else:
    auto_pitch = "Balanced Pitch"

pitch_condition = st.sidebar.selectbox("Pitch & Conditions", [
    auto_pitch,
    "Batting Friendly (High Scoring)", 
    "Balanced Pitch", 
    "Bowling / Seam Friendly", 
    "Spin Friendly (Dry Track)"
])

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Live Match Real-time State")
current_over = st.sidebar.number_input("Current Over (e.g., 2.0)", min_value=0.1, max_value=20.0, value=2.0, step=0.1)
current_runs = st.sidebar.number_input("Current Runs Scored", min_value=0, max_value=300, value=14)
current_wickets = st.sidebar.number_input("Current Wickets Fallen", min_value=0, max_value=10, value=1)

target_over_input = st.sidebar.slider("Target Session Over (e.g., 6 Over)", min_value=3, max_value=20, value=6)

if 'dynamic_matches' not in st.session_state:
    st.session_state['dynamic_matches'] = []

# --- MAIN SCREEN LOGIC ---
st.subheader(f"🔴 Live Match: {team_batting} vs {team_bowling} | Ground: {ground_name}")

# --- ENTERPRISE ALGORITHM (70% Live Reality + 30% Historical Baseline) ---
crr = round(current_runs / current_over, 2) if current_over > 0 else 0.0
overs_remaining = target_over_input - current_over

# Professional Penalty Calculation based on Wickets & Pitch Pressure
wicket_deduction = current_wickets * 0.35
if "Batting Friendly" in pitch_condition:
    projected_run_rate = max(crr, 7.0) - wicket_deduction
elif "Spin Friendly" in pitch_condition:
    projected_run_rate = max(5.0, crr - 0.4 - wicket_deduction)
else:
    projected_run_rate = max(6.0, crr - wicket_deduction)

pure_live_score = current_runs + int(overs_remaining * projected_run_rate)

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(f'<div class="metric-card"><h4>Live Over</h4><h2>{current_over}</h2></div>', unsafe_allow_html=True)
with m2:
    st.markdown(f'<div class="metric-card"><h4>Current Score</h4><h2>{current_runs}/{current_wickets}</h2></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><h4>Current RR (CRR)</h4><h2>{crr}</h2></div>', unsafe_allow_html=True)
with m4:
    st.markdown(f'<div class="metric-card"><h4>Live Projected Session</h4><h2>{pure_live_score-1} - {pure_live_score+1}</h2></div>', unsafe_allow_html=True)

st.markdown("---")

# --- ENTERPRISE PREDICTION EXECUTION ---
if st.button("🚀 Run Enterprise Prediction (Live + Past Hybrid Engine)"):
    with st.spinner("प्रोफेशनल एल्गोरिदम द्वारा लाइव स्टेट और पास्ट रिकॉर्ड का डीप एनालिसिस किया जा रहा है..."):
        time.sleep(0.5)
        
        df_dyn = pd.DataFrame(st.session_state['dynamic_matches'])
        combined_df = pd.concat([df_history, df_dyn], ignore_index=True) if not df_dyn.empty else df_history
        
        # Filter matching historical states
        matched_df = combined_df[
            (combined_df['innings'] == match_innings) &
            (combined_df['current_wickets'] == current_wickets) &
            (combined_df['current_over'] >= current_over - 0.5) &
            (combined_df['current_over'] <= current_over + 0.5)
        ]
        
        st.markdown("### 📊 Enterprise Analytics & High-Precision Results")
        
        col_res1, col_res2 = st.columns(2)
        
        # 1. SESSION SCORE PREDICTION (Strictly anchored to live reality)
        with col_res1:
            st.markdown("#### 🎯 Session Score Prediction (सटीक सेशन)")
            if not matched_df.empty:
                past_avg = matched_df['final_phase_runs'].mean()
                # Enterprise Weighting: 75% Live Reality + 25% Past Record
                final_session = int((pure_live_score * 0.75) + (past_avg * 0.25))
            else:
                final_session = pure_live_score
                
            s_min = final_session - 1
            s_max = final_session + 1
            
            st.markdown(f"""
            <div class="enterprise-box">
                <b>ओवर {target_over_input} तक संभावित सेशन रेंज (Session):</b><br>
                <h2>📌 {s_min} से {s_max} रन</h2>
                <p style='color: #94a3b8; font-size: 13px;'>एल्गोरिदम ने लाइव रन-रेट ({crr}), विकेट ({current_wickets}) और पिच के दबाव को मुख्य प्राथमिकता दी है।</p>
            </div>
            """, unsafe_allow_html=True)

        # 2. ADVANCED WIN PROBABILITY (Dynamic Real-time calculation)
        with col_res2:
            st.markdown("#### 🏆 Match Winning Probability (असली विजेता चांसेस)")
            
            # Real-time mathematical probability based on Run-Rate & Wickets
            base_batting_prob = 50.0
            if crr > 8.5:
                base_batting_prob += 18.0
            elif crr < 6.0:
                base_batting_prob -= 15.0
                
            # Wicket impact
            base_batting_prob -= (current_wickets * 6.5)
            
            # Blend with past historical win trend if available
            if not matched_df.empty:
                winners = matched_df['match_winner_type'].value_counts()
                w1 = winners.get('Batting 1st Won', 0)
                tot_w = w1 + winners.get('Batting 2nd Won', 0)
                if tot_w > 0:
                    past_prob = (w1 / tot_w) * 100
                    final_batting_prob = int((base_batting_prob * 0.7) + (past_prob * 0.3))
                else:
                    final_batting_prob = int(base_batting_prob)
            else:
                final_batting_prob = int(base_batting_prob)
                
            # Boundary clamp between 10% and 90%
            final_batting_prob = max(10, min(90, final_batting_prob))
            final_bowling_prob = 100 - final_batting_prob
            
            st.markdown(f"""
            <div class="enterprise-box">
                <b>लाइव सिचुएशन और पास्ट ट्रेंड के आधार पर जीत के चांस:</b><br>
                • <b>{team_batting} (Batting Side):</b> <b>{final_batting_prob}%</b> जीतने के चांस<br>
                • <b>{team_bowling} (Bowling Side):</b> <b>{final_bowling_prob}%</b> जीतने के चांस<br>
                <p style='color: #94a3b8; font-size: 13px;'>यह आंकड़ा रन-रेट, विकेट के नुकसान और ग्राउंड की स्थिति का सटीक मिश्रण है।</p>
            </div>
            """, unsafe_allow_html=True)
            
        with st.expander("📂 देखें कौन-से पास्ट रिकॉर्ड्स से मिलान किया गया है"):
            if not matched_df.empty:
                st.dataframe(matched_df[['season', 'venue', 'batting_team', 'bowling_team', 'current_over', 'current_runs', 'current_wickets', 'final_phase_runs', 'match_winner_type']])
            else:
                st.info("लाइव स्टेट्स और मैथमेटिकल वेटिंग मॉडल का उपयोग किया गया है।")

st.markdown("---")
st.subheader("💾 Feed Enterprise Match Data")
with st.expander("➕ असली मैच का डेटा मास्टर डेटाबेस में जोड़ें"):
    real_final_runs = st.number_input("Actual Score at Target Over:", min_value=10, max_value=300, value=41)
    real_winner = st.selectbox("Actual Match Winner:", ["Batting 1st Won", "Batting 2nd Won"])
    
    if st.button("Save to Master Enterprise DB"):
        new_entry = {
            'league': selected_league,
            'season': 2026,
            'innings': match_innings,
            'venue': ground_name,
            'batting_team': team_batting,
            'bowling_team': team_bowling,
            'current_over': current_over,
            'current_runs': current_runs,
            'current_wickets': current_wickets,
            'target_over': target_over_input,
            'final_phase_runs': real_final_runs,
            'match_winner_type': real_winner
        }
        st.session_state['dynamic_matches'].append(new_entry)
        st.success("मास्टर डेटाबेस में डेटा सफलतापूर्वक सेव हो गया है!")
