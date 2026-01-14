import os
import random
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
from datetime import datetime

# --- 1. CONFIGURATION ---
SEC_HEADERS = {"User-Agent": "AlphaInsider/1.0 (montedimes@gmail.com)"}

# ENV VARS
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") 
CONGRESS_API_URL = os.getenv("CONGRESS_API_URL", "https://api.quiverquant.com/beta/live/congresstrading") 
PUBLIC_DATA_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"

# --- GLOBAL MEMORY ---
congress_cache = {"data": None, "mode": "UNKNOWN"}

# --- HELPER: DOWNLOAD PUBLIC DATA ---
def download_public_data():
    """Downloads the massive public dataset as a fallback."""
    print("🌍 FALLBACK: Downloading Public S3 Dataset...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(PUBLIC_DATA_URL, headers=headers, timeout=60)
        if r.status_code == 200:
            df = pd.DataFrame(r.json())
            df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
            congress_cache["data"] = df
            congress_cache["mode"] = "LOCAL"
            print(f"✅ SUCCESS: Loaded {len(df)} trades from Public S3.")
            return True
    except Exception as e:
        print(f"❌ PUBLIC LOAD ERROR: {e}")
    return False

# --- LIFESPAN (STARTUP LOGIC) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 SYSTEM BOOT: Initializing Data Engines...")
    
    # 1. Try to use API Mode if Key exists
    if CONGRESS_API_KEY:
        print(f"💎 PRO MODE: Key detected. API is active.")
        congress_cache["mode"] = "API"
    else:
        # 2. If no key, go straight to Public Mode
        download_public_data()
    
    yield
    congress_cache["data"] = None

app = FastAPI(title="AlphaInsider Backend", version="9.0 (Self-Healing)", lifespan=lifespan)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELS ---
class Signal(BaseModel):
    ticker: str
    sentiment: str       
    conviction: str      
    corporate_activity: str
    congress_activity: str
    legislative_context: Optional[str] = None

# --- ENGINE 1: SEC CORPORATE DATA ---
def get_real_sec_data(ticker: str):
    try:
        # Map Ticker to CIK
        cik_map_url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(cik_map_url, headers=SEC_HEADERS, timeout=5)
        if r.status_code != 200: return None
        
        cik_data = r.json()
        target_cik = None
        ticker_upper = ticker.upper()
        
        for key, val in cik_data.items():
            if val['ticker'] == ticker_upper:
                target_cik = str(val['cik_str']).zfill(10) 
                break
        
        if not target_cik: return None

        # Fetch Filings
        submissions_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
        r_sub = requests.get(submissions_url, headers=SEC_HEADERS, timeout=5)
        if r_sub.status_code != 200: return None
            
        recent_forms = r_sub.json()['filings']['recent']
        df = pd.DataFrame(recent_forms)
        
        # Filter for Form 4
        insider_trades = df[df['form'] == '4']
        if not insider_trades.empty:
            latest = insider_trades.iloc[0]
            return {
                "description": f"New SEC Form 4 Filed on {latest['filingDate']}",
                "date": latest['filingDate']
            }
    except:
        return None
    return None

# --- ENGINE 2: CONGRESSIONAL DATA (SMART FAILOVER) ---
def get_congress_data(ticker: str):
    mode = congress_cache.get("mode")
    ticker_upper = ticker.upper()

    # --- STRATEGY A: PRO API ---
    if mode == "API":
        try:
            headers = {
                "Authorization": f"Bearer {CONGRESS_API_KEY}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            params = {"ticker": ticker_upper} 
            
            # Fast Timeout (3s) - If it blocks, we failover immediately
            response = requests.get(CONGRESS_API_URL, headers=headers, params=params, timeout=3)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    latest = data[0]
                    rep = latest.get('Representative') or latest.get('representative') or "Unknown Rep"
                    type_ = latest.get('Transaction') or latest.get('type') or "Trade"
                    date = latest.get('ReportDate') or latest.get('transaction_date') or "Recently"
                    return {"description": f"{rep} ({type_}) on {date}"}
                return None 
            
            # IF BLOCKED (500/403) -> SWITCH TO PUBLIC MODE PERMANENTLY
            elif response.status_code in [403, 500, 520]:
                print(f"⚠️ API BLOCKED ({response.status_code}). Switching to Public S3 Mode...")
                download_public_data() # Load the backup data
                congress_cache["mode"] = "LOCAL" # Switch mode for next time
                return get_congress_data(ticker) # Recursive call to try again immediately

        except Exception as e:
            print(f"❌ API ERROR: {e}. Switching to Public S3 Mode...")
            download_public_data()
            congress_cache["mode"] = "LOCAL"
            return get_congress_data(ticker)

    # --- STRATEGY B: LOCAL CACHE (FALLBACK) ---
    elif mode == "LOCAL":
        df = congress_cache["data"]
        if df is None: return None
        
        matches = df[df['ticker'] == ticker_upper]
        if not matches.empty:
            matches = matches.sort_values(by='transaction_date', ascending=False)
            latest = matches.iloc[0]
            rep = latest.get('representative', 'Unknown')
            type_ = latest.get('type', 'Trade')
            date = str(latest['transaction_date']).split(' ')[0]
            return {"description": f"{rep} {type_} on {date}"}
            
    return None

# --- FALLBACK GENERATOR ---
def generate_mock_signal(ticker_override=None):
    tickers = ["PLTR", "XOM", "META", "AMD", "MSFT"]
    ticker = ticker_override if ticker_override else random.choice(tickers)
    is_bullish = random.choice([True, False])
    return Signal(
        ticker=ticker,
        sentiment="Bullish" if is_bullish else "Bearish",
        conviction="High" if random.random() > 0.5 else "Moderate",
        corporate_activity="No Recent Filings",
        congress_activity="No Recent Activity",
        legislative_context="General Market Monitoring"
    )

# --- API ENDPOINTS ---
@app.get("/")
def health_check():
    return {
        "status": "active", 
        "mode": congress_cache.get("mode", "Unknown"),
    }

@app.get("/api/signals")
def get_alpha_signals(ticker: str = "NVDA"):
    signals = []
    target = ticker.upper()

    sec_data = get_real_sec_data(target)
    congress_data = get_congress_data(target)
    
    main_signal = generate_mock_signal(ticker_override=target)
    main_signal.ticker = f"{target} (LIVE)"
    
    if sec_data: main_signal.corporate_activity = sec_data['description']
    if congress_data: main_signal.congress_activity = congress_data['description']
    
    if sec_data or congress_data:
        main_signal.conviction = "High"
        main_signal.sentiment = "Bullish"
    else:
        main_signal.sentiment = "Neutral"

    signals.append(main_signal)
    for _ in range(3): signals.append(generate_mock_signal())

    return signals

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)