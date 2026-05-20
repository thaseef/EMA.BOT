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
    page_title="INSTITUTIONAL ALGO V6.0 — CAPITAL TRADE ENGINE",
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

# 10-second snappy UI auto-updates
st_autorefresh(interval=10000, key="datarefresh")

TELEGRAM_TOKEN = os.getenv("8761349419:AAHbMQy2eCqQ9RjgSP99KXY-8fVJ0caVf7Y")
TELEGRAM_CHAT_ID = os.getenv("7999641132")

SHORT_EMA = 50
LONG_EMA = 200
BASE_URL = "https://data-api.binance.vision/api/v3/klines"
ALGO_LOG_FILE = "algo_history.csv"
ACTIVE_TRADES_FILE = "active_trades.csv"
TRADE_JOURNAL_FILE = "trade_history.csv"

# Initial File Foundations
for f, cols in [
    (ALGO_LOG_FILE, ["Time_Triggered", "Asset", "Signal", "Status", "Price", "Macro_Trend"]),
    (ACTIVE_TRADES_FILE, ["Asset", "Entry_Price", "TP", "SL", "Capital", "Time_Opened"]),
    (TRADE_JOURNAL_FILE, ["Time_Closed", "Asset", "Capital", "Entry_Price", "Exit_Price", "TP", "SL", "Final_PNL_Pct", "Final_PNL_Cash", "Outcome"])
]:
    if not os.path.exists(f):
        pd.DataFrame(columns=cols).to_csv(f, index=False)

# UI Tracking States
if "ignored_assets" not in st.session_state:
    st.session_state.ignored_assets = set()
if "staging_asset" not in st.session_state:
    st.session_state.staging_asset = None

# -----------------------------
# Fundamental Wire Fetcher
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
    return re.sub(re.compile('<.*?>'), '', raw_html).replace("Google News", "")

