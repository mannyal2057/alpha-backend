import random
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
from datetime import datetime
import io

# --- CONFIGURATION ---
# SEC User-Agent (Required for access)
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/1.0 (montedimes@gmail.com)"
}

# Congress Data URL (Public S3 Bucket)
CONGRESS_DATA_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"

app = FastAPI(title="AlphaInsider Backend", version="3.0")

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
        # 1. Map Ticker to CIK
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

        # 2. Fetch Submission History
        submissions_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
        r_sub = requests.get(submissions_url, headers=SEC_HEADERS, timeout=5)
        if r_sub.status_code != 200: return None
            
        company_data = r_sub.json()
        recent_forms = company_data['filings']['recent']
        df = pd.DataFrame(recent_forms)
        
        # 3. Filter for Form 4 (Insider Trades)
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

# --- ENGINE 2: CONGRESSIONAL DATA (NEW!) ---
def get_real_congress_data(ticker: str):
    """
    Fetches the House Stock Watcher JSON and filters for the specific ticker.
    """
    try:
        # 1. Download the Data (Note: This file is ~10MB, might take 1-2s)
        # In a production app, we would cache this daily.
        r = requests.get(CONGRESS_DATA_URL)
        if r.status_code != 200: return None

        # 2. Parse into Pandas
        data = r.json()
        df = pd.DataFrame(data)
        
        # 3. Filter by Ticker
        # The dataset uses 'ticker' column (e.g. 'NVDA')
        ticker_match = df[df['ticker'] == ticker.upper()]
        
        if not ticker_match.empty:
            # Sort by transaction date (descending)
            ticker_match['transaction_date'] = pd.to_datetime(ticker_match['transaction_date'], errors='coerce')
            ticker_match = ticker_match.sort_values(by='transaction_date', ascending=False)
            
            latest = ticker_match.iloc[0]
            
            # Format: "Rep. Pelosi (D-CA) Buy"
            rep_name = latest.get('representative', 'Unknown Rep')
            action = latest.get('type', 'Trade') # purchase/sale_full
            date_str = str(latest['transaction_date']).split(' ')[0]
            
            return {
                "description": f"{rep_name} {action} on {date_str}",
                "date": date_str
            }
            
    except Exception as e:
        print(f"Congress Error: {e}")
        return None
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
    return {"status": "active", "version": "3.0 (Dual Engine)"}

@app.get("/api/signals")
def get_alpha_signals(ticker: str = "NVDA"):
    signals = []
    target_ticker = ticker.upper()

    # --- 1. RUN THE ENGINES ---
    sec_data = get_real_sec_data(target_ticker)
    congress_data = get_real_congress_data(target_ticker)
    
    # --- 2. BUILD THE MASTER SIGNAL ---
    # Start with a base signal
    master_signal = generate_mock_signal(ticker_override=target_ticker)
    master_signal.ticker = f"{target_ticker} (LIVE)"
    
    # Inject SEC Data
    if sec_data:
        master_signal.corporate_activity = sec_data['description']
        
    # Inject Congress Data
    if congress_data:
        master_signal.congress_activity = congress_data['description']
        
    # Determine Sentiment (Simple Logic)
    # If both engines found data, we mark it High Conviction
    if sec_data or congress_data:
        master_signal.conviction = "High"
        master_signal.sentiment = "Bullish" # Simplified for tutorial
    else:
        master_signal.ticker = target_ticker
        master_signal.corporate_activity = "No Recent Form 4"
        master_signal.congress_activity = "No Recent House Trades"
        master_signal.conviction = "Low"
        master_signal.sentiment = "Neutral"

    signals.append(master_signal)

    # --- 3. ADD CONTEXT ROWS ---
    for _ in range(3):
        signals.append(generate_mock_signal())

    return signals

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)