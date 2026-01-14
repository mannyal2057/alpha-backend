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
# The background thread updates this. The API reads from this.
congress_cache = {"data": None, "mode": "STARTING", "last_updated": None}

# --- 2. DATA WORKER FUNCTIONS ---

def download_public_data():
    """Downloads public S3 data (Forensic Mode). Returns DataFrame or None."""
    print(f"🌍 WORKER: Downloading Public S3 Data at {datetime.now()}...")
    try:
        # Use a real browser header to avoid 403 blocks
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(PUBLIC_DATA_URL, headers=headers, timeout=60)
        
        if r.status_code == 200:
            df = pd.DataFrame(r.json())
            df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
            
            # Forensic Logs
            latest_date = df['transaction_date'].max()
            print(f"✅ WORKER SUCCESS: Loaded {len(df)} trades. Latest date in file: {latest_date}")
            return df
        else:
            print(f"❌ WORKER FAILED: S3 returned status {r.status_code}")
            return None
    except Exception as e:
        print(f"❌ WORKER ERROR: {e}")
        return None

def run_background_scanner():
    """
    The 'Heartbeat' of your app.
    Runs in a separate thread. Wakes up every hour to refresh data.
    """
    print("⏳ BACKGROUND SCANNER STARTED...")
    
    while True:
        # 1. Try Custom API First (If Key Exists)
        if CONGRESS_API_KEY:
            # Note: For many APIs, you don't 'download' everything. 
            # You might just rely on live queries. 
            # But if you want to avoid blocking, you can stick to Public Data for the bulk list.
            print("💎 PRO MODE: API Key is active. (Using hybrid mode)")
            congress_cache["mode"] = "API"
        
        # 2. Always refresh the Public Backup (Reliable Baseline)
        df = download_public_data()
        if df is not None:
            congress_cache["data"] = df
            congress_cache["mode"] = "READY"
            congress_cache["last_updated"] = datetime.now()
        
        # 3. Sleep for 1 Hour (3600 seconds)
        print("💤 SCANNER SLEEPING: See you in 1 hour.")
        time.sleep(3600)

# --- 3. FASTAPI LIFESPAN (STARTUP) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the scanner in a background thread
    scan_thread = threading.Thread(target=run_background_scanner, daemon=True)
    scan_thread.start()
    
    yield
    # Cleanup on shutdown
    congress_cache["data"] = None

app = FastAPI(title="AlphaInsider Backend", version="10.0 (Threaded)", lifespan=lifespan)

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

# --- ENGINE 2: CONGRESS DATA (Instant Cache) ---
def get_congress_data(ticker: str):
    """
    Reads INSTANTLY from memory. No API calls. No blocking.
    """
    ticker_upper = ticker.upper()
    
    # 1. Check Local Cache (Populated by Background Thread)
    df = congress_cache.get("data")
    if df is not None:
        matches = df[df['ticker'] == ticker_upper]
        if not matches.empty:
            matches = matches.sort_values(by='transaction_date', ascending=False)
            latest = matches.iloc[0]
            
            rep = latest.get('representative', 'Unknown')
            type_ = latest.get('type', 'Trade')
            date = str(latest['transaction_date']).split(' ')[0]
            return {"description": f"{rep} {type_} on {date}"}

    # 2. If Pro Key exists, try one live fetch (Optional fallback)
    if CONGRESS_API_KEY:
        try:
            # Pro API Logic (Only runs if cache missed)
            headers = {"Authorization": f"Bearer {CONGRESS_API_KEY}", "Accept": "application/json"}
            r = requests.get(CONGRESS_API_URL, headers=headers, params={"ticker": ticker_upper}, timeout=2)
            if r.status_code == 200 and len(r.json()) > 0:
                 return {"description": "Recent Trade Detected (Live API)"}
        except:
            pass

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
        "worker_mode": congress_cache["mode"],
        "last_updated": congress_cache["last_updated"]
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