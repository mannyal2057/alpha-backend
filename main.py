import os
import json
import random
import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
CONGRESS_KEY = os.getenv("CONGRESS_API_KEY", "DEMO_KEY") 
SEC_HEADERS = { "User-Agent": "AlphaInsider/32.0 (admin@alphainsider.io)", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov" }
DB_FILE = "paper_trading.json"

# --- CACHE ---
CIK_CACHE = {} 
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- TRADING DATABASE ---
def load_db():
    if not os.path.exists(DB_FILE):
        default_db = {"cash": 100000.0, "holdings": {}, "history": []}
        with open(DB_FILE, "w") as f: json.dump(default_db, f)
        return default_db
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return {"cash": 100000.0, "holdings": {}, "history": []}

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)

class TradeRequest(BaseModel):
    ticker: str
    action: str
    quantity: int

# --- SECTOR DATA ---
SECTOR_PEERS = { "NVDA": ["AMD", "INTC", "AVGO", "QCOM"], "F": ["GM", "TM", "HMC", "TSLA"], "TSLA": ["RIVN", "LCID", "F", "GM"], "VERO": ["PODD", "DXCM", "MDT"], "SOFI": ["LC", "UPST", "COIN", "HOOD"], "COIN": ["HOOD", "MARA", "RIOT"], "SQ": ["PYPL", "COIN"], "BA": ["LMT", "RTX", "GD"], "PFE": ["MRK", "BMY", "LLY"], "AAL": ["DAL", "UAL", "LUV"], "AAPL": ["MSFT", "GOOGL", "AMZN"], "XOM": ["CVX", "SHEL", "BP"] }
SECTOR_MAP = { "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI"], "CRYPTO": ["COIN", "HOOD", "SQ", "MARA"], "DEFENSE": ["LMT", "RTX", "BA", "GD", "GE"], "ENERGY": ["XOM", "CVX", "KMI", "OXY"], "HEALTH": ["PFE", "LLY", "MRK", "VERO", "IBRX"], "EV": ["TSLA", "RIVN", "LCID", "F", "GM"], "FINANCE": ["JPM", "BAC", "V", "MA", "SOFI"] }
CONGRESS_TRADES_DB = { "NVDA": {"pol": "Rep. Pelosi", "type": "Purchase", "date": "2024-11-22"}, "MSFT": {"pol": "Rep. Khanna", "type": "Purchase", "date": "2024-12-15"}, "LMT": {"pol": "Rep. Rutherford", "type": "Purchase", "date": "2024-12-05"}, "RTX": {"pol": "Sen. Tuberville", "type": "Purchase", "date": "2024-11-28"} }
MARKET_UNIVERSE = ["NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI", "SOFI", "COIN", "HOOD", "PYPL", "SQ", "JPM", "BAC", "LMT", "RTX", "BA", "GE", "XOM", "CVX", "AA", "KMI", "AMZN", "WMT", "COST", "F", "GM", "RIVN", "LCID", "PFE", "LLY", "MRK", "IBRX", "MRNA", "VERO", "DXCM"]

# --- CORE LOGIC ---
def fetch_real_legislation():
    url = f"https://api.congress.gov/v3/bill?api_key={CONGRESS_KEY}&limit=25&sort=updateDate+desc"
    cleaned_bills = []
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            bills = r.json().get('bills', [])
            for b in bills:
                title = str(b.get('title', 'Unknown')).upper()
                bill_id = f"{b.get('type', 'HR').upper()} {b.get('number', '000')}"
                impact, score, sector = "Neutral: Monitoring.", 50, None
                if "INTELLIGENCE" in title or "TECHNOLOGY" in title: impact, score, sector = "Bullish: Tech investment.", 85, "AI"
                elif "DEFENSE" in title: impact, score, sector = "Direct Beneficiary: Military.", 92, "DEFENSE"
                elif "ENERGY" in title: impact, score, sector = "Bullish: Infrastructure.", 80, "ENERGY"
                elif "HEALTH" in title: impact, score, sector = "Neutral: Health funding.", 65, "HEALTH"
                elif "CRYPTO" in title: impact, score, sector = "Bullish: Crypto Regs.", 88, "CRYPTO"
                if sector: cleaned_bills.append({ "bill_id": bill_id, "bill_name": title[:60]+"...", "bill_sponsor": "Congress", "impact_score": score, "market_impact": impact, "sector": sector })
    except: pass
    
    # ALWAYS ADD FALLBACKS to ensure non-empty display
    cleaned_bills.append({ "bill_id": "H.R. 8070", "bill_name": "Natl Defense Auth Act", "bill_sponsor": "Rep. Rogers", "impact_score": 92, "market_impact": "Direct Beneficiary: Military.", "sector": "DEFENSE" })
    cleaned_bills.append({ "bill_id": "H.R. 2882", "bill_name": "Appropriations Act", "bill_sponsor": "Rep. Granger", "impact_score": 60, "market_impact": "Neutral: Gov Funding.", "sector": "FINANCE" })
    cleaned_bills.append({ "bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer", "impact_score": 85, "market_impact": "Bullish: Tech Standards.", "sector": "AI" })
    
    return cleaned_bills