# -----------------------------
# Core Algorithmic Scanner Engine
# -----------------------------
class BackgroundScanner:
    def __init__(self):
        self.results_data = []
        self.btc_mtfa = {"Price": "$0.00", "15M": "⚪ Scanning", "1H": "⚪ Scanning", "4H": "⚪ Scanning", "1D": "⚪ Scanning"}
        self.last_update_time = "Initializing Framework..."
        self.alerted_candles = {}
        self.is_running = True
        
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
            return "UPTREND" if ema_50 > ema_200 else "DOWNTREND" if ema_50 < ema_200 else "SIDEWAY"
        except: return "ERROR"

    def get_btc_trend(self, interval):
        try:
            params = {"symbol": "BTCUSDT", "interval": interval, "limit": 250}
            resp = requests.get(BASE_URL, params=params, timeout=5).json()
            close_prices = pd.Series([float(x[4]) for x in resp])
            ema_50 = close_prices.ewm(span=SHORT_EMA, adjust=False).mean().iloc[-2]
            ema_200 = close_prices.ewm(span=LONG_EMA, adjust=False).mean().iloc[-2]
            return "🟢 UPTREND" if ema_50 > ema_200 else "🔴 DOWNTREND" if ema_50 < ema_200 else "⚪ SIDEWAY"
        except: return "⚪ ERROR"

    def send_telegram(self, title, body):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
        def _send():
            msg = f"{title}\n\n{body}"
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
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
                    return {"Asset": symbol, "Signal": "🚫 BLOCKED (BTC Daily Bearish)", "Status": "FILTERED", "Price": price}

                trend_macro = self.get_macro_trend_1h(symbol)
                price_above_emas = (price > curr_e_short) and (price > curr_e_long)
                
                if not (trend_macro == "UPTREND" and price_above_emas):
                    return {"Asset": symbol, "Signal": "🚫 BLOCKED (Macro Counter-Trend)", "Status": "FILTERED", "Price": price}

                closed_vol = df["vol"].iloc[-2]
                avg_vol_20 = df["vol"].iloc[-22:-2].mean()
                vol_status = "🌋 2X MASSIVE" if closed_vol > (avg_vol_20 * 2.0) else "🔥 1.5X SURGE" if closed_vol > (avg_vol_20 * 1.5) else "🧊 Low Volume" if closed_vol < (avg_vol_20 * 0.5) else "⚪ Normal"
                
                if self.alerted_candles.get(symbol) != closed_candle_time:
                    sl_tz = pytz.timezone('Asia/Colombo')
                    time_triggered = datetime.now(sl_tz).strftime("%Y-%m-%d %I:%M:%S %p")
                    
                    pd.DataFrame([{
                        "Time_Triggered": time_triggered, "Asset": symbol, "Signal": sig,
                        "Status": "TRIGGERED", "Price": f"${round(price, 6)}", "Macro_Trend": trend_macro
                    }]).to_csv(ALGO_LOG_FILE, mode='a', header=False, index=False)
                    
                    self.send_telegram(
                        "🏛️ *15M BULLISH CROSSOVER DETECTED* 🏛️",
                        f"**Asset:** {symbol}\n**Action:** {sig}\n**Execution Price:** ${round(price, 6)}\n\n📈 **Trend Filters:**\n• 1H Filter: {trend_macro}\n• Volume Status: {vol_status}"
                    )
                    self.alerted_candles[symbol] = closed_candle_time

            return {"Asset": symbol, "Signal": sig, "Status": "VALIDATED" if is_cross else "TRACKING", "Price": price}
        except:
            return None

    def evaluate_live_trade_rules(self):
        """Processes atomic execution tracking, tracking real capital and target barriers."""
        if not os.path.exists(ACTIVE_TRADES_FILE): return
        try:
            active_df = pd.read_csv(ACTIVE_TRADES_FILE)
            if active_df.empty: return
            
            updated_active = []
            sl_tz = pytz.timezone('Asia/Colombo')

            for _, trade in active_df.iterrows():
                asset = trade['Asset']
                entry = float(trade['Entry_Price'])
                tp = float(trade['TP'])
                sl = float(trade['SL'])
                capital = float(trade['Capital'])
                time_opened = trade['Time_Opened']

                try:
                    p_resp = requests.get(f"https://data-api.binance.vision/api/v3/ticker/price?symbol={asset}", timeout=2).json()
                    curr_price = float(p_resp['price'])
                except:
                    updated_active.append(trade.to_dict())
                    continue

                hit_tp = curr_price >= tp
                hit_sl = curr_price <= sl

                if hit_tp or hit_sl:
                    outcome = "TP HIT ✅" if hit_tp else "SL HIT ❌"
                    final_pnl_pct = ((curr_price - entry) / entry) * 100
                    final_pnl_cash = capital * (final_pnl_pct / 100)
                    time_closed = datetime.now(sl_tz).strftime("%Y-%m-%d %I:%M:%S %p")

                    # Push into the New Registry Database Structure
                    pd.DataFrame([{
                        "Time_Closed": time_closed, "Asset": asset, "Capital": capital, "Entry_Price": entry,
                        "Exit_Price": curr_price, "TP": tp, "SL": sl, "Final_PNL_Pct": f"{round(final_pnl_pct, 2)}%",
                        "Final_PNL_Cash": f"${round(final_pnl_cash, 2)}", "Outcome": outcome
                    }]).to_csv(TRADE_JOURNAL_FILE, mode='a', header=False, index=False)

                    # Send Updated Telegram alert containing real-money cash calculations
                    self.send_telegram(
                        f"🏛️ *TRADE AUTOMATICALLY CLOSED ({outcome})*",
                        f"**Asset:** {asset}\n**Invested Capital:** ${round(capital, 2)}\n**Entry Price:** ${entry}\n**Exit Price:** ${curr_price}\n\n📊 **Metrics:**\n• Final PNL %: {round(final_pnl_pct, 2)}%\n• Final Profit/Loss: {'+$' if final_pnl_cash >= 0 else '-$'}{round(abs(final_pnl_cash), 2)}"
                    )
                else:
                    updated_active.append(trade.to_dict())

            pd.DataFrame(updated_active, columns=["Asset", "Entry_Price", "TP", "SL", "Capital", "Time_Opened"]).to_csv(ACTIVE_TRADES_FILE, index=False)
        except Exception as e:
            pass

    def scan_loop(self):
        while self.is_running:
            try:
                price_resp = requests.get("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", timeout=5).json()
                self.btc_mtfa["Price"] = f"${round(float(price_resp['price']), 2):,}"
                self.btc_mtfa["15M"] = self.get_btc_trend("15m")
                self.btc_mtfa["1H"] = self.get_btc_trend("1h")
                self.btc_mtfa["4H"] = self.get_btc_trend("4h")
                self.btc_mtfa["1D"] = self.get_btc_trend("1d")
            except: pass

            self.evaluate_live_trade_rules()

            current_btc_1d = self.btc_mtfa["1D"]
            coins = self.get_top_usdt_pairs()
            new_results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
                futures = [executor.submit(self.process_coin, symbol, current_btc_1d, i+1) for i, symbol in enumerate(coins)]
                for future in concurrent.futures.as_completed(futures):
                    res = future.result()
                    if res is not None: new_results.append(res)

            self.results_data = sorted(new_results, key=lambda x: x['Asset'])
            sl_timezone = pytz.timezone('Asia/Colombo')
            self.last_update_time = datetime.now(sl_timezone).strftime("%I:%M:%S %p")
            time.sleep(15)

