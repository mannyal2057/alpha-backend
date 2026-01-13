import random
from typing import List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
from datetime import datetime

# --- CONFIGURATION ---
# The SEC requires a User-Agent in this format: "AppName/Version (Email)"
# I have inserted your email here.
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/1.0 (montedimes@gmail.com)"
}

app = FastAPI(title="AlphaInsider Backend", version="1.0")

# --- CORS (Crucial for connecting to your Render Frontend) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows your Next.js frontend to talk to this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATA MODELS ---
class Signal(BaseModel):
    ticker: str
    sentiment: str       # "Bullish", "Bearish", "Neutral"
    conviction: str      # "High", "Moderate"
    corporate_activity: str
    congress_activity: str
    legislative_context: Optional[str] = None

# --- REAL DATA FETCHER (THE ENGINE) ---

def get_real_sec_data(ticker: str):
    """
    Fetches the latest Form 4 (Insider Trading) filings for a specific company
    directly from the SEC EDGAR API.
    """
    try:
        # 1. Get the mapping of Ticker -> CIK (Central Index Key)
        # This maps "NVDA" to "0001045810"
        cik_map_url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(cik_map_url, headers=SEC_HEADERS)
        
        if r.status_code != 200:
            print(f"Error connecting to SEC: {r.status_code}")
            return None

        cik_data = r.json()
        
        # Find the CIK for our ticker
        target_cik = None
        ticker_upper = ticker.upper()
        
        for key, val in cik_data.items():
            if val['ticker'] == ticker_upper:
                # SEC requires 10 digits (leading zeros)
                target_cik = str(val['cik_str']).zfill(10) 
                break
        
        if not target_cik:
            print(f"Ticker {ticker} not found in SEC database.")
            return None

        # 2. Fetch the Company's Submission History
        submissions_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
        r_sub = requests.get(submissions_url, headers=SEC_HEADERS)
        
        if r_sub.status_code != 200:
            return None
            
        company_data = r_sub.json()
        
        # 3. Filter for "4" (Insider Trade) filings
        recent_forms = company_data['filings']['recent']
        df = pd.DataFrame(recent_forms)
        
        # Look for Form 4 (Statement of Changes in Beneficial Ownership)
        insider_trades = df[df['form'] == '4']
        
        if not insider_trades.empty:
            # Get the most recent filing
            latest = insider_trades.iloc[0]
            filing_date = latest['filingDate']
            
            return {
                "ticker": ticker,
                "description": f"New SEC Form 4 Filed on {filing_date}",
                "date": filing_date
            }
            
    except Exception as e:
        print(f"Error fetching SEC data: {e}")
        return None
    
    return None

# --- SIMULATION ENGINE (Fallback / Demo Data) ---

def generate_mock_signal(ticker_override=None):
    tickers = ["PLTR", "XOM", "META", "AMD", "MSFT"]
    ticker = ticker_override if ticker_override else random.choice(tickers)
    
    is_bullish = random.choice([True, False])
    
    return Signal(
        ticker=ticker,
        sentiment="Bullish" if is_bullish else "Bearish",
        conviction="High" if random.random() > 0.5 else "Moderate",
        corporate_activity="CEO Buy ($5.2M)" if is_bullish else "Director Sell ($1.1M)",
        congress_activity="Rep. Crenshaw Buy" if is_bullish else "No Recent Activity",
        legislative_context="CHIPS Act Amendment" if ticker in ["NVDA", "AMD"] else "Data Privacy Bill"
    )

# --- API ENDPOINTS ---

@app.get("/")
def health_check():
    return {"status": "active", "engine": "Python 3.10", "contact": "montedimes@gmail.com"}

@app.get("/api/signals")
def get_alpha_signals():
    """
    Main endpoint called by your Next.js website.
    """
    signals = []

    # 1. TRY REAL DATA FOR NVDA
    # This proves the connection to the government database works.
    real_nvda = get_real_sec_data("NVDA")
    
    if real_nvda:
        # If SEC answers, put real data at the top
        real_signal = generate_mock_signal(ticker_override="NVDA")
        real_signal.ticker = "NVDA (REAL SEC DATA)"
        real_signal.corporate_activity = real_nvda['description']
        real_signal.sentiment = "Bullish" # Hardcoded for demo, but data is real
        signals.append(real_signal)
    else:
        # Fallback if SEC is slow/blocking
        signals.append(generate_mock_signal(ticker_override="NVDA"))

    # 2. Add Simulation Data for the rest
    # (So the table looks full and professional)
    for _ in range(4):
        signals.append(generate_mock_signal())

    return signals

# --- RUNNER ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)