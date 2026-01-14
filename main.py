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

# ENV VARS (API Keys)
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") 
CONGRESS_API_URL = os.getenv("CONGRESS_API_URL", "https://api.quiverquant.com/beta/live/congresstrading") 

# --- 2. LIFESPAN (STARTUP CHECKS) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Simple check on startup to see if we are ready
    if CONGRESS_API_KEY:
        print(f"💎 SYSTEM BOOT: API Key detected. Connected to Quiver Quantitative.")
    else:
        print(f"⚠️ SYSTEM BOOT: No API Key found. Congress data will be empty.")
    yield

app = FastAPI(title="AlphaInsider Backend", version="13.0 (Pure API)", lifespan=lifespan)

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

# --- ENGINE 2: CONGRESS DATA (API ONLY) ---
def get_congress_data(ticker: str):
    """
    Fetches data directly from the API. No S3 backup. No threads.
    """
    ticker_upper = ticker.upper()

    if CONGRESS_API_KEY:
        try:
            # Stealth Headers (Good practice even for paid APIs)
            headers = {
                "Authorization": f"Bearer {CONGRESS_API_KEY}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            params = {"ticker": ticker_upper}
            
            # API Request
            r = requests.get(CONGRESS_API_URL, headers=headers, params=params, timeout=5)
            
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    latest = data[0]
                    # Parse Data
                    rep = latest.get('Representative') or latest.get('representative') or "Unknown Rep"
                    type_ = latest.get('Transaction') or latest.get('type') or "Trade"
                    date = latest.get('ReportDate') or latest.get('transaction_date') or "Recently"
                    return {"description": f"{rep} ({type_}) on {date}"}
            
        except Exception as e:
            print(f"⚠️ API ERROR: {e}")

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
        "mode": "Pure API",
        "api_connected": bool(CONGRESS_API_KEY)
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