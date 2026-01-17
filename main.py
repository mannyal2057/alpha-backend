import os
import random
import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/21.0 (admin@alphainsider.io)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}
CIK_CACHE = {} 

# --- THE SHARED "CLIPBOARD" (CACHE) ---
# This variable lives in the server's RAM. All users share it.
SERVER_CACHE = {
    "buys": [],
    "cheap": [],
    "sells": [],
    "last_updated": None
}

# --- THE SCANNER UNIVERSE ---
MARKET_UNIVERSE = [
    "NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI", "SMCI", "ARM",
    "SOFI", "COIN", "HOOD", "PYPL", "SQ", "JPM", "BAC", "V", "MA",
    "LMT", "RTX", "BA", "GE", "CAT", "DE", "HON",
    "XOM", "CVX", "AA", "KMI", "OXY", "COP", "SLB",
    "AMZN", "WMT", "COST", "TGT", "F", "GM", "RIVN", "LCID",
    "PFE", "LLY", "MRK", "UNH", "IBRX", "MRNA", "VERO", "DXCM"
]

# --- LEGISLATIVE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    if t in ["LMT", "RTX"]: return {"bill_id": "H.R. 8070", "impact_score": 95, "market_impact": "Direct Beneficiary: Defense spending increase."}
    if t in ["NVDA", "AMD", "MSFT"]: return {"bill_id": "S. 2714", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t in ["KMI", "AA", "XOM"]: return {"bill_id": "H.R. 1", "impact_score": 85, "market_impact": "Bullish: Energy infrastructure permits."}
    if t in ["SOFI", "COIN"]: return {"bill_id": "H.R. 4763", "impact_score": 85, "market_impact": "Bullish: Crypto/Fintech regulatory clarity."}
    if t in ["F", "GM"]: return {"bill_id": "H.R. 4468", "impact_score": 82, "market_impact": "Bullish: Slowing EV mandates helps margins."}
    
    if t in ["PLTR", "AI"]: return {"bill_id": "S. 2714", "impact_score": 40, "market_impact": "Bearish: Compliance costs for AI software."}
    if t in ["LCID", "RIVN"]: return {"bill_id": "H.R. 4468", "impact_score": 30, "market_impact": "Bearish: Removal of EV-only subsidies."}
    
    return {"bill_id": "H.R. 5525", "impact_score": 50, "market_impact": "Neutral: General market monitoring."}

# --- CORE ANALYSIS ---
def analyze_stock(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        fast = stock.fast_info
        price = fast.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        vol = fast.last_volume
        vol_str = "High (Buying)" if (vol and vol > 1000000) else "Neutral"
        try: eps = stock.info.get('trailingEps', 0)
        except: eps = 0
        fin_str = "Profitable" if eps > 0 else "Unprofitable"
    except:
        price = 0.0
        price_str, vol_str, fin_str = "N/A", "N/A", "N/A"

    leg = get_legislative_intel(ticker)
    
    # Quick Corporate Action Check
    action_text = "Monitoring..."
    try:
        trades = stock.insider_transactions
        if trades is not None and not trades.empty:
            latest = trades.iloc[0]
            # Simple check, no date filter for speed in background loop
            who = str(latest.get('Insider', 'Exec')).split(' ')[-1]
            raw = str(latest.get('Text', '')).lower()
            act = "Sold" if "sale" in raw or "sold" in raw else "Bought"
            # Just grab the date
            date_val = latest.get('Start Date') or latest.name
            date_str = pd.to_datetime(date_val).strftime('%b %d')
            action_text = f"{who} ({act}) {date_str}"
    except: pass

    score = leg['impact_score']
    if "High" in vol_str: score += 5
    
    if score >= 75: rating, timing = "STRONG BUY", "Accumulate"
    elif score >= 60: rating, timing = "BUY", "Add Dip"
    elif score <= 45: rating, timing = "SELL", "Exit"
    else: rating, timing = "HOLD", "Wait"

    return {
        "ticker": ticker,
        "raw_price": price or 0,
        "price": price_str,
        "volume_signal": vol_str,
        "financial_health": fin_str,
        "legislation_score": score,
        "timing_signal": timing,
        "sentiment": "Bullish" if "BUY" in rating else "Bearish",
        "final_score": rating,
        "corporate_activity": action_text,
        "market_impact": leg.get('market_impact', 'N/A')
    }

# --- BACKGROUND WORKER (THE ROBOT) ---
async def update_market_scanner():
    """This runs automatically every 10 minutes in the background."""
    while True:
        print("🔄 [BACKGROUND] Starting Market Scan...")
        results = []
        
        # 1. Heavy Lifting
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ticker = {executor.submit(analyze_stock, sym): sym for sym in MARKET_UNIVERSE}
            for future in concurrent.futures.as_completed(future_to_ticker):
                try: results.append(future.result())
                except: pass
        
        # 2. Sort & Filter into Cache
        # BUYS
        results.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["buys"] = results[:5]
        
        # CHEAP
        cheap = [x for x in results if x['raw_price'] < 50 and x['raw_price'] > 0]
        cheap.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["cheap"] = cheap[:5]
        
        # SELLS (Lowest Score)
        results.sort(key=lambda x: x['legislation_score'], reverse=False)
        SERVER_CACHE["sells"] = results[:5]
        
        SERVER_CACHE["last_updated"] = datetime.now().strftime("%H:%M:%S")
        print(f"✅ [BACKGROUND] Cache Updated at {SERVER_CACHE['last_updated']}")
        
        # 3. Sleep for 10 minutes (600 seconds)
        await asyncio.sleep(600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v21.0 (Shared Server Cache).")
    
    # 1. Load SEC Data
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=3)
        if r.status_code == 200:
            data = r.json()
            for key in data: CIK_CACHE[data[key]['ticker']] = str(data[key]['cik_str']).zfill(10)
    except: pass
    
    # 2. Start the Background Robot
    asyncio.create_task(update_market_scanner())
    
    yield

app = FastAPI(title="AlphaInsider Pro", version="21.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/scanner")
def get_scanner_data(mode: str = "buys"):
    # This endpoint is now INSTANT because it just reads from memory
    return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    # Keep standard search logic for manual lookups
    if single: return [analyze_stock(ticker.upper())]
    return [analyze_stock(ticker.upper())]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)