def get_legislative_intel(ticker: str):
    for bill in ACTIVE_BILLS_CACHE:
        if ticker in SECTOR_MAP.get(bill['sector'], []): return bill
    return {"bill_id": "N/A", "impact_score": 50, "market_impact": "No active legislation found.", "bill_sponsor": "N/A"}

def analyze_stock(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        try: 
            fast = stock.fast_info
            price = fast.last_price or 0.0
            vol = fast.last_volume or 0
        except: price, vol = 0.0, 0
        price_str = f"${price:.2f}"
        vol_str = "High (Buying)" if vol > 1000000 else "Neutral"
    except: return {"ticker": ticker, "raw_price": 0, "final_score": "HOLD", "legislation_score": 50, "price": "N/A"}

    leg = get_legislative_intel(ticker)
    score = leg.get('impact_score', 50)
    if "High" in vol_str: score += 5
    
    # Congress Bonus
    congress_note = "No Recent Activity"
    trade_data = CONGRESS_TRADES_DB.get(ticker)
    if trade_data:
        if trade_data['type'] == "Purchase": score += 25; congress_note = f"{trade_data['pol']} (Bought) +25%"
        elif trade_data['type'] == "Sale": score -= 25; congress_note = f"{trade_data['pol']} (Sold) -25%"

    # Insider Trades (RESTORED)
    action_text = "No Recent Trades"
    cutoff_date = datetime.now() - timedelta(days=540)
    try:
        trades = stock.insider_transactions
        if trades is not None and not trades.empty:
            if 'Start Date' in trades.columns: trades = trades.sort_values(by='Start Date', ascending=False)
            latest = trades.iloc[0]
            trade_date = latest.get('Start Date') or latest.name
            if trade_date and pd.to_datetime(trade_date) > cutoff_date:
                full_name = str(latest.get('Insider', 'Exec')).split(' ')
                who = full_name[-1] if len(full_name) > 1 else full_name[0]
                raw = str(latest.get('Text', '')).lower()
                act = "Sold" if "sale" in raw or "sold" in raw else "Bought"
                date_str = pd.to_datetime(trade_date).strftime('%b %d')
                action_text = f"{who} ({act}) {date_str}"
    except: pass

    if score > 99: score = 99
    if score >= 75: rating, sentiment, timing = "STRONG BUY", "Bullish", "Accumulate"
    elif score >= 60: rating, sentiment, timing = "BUY", "Bullish", "Add Dip"
    elif score <= 45: rating, sentiment, timing = "SELL", "Bearish", "Exit"
    else: rating, sentiment, timing = "HOLD", "Neutral", "Wait"

    return { 
        "ticker": ticker, 
        "raw_price": price, 
        "price": price_str, 
        "legislation_score": score, 
        "final_score": rating, 
        "sentiment": sentiment, # RESTORED
        "timing_signal": timing, # RESTORED
        "volume_signal": vol_str, # RESTORED
        "congress_activity": congress_note, 
        "corporate_activity": action_text, # RESTORED
        "bill_id": leg.get('bill_id', 'N/A'), # RESTORED
        "bill_sponsor": leg.get('bill_sponsor', 'N/A'), # RESTORED
        "market_impact": leg.get('market_impact', 'N/A')
    }

# --- BACKGROUND WORKER ---
async def update_market_scanner():
    global ACTIVE_BILLS_CACHE
    while True:
        print("🔄 [BACKGROUND] Refreshing Intelligence...")
        bills = fetch_real_legislation()
        if bills: ACTIVE_BILLS_CACHE = bills
        
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ticker = {executor.submit(analyze_stock, sym): sym for sym in MARKET_UNIVERSE}
            for future in concurrent.futures.as_completed(future_to_ticker):
                try: results.append(future.result())
                except: pass
        
        results.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["buys"] = results[:5]
        cheap = [x for x in results if 0 < x['raw_price'] < 50]
        cheap.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["cheap"] = cheap[:5]
        results.sort(key=lambda x: x['legislation_score'], reverse=False)
        SERVER_CACHE["sells"] = results[:5]
        SERVER_CACHE["last_updated"] = datetime.now().strftime("%H:%M:%S")
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v32.0 (Restored Data Fields).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="32.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/portfolio")
def get_portfolio():
    db = load_db()
    total_equity = db["cash"]
    holdings_