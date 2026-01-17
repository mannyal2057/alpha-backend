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
CONGRESS_KEY = os.getenv("CONGRESS_API_KEY", "DEMO_KEY") 

SEC_HEADERS = {
    "User-Agent": "AlphaInsider/26.0 (admin@alphainsider.io)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}

# --- CACHE ---
CIK_CACHE = {} 
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- SECTOR PEERS (Restored for Search Bar) ---
SECTOR_PEERS = {
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM"],
    "AMD":  ["NVDA", "INTC", "AVGO", "QCOM", "TSM"],
    "F":    ["GM", "TM", "HMC", "TSLA", "RIVN"],
    "TSLA": ["RIVN", "LCID", "F", "GM", "TM"],
    "VERO": ["PODD", "DXCM", "MDT", "EW", "BSX"],
    "PODD": ["VERO", "DXCM", "MDT", "EW", "BSX"],
    "SOFI": ["LC", "UPST", "COIN", "HOOD", "PYPL"],
    "COIN": ["HOOD", "MARA", "RIOT", "MSTR", "SQ"],
    "SQ":   ["PYPL", "COIN", "HOOD", "AFRM", "V"], # Added SQ peers
    "PFE":  ["MRK", "BMY", "LLY", "JNJ", "ABBV"],
    "IBRX": ["MRNA", "NVAX", "BNTX", "GILD", "REGN"],
    "AAL":  ["DAL", "UAL", "LUV", "SAVE", "JBLU"],
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META", "NFLX"],
    "XOM":  ["CVX", "SHEL", "BP", "TTE", "COP"]
}

# --- SECTOR MAPPING (For Congress) ---
SECTOR_MAP = {
    "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR"],
    "CRYPTO": ["COIN", "HOOD", "SQ", "MARA"],
    "DEFENSE": ["LMT", "RTX", "BA", "GD"],
    "ENERGY": ["XOM", "CVX", "KMI", "OXY"],
    "HEALTH": ["PFE", "LLY", "MRK", "UNH", "VERO"],
    "EV": ["TSLA", "RIVN", "LCID", "F", "GM"]
}

# --- UNIVERSE ---
MARKET_UNIVERSE = [
    "NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI",
    "SOFI", "COIN", "HOOD", "PYPL", "SQ", "JPM", "BAC",
    "LMT", "RTX", "BA", "GE", "XOM", "CVX", "AA", "KMI",
    "AMZN", "WMT", "COST", "F", "GM", "RIVN", "LCID",
    "PFE", "LLY", "MRK", "IBRX", "MRNA", "VERO", "DXCM"
]

# --- LEGISLATIVE ENGINE ---
def fetch_real_legislation():
    url = f"https://api.congress.gov/v3/bill?api_key={CONGRESS_KEY}&limit=25&sort=updateDate+desc"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            bills = r.json().get('bills', [])
            cleaned_bills = []
            
            for b in bills:
                title = str(b.get('title', 'Unknown')).upper()
                bill_id = f"{b.get('type', 'HR').upper()} {b.get('number', '000')}"
                
                impact = "Neutral: Monitoring progress."
                score = 50
                sector = None

                if "INTELLIGENCE" in title or "TECHNOLOGY" in title:
                    impact = "Bullish: Tech sector investment."
                    score = 85
                    sector = "AI"
                elif "DEFENSE" in title or "ARMED FORCES" in title:
                    impact = "Direct Beneficiary: Military spending."
                    score = 92
                    sector = "DEFENSE"
                elif "ENERGY" in title or "PIPELINE" in title:
                    impact = "Bullish: Infrastructure development."
                    score = 80
                    sector = "ENERGY"
                elif "HEALTH" in title or "MEDICAL" in title:
                    impact = "Neutral/Bullish: Public health funding."
                    score = 65
                    sector = "HEALTH"
                elif "CRYPTO" in title or "DIGITAL" in title:
                    impact = "Bullish: Regulatory framework."
                    score = 88
                    sector = "CRYPTO"

                cleaned_bills.append({
                    "bill_id": bill_id,
                    "bill_name": title[:60] + "...",
                    "impact_score": score,
                    "market_impact": impact,
                    "sector": sector
                })
            return cleaned_bills
    except: pass
    return []

def get_legislative_intel(ticker: str):
    for bill in ACTIVE_BILLS_CACHE:
        sector = bill['sector']
        if sector and sector in SECTOR_MAP:
            if ticker in SECTOR_MAP[sector]:
                return bill
    return {"bill_id": "N/A", "impact_score": 50, "market_impact": "No active legislation found."}

