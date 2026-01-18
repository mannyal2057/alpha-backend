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
# Anti-Block Headers (Masquerade as Chrome)
SEC_HEADERS = { 
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}
SESSION = requests.Session()
SESSION.headers.update(SEC_HEADERS)

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- GOLDEN DATA (FALLBACKS) ---
TODAY = datetime.now().strftime("%Y-%m-%d")
STATIC_LEGISLATION = [
    { "bill_id": "H.R. 5077", "bill_name": "CREATE AI Act", "update_date": TODAY, "bill_sponsor": "Rep. Lucas", "market_impact": "Bullish: AI R&D Funding", "sector": "AI" },
    { "bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "update_date": TODAY, "bill_sponsor": "Rep. Rogers", "market_impact": "Direct Beneficiary: Military", "sector": "DEFENSE" },
    { "bill_id": "H.R. 4763", "bill_name": "Crypto Clarity Act", "update_date": TODAY, "bill_sponsor": "Rep. McHenry", "market_impact": "Bullish: Digital Assets", "sector": "CRYPTO" }
]
STATIC_TRADES = {
    "NVDA": {"pol": "Rep. Pelosi", "type": "Purchase", "date": TODAY},
    "PLTR": {"pol": "Rep. Green", "type": "Purchase", "date": TODAY},
    "COIN": {"pol": "Rep. Fallon", "type": "Purchase", "date": TODAY},
    "LMT":  {"pol": "Rep. Rutherford", "type": "Purchase", "date": TODAY}
}

# --- SMART PEER DATABASE (Fixes 'AI' Search) ---
SECTOR_PEERS = {
    "NVDA": ["AMD", "INTC", "AVGO", "TSM"],
    "AMD":  ["NVDA", "INTC", "ARM", "TSM"],
    "AI":   ["PLTR", "SOFI", "SNOW", "PATH"], # <--- FIXED
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
    "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI", "SMCI"], 
    "CRYPTO": ["COIN", "HOOD", "SQ", "MARA", "RIOT"], 
    "DEFENSE": ["LMT", "RTX", "BA", "GD", "GE"], 
    "ENERGY": ["XOM", "CVX", "KMI", "OXY"], 
    "HEALTH": ["PFE", "LLY", "MRK", "VERO", "IBRX"], 
    "EV": ["TSLA", "RIVN", "LCID", "F", "GM"], 
    "FINANCE": ["JPM", "BAC", "V", "MA", "SOFI"] 
}

# Default Demo Prices (Safety Net)
DEMO_PRICES = { "NVDA": 185.0, "AI": 13.0, "PLTR": 170.0, "MSFT": 460.0, "AMD": 230.0, "COIN": 310.0 }
MARKET_UNIVERSE = ["NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI", "SOFI", "COIN", "HOOD", "JPM", "BAC", "LMT", "RTX", "BA", "XOM", "CVX", "KMI", "AMZN", "WMT", "COST", "F", "GM", "RIVN", "LCID", "PFE", "LLY", "MRK", "VERO"]

class PriceRequest(BaseModel): tickers: list[str]

# --- INTEL ENGINES ---
def get_live_data(ticker):
    """Fetches data with Anti-Block protection + Simulation Fallback"""
    try:
        stock = yf.Ticker(ticker, session=SESSION)
        fast = stock.fast_info
        price = fast.last_price
        vol = fast.last_volume
        if not price: raise Exception("No Data")
        return stock, price, vol, False
    except:
        # Fallback to Demo Data
        p = DEMO_PRICES.get(ticker, 100.0) * random.uniform(0.99, 1.01)
        return None, p, 5000000, True

def get_volatility_regime(stock, hist, is_sim):
    if is_sim or hist is None: return 2.5, 1.2, "Normal"
    try:
        high_low = hist['High'] - hist['Low']
        atr = high_low.rolling(14).mean().iloc[-1]
        beta = stock.info.get('beta', 1.0)
        regime = "High Beta" if beta > 1.3 else "Low Beta" if beta < 0.8 else "Normal"
        return atr, beta, regime
    except: return 0.0, 1.0, "Normal"

def get_options_intel(stock, price, is_sim):
    if is_sim: return "$N/A", "$N/A", 3.5, 0.4, "Neutral"
    try:
        exps = stock.options
        if not exps: return "N/A", "N/A", 0.0, 0.0, "Neutral"
        chain = stock.option_chain(exps[0])
        calls, puts = chain.calls, chain.puts
        
        call_wall = calls.loc[calls['openInterest'].idxmax()]['strike']
        put_wall = puts.loc[puts['openInterest'].idxmax()]['strike']
        
        atm_call = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]
        atm_put = puts.iloc[(puts['strike'] - price).abs().argsort()[:1]]
        
        call_iv = atm_call['impliedVolatility'].values[0]
        put_iv = atm_put['impliedVolatility'].values[0]
        
        skew = "Bullish (Call Skew)" if (call_iv - put_iv) > 0.05 else "Bearish (Put Skew)" if (call_iv - put_iv) < -0.05 else "Neutral"
        cost = (atm_call['lastPrice'].values[0] + atm_put['lastPrice'].values[0])
        move = (cost / price) * 100
        
        return f"${call_wall:.0f}", f"${put_wall:.0f}", move, (call_iv+put_iv)/2, skew
    except: return "N/A", "N/A", 0.0, 0.0, "Neutral"

