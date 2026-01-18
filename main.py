import os
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
import numpy as np

# --- CONFIGURATION ---
CONGRESS_KEY = os.getenv("CONGRESS_API_KEY", "DEMO_KEY") 
SEC_HEADERS = { "User-Agent": "AlphaInsider/39.0 (admin@alphainsider.io)", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov" }

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- GOLDEN DATA ---
TODAY = datetime.now().strftime("%Y-%m-%d")
STATIC_FED_MEETINGS = ["2026-01-28", "2026-03-18", "2026-05-06"] 

STATIC_LEGISLATION = [
    { "bill_id": "H.R. 5077", "bill_name": "CREATE AI Act", "update_date": TODAY, "bill_sponsor": "Rep. Lucas", "market_impact": "Bullish: AI R&D Funding", "sector": "AI" },
    { "bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "update_date": TODAY, "bill_sponsor": "Rep. Rogers", "market_impact": "Direct Beneficiary: Military", "sector": "DEFENSE" },
    { "bill_id": "H.R. 4763", "bill_name": "Crypto Clarity Act", "update_date": TODAY, "bill_sponsor": "Rep. McHenry", "market_impact": "Bullish: Digital Assets", "sector": "CRYPTO" }
]

STATIC_TRADES = {
    "NVDA": {"pol": "Rep. Pelosi", "type": "Purchase", "date": TODAY},
    "PLTR": {"pol": "Rep. Green", "type": "Purchase", "date": TODAY},
    "COIN": {"pol": "Rep. Fallon", "type": "Purchase", "date": TODAY},
    "LMT": {"pol": "Rep. Rutherford", "type": "Purchase", "date": TODAY}
}

# --- EXPANDED PEER DATABASE ---
# This ensures specific stocks get specific comparisons
SECTOR_PEERS = {
    "NVDA": ["AMD", "INTC", "AVGO", "TSM"],
    "AMD":  ["NVDA", "INTC", "ARM", "TSM"],
    "AI":   ["PLTR", "SOFI", "SNOW", "PATH"], # Fixed: AI (C3.ai) Peers
    "PLTR": ["AI", "SNOW", "DDOG", "MDB"],
    "F":    ["GM", "TM", "TSLA", "RIVN"],
    "TSLA": ["RIVN", "LCID", "F", "GM"],
    "COIN": ["HOOD", "MARA", "RIOT", "MSTR"],
    "HOOD": ["COIN", "SCHW", "IBKR", "SOFI"],
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL"],
    "LMT":  ["RTX", "BA", "GD", "NOC"],
    "RTX":  ["LMT", "BA", "GE", "HON"],
    "XOM":  ["CVX", "SHEL", "BP", "COP"],
    "PFE":  ["MRK", "LLY", "JNJ", "ABBV"],
    "JPM":  ["BAC", "C", "WFC", "GS"]
}

SECTOR_MAP = { 
    "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI", "SMCI", "AVGO", "INTC", "ARM"], 
    "CRYPTO": ["COIN", "HOOD", "SQ", "MARA", "RIOT", "MSTR"], 
    "DEFENSE": ["LMT", "RTX", "BA", "GD", "GE", "NOC", "LHX"], 
    "ENERGY": ["XOM", "CVX", "KMI", "OXY", "SLB", "HAL"], 
    "HEALTH": ["PFE", "LLY", "MRK", "VERO", "IBRX", "JNJ", "UNH"], 
    "EV": ["TSLA", "RIVN", "LCID", "F", "GM", "TM"], 
    "FINANCE": ["JPM", "BAC", "V", "MA", "SOFI", "C", "WFC", "GS"] 
}

MARKET_UNIVERSE = ["NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI", "SOFI", "COIN", "HOOD", "JPM", "BAC", "LMT", "RTX", "BA", "XOM", "CVX", "KMI", "AMZN", "WMT", "COST", "F", "GM", "RIVN", "LCID", "PFE", "LLY", "MRK", "VERO"]

class PriceRequest(BaseModel): tickers: list[str]

# --- INTEL ENGINES ---
def get_volatility_regime(stock, hist):
    try:
        high_low = hist['High'] - hist['Low']
        high_close = (hist['High'] - hist['Close'].shift()).abs()
        low_close = (hist['Low'] - hist['Close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(14).mean().iloc[-1]
        beta = stock.info.get('beta', 1.0)
        regime = "High Beta (Aggressive)" if beta > 1.5 else "Low Beta (Defensive)" if beta < 0.8 else "Normal"
        return atr, beta, regime
    except: return 0.0, 1.0, "Unknown"

def get_options_structure(stock, price):
    try:
        exps = stock.options
        if not exps: return "N/A", "N/A", "N/A", 0.0
        chain = stock.option_chain(exps[0])
        calls, puts = chain.calls, chain.puts
        call_wall = calls.loc[calls['openInterest'].idxmax()]['strike']
        put_wall = puts.loc[puts['openInterest'].idxmax()]['strike']
        atm_call = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]
        atm_put = puts.iloc[(puts['strike'] - price).abs().argsort()[:1]]
        straddle_cost = (atm_call['lastPrice'].values[0] + atm_put['lastPrice'].values[0])
        exp_move_pct = (straddle_cost / price) * 100
        iv = atm_call['impliedVolatility'].values[0]
        return f"${call_wall:.0f}", f"${put_wall:.0f}", f"+/- {exp_move_pct:.1f}%", iv
    except: return "N/A", "N/A", "N/A", 0.0

def get_event_risk(ticker, stock):
    risk_score, events = 0, []
    try:
        cal = stock.calendar
        if not cal.empty:
            days_to = (pd.to_datetime(cal.iloc[0, 0]).replace(tzinfo=None) - datetime.now()).days
            if 0 <= days_to <= 7: risk_score += 3; events.append(f"Earnings {days_to}d")
    except: pass
    return risk_score, ", ".join(events) if events else "None"

def analyze_stock(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1mo")
        fast = stock.fast_info
        price = fast.last_price or 0.0
        if price == 0: raise Exception("No Data")

        atr, beta, vol_regime = get_volatility_regime(stock, hist)
        call_wall, put_wall, exp_move, iv = get_options_structure(stock, price)
        event_risk_score, upcoming_events = get_event_risk(ticker, stock)

        leg_score = 50
        leg = None
        for bill in ACTIVE_BILLS_CACHE:
            if ticker in SECTOR_MAP.get(bill['sector'], []): 
                leg = bill; leg_score = 85; break
        
        congress_note = "No Recent Activity"
        if ticker in STATIC_TRADES:
            td = STATIC_TRADES[ticker]
            if td['type'] == "Purchase": leg_score += 20; congress_note = f"{td['pol']} Bought (+20)"
            
        risk_val = (iv * 100) + (beta * 10) + (event_risk_score * 10)
        risk_level = "High (Volatile)" if risk_val > 60 else "Medium" if risk_val > 30 else "Low (Safe)"

        if leg_score >= 80 and risk_level == "Low (Safe)": rating = "STRONG BUY"
        elif leg_score >= 60: rating = "BUY"
        else: rating = "HOLD"

        return { 
            "ticker": ticker, "raw_price": price, "price": f"${price:.2f}",
            "final_score": rating, "sentiment": "Bullish" if rating != "HOLD" else "Neutral",
            "risk_level": risk_level, "expected_move": exp_move,
            "volatility_regime": vol_regime, "congress_activity": congress_note,
            "bill_id": leg.get('bill_id', 'N/A') if leg else "N/A",
            "corporate_activity": upcoming_events if upcoming_events != "None" else "No Events"
        }
    except Exception as e:
        return { 
            "ticker": ticker, "raw_price": 0, "price": "N/A", "final_score": "HOLD", "sentiment": "Neutral", 
            "risk_level": "Unknown", "expected_move": "N/A", "volatility_regime": "N/A",
            "congress_activity": "N/A", "bill_id": "N/A", "corporate_activity": "Data Unavailable"
        }

# --- SEARCH ENGINE ---
def get_peers(ticker):
    # 1. Direct Match
    if ticker in SECTOR_PEERS: return SECTOR_PEERS[ticker]
    
    # 2. Sector Match
    for sector, stocks in SECTOR_MAP.items():
        if ticker in stocks:
            # Return 4 random peers from the same sector
            peers = [s for s in stocks if s != ticker]
            return peers[:4] if len(peers) >= 4 else peers
            
    # 3. Fallback (Tech Giants)
    return ["AAPL", "MSFT", "NVDA", "GOOGL"]

def fetch_real_legislation(): return STATIC_LEGISLATION

async def update_market_scanner():
    global ACTIVE_BILLS_CACHE
    while True:
        ACTIVE_BILLS_CACHE = fetch_real_legislation()
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futs = {executor.submit(analyze_stock, s): s for s in MARKET_UNIVERSE}
            for f in concurrent.futures.as_completed(futs): results.append(f.result())
        
        # --- FIXED SCANNER LOGIC ---
        try:
            # 1. TOP PICKS: Sort by Score (Highest First)
            results.sort(key=lambda x: (x.get('final_score') == "STRONG BUY", x.get('final_score') == "BUY"), reverse=True)
            SERVER_CACHE["buys"] = results[:5]
            
            # 2. CHEAP PICKS: Filter < $50 THEN Sort
            cheap_stocks = [x for x in results if 0 < x.get('raw_price', 0) < 50]
            cheap_stocks.sort(key=lambda x: (x.get('final_score') == "STRONG BUY", x.get('final_score') == "BUY"), reverse=True)
            SERVER_CACHE["cheap"] = cheap_stocks[:5]
            
            # 3. SELLS: Sort by Score (Lowest First)
            results.sort(key=lambda x: (x.get('final_score') == "STRONG BUY"), reverse=False)
            SERVER_CACHE["sells"] = results[:5]
            
        except Exception as e: print(f"Scanner Sort Error: {e}")
        
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v39.0 (Smart Search Engine).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="39.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.post("/api/prices")
def get_batch_prices(req: PriceRequest):
    data = {}
    for t in req.tickers:
        try: data[t] = yf.Ticker(t).fast_info.last_price or 0.0
        except: data[t] = 0.0
    return data

@app.get("/api/scanner")
def get_scanner_data(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    target = ticker.upper()
    
    # ALWAYS FETCH 5 RESULTS
    # 1. Analyze Target
    results = [analyze_stock(target)]
    
    # 2. Find and Analyze Peers
    peers = get_peers(target)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futs = {executor.submit(analyze_stock, p): p for p in peers}
        for f in concurrent.futures.as_completed(futs): 
            res = f.result()
            if res['price'] != "N/A": results.append(res)
            
    # Ensure we return at least the main ticker if peers fail
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)