# --- STOCK ANALYSIS (With Safe Mode) ---
def analyze_stock(ticker: str):
    try:
        # SAFE MODE: Wrap Yahoo calls to prevent crashes on "SQ" or delisted stocks
        stock = yf.Ticker(ticker)
        
        # Try-Except block specifically for price fetching
        try:
            fast = stock.fast_info
            price = fast.last_price or 0.0
            vol = fast.last_volume or 0
        except:
            # If Yahoo fails (404), return dummy data but DON'T CRASH
            price = 0.0
            vol = 0
            
        price_str = f"${price:.2f}"
        vol_str = "High (Buying)" if vol > 1000000 else "Neutral"
        fin_str = "Stable"
    except:
        # Ultimate fallback
        return {
            "ticker": ticker, "raw_price": 0, "price": "N/A", 
            "volume_signal": "N/A", "financial_health": "N/A",
            "legislation_score": 50, "timing_signal": "Wait", 
            "sentiment": "Neutral", "final_score": "HOLD",
            "corporate_activity": "Data Unavailable", "bill_id": "N/A",
            "market_impact": "N/A"
        }

    leg = get_legislative_intel(ticker)
    
    # Insider Trades
    action_text = "Monitoring..."
    cutoff_date = datetime.now() - timedelta(days=540)
    try:
        trades = stock.insider_transactions
        if trades is not None and not trades.empty:
            if 'Start Date' in trades.columns: trades = trades.sort_values(by='Start Date', ascending=False)
            latest = trades.iloc[0]
            trade_date = latest.get('Start Date') or latest.name
            
            if trade_date and pd.to_datetime(trade_date) > cutoff_date:
                who = str(latest.get('Insider', 'Exec')).split(' ')[-1]
                raw = str(latest.get('Text', '')).lower()
                act = "Sold" if "sale" in raw or "sold" in raw else "Bought"
                date_str = pd.to_datetime(trade_date).strftime('%b %d')
                action_text = f"{who} ({act}) {date_str}"
    except: pass

    score = leg.get('impact_score', 50)
    if "High" in vol_str: score += 5
    
    if score >= 75: rating, timing = "STRONG BUY", "Accumulate"
    elif score >= 60: rating, timing = "BUY", "Add Dip"
    elif score <= 45: rating, timing = "SELL", "Exit"
    else: rating, timing = "HOLD", "Wait"

    return {
        "ticker": ticker,
        "raw_price": price,
        "price": price_str,
        "volume_signal": vol_str,
        "financial_health": fin_str,
        "legislation_score": score,
        "timing_signal": timing,
        "sentiment": "Bullish" if "BUY" in rating else "Bearish",
        "final_score": rating,
        "corporate_activity": action_text,
        "congress_activity": "No Recent Activity",
        "bill_id": leg.get('bill_id', 'N/A'),
        "bill_name": leg.get('bill_name', 'Appropriations'),
        "market_impact": leg.get('market_impact', 'N/A')
    }

# --- BACKGROUND WORKER ---
async def update_market_scanner():
    global ACTIVE_BILLS_CACHE
    while True:
        print("🔄 [BACKGROUND] Refreshing Intelligence...")
        
        # 1. Bills
        bills = fetch_real_legislation()
        if bills: ACTIVE_BILLS_CACHE = bills
        
        # 2. Stocks
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ticker = {executor.submit(analyze_stock, sym): sym for sym in MARKET_UNIVERSE}
            for future in concurrent.futures.as_completed(future_to_ticker):
                try: results.append(future.result())
                except: pass
        
        # 3. Sort & Cache
        results.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["buys"] = results[:5]
        
        cheap = [x for x in results if 0 < x['raw_price'] < 50]
        cheap.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["cheap"] = cheap[:5]
        
        results.sort(key=lambda x: x['legislation_score'], reverse=False)
        SERVER_CACHE["sells"] = results[:5]
        
        SERVER_CACHE["last_updated"] = datetime.now().strftime("%H:%M:%S")
        print(f"✅ [BACKGROUND] Cycle Complete at {SERVER_CACHE['last_updated']}")
        
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v26.0 (Safe Mode + Restored Peers).")
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=5)
        if r.status_code == 200:
            data = r.json()
            for key in data: CIK_CACHE[data[key]['ticker']] = str(data[key]['cik_str']).zfill(10)
    except: pass
    
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="26.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/scanner")
def get_scanner_data(mode: str = "buys"):
    return SERVER_CACHE.get(mode, [])

# --- FIXED SIGNAL ENDPOINT (Restored Peer Search) ---
@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    t = ticker.upper()
    
    # 1. Single Mode (Fastest) - Used by Top Picks Page
    if single: return [analyze_stock(t)]

    # 2. Search Mode (Full Context) - Used by Search Bar
    # RESTORED: Find Peers
    competitors = SECTOR_PEERS.get(t, ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"])
    # List: Main + 5 Competitors
    all_tickers = [t] + competitors[:5]
    
    results = []
    # Use threads for speed (approx 1.5s latency)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_to_ticker = {executor.submit(analyze_stock, sym): sym for sym in all_tickers}
        for future in concurrent.futures.as_completed(future_to_ticker):
            try: results.append(future.result())
            except: pass
    
    # Sort: Main Ticker first
    results.sort(key=lambda x: (x['ticker'] == t), reverse=True)
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)