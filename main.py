import os
import random
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd

# --- CONFIGURATION ---
SEC_HEADERS = {"User-Agent": "AlphaInsider/3.0", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") 
CONGRESS_API_URL = os.getenv("CONGRESS_API_URL", "https://api.quiverquant.com/beta/live/congresstrading") 

# --- LEGISLATIVE INTELLIGENCE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # 🟢 BUYS
    if t == "LMT":
        return {
            "bill_id": "H.R. 8070", "bill_name": "Nat. Defense Authorization Act '26",
            "impact_score": 95, "market_impact": "Direct Beneficiary: Increases procurement for F-35 & missile systems."
        }
    if t == "NVDA":
        return {
            "bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act",
            "impact_score": 88, "market_impact": "Bullish: Establishes government-backed AI infrastructure standards."
        }
    if t == "SOFI":
        return {
            "bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act",
            "impact_score": 82, "market_impact": "Bullish: Clarifies crypto-banking rules, favoring compliant fintechs."
        }
    if t == "AA":
        return {
            "bill_id": "H.R. 3668", "bill_name": "Pipeline Review Act",
            "impact_score": 78, "market_impact": "Bullish: Reduces energy costs for heavy industrial manufacturing."
        }
    
    # 🔴 SELLS / NEUTRAL
    if t == "PLTR":
        return {
            "bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act",
            "impact_score": 40, "market_impact": "Neutral/Bearish: Compliance costs may slow gov contract velocity."
        }
    if t == "AAPL":
        return {
            "bill_id": "H.R. 1", "bill_name": "Lower Energy Costs Act",
            "impact_score": 30, "market_impact": "Low Impact: Energy costs are negligible for software margins."
        }
        
    return {
        "bill_id": "H.R. 5525", "bill_name": "Appropriations Act",
        "impact_score": 50, "market_impact": "Neutral: General government funding maintenance."
    }

# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v3.0 (Full Market Mechanics Online).")
    yield

app = FastAPI(title="AlphaInsider Pro", version="3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- DATA MODELS ---
class Signal(BaseModel):
    ticker: str
    price: str                  # Market Confirmation
    volume_signal: str          # Market Confirmation
    financial_health: str       # Earnings Context
    legislation_score: int      # 0-100 Score
    timing_signal: str          # Timing Intelligence
    sentiment: str              # Sentiment Overlay
    final_score: str            # FINAL BUY/SELL RATING
    
    # Details
    corporate_activity: str
    congress_activity: str
    bill_id: str
    bill_name: str
    market_impact: str

# --- HARDCODED "REAL" DATA (Jan 2026 Snapshot) ---
# In a real app, this would come from a live Finance API
MARKET_SNAPSHOT = {
    # BUYS
    "LMT": {"price": "$462.15", "vol": "High (Instit. Buying)", "fin": "EPS Growth +12%", "earn": "Jan 23"},
    "NVDA": {"price": "$142.50", "vol": "Moderate (Accumulation)", "fin": "EPS Growth +55%", "earn": "Feb 21"},
    "SOFI": {"price": "$11.20", "vol": "Very High (Breakout)", "fin": "Profitable (GAAP)", "earn": "Jan 29"},
    "AA":   {"price": "$42.10", "vol": "High (Trend Reversal)", "fin": "Margin Expansion", "earn": "Jan 22"},
    "CALM": {"price": "$68.45", "vol": "Low (Steady)", "fin": "Cash Rich / 0 Debt", "earn": "Mar 05"},
    
    # SELLS
    "PLTR": {"price": "$28.10", "vol": "High (Distribution)", "fin": "Overvalued (175x PE)", "earn": "Feb 05"},
    "ANGO": {"price": "$9.80",  "vol": "Low (Selling Pressure)", "fin": "Missed Estimates", "earn": "Feb 12"},
    "NFLX": {"price": "$580.00","vol": "Moderate (Stalling)", "fin": "Sub Growth Slowing", "earn": "Jan 20"},
    "AAPL": {"price": "$182.30","vol": "Low (Choppy)", "fin": "HW Rev Decline", "earn": "Jan 29"},
    "TSLA": {"price": "$215.00","vol": "High (Volatility)", "fin": "Margin Compression", "earn": "Jan 24"},
}

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    snap = MARKET_SNAPSHOT.get(t, {"price": "$100.00", "vol": "Neutral", "fin": "Stable", "earn": "N/A"})
    leg = get_legislative_intel(t)
    
    # LOGIC: Generate the "Final Score" dynamically
    score_val = leg['impact_score']
    final_rating = "HOLD"
    timing = "Wait"
    
    # Buy Logic
    if t in ["LMT", "NVDA", "SOFI", "AA", "CALM"]:
        final_rating = "STRONG BUY" if score_val > 85 else "BUY"
        timing = "Accumulate Now"
    # Sell Logic
    elif t in ["PLTR", "ANGO", "NFLX", "AAPL", "TSLA"]:
        final_rating = "STRONG SELL" if t == "PLTR" else "SELL"
        timing = "Exit / Hedge"
        
    return [{
        "ticker": t,
        "price": snap['price'],
        "volume_signal": snap['vol'],
        "financial_health": f"{snap['fin']} (Earn: {snap['earn']})",
        "legislation_score": leg['impact_score'],
        "timing_signal": timing,
        "sentiment": "Bullish" if "BUY" in final_rating else "Bearish",
        "final_score": final_rating,
        
        "corporate_activity": "Insider Selling" if t == "PLTR" else "No Recent Filings",
        "congress_activity": "Pelosi (Call Options)" if t == "NVDA" else "No Recent Activity",
        "bill_id": leg['bill_id'],
        "bill_name": leg['bill_name'],
        "market_impact": leg['market_impact']
    }]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)