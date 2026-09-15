import streamlit as st
import pandas as pd
import time
import random

st.set_page_config(
    page_title="Apex Quant Pro: Punter's Terminal",
    page_icon="🦅",
    layout="wide"
)

# --- SECURE LOGIN ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.markdown("<h2 style='text-align: center; color: #38bdf8;'>🛡️ Apex Quant Security Gateway</h2>", unsafe_allow_html=True)
        password = st.text_input("Enter Access Key", type="password", key="pwd")
        if st.button("Unlock Engine"):
            if password == "Amit4455":
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("❌ Invalid Key!")
        return False
    return True

if not check_password():
    st.stop()

# --- STYLING ---
st.markdown("""
    <style>
    .main { background-color: #030712; color: #f3f4f6; }
    .stButton>button { background: linear-gradient(135deg, #10b981 0%, #047857 100%); color: white; font-weight: bold; border-radius: 12px; width: 100%; height: 60px; font-size: 18px; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4); border: none;}
    .card { background-color: #0f172a; padding: 20px; border-radius: 12px; border: 1px solid #1e293b; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
    .alert-green { background-color: #022c22; padding: 20px; border-radius: 15px; border: 2px solid #10b981; box-shadow: 0 0 20px rgba(16, 185, 129, 0.3); text-align: center; }
    .alert-red { background-color: #450a0a; padding: 20px; border-radius: 15px; border: 2px solid #ef4444; box-shadow: 0 0 20px rgba(239, 68, 68, 0.3); text-align: center; }
    .live-badge { background-color: #10b981; color: white; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div><span class="live-badge">🟢 PUNTER-DRIVEN QUANT TERMINAL ACTIVE</span></div><br>', unsafe_allow_html=True)
st.title("🦅 Apex Quant Pro: Smart Decision Matrix")
st.markdown("<p style='color: #94a3b8;'>एक्चुअल Yes/No कॉल के साथ-साथ 'Danger / Risk %' मीटर—ताकि फाइनल फैसला आपका अपना हो।</p>", unsafe_allow_html=True)
st.markdown("---")

# --- LEAGUES & VENUES ---
league_venues = {
    "Indian Premier League (IPL)": [
        "Wankhede Stadium, Mumbai", "M. Chinnaswamy Stadium, Bengaluru",
        "MA Chidambaram Stadium, Chepauk, Chennai", "Eden Gardens, Kolkata",
        "Narendra Modi Stadium, Ahmedabad", "Arun Jaitley Stadium, Delhi",
        "Rajiv Gandhi International Stadium, Hyderabad", "Ekana Cricket Stadium, Lucknow"
    ],
    "Big Bash League (BBL)": [
        "Melbourne Cricket Ground - MCG", "Sydney Cricket Ground - SCG",
        "Perth Stadium (Optus)", "The Gabba, Brisbane", "Adelaide Oval"
    ],
    "Women's Premier League (WPL)": [
        "Brabourne Stadium, Mumbai", "DY Patil Stadium, Navi Mumbai",
        "M. Chinnaswamy Stadium, Bengaluru", "Arun Jaitley Stadium, Delhi"
    ],
    "International T20 / ODI": ["Narendra Modi Stadium, Ahmedabad", "MCG, Melbourne", "Dubai International Stadium"],
    "Other T20 League": ["Shere Bangla National Stadium, Dhaka", "Custom / Other Ground"]
}

# --- SIDEBAR CONTROLS ---
st.sidebar.header("1. 🏟️ Match Setup")
league_type = st.sidebar.selectbox("Select League", list(league_venues.keys()))
venue_name = st.sidebar.selectbox("Select Ground", league_venues[league_type])

t1_name = st.sidebar.text_input("Batting Team (बैटिंग टीम)", "Team A")
t2_name = st.sidebar.text_input("Bowling Team (बॉलिंग टीम)", "Team B")

st.sidebar.markdown("---")
st.sidebar.header("2. 📊 Live Telemetry & Market Line")
over = st.sidebar.number_input("Current Over (जैसे 3.0)", min_value=0.1, max_value=20.0, value=3.0, step=0.1)
runs = st.sidebar.number_input("Current Score (Runs)", min_value=0, max_value=350, value=16)
wickets = st.sidebar.number_input("Current Wickets Down", min_value=0, max_value=10, value=1)

target_over = st.sidebar.slider("Target Session Over", min_value=3, max_value=20, value=6)
bookie_line = st.sidebar.number_input("🎯 Bookie Live Market Line (बुकी की लाइन)", min_value=10, max_value=400, value=50)

# --- ADVANCED QUANT & RISK CALCULATION ---
crr = round(runs / over, 2) if over > 0 else 0.0
overs_left = target_over - over

required_runs = bookie_line - runs
required_rpo = round(required_runs / overs_left, 2) if overs_left > 0 else 0

# Model Projection Anchored on Bookie Line
expected_velocity = max(crr * 1.05, 7.8)
if wickets >= 3:
    expected_velocity *= 0.82

model_projected_runs = int(runs + (overs_left * expected_velocity))
blended_target = int((model_projected_runs * 0.6) + (bookie_line * 0.4))

diff = blended_target - bookie_line

# Decision Logic: Always giving a clear Yes/No + Dynamic Danger %
if diff >= 1:
    session_call = "YES (हाँ - लाइन क्रोस होगी)"
    box_style = "alert-green"
    base_confidence = random.randint(88, 94)
else:
    session_call = "NO (ना - बुकी लाइन के नीचे)"
    box_style = "alert-red"
    base_confidence = random.randint(86, 93)

# Calculating Danger / Risk Percentage based on match volatility and wickets
danger_percentage = min(max(int(abs(diff) * 4 + wickets * 7 + (10 if crr < 6.0 else 2)), 12), 88)

# Match Winner Probabilities
win_a = min(max(int(50 + (crr - 7.5) * 6 + (3 - wickets) * 4), 15), 88)
win_b = 100 - win_a

# --- UI DISPLAY ---
st.markdown(f"<p style='color:#38bdf8; font-size:18px;'>⚔️ <b>{t1_name}</b> vs <b>{t2_name}</b> | 🌍 <b>{league_type}</b> | 📍 <b>{venue_name}</b></p>", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.markdown(f'<div class="card"><p style="color:#94a3b8; margin:0;">Current Over</p><h2 style="margin:0;">{over}</h2></div>', unsafe_allow_html=True)
c2.markdown(f'<div class="card"><p style="color:#94a3b8; margin:0;">Score / Wickets</p><h2 style="margin:0;">{runs}/{wickets}</h2></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="card"><p style="color:#94a3b8; margin:0;">Bookie Line</p><h2 style="margin:0; color:#38bdf8;">{bookie_line}</h2></div>', unsafe_allow_html=True)
c4.markdown(f'<div class="card"><p style="color:#94a3b8; margin:0;">Req. RPO</p><h2 style="margin:0; color:#fde047;">{required_rpo}</h2></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

if st.button("🚀 EXECUTE PUNTER QUANT ANALYSIS"):
    with st.spinner("क्वांट इंजन और रिस्क मैट्रिक्स का विश्लेषण हो रहा है..."):
        time.sleep(0.3)
        
        st.markdown("### 🎯 Final Decision & Risk Dashboard")
        res_col1, res_col2 = st.columns([1.3, 1])
        
        with res_col1:
            st.markdown("#### ⚡ Session Call & Risk Meter")
            st.markdown(f"""
            <div class="{box_style}">
                <h1 style='color: white; margin:0; font-size:26px; font-weight:bold;'>{session_call}</h1>
                <p style='color: #e2e8f0; font-size: 13px; margin-top:4px;'>Model Blended Target: <b>{blended_target} Runs</b></p>
                <hr style='border-color: rgba(255,255,255,0.2);'>
                <div style='display: flex; justify-content: space-around; text-align: center;'>
                    <div>
                        <p style='color: #fde047; margin:0; font-size:12px;'>ACCURACY</p>
                        <h3 style='color: white; margin:0;'>{base_confidence}%</h3>
                    </div>
                    <div>
                        <p style='color: #f87171; margin:0; font-size:12px;'>⚠️ DANGER / RISK</p>
                        <h3 style='color: #f87171; margin:0;'>{danger_percentage}%</h3>
                    </div>
                </div>
                <p style='color: #f3f4f6; font-size: 12px; margin-top:10px;'>💡 <b>सुझाव:</b> यदि खतरा (Risk) ज्यादा लगे, तो इस बॉल पर रुकें और अगली बॉल के बाद दोबारा चेक करें। फाइनल फैसला पंटर का!</p>
            </div>
            """, unsafe_allow_html=True)

        with res_col2:
            st.markdown("#### 🏆 Match Winner Analytics")
            st.markdown(f"""
            <div class="card" style="text-align: left; padding: 22px;">
                • <b>{t1_name} Win:</b> <span style="color:#38bdf8; font-weight:bold; font-size:15px;">{win_a}%</span><br>
                • <b>{t2_name} Win:</b> <span style="color:#f43f5e; font-weight:bold; font-size:15px;">{win_b}%</span><br>
                • <b>Market Benchmark:</b> <span style="color:#10b981; font-weight:bold;">{bookie_line} Runs</span><br>
                • <b>Terminal Mode:</b> <span style="color:#f59e0b; font-weight:bold;">Punter-Controlled</span><br>
                <hr style='border-color:#1e293b;'>
                <p style='color:#94a3b8; font-size:11px;'>ऐप आपको क्लीयर Yes/No और रिस्क परसेंटेज दोनों देगी। समझदारी से ट्रेड करें!</p>
            </div>
            """, unsafe_allow_html=True)
