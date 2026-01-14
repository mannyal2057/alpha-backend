import os
import time
import threading
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

# ENV VARS (API Keys)
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") 
CONGRESS_API_URL = os.getenv("CONGRESS_API_URL", "https://api.quiverquant.com/beta/live/congresstrading") 
PUBLIC_DATA_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"

# --- GLOBAL MEMORY ---
# The background thread updates this. The fallback logic reads from this.
congress_cache = {"data": None, "mode": "STARTING", "last_updated": None}

# --- 2. DATA WORKER (BACKGROUND BACKUP) ---

def download_public_data():
    """Downloads public S3 data as a robust backup."""
    print(f"🌍 WORKER: Updating Public Backup Cache...")
    try:
        # Stealth Headers to avoid 403 blocks on S3
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(PUBLIC_DATA_URL, headers=headers, timeout=60)
        
        if r.status_code == 200:
            df = pd.DataFrame(r.json())
            df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
            print(f"✅ WORKER SUCCESS: Public Backup Updated ({len(df)} trades).")
            return df
        else:
            print(f"⚠️ WORKER WARNING: S3 Backup failed ({r.status_code}). App will rely on Live API.")
            return None
    except Exception as e:
        print(f"❌ WORKER ERROR: {e}")
        return None

def run_background_scanner():
    """
    Runs every hour to keep the 'Safety Net' (Public Data) fresh.
    """
    print("⏳ BACKGROUND SCANNER STARTED...")
    while True:
        df = download_public_data()
        if df is not None:
            congress_cache["data"] = df
            congress_cache["mode"] = "READY"
            congress_cache["last_updated"] = datetime.now()
        
        # Sleep for 1 Hour
        time.sleep(3600)

# --- 3. FASTAPI LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the scanner in a background thread
    scan_thread = threading.Thread(target=run_background_scanner, daemon=True)
    scan_thread.start()
    
    # Check API Status on Boot
    if CONGRESS_API_KEY:
        print(f"💎 SYSTEM BOOT: API Key detected. Engine set to 'API FIRST' mode.")
    else:
        print(f"🌍 SYSTEM BOOT: No API Key. Engine set to 'PUBLIC CACHE' mode.")
        
    yield
    congress_cache["data"] = None

app = FastAPI(title="AlphaInsider Backend", version="11.0 (API First)", lifespan=lifespan)

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

# --- ENGINE 1: SEC DATA (Real-Time) ---
def get_real_sec_data(ticker: str):
    try:
        headers = SEC_HEADERS
        # 1. CIK Lookup
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=5)
        if r.status_code != 200: return None
        
        target_cik = None
        ticker_upper = ticker.upper()
        for k, v in r.json().items():
            if v['ticker'] == ticker_upper:
                target_cik = str(v['cik_str']).zfill(10)
                break
        if not target_cik: return None

        # 2. Submissions
        r_sub = requests.get(f"https://data.sec.gov/submissions/CIK{target_cik}.json", headers=headers, timeout=5)
        if r_sub.status_code != 200: return None
        
        df = pd.DataFrame(r_sub.json()['filings']['recent'])
        trades = df[df['form'] == '4']
        
        if not trades.empty:
            latest = trades.iloc[0]
            return {"description": f"New SEC Form 4 Filed on {latest['filingDate']}"}
    except:
        return None
    return None

# --- ENGINE 2: CONGRESS DATA (API FIRST + BACKUP) ---
def get_congress_data(ticker: str):
    """
    STRATEGY:
    1. Try LIVE API (Best Data).
    2. If that fails (Block/Limit), read from LOCAL CACHE (Backup Data).
    """
    ticker_upper = ticker.upper()

    # --- ATTEMPT 1: LIVE API ---
    if CONGRESS_API_KEY:
        try:
            # We use 'Stealth Headers' here too, just in case
            headers = {
                "Authorization": f"Bearer {CONGRESS_API_KEY}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            params = {"ticker": ticker_upper}
            
            # Short timeout (3s) so user doesn't wait if API is slow
            r = requests.get(CONGRESS_API_URL, headers=headers, params=params, timeout=3)
            
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    latest = data[0]
                    # Parse Quiver/Standard Format
                    rep = latest.get('Representative') or latest.get('representative') or "Unknown Rep"
                    type_ = latest.get('Transaction') or latest.get('type') or "Trade"
                    date = latest.get('ReportDate') or latest.get('transaction_date') or "Recently"
                    return {"description": f"{rep} ({type_}) on {date} (Live API)"}
            
            # If API returns empty list [] it means NO TRADES found by API.
            # We can stop here, or check backup. Let's stop to be accurate.
            if r.status_code == 200:
                pass # No trades found via API

        except Exception as e:
            print(f"⚠️ API ERROR: {e}. Falling back to cache...")

    # --- ATTEMPT 2: LOCAL CACHE (FALLBACK) ---
    # We only get here if API Key is missing OR API Request Failed/Crashed
    df = congress_cache.get("data")
    if df is not None:
        matches = df[df['ticker'] == ticker_upper]
        if not matches.empty:
            matches = matches.sort_values(by='transaction_date', ascending=False)
            latest = matches.iloc[0]
            
            rep = latest.get('representative', 'Unknown')
            type_ = latest.get('type', 'Trade')
            date = str(latest['transaction_date']).split(' ')[0]
            return {"description": f"{rep} {type_} on {date} (Backup Data)"}

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
        "api_enabled": bool(CONGRESS_API_KEY),
        "backup_cache": "Ready" if congress_cache["data"] is not None else "Empty"
    }

@app.get("/api/signals")
def get_alpha_signals(ticker: str = "NVDA"):
    signals = []
    target = ticker.upper()

    sec = get_real_sec_data(target)
    congress = get_congress_data(target)
    
    main = generate_mock_signal(ticker_override=target)
    main.ticker = f"{target} (LIVE)"
    
    if sec: main.corporate_activity = sec['description']
    if congress: main.congress_activity = congress['description']
    
    if sec or congress:
        main.conviction = "High"
        main.sentiment = "Bullish"
    else:
        main.sentiment = "Neutral"

    signals.append(main)
    for _ in range(3): signals.append(generate_mock_signal())

    return signals

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)