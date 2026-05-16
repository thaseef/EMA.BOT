%%writefile app.py
import streamlit as st
import pandas as pd
import numpy as np
import requests
from streamlit_autorefresh import st_autorefresh
import threading
import time
from datetime import datetime
import pytz
import concurrent.futures
import os
import feedparser
import re

# -----------------------------
# Page Configuration & Styling
# -----------------------------
st.set_page_config(
    page_title="INSTITUTIONAL ALGO V6.0 — 200 ASSET MATRIX",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    .stApp {
        background-color: #050714 !important;
        background-image: radial-gradient(circle at top right, #101630 0%, #050714 60%);
        color: #E0E6ED;
        font-family: 'Inter', sans-serif;
    }
    header[data-testid="stHeader"] { background: transparent !important; }
    .top-nav {
        display: flex; align-items: center; background: rgba(16, 22, 48, 0.6);
        border: 1px solid rgba(41, 56, 102, 0.5); border-radius: 12px;
        padding: 15px 25px; margin-bottom: 10px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(8px);
    }
    .top-nav-logo { font-size: 20px; font-weight: 800; color: #5D88FF; margin-right: 40px; display: flex; align-items: center; gap: 10px; }
    .top-nav-item { color: #8C9BB5; margin-right: 30px; font-size: 14px; font-weight: 500; }
    .top-nav-item.active { color: #FFFFFF; background: rgba(93, 136, 255, 0.15); padding: 8px 16px; border-radius: 8px; border: 1px solid rgba(93, 136, 255, 0.3); }
    .dash-card { background: rgba(13, 18, 38, 0.7); border: 1px solid rgba(34, 46, 84, 0.8); border-radius: 16px; padding: 20px; height: 100%; box-shadow: 0 4px 15px rgba(0,0,0,0.2); backdrop-filter: blur(10px); }
    .card-title { color: #FFFFFF; font-size: 16px; font-weight: 600; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; }
    .card-subtitle { color: #8C9BB5; font-size: 12px; }
    .metric-box { background: rgba(5, 7, 20, 0.5); border: 1px solid rgba(41, 56, 102, 0.4); border-radius: 10px; padding: 15px; text-align: center; margin-bottom: 10px; }
    .metric-value-up { color: #00E676; font-weight: 700; font-size: 16px; }
    .metric-value-down { color: #FF4B4B; font-weight: 700; font-size: 16px; }
    .metric-value-neutral { color: #B0BEC5; font-weight: 700; font-size: 16px; }
    [data-testid="stDataFrame"] { background: rgba(13, 18, 38, 0.7); border: 1px solid rgba(34, 46, 84, 0.8); border-radius: 16px; padding: 10px; }
    .text-glow-blue { color: #5D88FF; text-shadow: 0 0 10px rgba(93, 136, 255, 0.4); }
    .filter-item { color: #8C9BB5; font-size: 13px; padding: 8px 0; border-bottom: 1px solid rgba(41, 56, 102, 0.3); }
    div.row-widget.stRadio > div { flex-direction: column; gap: 10px; }
    .stTabs [data-baseweb="tab-list"] { background-color: rgba(13, 18, 38, 0.7); border-radius: 10px; padding: 5px; margin-bottom: 15px; }
    .stTabs [data-baseweb="tab"] { color: #8C9BB5; }
    .stTabs [aria-selected="true"] { color: #FFFFFF !important; background-color: rgba(93, 136, 255, 0.15) !important; border-radius: 8px; }
    
    .ticker-wrap {
        width: 100%; overflow: hidden; background-color: rgba(5, 7, 20, 0.8);
        border: 1px solid rgba(93, 136, 255, 0.3); padding: 8px 0; border-radius: 8px;
        margin-bottom: 20px; box-shadow: inset 0 0 10px rgba(0,0,0,0.5);
    }
    .ticker {
        display: inline-block; white-space: nowrap; animation: ticker 100s linear infinite; 
        color: #E0E6ED; font-size: 14px; font-weight: 500;
    }
    .ticker:hover { animation-play-state: paused; }
    @keyframes ticker { 0% { transform: translate3d(100%, 0, 0); } 100% { transform: translate3d(-100%, 0, 0); } }
    .ticker-item { margin-right: 50px; }
    .ticker-highlight { color: #FF4B4B; font-weight: bold; margin-right: 5px; } 
    </style>
""", unsafe_allow_html=True)

st_autorefresh(interval=30000, key="datarefresh")

TELEGRAM_TOKEN = os.getenv("8761349419:AAHbMQy2eCqQ9RjgSP99KXY-8fVJ0caVf7Y")
TELEGRAM_CHAT_ID = os.getenv("7999641132")

SHORT_EMA = 50
LONG_EMA = 200
BASE_URL = "https://data-api.binance.vision/api/v3/klines"
HISTORY_FILE = "algo_history.csv"

# -----------------------------
# US Macro News Ticker Fetcher
# -----------------------------
@st.cache_data(ttl=300) 
def get_live_news():
    try:
        search_query = "Trump+OR+USA+OR+War+OR+Iran+OR+Economy"
        url = f"https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        return feed.entries[:12]
    except:
        return []

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html).replace("Google News", "")

def get_image_url(entry):
    if 'media_content' in entry and len(entry.media_content) > 0:
        return entry.media_content[0]['url']
    if 'summary' in entry:
        img_match = re.search(r'<img[^>]+src="([^">]+)"', entry.summary)
        if img_match: return img_match.group(1)
    return ""

# -----------------------------
# Background Scanner Engine
# -----------------------------
class BackgroundScanner:
    def __init__(self):
        self.results_data = []
        # Standardized tracking keys to uppercase "15M"
        self.btc_mtfa = {"Price": "$0.00", "15M": "⚪ Scanning", "1H": "⚪ Scanning", "4H": "⚪ Scanning", "1D": "⚪ Scanning"}
        self.last_update_time = "Initializing 15M Framework..."
        self.alerted_candles = {}
        self.is_running = True
        
        if not os.path.exists(HISTORY_FILE):
            pd.DataFrame(columns=["Time_Triggered", "Asset", "Signal", "Status", "Price", "Macro_Trend"]).to_csv(HISTORY_FILE, index=False)

        thread = threading.Thread(target=self.scan_loop, daemon=True)
        thread.start()

    def get_top_usdt_pairs(self):
        try:
            url = "https://data-api.binance.vision/api/v3/ticker/24hr"
            response = requests.get(url, timeout=10).json()
            pairs = [d for d in response if d['symbol'].endswith('USDT')]
            pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
            top_pairs = [d['symbol'] for d in pairs[:200]] 
            if "BTCUSDT" not in top_pairs: top_pairs.insert(0, "BTCUSDT")
            return top_pairs
        except: return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def get_macro_trend_1h(self, symbol):
        try:
            params = {"symbol": symbol, "interval": "1h", "limit": 250}
            resp = requests.get(BASE_URL, params=params, timeout=5).json()
            close_prices = pd.Series([float(x[4]) for x in resp])
            ema_50 = close_prices.ewm(span=SHORT_EMA, adjust=False).mean().iloc[-2]
            ema_200 = close_prices.ewm(span=LONG_EMA, adjust=False).mean().iloc[-2]
            if ema_50 > ema_200: return "UPTREND"
            elif ema_50 < ema_200: return "DOWNTREND"
            else: return "SIDEWAY"
        except: return "ERROR"

    def get_btc_trend(self, interval):
        try:
            params = {"symbol": "BTCUSDT", "interval": interval, "limit": 250}
            resp = requests.get(BASE_URL, params=params, timeout=5).json()
            close_prices = pd.Series([float(x[4]) for x in resp])
            ema_50 = close_prices.ewm(span=SHORT_EMA, adjust=False).mean().iloc[-2]
            ema_200 = close_prices.ewm(span=LONG_EMA, adjust=False).mean().iloc[-2]
            if ema_50 > ema_200: return "🟢 UPTREND"
            elif ema_50 < ema_200: return "🔴 DOWNTREND"
            else: return "⚪ SIDEWAY"
        except: return "⚪ ERROR"

    def send_telegram(self, coin, signal, trend_macro, vol, price):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
        
        def _send():
            message = (
                f"🏛️ *15M BULLISH CROSSOVER DETECTED* 🏛️\n\n"
                f"**Asset:** {coin}\n"
                f"**Action:** {signal}\n"
                f"**Execution Price:** ${price}\n\n"
                f"📈 **Trend Filters:**\n"
                f"• 1H Macro Filter: {trend_macro}\n"
                f"• Volume Status: {vol}\n"
            )
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
            except: pass
            
        threading.Thread(target=_send, daemon=True).start()

    def process_coin(self, symbol, current_btc_1d, rank):
        try:
            params = {"symbol": symbol, "interval": "15m", "limit": 250}
            resp = requests.get(BASE_URL, params=params, timeout=5).json()
            df = pd.DataFrame(resp, columns=["open_time", "open", "high", "low", "close", "vol", "close_time", "qav", "not", "tbbv", "tbqv", "ig"])
            df[["open", "high", "low", "close", "vol"]] = df[["open", "high", "low", "close", "vol"]].astype(float)

            ema_short = df["close"].ewm(span=SHORT_EMA, adjust=False).mean()
            ema_long = df["close"].ewm(span=LONG_EMA, adjust=False).mean()
            
            prev_e_short, prev_e_long = ema_short.iloc[-3], ema_long.iloc[-3]
            curr_e_short, curr_e_long = ema_short.iloc[-2], ema_long.iloc[-2]

            price = df["close"].iloc[-1]
            closed_candle_time = df["close_time"].iloc[-2]

            sig, specific_trend, is_cross = "⚪ Neutral", "⚪ SIDEWAY", False

            if curr_e_short > curr_e_long: specific_trend = "🟢 UPTREND"
            elif curr_e_short < curr_e_long: specific_trend = "🔴 DOWNTREND"

            if prev_e_short < prev_e_long and curr_e_short > curr_e_long:
                sig = "🚀 ⭐ TOP 40 15M CROSS" if rank <= 40 else "🚀 15M BULLISH CROSS"
                is_cross = True
            elif prev_e_short > prev_e_long and curr_e_short < curr_e_long:
                return None
            else: 
                sig = specific_trend

            if is_cross:
                if "DOWN" in current_btc_1d:
                    return {"Asset": symbol, "Signal": "🚫 BLOCKED (BTC Daily Bearish)", "Status": "FILTERED", "Price": f"${round(price, 6)}", "Action": "-"}

                trend_macro = self.get_macro_trend_1h(symbol)
                price_above_emas = (price > curr_e_short) and (price > curr_e_long)
                
                if not (trend_macro == "UPTREND" and price_above_emas):
                    return {"Asset": symbol, "Signal": "🚫 BLOCKED (Macro Counter-Trend)", "Status": "FILTERED", "Price": f"${round(price, 6)}", "Action": "-"}

                closed_vol = df["vol"].iloc[-2]
                avg_vol_20 = df["vol"].iloc[-22:-2].mean()
                vol_status = "🌋 2X MASSIVE" if closed_vol > (avg_vol_20 * 2.0) else "🔥 1.5X SURGE" if closed_vol > (avg_vol_20 * 1.5) else "🧊 Low Volume" if closed_vol < (avg_vol_20 * 0.5) else "⚪ Normal"
                
                if self.alerted_candles.get(symbol) != closed_candle_time:
                    sl_tz = pytz.timezone('Asia/Colombo')
                    time_triggered = datetime.now(sl_tz).strftime("%Y-%m-%d %I:%M:%S %p")
                    
                    new_history_row = pd.DataFrame([{
                        "Time_Triggered": time_triggered,
                        "Asset": symbol,
                        "Signal": sig,
                        "Status": "TRIGGERED",
                        "Price": f"${round(price, 6)}",
                        "Macro_Trend": trend_macro
                    }])
                    new_history_row.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
                    
                    self.send_telegram(symbol, sig, trend_macro, vol_status, round(price, 6))
                    self.alerted_candles[symbol] = closed_candle_time

            tv_symbol = symbol.replace("USDT", "USDT")
            return {
                "Asset": symbol, 
                "Signal": sig, 
                "Status": "VALIDATED" if is_cross else "TRACKING",
                "Price": f"${round(price, 6)}",
                "Action": f"https://www.tradingview.com/chart/?symbol=BINANCE:{tv_symbol}"
            }
        except:
            return None

    def scan_loop(self):
        while self.is_running:
            try:
                price_resp = requests.get("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", timeout=5).json()
                self.btc_mtfa["Price"] = f"${round(float(price_resp['price']), 2):,}"
                # Uniform uppercase assignment to match the UI block expectations
                self.btc_mtfa["15M"] = self.get_btc_trend("15m")
                self.btc_mtfa["1H"] = self.get_btc_trend("1h")
                self.btc_mtfa["4H"] = self.get_btc_trend("4h")
                self.btc_mtfa["1D"] = self.get_btc_trend("1d")
            except: pass

            current_btc_1d = self.btc_mtfa["1D"]
            coins = self.get_top_usdt_pairs()
            new_results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
                futures = [executor.submit(self.process_coin, symbol, current_btc_1d, i+1) for i, symbol in enumerate(coins)]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result is not None:
                        new_results.append(result)

            new_results = sorted(new_results, key=lambda x: x['Asset'])
            self.results_data = new_results
            sl_timezone = pytz.timezone('Asia/Colombo')
            self.last_update_time = datetime.now(sl_timezone).strftime("%I:%M:%S %p")
            time.sleep(25)

@st.cache_resource
def get_scanner(): return BackgroundScanner()
scanner_engine = get_scanner()

# -----------------------------
# Dashboard UI Render Engine
# -----------------------------
st.markdown(f"""
    <div class="top-nav">
        <div class="top-nav-logo">
            🏛️ <span class="text-glow-blue">INSTITUTIONAL V6 (200 COIN INTERFACE)</span>
        </div>
        <div style="display: flex;">
            <div class="top-nav-item active">🖥 Live Dashboard</div>
            <div class="top-nav-item">⚙️ Settings</div>
        </div>
        <div style="color: #8C9BB5; font-size: 13px;">
            🔴 Engine Heartbeat: {scanner_engine.last_update_time}
        </div>
    </div>
""", unsafe_allow_html=True)

news_entries = get_live_news()
if news_entries:
    ticker_text = ""
    for entry in news_entries[:10]:
        ticker_text += f"<span class='ticker-item'><span class='ticker-highlight'>🔴 BREAKING US NEWS:</span> {entry.title}</span>"
    st.markdown(f'<div class="ticker-wrap"><div class="ticker">{ticker_text}</div></div>', unsafe_allow_html=True)

tab_dash, tab_history, tab_news = st.tabs(["📊 Live Scanner", "📜 Historical Registry", "📰 Macro Intel"])

with tab_dash:
    st.markdown("<h3 style='color: white; margin-bottom: 20px; margin-top: -10px;'>System Diagnostics</h3>", unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1])

    def get_class(trend): 
        return "metric-value-up" if "UP" in trend else "metric-value-down" if "DOWN" in trend else "metric-value-neutral"

    with col1:
        st.markdown("""
            <div class="dash-card">
                <div class="card-title">Active Filters <span style="font-size: 12px; color: #00E676;">● 200 Coin Tracking Matrix</span></div>
                <div class="card-subtitle" style="margin-bottom: 15px;">Pure Execution Tracking</div>
                <div class="filter-item">✔️ 15-Minute EMA Bullish Crossover</div>
                <div class="filter-item">✔️ 1-Hour Macro Structural Verification</div>
                <div class="filter-item" style="border: none;">🛡️ BTC Daily Regime Lock</div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        btc_price = scanner_engine.btc_mtfa['Price']
        st.markdown(f"""
            <div class="dash-card">
                <div class="card-title">Bitcoin Index <span style="color: #5D88FF; font-weight: bold;">{btc_price}</span></div>
                <div class="card-subtitle" style="margin-bottom: 15px;">Regime Trend Profiles</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div class="metric-box"><div style="font-size: 12px; color: #8C9BB5; margin-bottom: 5px;">15M Status</div><div class="{get_class(scanner_engine.btc_mtfa['15M'])}">{scanner_engine.btc_mtfa['15M']}</div></div>
                    <div class="metric-box"><div style="font-size: 12px; color: #8C9BB5; margin-bottom: 5px;">1H Status</div><div class="{get_class(scanner_engine.btc_mtfa['1H'])}">{scanner_engine.btc_mtfa['1H']}</div></div>
                    <div class="metric-box"><div style="font-size: 12px; color: #8C9BB5; margin-bottom: 5px;">4H Status</div><div class="{get_class(scanner_engine.btc_mtfa['4H'])}">{scanner_engine.btc_mtfa['4H']}</div></div>
                    <div class="metric-box"><div style="font-size: 12px; color: #8C9BB5; margin-bottom: 5px;">Daily Status</div><div class="{get_class(scanner_engine.btc_mtfa['1D'])}">{scanner_engine.btc_mtfa['1D']}</div></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if not scanner_engine.results_data:
        st.markdown("""
            <div class="dash-card" style="text-align: center; padding: 40px;">
                <h3 style="color: #5D88FF;">⏳ Constructing Core 200 Asset 15M Matrix...</h3>
                <p style="color: #8C9BB5;">Synchronizing with the Binance API data pipeline. Standby.</p>
            </div>
        """, unsafe_allow_html=True)
    else:
        df_all = pd.DataFrame(scanner_engine.results_data)
        df_display = df_all[["Asset", "Signal", "Status", "Price", "Action"]]
        df_crosses = df_display[df_display['Signal'].str.contains('CROSS', na=False)]
        df_others = df_display[~df_display['Signal'].str.contains('CROSS', na=False)]
        
        def color_rows(val):
            if isinstance(val, str):
                if 'http' in val: return '' 
                if 'CROSS' in val: return 'background-color: rgba(93, 136, 255, 0.2); color: #FFFFFF; font-weight: bold; border-left: 3px solid #5D88FF;'
                if 'BLOCKED' in val: return 'color: #FF4B4B; font-weight: bold;'
                if 'UPTREND' in val: return 'color: #00E676;'
                if 'DOWNTREND' in val: return 'color: #FF4B4B;'
            return ''

        link_config = {"Action": st.column_config.LinkColumn("Chart", display_text="📈 Open Link", width="small")}

        if not df_crosses.empty:
            st.markdown('<div class="dash-card" style="padding-bottom: 0; border: 1px solid #5D88FF; background: rgba(93, 136, 255, 0.05); margin-bottom: 20px;"><div class="card-title" style="color: #5D88FF;">🚀 VALIDATED DIRECT SIGNALS TRADING WINDOW</div></div>', unsafe_allow_html=True)
            st.dataframe(df_crosses.style.map(color_rows), use_container_width=True, hide_index=True, column_config=link_config)
        else:
            st.markdown('<div class="dash-card" style="padding: 15px; margin-bottom: 20px; border: 1px dashed rgba(41, 56, 102, 0.8);"><div style="color: #8C9BB5; text-align: center; font-size: 14px;">No structural 15M crossovers observed across the 200 asset array.</div></div>', unsafe_allow_html=True)

        st.markdown('<div class="dash-card" style="padding-bottom: 0;"><div class="card-title">🌐 Asset Registry Stream (Top 200 Volume Markets)</div></div>', unsafe_allow_html=True)
        st.dataframe(df_others.style.map(color_rows), use_container_width=True, height=400, hide_index=True, column_config=link_config)

with tab_history:
    st.markdown("<h3 style='color: white; margin-bottom: 20px; margin-top: 10px;'>📜 Signal Registry Log</h3>", unsafe_allow_html=True)
    if os.path.exists(HISTORY_FILE):
        history_df = pd.read_csv(HISTORY_FILE)
        if not history_df.empty:
            history_df = history_df.iloc[::-1].reset_index(drop=True)
            st.dataframe(history_df.style.map(lambda v: 'color: #00E676; font-weight: bold;' if 'LONG' in str(v) else ''), use_container_width=True, height=600)
            st.download_button(label="📥 Export Registry Dataset (CSV)", data=history_df.to_csv(index=False).encode('utf-8'), file_name="algo_15m_history.csv", mime="text/csv")
        else:
            st.info("Signal ledger is clear. Monitoring market array...")
    else:
        st.info("Signal ledger is clear. Monitoring market array...")

with tab_news:
    st.markdown("<h3 style='color: white; margin-bottom: 20px; margin-top: 10px;'>📰 Fundamental Wire Feed</h3>", unsafe_allow_html=True)
    if news_entries:
        for entry in news_entries[:10]:
            clean_summary = clean_html(entry.summary)
            img_url = get_image_url(entry)
            img_html = f'<img src="{img_url}" style="width: 100%; border-radius: 8px; margin-bottom: 15px; object-fit: cover; max-height: 250px;" onerror="this.style.display=\'none\'">' if img_url else ""
            st.markdown(f'<div class="dash-card" style="margin-bottom: 20px; padding: 20px; border-left: 4px solid #FF4B4B;">{img_html}<div style="font-weight: 700; font-size: 18px; color: #FFFFFF; margin-bottom: 10px;">{entry.title}</div><div style="color: #E0E6ED; font-size: 14px; line-height: 1.5; margin-bottom: 10px;">{clean_summary}</div><div style="color: #8C9BB5; font-size: 12px; font-weight: bold;">🕒 {entry.published}</div></div>', unsafe_allow_html=True)