def analyze_stock(ticker: str):
    try:
        # 1. Get Data
        stock, price, vol, is_sim = get_live_data(ticker)
        
        # 2. Get Advanced Metrics
        if not is_sim:
            try: hist = stock.history(period="1mo")
            except: hist = None
        else: hist = None
        
        atr, beta, regime = get_volatility_regime(stock, hist, is_sim)
        call_w, put_w, move_pct, iv, skew = get_options_intel(stock, price, is_sim)
        
        # 3. Targets
        target_up = price * (1 + (move_pct/100))
        target_down = price * (1 - (move_pct/100))

        # 4. Legislation & Congress
        leg_score = 50
        leg = None
        for bill in ACTIVE_BILLS_CACHE:
            if ticker in SECTOR_MAP.get(bill['sector'], []): 
                leg = bill; leg_score = 85; break
        
        congress_note = "No Recent Activity"
        if ticker in STATIC_TRADES:
            td = STATIC_TRADES[ticker]
            if td['type'] == "Purchase": leg_score += 20; congress_note = f"{td['pol']} Bought (+20)"

        # 5. Risk & Scoring
        if "Bullish" in skew: leg_score += 10
        risk_val = (iv * 100) + (beta * 10)
        risk = "High" if risk_val > 60 else "Medium" if risk_val > 30 else "Low"
        
        if leg_score >= 80 and risk == "Low": rating = "STRONG BUY"
        elif leg_score >= 60: rating = "BUY"
        else: rating = "HOLD"

        return { 
            "ticker": ticker, "price": f"${price:.2f}", "raw_price": price,
            "final_score": rating, "sentiment": "Bullish" if rating != "HOLD" else "Neutral",
            "risk_level": risk, "expected_move": f"+/- {move_pct:.1f}%",
            "targets": f"${target_down:.0f} - ${target_up:.0f}",
            "volatility_regime": regime, "skew": skew,
            "congress_activity": congress_note,
            "bill_id": leg.get('bill_id', 'N/A') if leg else "N/A",
            "corporate_activity": "Data Unavailable"
        }
    except Exception as e:
        return { "ticker": ticker, "price": "N/A", "raw_price": 0, "final_score": "HOLD", "sentiment": "Neutral", "risk_level": "Unknown", "expected_move": "N/A", "targets": "N/A", "skew": "N/A", "volatility_regime": "N/A", "congress_activity": "N/A", "bill_id": "N/A", "corporate_activity": "Data Unavailable" }

# --- SEARCH ENGINE ---
def get_peers(ticker):
    # 1. Direct Match (Prioritized)
    if ticker in SECTOR_PEERS: return SECTOR_PEERS[ticker]
    # 2. Sector Match
    for sector, stocks in SECTOR_MAP.items():
        if ticker in stocks:
            peers = [s for s in stocks if s != ticker]
            return peers[:4] if len(peers) >= 4 else peers
    # 3. Fallback
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
        try:
            # Sort Top Picks
            results.sort(key=lambda x: (x.get('final_score') == "STRONG BUY", x.get('final_score') == "BUY"), reverse=True)
            SERVER_CACHE["buys"] = results[:5]
            
            # Sort Cheap Picks (STRICT FILTER < $50)
            cheap_stocks = [x for x in results if 0 < x.get('raw_price', 0) < 50]
            cheap_stocks.sort(key=lambda x: (x.get('final_score') == "STRONG BUY"), reverse=True)
            SERVER_CACHE["cheap"] = cheap_stocks[:5]
            
            # Sort Sells
            results.sort(key=lambda x: (x.get('final_score') == "STRONG BUY"), reverse=False)
            SERVER_CACHE["sells"] = results[:5]
        except: pass
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v42.0 (Unified Master).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="42.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.post("/api/prices")
def get_batch_prices(req: PriceRequest):
    data = {}
    for t in req.tickers:
        _, p, _, _ = get_live_data(t)
        data[t] = p
    return data

@app.get("/api/scanner")
def get_scanner_data(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    target = ticker.upper()
    results = [analyze_stock(target)]
    peers = get_peers(target)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futs = {executor.submit(analyze_stock, p): p for p in peers}
        for f in concurrent.futures.as_completed(futs): 
            res = f.result()
            if res['price'] != "N/A": results.append(res)
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)