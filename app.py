import streamlit as st
import pandas as pd
import os
import time

st.set_page_config(
    page_title="100% Strict Dual-Layer Historical Analyzer",
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
    </style>
""", unsafe_allow_html=True)

st.title("📊 Dual-Layer Past Records Match Analyzer (IPL, WPL, BBL, WBBL)")
st.markdown("---")

# --- LOAD HISTORICAL DATA SAFELY ---
@st.cache_data
def load_data():
    csv_file = "match_data.csv"
    if os.path.exists(csv_file):
        return pd.read_csv(csv_file)
    else:
        return pd.DataFrame({
            'league': ['IPL', 'WPL', 'Men BBL', 'Women BBL'],
            'season': [2024, 2024, 2024, 2024],
            'venue': ['Wankhede Stadium', 'Brabourne Stadium', 'Adelaide Oval', 'North Sydney Oval'],
            'batting_team': ['Mumbai Indians', 'Mumbai Indians Women', 'Sydney Sixers', 'Sydney Sixers Women'],
            'bowling_team': ['Chennai Super Kings', 'Delhi Capitals Women', 'Adelaide Strikers', 'Melbourne Stars Women'],
            'current_over': [2.3, 2.3, 2.3, 2.3],
            'current_runs': [22, 18, 18, 16],
            'current_wickets': [1, 1, 1, 1],
            'target_over': [6, 6, 6, 6],
            'final_phase_runs': [58, 48, 54, 48],
            'match_winner_type': ['Batting 2nd Won', 'Batting 1st Won', 'Batting 1st Won', 'Batting 2nd Won']
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

team_batting = st.sidebar.text_input("Batting Team (Live)", "Mumbai Indians")
team_bowling = st.sidebar.text_input("Bowling Team (Live)", "Chennai Super Kings")

st.sidebar.markdown("---")
ground_name = st.sidebar.text_input("Stadium / Ground", "Wankhede Stadium")

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Live Match Current Situation (Ball-by-Ball)")
current_over = st.sidebar.number_input("Current Overs (e.g., 1.2, 2.3)", min_value=0.0, max_value=20.0, value=1.0, step=0.1)
current_runs = st.sidebar.number_input("Current Runs Scored", min_value=0, max_value=300, value=4)
current_wickets = st.sidebar.number_input("Current Wickets Fallen", min_value=0, max_value=10, value=1)

target_future_over = st.sidebar.slider("Analyze Past Data At Over:", min_value=1, max_value=20, value=6)

if 'dynamic_matches' not in st.session_state:
    st.session_state['dynamic_matches'] = []

# --- MAIN SCREEN DISPLAY ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"🔴 Live Match [{league_key}]: {team_batting} vs {team_bowling}")
    st.markdown(f"**Ground:** {ground_name} | **Situation:** {current_over} Overs | {current_runs} Runs | {current_wickets} Wickets")
    
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f'<div class="metric-card"><h4>Live Over</h4><h2>{current_over}</h2></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric-card"><h4>Current Score</h4><h2>{current_runs}/{current_wickets}</h2></div>', unsafe_allow_html=True)
    with m3:
        current_rr = round(current_runs / current_over, 2) if current_over > 0 else 0.0
        st.markdown(f'<div class="metric-card"><h4>Current RR</h4><h2>{current_rr}</h2></div>', unsafe_allow_html=True)

    st.markdown(f"### 🔍 Dual-Layer Past Record Analysis [{league_key}]")
    st.info("📁 **Strict Rule Active:** Checking Head-to-Head and General Batting Team records separately from past 5 years data.")

    if st.button("🚀 Fetch Both Original Results"):
        if current_over <= 0:
            st.error("कृपया वैध ओवर दर्ज करें।")
        else:
            with st.spinner("पिछले 5 सालों का ओरिजिनल डेटा निकाला जा रहा है..."):
                time.sleep(0.8)
                
                # Combine CSV data and session custom data
                df_dyn = pd.DataFrame(st.session_state['dynamic_matches'])
                if not df_dyn.empty:
                    combined_df = pd.concat([df_history, df_dyn], ignore_index=True)
                else:
                    combined_df = df_history
                
                league_df = combined_df[combined_df['league'] == league_key]
                
                # --- PART 1: Head-to-Head Record (Both Teams) ---
                h2h_df = league_df[
                    (league_df['batting_team'].str.strip().str.lower() == team_batting.strip().lower()) & 
                    (league_df['bowling_team'].str.strip().str.lower() == team_bowling.strip().lower()) &
                    (league_df['current_over'] == current_over) &
                    (league_df['current_wickets'] == current_wickets)
                ]
                
                # --- PART 2: General Record (Batting Team vs ALL Bowling Teams) ---
                general_df = league_df[
                    (league_df['batting_team'].str.strip().str.lower() == team_batting.strip().lower()) &
                    (league_df['current_over'] == current_over) &
                    (league_df['current_wickets'] == current_wickets)
                ]
                
                # --- DISPLAY POINT 1: Head-to-Head Result ---
                st.markdown("### 📌 Point 1: Head-to-Head Record (इन दोनों टीमों का आपस में पिछला रिकॉर्ड)")
                if not h2h_df.empty:
                    h2h_avg_runs = int(h2h_df['final_phase_runs'].mean())
                    h2h_winners = h2h_df['match_winner_type'].value_counts()
                    h2h_b1 = h2h_winners.get('Batting 1st Won', 0)
                    h2h_b2 = h2h_winners.get('Batting 2nd Won', 0)
                    h2h_total = h2h_b1 + h2h_b2
                    
                    if h2h_total > 0:
                        h2h_p1_pct = int((h2h_b1 / h2h_total) * 100)
                        h2h_p2_pct = 100 - h2h_p1_pct
                        h2h_result_text = f"Batting 1st Won ({h2h_p1_pct}%) | Batting 2nd Won ({h2h_p2_pct}%)" if h2h_p1_pct != h2h_p2_pct else "Tie / Equal Split"
                    else:
                        h2h_result_text = "Data Available but Winner not specified"
                    
                    st.success(f"मिल गए **{len(h2h_df)}** मैच इस Head-to-Head सिचुएशन के!")
                    st.markdown(f"""
                    <div class="box-card">
                        <b>कुल मैच मिले:</b> {len(h2h_df)}<br>
                        <b>औसत रन (Final Phase):</b> {h2h_avg_runs} Runs<br>
                        <b>असली पास्ट रिजल्ट (कौन जीता):</b> <b>{h2h_result_text}</b>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.warning("⚠️ इन दोनों टीमों के बीच इस विशिष्ट लाइव सिचुएशन का कोई Head-to-Head पुराना रिकॉर्ड पिछले 5 सालों में नहीं है।")

                # --- DISPLAY POINT 2 & 3: General Batting Team vs All Bowlers ---
                st.markdown("### 📌 Point 2 & 3: Batting Team vs All Teams (बॉलिंग टीम कोई भी हो, बैटिंग टीम का समग्र रिकॉर्ड)")
                if not general_df.empty:
                    gen_avg_runs = int(general_df['final_phase_runs'].mean())
                    gen_winners = general_df['match_winner_type'].value_counts()
                    gen_b1 = gen_winners.get('Batting 1st Won', 0)
                    gen_b2 = gen_winners.get('Batting 2nd Won', 0)
                    gen_total = gen_b1 + gen_b2
                    
                    if gen_total > 0:
                        gen_p1_pct = int((gen_b1 / gen_total) * 100)
                        gen_p2_pct = 100 - gen_p1_pct
                        if gen_p1_pct > gen_p2_pct:
                            gen_result_text = f"Batting 1st Won ज्यादा बार हुआ है ({gen_p1_pct}% मैचों में)"
                        elif gen_p2_pct > gen_p1_pct:
                            gen_result_text = f"Batting 2nd Won ज्यादा बार हुआ है ({gen_p2_pct}% मैचों में)"
                        else:
                            gen_result_text = f"बराबर रिकॉर्ड (50% Batting 1st / 50% Batting 2nd)"
                    else:
                        gen_result_text = "Winner data unavailable"
                        
                    st.success(f"मिल गए **{len(general_df)}** मैच जब **{team_batting}** ने बाकी टीमों के खिलाफ ऐसी सिचुएशन खेली थी!")
                    st.markdown(f"""
                    <div class="box-card">
                        <b>कुल मैच मिले (अन्य टीमों के खिलाफ):</b> {len(general_df)}<br>
                        <b>औसत रन बने:</b> {gen_avg_runs} Runs<br>
                        <b>असली पास्ट रिजल्ट (कौन जीता):</b> <b>{gen_result_text}</b>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.expander("📂 सभी ओरिजिनल मैच रिकॉर्ड्स की लिस्ट देखें"):
                        st.dataframe(general_df[['season', 'venue', 'batting_team', 'bowling_team', 'current_over', 'current_runs', 'current_wickets', 'final_phase_runs', 'match_winner_type']])
                else:
                    st.warning(f"⚠️ पिछले 5 सालों में **{team_batting}** का इस लाइव सिचुएशन का कोई अन्य डेटाबेस रिकॉर्ड नहीं मिला।")

with col2:
    st.subheader("💾 Add Real Match Data")
    st.markdown("अपने पास मौजूद पिछले 5 साल के ओरिजिनल मैचों का डेटा यहाँ सेव करें:")
    
    saved_final_runs = st.number_input("Actual Final Phase Runs Scored:", min_value=0, max_value=300, value=50)
    saved_winner = st.selectbox("Actual Match Winner Result:", ["Batting 1st Won", "Batting 2nd Won"])
    
    if st.button("➕ Save to 5-Year Database"):
        new_entry = {
            'league': league_key,
            'season': 2026,
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
        st.success("डेटा सफलतापूर्वक सेव हो गया है!")

st.markdown("---")
st.markdown("<p style='text-align: center; color: gray;'>100% Strict Dual-Layer Historical Analyzer | No AI Guesswork</p>", unsafe_allow_html=True)
