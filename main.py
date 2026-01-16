import os
import random
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
import yfinance as yf  # <--- NEW IMPORT

# --- CONFIGURATION ---
SEC_HEADERS = {"User-Agent": "AlphaInsider/3.0", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") 
CONGRESS_API_URL = os.getenv("CONGRESS_API_URL", "https://api.quiverquant.com/beta/live/congresstrading") 

# --- LEGISLATIVE INTELLIGENCE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # 🟢 BUYS
    if t == "LMT":
        return {"bill_id": "H.R. 8070", "bill_name": "Nat. Defense Authorization Act '26", "impact_score": 95, "market_impact": "Direct Beneficiary: Increases procurement for F-35 & missile systems."}
    if t == "NVDA":
        return {"bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act", "impact_score": 88, "market_impact": "Bullish: Establishes government-backed AI infrastructure standards."}
    if t == "SOFI":
        return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "impact_score": 82, "market_impact": "Bullish: Clarifies crypto-banking rules, favoring compliant fintechs."}
    if t == "AA":
        return {"bill_id": "H.R. 3668", "bill_name": "Pipeline Review Act", "impact_score": 78, "market_impact": "Bullish: Reduces energy costs for heavy industrial manufacturing."}
    
    # 🔴 SELLS / NEUTRAL
    if t == "PLTR":
        return {"bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act", "impact_score": 40, "market_impact": "Neutral/Bearish: Compliance costs may slow gov contract velocity."}
    if t == "AAPL":
        return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs Act", "impact_score": 30, "market_impact": "Low Impact: Energy costs are negligible for software margins."}
        
    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "impact_score": 50, "market_impact": "Neutral: General government funding maintenance."}

# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v3.1 (Live Market Data Online).")
    yield

app = FastAPI(title="AlphaInsider Pro", version="3.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- DATA MODELS ---
class Signal(BaseModel):
    ticker: str
    price: str                  
    volume_signal: str          
    financial_health: str       
    legislation_score: int      
    timing_signal: str          
    sentiment: str              
    final_score: str            
    corporate_activity: str
    congress_activity: str
    bill_id: str
    bill_name: str
    market_impact: str

# --- ENGINE: LIVE MARKET DATA (YFINANCE) ---
def get_real_market_data(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        
        # 1. Get Live Price
        # fast_info is much faster than .info
        price = stock.fast_info.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        
        # 2. Volume Analysis
        history = stock.history(period="5d")
        if not history.empty:
            avg_vol = history['Volume'].mean()
            curr_vol = history['Volume'].iloc[-1]
            if curr_vol > avg_vol * 1.3:
                vol_str = "High (Instit. Buying)"
            elif curr_vol < avg_vol * 0.7:
                vol_str = "Low (Drying Up)"
            else:
                vol_str = "Moderate (Steady)"
        else:
            vol_str = "Neutral"

        # 3. Financial Health (EPS Check)
        # We wrap this in try/except because sometimes yahoo data is missing
        try:
            info = stock.info
            eps = info.get('trailingEps', 0)
            if eps and eps > 0:
                fin_str = "Profitable (Positive EPS)"
            else:
                fin_str = "Unprofitable (Cash Burn)"
        except:
            fin_str = "Stable"

        # 4. Next Earnings
        try:
            cal = stock.calendar
            if cal and 'Earnings Date' in cal:
                earn_date = cal['Earnings Date'][0] # List of dates
                earn_str = earn_date.strftime("%b %d")
            else:
                earn_str = "TBD"
        except:
            earn_str = "TBD"

        return {"price": price_str, "vol": vol_str, "fin": fin_str, "earn": earn_str}

    except Exception as e:
        print(f"Market Data Error for {ticker}: {e}")
        return {"price": "N/A", "vol": "N/A", "fin": "N/A", "earn": "N/A"}


@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    
    # CALL LIVE ENGINE
    market_data = get_real_market_data(t)
    leg = get_legislative_intel(t)
    
    # SCORING LOGIC
    score_val = leg['impact_score']
    final_rating = "HOLD"
    timing = "Wait"
    
    # Simple logic for demo purposes
    if score_val > 80:
        final_rating = "STRONG BUY"
        timing = "Accumulate Now"
    elif score_val < 45:
        final_rating = "SELL"
        timing = "Exit / Hedge"
    elif score_val > 60:
        final_rating = "BUY"
        timing = "Watch Dip"
        
    return [{
        "ticker": t,
        "price": market_data['price'],
        "volume_signal": market_data['vol'],
        "financial_health": f"{market_data['fin']} (Earn: {market_data['earn']})",
        "legislation_score": leg['impact_score'],
        "timing_signal": timing,
        "sentiment": "Bullish" if "BUY" in final_rating else "Bearish",
        "final_score": final_rating,
        
        # Mock Context for Details
        "corporate_activity": "Insider Selling" if t == "PLTR" else "No Recent Filings",
        "congress_activity": "Pelosi (Call Options)" if t == "NVDA" else "No Recent Activity",
        "bill_id": leg['bill_id'],
        "bill_name": leg['bill_name'],
        "market_impact": leg['market_impact']
    }]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)