import os
import random
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
SEC_HEADERS = {"User-Agent": "AlphaInsider/4.0", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") 
CONGRESS_API_URL = os.getenv("CONGRESS_API_URL", "https://api.quiverquant.com/beta/live/congresstrading") 

# --- LEGISLATIVE INTELLIGENCE ENGINE (ALL TICKERS RESTORED) ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # 1. THE "BUY" LIST (Pro Terminal)
    if t == "LMT":
        return {"bill_id": "H.R. 8070", "bill_name": "Nat. Defense Authorization Act", "impact_score": 95, "market_impact": "Direct Beneficiary: Increases procurement for F-35 & missile systems."}
    if t == "NVDA":
        return {"bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act", "impact_score": 88, "market_impact": "Bullish: Establishes government-backed AI infrastructure standards."}
    if t == "SOFI":
        return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "impact_score": 82, "market_impact": "Bullish: Clarifies crypto-banking rules, favoring compliant fintechs."}
    if t == "AA":
        return {"bill_id": "H.R. 3668", "bill_name": "Pipeline Review Act", "impact_score": 78, "market_impact": "Bullish: Reduces energy costs for heavy industrial manufacturing."}
    if t == "CALM":
        return {"bill_id": "H.R. 4368", "bill_name": "Agriculture Appropriations", "impact_score": 75, "market_impact": "Bullish: Subsidies for domestic food production stability."}

    # 2. THE "SELL" LIST (Pro Terminal)
    if t == "PLTR":
        return {"bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act", "impact_score": 40, "market_impact": "Neutral/Bearish: Compliance costs may slow gov contract velocity."}
    if t == "AAPL":
        return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs Act", "impact_score": 30, "market_impact": "Low Impact: Energy costs are negligible for software margins."}
    if t == "NFLX":
        return {"bill_id": "S. 686", "bill_name": "RESTRICT Act", "impact_score": 25, "market_impact": "Bearish: Potential data privacy restrictions impacting ad-tier revenue."}
    if t == "TSLA":
        return {"bill_id": "H.R. 4468", "bill_name": "Choice in Automobile Retail Sales", "impact_score": 35, "market_impact": "Bearish: Rolls back some EV mandates, increasing competition from hybrids."}

    # 3. THE "LEGISLATION TRACKER" LIST (Restored for Page 3)
    if t in ["XOM", "CVX", "BP"]:
        return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs Act", "impact_score": 90, "market_impact": "Highly Bullish: Expands offshore drilling leases and speeds up permits."}
    if t in ["COIN", "MARA", "RIOT"]:
        return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "impact_score": 85, "market_impact": "Bullish: Creates regulatory clarity for digital assets."}
    if t in ["MSFT", "GOOGL", "META"]:
        return {"bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act", "impact_score": 80, "market_impact": "Bullish: Entrenched tech giants can easily afford compliance costs."}
    if t == "IBM":
        return {"bill_id": "H.R. 5525", "bill_name": "Continuing Appropriations Act", "impact_score": 50, "market_impact": "Neutral: General government IT contract maintenance."}

    # DEFAULT FALLBACK
    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "impact_score": 50, "market_impact": "Neutral: General market monitoring."}

# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v4.0 (Unified Data Engine).")
    yield

app = FastAPI(title="AlphaInsider Pro", version="4.0", lifespan=lifespan)
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

# --- ENGINE: LIVE MARKET DATA ---
def get_real_market_data(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        # Fast Info
        price = stock.fast_info.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        
        # Volume
        history = stock.history(period="5d")
        if not history.empty:
            avg_vol = history['Volume'].mean()
            curr_vol = history['Volume'].iloc[-1]
            if curr_vol > avg_vol * 1.3: vol_str = "High (Instit. Buying)"
            elif curr_vol < avg_vol * 0.7: vol_str = "Low (Drying Up)"
            else: vol_str = "Moderate (Steady)"
        else: vol_str = "Neutral"

        # Financials
        try:
            info = stock.info
            eps = info.get('trailingEps', 0)
            fin_str = "Profitable" if eps and eps > 0 else "Unprofitable"
        except: fin_str = "Stable"

        # Earnings
        try:
            cal = stock.calendar
            # yfinance structure varies, sometimes it's a dict, sometimes dataframe
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                earn_str = cal['Earnings Date'][0].strftime("%b %d")
            else:
                earn_str = "TBD"
        except: earn_str = "TBD"

        return {"price": price_str, "vol": vol_str, "fin": fin_str, "earn": earn_str}

    except:
        return {"price": "N/A", "vol": "N/A", "fin": "N/A", "earn": "N/A"}

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    market_data = get_real_market_data(t)
    leg = get_legislative_intel(t)
    
    score_val = leg['impact_score']
    
    # DYNAMIC SCORING
    if score_val > 80:
        final_rating = "STRONG BUY"
        timing = "Accumulate"
    elif score_val < 45:
        final_rating = "SELL"
        timing = "Exit"
    else:
        final_rating = "HOLD"
        timing = "Wait"
        
    return [{
        "ticker": t,
        "price": market_data['price'],
        "volume_signal": market_data['vol'],
        "financial_health": f"{market_data['fin']} (Earn: {market_data['earn']})",
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