@st.cache_resource
def get_scanner(): return BackgroundScanner()
scanner_engine = get_scanner()

# -----------------------------
# Dashboard Presentation Space
# -----------------------------
st.markdown(f"""
    <div class="top-nav">
        <div class="top-nav-logo">
            🏛️ <span class="text-glow-blue">INSTITUTIONAL CORE V6.0 — CAPITAL CONTROLLER</span>
        </div>
        <div style="color: #8C9BB5; font-size: 13px; margin-left: auto;">
            🔴 Engine Heartbeat: {scanner_engine.last_update_time}
        </div>
    </div>
""", unsafe_allow_html=True)

news_entries = get_live_news()
if news_entries:
    ticker_text = "".join([f"<span class='ticker-item'><span class='ticker-highlight'>🔴 BREAKING US NEWS:</span> {entry.title}</span>" for entry in news_entries[:10]])
    st.markdown(f'<div class="ticker-wrap"><div class="ticker">{ticker_text}</div></div>', unsafe_allow_html=True)

tab_dash, tab_running, tab_journal, tab_intel = st.tabs(["📊 Radar Scanner", "⚡ Active Portfolio", "📜 Trade Ledger", "📰 Macro Intel"])

# -------------------------------------------------------------
# TAB 1: RADAR SCANNER & MANAGEMENT PANEL
# -------------------------------------------------------------
with tab_dash:
    st.markdown("<h3 style='color: white; margin-top:-10px;'>System Diagnostics</h3>", unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("""
            <div class="dash-card">
                <div class="card-title">Active Matrix Parameters <span style="font-size: 12px; color: #00E676;">● Portfolio Tracking Active</span></div>
                <div class="filter-item">✔️ 15-Minute EMA Trend Intersect Cross</div>
                <div class="filter-item">✔️ 1-Hour Verification Filter</div>
                <div class="filter-item" style="border: none;">🛡️ BTC Regime Lock Out Protocol</div>
            </div>
        """, unsafe_allow_html=True)

    def get_class(trend): return "metric-value-up" if "UP" in trend else "metric-value-down" if "DOWN" in trend else "metric-value-neutral"
    with col2:
        st.markdown(f"""
            <div class="dash-card">
                <div class="card-title">Bitcoin Regime Cluster <span style="color: #5D88FF; font-weight: bold;">{scanner_engine.btc_mtfa['Price']}</span></div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                    <div class="metric-box"><div style="font-size: 11px; color: #8C9BB5;">15M</div><div class="{get_class(scanner_engine.btc_mtfa['15M'])}">{scanner_engine.btc_mtfa['15M']}</div></div>
                    <div class="metric-box"><div style="font-size: 11px; color: #8C9BB5;">1H</div><div class="{get_class(scanner_engine.btc_mtfa['1H'])}">{scanner_engine.btc_mtfa['1H']}</div></div>
                    <div class="metric-box"><div style="font-size: 11px; color: #8C9BB5;">4H</div><div class="{get_class(scanner_engine.btc_mtfa['4H'])}">{scanner_engine.btc_mtfa['4H']}</div></div>
                    <div class="metric-box"><div style="font-size: 11px; color: #8C9BB5;">Daily</div><div class="{get_class(scanner_engine.btc_mtfa['1D'])}">{scanner_engine.btc_mtfa['1D']}</div></div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="dash-card" style="border: 1px solid #5D88FF; background: rgba(93, 136, 255, 0.03);"><div class="card-title" style="color: #5D88FF;">🚀 VALIDATED DIRECT SIGNALS TRADING WINDOW</div></div>', unsafe_allow_html=True)
    
    raw_scan = scanner_engine.results_data
    cross_signals = [s for s in raw_scan if "CROSS" in s['Signal'] and s['Asset'] not in st.session_state.ignored_assets]

    if cross_signals:
        for idx, sig in enumerate(cross_signals):
            coin_name = sig['Asset']
            coin_price = sig['Price']
            
            with st.container():
                c_lbl, c_prc, c_act1, c_act2 = st.columns([2, 2, 1, 1])
                c_lbl.markdown(f"<div style='padding-top:10px; font-weight:bold; color:#00E676;'>{coin_name}</div>", unsafe_allow_html=True)
                c_prc.markdown(f"<div style='padding-top:10px;'>Signal Price: <b>${round(coin_price, 6)}</b></div>", unsafe_allow_html=True)
                
                if c_act1.button("📥 ACCEPT", key=f"acc_{coin_name}_{idx}"):
                    st.session_state.staging_asset = {"Asset": coin_name, "Price": coin_price}
                
                if c_act2.button("🚫 IGNORE", key=f"ign_{coin_name}_{idx}"):
                    st.session_state.ignored_assets.add(coin_name)
                    st.rerun()

        # STEP 2 REMASTERED: 4 BOX PARAMETER SELECTION
        if st.session_state.staging_asset:
            st.markdown("---")
            st.markdown(f"### ⚙️ Configure Execution Parameter Set: **{st.session_state.staging_asset['Asset']}**")
            
            st_col1, st_col2, st_col3, st_col4 = st.columns(4)
            entry_input = st_col1.number_input("1. Entry Price ($)", value=float(st.session_state.staging_asset['Price']), format="%.6f")
            tp_input = st_col2.number_input("2. Take Profit (TP) ($)", value=float(st.session_state.staging_asset['Price'] * 1.02), format="%.6f")
            sl_input = st_col3.number_input("3. Stop Loss (SL) ($)", value=float(st.session_state.staging_asset['Price'] * 0.99), format="%.6f")
            capital_input = st_col4.number_input("4. Invested Capital ($)", value=100.0, step=10.0, format="%.2f")

            action_col1, action_col2 = st.columns([1, 5])
            if action_col1.button("🔥 CONFIRM EXECUTION"):
                active_df = pd.read_csv(ACTIVE_TRADES_FILE)
                
                if not (active_df['Asset'] == st.session_state.staging_asset['Asset']).any():
                    sl_tz = pytz.timezone('Asia/Colombo')
                    now_str = datetime.now(sl_tz).strftime("%Y-%m-%d %I:%M:%S %p")
                    
                    pd.DataFrame([{
                        "Asset": st.session_state.staging_asset['Asset'], "Entry_Price": entry_input,
                        "TP": tp_input, "SL": sl_input, "Capital": capital_input, "Time_Opened": now_str
                    }]).to_csv(ACTIVE_TRADES_FILE, mode='a', header=False, index=False)
                    
                    st.success(f"Position committed to processing module: {st.session_state.staging_asset['Asset']}")
                    st.session_state.ignored_assets.add(st.session_state.staging_asset['Asset'])
                    st.session_state.staging_asset = None
                    st.rerun()
                else:
                    st.warning("Asset is already listed inside active operational tracking loop.")

            if action_col2.button("Cancel Layout"):
                st.session_state.staging_asset = None
                st.rerun()
    else:
        st.markdown("<div style='color:#8C9BB5; text-align:center; padding:15px;'>No actionable crossover markers discovered in the active tracking frame.</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="dash-card"><div class="card-title">🌐 Asset Registry Matrix (Top Markets)</div></div>', unsafe_allow_html=True)
    other_signals = [s for s in raw_scan if "CROSS" not in s['Signal']]
    if other_signals:
        df_display = pd.DataFrame(other_signals)[["Asset", "Signal", "Price"]]
        st.dataframe(df_display, use_container_width=True, height=350, hide_index=True)

# -------------------------------------------------------------
# TAB 2: ACTIVE PORTFOLIO & RISK MODULE (UPGRADED CALCULATIONS)
# -------------------------------------------------------------
with tab_running:
    st.markdown("<h3 style='color: white; margin-top: 10px;'>⚡ Live Capital Portfolio & Risk Engine</h3>", unsafe_allow_html=True)
    
    if os.path.exists(ACTIVE_TRADES_FILE):
        active_df = pd.read_csv(ACTIVE_TRADES_FILE)
        
        if not active_df.empty:
            portfolio_data = []
            
            for _, row in active_df.iterrows():
                asset = row['Asset']
                entry = float(row['Entry_Price'])
                tp = float(row['TP'])
                sl = float(row['SL'])
                capital = float(row['Capital'])
                
                try:
                    p_resp = requests.get(f"https://data-api.binance.vision/api/v3/ticker/price?symbol={asset}", timeout=2).json()
                    current_price = float(p_resp['price'])
                except:
                    current_price = entry

                # Upgraded Math Engine Formulation Models
                pnl_pct = ((current_price - entry) / entry) * 100
                pnl_cash = capital * (pnl_pct / 100)
                
                reward_pct = ((tp - entry) / entry) * 100
                reward_cash = capital * (reward_pct / 100)
                
                risk_pct = ((entry - sl) / entry) * 100
                risk_cash = capital * (risk_pct / 100)
                
                rrr = (tp - entry) / (entry - sl) if (entry - sl) != 0 else 0

                portfolio_data.append({
                    "Asset": asset,
                    "Capital": f"${round(capital, 2)}",
                    "Entry Price": f"${round(entry, 6)}",
                    "Current Price": f"${round(current_price, 6)}",
                    "Live PNL (%)": f"{'+' if pnl_pct >= 0 else ''}{round(pnl_pct, 2)}%",
                    "Live PNL ($)": f"{'+$' if pnl_cash >= 0 else '-$'}{round(abs(pnl_cash), 2)}",
                    "Target (TP)": f"${round(tp, 6)}",
                    "Stop Floor (SL)": f"${round(sl, 6)}",
                    "Max Profit ($)": f"${round(reward_cash, 2)}",
                    "Max Risk ($)": f"${round(risk_cash, 2)}",
                    "RRR": f"1:{round(rrr, 2)}",
                    "Status": "RUNNING ⚡"
                })

            port_df = pd.DataFrame(portfolio_data)

            def style_live_returns(val):
                if isinstance(val, str):
                    if '-' in val: return 'color: #FF4B4B; font-weight:bold;'
                    if '+' in val or '$' in val: return 'color: #00E676; font-weight:bold;'
                return ''
                
            st.dataframe(
                port_df.style.map(style_live_returns, subset=['Live PNL (%)', 'Live PNL ($)']), 
                use_container_width=True, 
                hide_index=True
            )
        else:
            st.info("No active capital allocations running.")
    else:
        st.info("No active capital allocations running.")

# -------------------------------------------------------------
# TAB 3: CLOSED JOURNAL REGISTRY (PERMANENT ARCHIVE STORAGE)
# -------------------------------------------------------------
with tab_journal:
    st.markdown("<h3 style='color: white; margin-top: 10px;'>📜 Historical Capital Trade Journal</h3>", unsafe_allow_html=True)
    if os.path.exists(TRADE_JOURNAL_FILE):
        journal_df = pd.read_csv(TRADE_JOURNAL_FILE)
        if not journal_df.empty:
            st.dataframe(journal_df.iloc[::-1], use_container_width=True, height=500, hide_index=True)
            st.download_button(
                label="📥 Export Ledger Dataset (CSV)",
                data=journal_df.to_csv(index=False).encode('utf-8'),
                file_name="capital_trade_history.csv",
                mime="text/csv"
            )
        else:
            st.info("Historical ledger is clear.")
    else:
        st.info("Historical ledger is clear.")

# -------------------------------------------------------------
# TAB 4: FUNDAMENTAL MONITOR WIRE
# -------------------------------------------------------------
with tab_intel:
    st.markdown("<h3 style='color: white; margin-top: 10px;'>📰 Fundamental Wire Feed</h3>", unsafe_allow_html=True)
    if news_entries:
        for entry in news_entries[:10]:
            clean_summary = clean_html(entry.summary)
            st.markdown(f'<div class="dash-card" style="margin-bottom: 20px; padding: 20px; border-left: 4px solid #FF4B4B;"><div style="font-weight: 700; font-size: 16px; color: #FFFFFF; margin-bottom: 10px;">{entry.title}</div><div style="color: #E0E6ED; font-size: 13px; line-height: 1.5; margin-bottom: 10px;">{clean_summary}</div><div style="color: #8C9BB5; font-size: 11px; font-weight: bold;">🕒 {entry.published}</div></div>', unsafe_allow_html=True)
