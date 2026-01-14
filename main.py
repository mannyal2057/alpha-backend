import random
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
from datetime import datetime
import io

# --- CONFIGURATION ---
SEC_HEADERS = {"User-Agent": "AlphaInsider/1.0 (montedimes@gmail.com)"}
CONGRESS_DATA_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"

# --- GLOBAL MEMORY (THE CACHE) ---
# We store the Congress data here so we don't have to download it every time.
congress_cache = {"data": None, "last_updated": None}

# --- LIFESPAN MANAGER (STARTUP EVENT) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. ON STARTUP: Download the heavy Congress data immediately
    print("🚀 SYSTEM BOOT: Pre-loading Congress Data...")
    try:
        r = requests.get(CONGRESS_DATA_URL, timeout=30)
        if r.status_code == 200:
            df = pd.DataFrame(r.json())
            # Optimize: Convert date column once
            df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
            congress_cache["data"] = df
            print(f"✅ SUCCESS: Loaded {len(df)} Congressional trades into memory.")
        else:
            print("❌ FAILURE: Could not download Congress data.")
    except Exception as e:
        print(f"❌ ERROR: {e}")
    
    yield # App runs here
    
    # 2. ON SHUTDOWN: Clear memory
    congress_cache["data"] = None

app = FastAPI(title="AlphaInsider Backend", version="4.0", lifespan=lifespan)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATA MODELS ---
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

        # Fetch Submission History
        submissions_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
        r_sub = requests.get(submissions_url, headers=SEC_HEADERS, timeout=5)
        if r_sub.status_code != 200: return None
            
        company_data = r_sub.json()
        recent_forms = company_data['filings']['recent']
        df = pd.DataFrame(recent_forms)
        
        # Filter for Form 4 (Insider Trades)
        insider_trades = df[df['form'] == '4']
        if not insider_trades.empty:
            latest = insider_trades.iloc[0]
            return {
                "description": f"New SEC Form 4 Filed on {latest['filingDate']}",
                "date": latest['filingDate']
            }
    except Exception as e:
        print(f"SEC Error: {e}")
        return None
    return None

# --- ENGINE 2: CONGRESSIONAL DATA (CACHE VERSION) ---
def get_cached_congress_data(ticker: str):
    """
    Queries the pre-loaded memory instead of downloading the file.
    Instant results!
    """
    df = congress_cache["data"]
    if df is None:
        return {"description": "Data Loading..."}
        
    try:
        # Filter by Ticker
        ticker_match = df[df['ticker'] == ticker.upper()]
        
        if not ticker_match.empty:
            # Sort by transaction date (descending)
            ticker_match = ticker_match.sort_values(by='transaction_date', ascending=False)
            latest = ticker_match.iloc[0]
            
            # Format: "Rep. Pelosi (D-CA) Buy"
            rep_name = latest.get('representative', 'Unknown Rep')
            action = latest.get('type', 'Trade') 
            date_str = str(latest['transaction_date']).split(' ')[0]
            
            return {
                "description": f"{rep_name} {action} on {date_str}",
                "date": date_str
            }
        else:
            return None # Truly no trades found
            
    except Exception as e:
        print(f"Congress Cache Error: {e}")
        return None

# --- SIMULATION (FALLBACK) ---
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
    # Show if data is loaded in the health check
    data_status = "Ready" if congress_cache["data"] is not None else "Loading..."
    return {"status": "active", "congress_data": data_status}

@app.get("/api/signals")
def get_alpha_signals(ticker: str = "NVDA"):
    signals = []
    target_ticker = ticker.upper()

    # 1. RUN THE ENGINES
    sec_data = get_real_sec_data(target_ticker)
    congress_data = get_cached_congress_data(target_ticker)
    
    # 2. BUILD MASTER SIGNAL
    master_signal = generate_mock_signal(ticker_override=target_ticker)
    master_signal.ticker = f"{target_ticker} (LIVE)"
    
    if sec_data:
        master_signal.corporate_activity = sec_data['description']
        
    if congress_data:
        master_signal.congress_activity = congress_data['description']
        
    # Sentiment Logic
    if sec_data or congress_data:
        master_signal.conviction = "High"
        master_signal.sentiment = "Bullish"
    else:
        master_signal.sentiment = "Neutral"

    signals.append(master_signal)

    # 3. ADD CONTEXT
    for _ in range(3):
        signals.append(generate_mock_signal())

    return signals

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)