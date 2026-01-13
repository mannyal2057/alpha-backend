import random
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# Set to TRUE to attempt real API calls (requires valid User-Agent)
# Set to FALSE to use robust simulation data (safer for dev/demo)
LIVE_DATA_MODE = False 

# SEC requires a user agent with an email: "CompanyName ContactEmail"
SEC_USER_AGENT = "AlphaInsider/1.0 (admin@alphainsider.com)"

app = FastAPI(title="AlphaInsider Backend", version="1.0")

# --- CORS (CRITICAL FOR NEXT.JS) ---
# Allows your Render frontend to talk to this Python backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATA MODELS ---
class Trade(BaseModel):
    ticker: str
    company_name: str
    sector: str
    date: str
    amount: str
    action: str  # "Buy" or "Sell"
    person: str  # CEO, Rep. Pelosi, etc.
    source: str  # "Corporate" or "Congress"
    price: float

class Signal(BaseModel):
    ticker: str
    sentiment: str  # "Bullish", "Bearish", "Neutral"
    conviction: str # "High", "Moderate"
    corporate_activity: str
    congress_activity: str
    legislative_context: Optional[str] = None

# --- REAL DATA FETCHERS (THE ALPHA) ---

def fetch_sec_data(ticker: str):
    """
    Connects to SEC EDGAR Submission History.
    Requires CIK lookup in a real production app.
    """
    if not LIVE_DATA_MODE: return None
    
    # 1. Get CIK (simplified for demo)
    headers = {"User-Agent": SEC_USER_AGENT}
    # Real logic would query https://www.sec.gov/files/company_tickers.json first
    
    # 2. Fetch Submissions
    # url = f"https://data.sec.gov/submissions/CIK{cik_number}.json"
    # response = requests.get(url, headers=headers)
    # return response.json()
    return None

def fetch_house_data():
    """
    Connects to House Stock Watcher API (Public JSON).
    """
    if not LIVE_DATA_MODE: return None
    
    url = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
    try:
        r = requests.get(url)
        df = pd.DataFrame(r.json())
        # Filter for recent trades
        return df.head(10).to_dict(orient="records")
    except:
        return None

# --- SIMULATION ENGINE (FOR IMMEDIATE UI DEV) ---

def generate_mock_signal():
    tickers = ["NVDA", "PLTR", "XOM", "META", "AMD", "MSFT"]
    ticker = random.choice(tickers)
    
    # Randomize context
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
    return {"status": "active", "mode": "Live" if LIVE_DATA_MODE else "Simulation"}

@app.get("/api/signals", response_model=List[Signal])
def get_alpha_signals():
    """
    Returns the correlated 'Alpha' signals (Insiders + Congress).
    """
    if LIVE_DATA_MODE:
        # In real mode, you would merge fetch_sec_data() and fetch_house_data()
        # and apply logic to find overlapping tickers.
        pass
    
    # Return 5 simulated high-quality signals
    return [generate_mock_signal() for _ in range(5)]

@app.get("/api/insiders", response_model=List[Trade])
def get_insider_trades():
    return [
        Trade(
            ticker="NVDA", company_name="Nvidia", sector="Tech",
            date="2025-04-12", amount="$5.2M", action="Buy",
            person="Jensen Huang (CEO)", source="Corporate", price=890.50
        ),
        Trade(
            ticker="META", company_name="Meta", sector="Tech",
            date="2025-04-10", amount="$1.2M", action="Sell",
            person="Susan Li (CFO)", source="Corporate", price=512.00
        )
    ]

@app.get("/api/congress", response_model=List[Trade])
def get_congress_trades():
    return [
        Trade(
            ticker="XOM", company_name="Exxon", sector="Energy",
            date="2025-04-05", amount="$250K", action="Buy",
            person="Rep. Higgins", source="Congress", price=118.20
        ),
        Trade(
            ticker="PLTR", company_name="Palantir", sector="Tech",
            date="2025-04-08", amount="$50K", action="Buy",
            person="Rep. Pelosi", source="Congress", price=24.50
        )
    ]

# --- RUNNER (For Local Dev) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)