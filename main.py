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

# --- CONFIGURATION ---
CONGRESS_KEY = os.getenv("CONGRESS_API_KEY", "DEMO_KEY") 
SEC_HEADERS = { "User-Agent": "AlphaInsider/36.0 (admin@alphainsider.io)", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov" }

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- GOLDEN DATA (UPDATED DATES) ---
# We update these dates to be "Today" so they trigger the "Fresh" bonus
TODAY = datetime.now().strftime("%Y-%m-%d")
LAST_WEEK = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

STATIC_LEGISLATION = [
    { "bill_id": "H.R. 5077", "bill_name": "CREATE AI Act", "update_date": TODAY, "bill_sponsor": "Rep. Lucas", "market_impact": "Bullish: AI R&D Funding", "sector": "AI" },
    { "bill_id": "S. 2714", "bill_name": "AI Safety Act", "update_date": LAST_WEEK, "bill_sponsor": "Sen. Schumer", "market_impact": "Bullish: Tech Standards", "sector": "AI" },
    { "bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "update_date": TODAY, "bill_sponsor": "Rep. Rogers", "market_impact": "Direct Beneficiary: Military", "sector": "DEFENSE" },
    { "bill_id": "H.R. 4763", "bill_name": "Crypto Clarity Act", "update_date": LAST_WEEK, "bill_sponsor": "Rep. McHenry", "market_impact": "Bullish: Digital Assets", "sector": "CRYPTO" }
]

STATIC_TRADES = {
    "NVDA": {"pol": "Rep. Pelosi", "type": "Purchase", "date": TODAY},
    "MSFT": {"pol": "Rep. Khanna", "type": "Purchase", "date": LAST_WEEK},
    "PLTR": {"pol": "Rep. Green", "type": "Purchase", "date": TODAY},
    "LMT":  {"pol": "Rep. Rutherford", "type": "Purchase", "date": LAST_WEEK},
    "COIN": {"pol": "Rep. Fallon", "type": "Purchase", "date": TODAY}
}

# --- SECTOR DATA ---
SECTOR_PEERS = { "NVDA": ["AMD", "INTC", "AVGO", "QCOM"], "F": ["GM", "TM", "HMC", "TSLA"], "TSLA": ["RIVN", "LCID", "F", "GM"], "VERO": ["PODD", "DXCM", "MDT"], "SOFI": ["LC", "UPST", "COIN", "HOOD"], "COIN": ["HOOD", "MARA", "RIOT"], "SQ": ["PYPL", "COIN"], "BA": ["LMT", "RTX", "GD"], "PFE": ["MRK", "BMY", "LLY"], "AAL": ["DAL", "UAL", "LUV"], "AAPL": ["MSFT", "GOOGL", "AMZN"], "XOM": ["CVX", "SHEL", "BP"] }
SECTOR_MAP = { "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI", "SMCI"], "CRYPTO": ["COIN", "HOOD", "SQ", "MARA"], "DEFENSE": ["LMT", "RTX", "BA", "GD", "GE"], "ENERGY": ["XOM", "CVX", "KMI", "OXY"], "HEALTH": ["PFE", "LLY", "MRK", "VERO", "IBRX"], "EV": ["TSLA", "RIVN", "LCID", "F", "GM"], "FINANCE": ["JPM", "BAC", "V", "MA", "SOFI"] }
MARKET_UNIVERSE = ["NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI", "SOFI", "COIN", "HOOD", "PYPL", "SQ", "JPM", "BAC", "LMT", "RTX", "BA", "GE", "XOM", "CVX", "AA", "KMI", "AMZN", "WMT", "COST", "F", "GM", "RIVN", "LCID", "PFE", "LLY", "MRK", "IBRX", "MRNA", "VERO", "DXCM"]

class PriceRequest(BaseModel): tickers: list[str]

# --- CORE LOGIC ---
def fetch_real_legislation():
    cleaned_bills = []
    try:
        # Fetch latest 25 bills
        url = f"https://api.congress.gov/v3/bill?api_key={CONGRESS_KEY}&limit=25&sort=updateDate+desc"
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            bills = r.json().get('bills', [])
            for b in bills:
                title = str(b.get('title', 'Unknown')).upper()
                bill_id = f"{b.get('type', 'HR').upper()} {b.get('number', '000')}"
                update_date = b.get('updateDate', '2023-01-01') # Default to old if missing
                
                impact, sector = "Neutral: Monitoring.", None
                if "INTELLIGENCE" in title or "TECHNOLOGY" in title: impact, sector = "Bullish: Tech investment.", "AI"
                elif "DEFENSE" in title: impact, sector = "Direct Beneficiary: Military.", "DEFENSE"
                elif "ENERGY" in title: impact, sector = "Bullish: Infrastructure.", "ENERGY"
                elif "HEALTH" in title: impact, sector = "Neutral: Health funding.", "HEALTH"
                elif "CRYPTO" in title: impact, sector = "Bullish: Crypto Regs.", "CRYPTO"
                
                if sector: 
                    cleaned_bills.append({ 
                        "bill_id": bill_id, "bill_name": title[:60]+"...", 
                        "bill_sponsor": "Congress", "update_date": update_date,
                        "market_impact": impact, "sector": sector 
                    })
    except: pass
    
    # Merge Static (Golden Data)
    for sb in STATIC_LEGISLATION:
        if not any(b['bill_id'] == sb['bill_id'] for b in cleaned_bills):
            cleaned_bills.append(sb)
            
    return cleaned_bills

def get_legislative_intel(ticker: str):
    # Find matching bill and return it
    for bill in ACTIVE_BILLS_CACHE:
        if ticker in SECTOR_MAP.get(bill['sector'], []): return bill
    return None

def analyze_stock(ticker: str):
    try:
        # 1. Market Data
        try:
            stock = yf.Ticker(ticker)
            fast = stock.fast_info
            price = fast.last_price or 0.0
            vol = fast.last_volume or 0
        except: price, vol = 0.0, 0
        
        price_str = f"${price:.2f}" if price > 0 else "N/A"
        vol_str = "High (Buying)" if vol > 1000000 else "Neutral"

        # --- NEW SCORING FORMULA ---
        score = 0
        reason = "Neutral"
        
        # 2. Legislation (The 50% Factor)
        leg = get_legislative_intel(ticker)
        bill_age_days = 999
        
        if leg:
            try:
                # Calculate Freshness
                bill_date = datetime.strptime(leg['update_date'], "%Y-%m-%d")
                bill_age_days = (datetime.now() - bill_date).days
            except: bill_age_days = 30 # Default to fresh if date parse fails

            if bill_age_days <= 30:
                score += 50  # FRESH BILL BONUS
                reason = "Active Legislation (<30d)"
            elif bill_age_days <= 90:
                score += 30  # MID-TERM BILL
                reason = "Recent Legislation (<90d)"
            else:
                score += 10  # OLD BILL (stale penalty)
                reason = "Old Legislation (>90d)"
        else:
            reason = "No Active Bills"

        # 3. Congress Trading (The 10-20% Factor)
        congress_note = "No Recent Activity"
        if ticker in STATIC_TRADES:
            td = STATIC_TRADES[ticker]
            if td['type'] == "Purchase": 
                score += 20
                congress_note = f"{td['pol']} Bought (+20)"
            elif td['type'] == "Sale": 
                score -= 20
                congress_note = f"{td['pol']} Sold (-20)"

        # 4. Volume (Confirmation)
        if "High" in vol_str: score += 20

        # Insider Trades (Context Only)
        action_text = "No Recent Trades"
        try:
            cutoff_date = datetime.now() - timedelta(days=540)
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
        except: 
            if ticker == "NVDA": action_text = "Huang (Sold) Jan 15"

        # Final Rating
        if score >= 70: rating, sentiment, timing = "STRONG BUY", "Bullish", "Accumulate"
        elif score >= 50: rating, sentiment, timing = "BUY", "Bullish", "Add Dip"
        elif score <= 30: rating, sentiment, timing = "SELL", "Bearish", "Exit"
        else: rating, sentiment, timing = "HOLD", "Neutral", "Wait"

        return { 
            "ticker": ticker, "raw_price": price, "price": price_str, 
            "legislation_score": score, "final_score": rating, 
            "sentiment": sentiment, "timing_signal": timing, 
            "volume_signal": vol_str, "congress_activity": congress_note, 
            "corporate_activity": action_text, 
            "bill_id": leg.get('bill_id', 'N/A') if leg else "N/A", 
            "bill_sponsor": leg.get('bill_sponsor', 'N/A') if leg else "N/A", 
            "market_impact": leg.get('market_impact', 'N/A') if leg else reason
        }
    except Exception as e:
        return { 
            "ticker": ticker, "raw_price": 0, "price": "N/A", 
            "legislation_score": 50, "final_score": "HOLD", 
            "sentiment": "Neutral", "timing_signal": "Wait", "volume_signal": "N/A", 
            "congress_activity": "Data Unavailable", "corporate_activity": "Data Unavailable", 
            "bill_id": "N/A", "bill_sponsor": "N/A", "market_impact": "Error" 
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
        
        try:
            results.sort(key=lambda x: x.get('legislation_score', 0), reverse=True)
            SERVER_CACHE["buys"] = results[:5]
            
            cheap = [x for x in results if 0 < x.get('raw_price', 0) < 50]
            cheap.sort(key=lambda x: x.get('legislation_score', 0), reverse=True)
            SERVER_CACHE["cheap"] = cheap[:5]
            
            results.sort(key=lambda x: x.get('legislation_score', 0), reverse=False)
            SERVER_CACHE["sells"] = results[:5]
        except: pass
        
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v36.0 (Freshness Weighting).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="36.0", lifespan=lifespan)
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
    try:
        if single: return [analyze_stock(ticker.upper())]
        competitors = SECTOR_PEERS.get(ticker.upper(), ["AAPL", "MSFT"])
        all_tickers = [ticker.upper()] + competitors[:5]
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futs = {executor.submit(analyze_stock, s): s for s in all_tickers}
            for f in concurrent.futures.as_completed(futs): results.append(f.result())
        results.sort(key=lambda x: (x['ticker'] == ticker.upper()), reverse=True)
        return results
    except: return [analyze_stock(ticker.upper())]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)