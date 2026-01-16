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
SEC_HEADERS = {"User-Agent": "AlphaInsider/5.0", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") 
CONGRESS_API_URL = os.getenv("CONGRESS_API_URL", "https://api.quiverquant.com/beta/live/congresstrading") 

# --- SECTOR DATABASE (COMPETITOR MAPPING) ---
SECTOR_PEERS = {
    # SEMICONDUCTORS
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM"],
    "AMD":  ["NVDA", "INTC", "AVGO", "QCOM", "TSM"],
    "INTC": ["AMD", "NVDA", "TSM", "TXN", "QCOM"],
    
    # BIG TECH
    "MSFT": ["AAPL", "GOOGL", "AMZN", "META", "ORCL"],
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META", "SONY"],
    "GOOGL":["MSFT", "AAPL", "AMZN", "META", "SNAP"],
    
    # BANKING & FINTECH
    "JPM":  ["BAC", "WFC", "C", "GS", "MS"],
    "BAC":  ["JPM", "WFC", "C", "GS", "MS"],
    "COIN": ["HOOD", "SQ", "PYPL", "MARA", "RIOT"],
    "SOFI": ["LC", "UPST", "ALLY", "COIN", "HOOD"],

    # DEFENSE
    "LMT":  ["RTX", "NOC", "GD", "BA", "LH"],
    "RTX":  ["LMT", "NOC", "GD", "BA", "GE"],
    
    # ENERGY
    "XOM":  ["CVX", "SHEL", "BP", "TTE", "COP"],
    "CVX":  ["XOM", "SHEL", "BP", "TTE", "OXY"],
    
    # PHARMA
    "PFE":  ["MRK", "JNJ", "LLY", "ABBV", "BMY"],
    "LLY":  ["NVO", "PFE", "MRK", "JNJ", "AMGN"],
    
    # EV / AUTO
    "TSLA": ["RIVN", "LCID", "F", "GM", "TM"],
    "F":    ["GM", "TSLA", "TM", "HMC", "STLA"]
}

# --- LEGISLATIVE INTELLIGENCE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # Known Legislation Map
    if t in ["NVDA", "AMD", "MSFT", "GOOGL", "META", "PLTR", "TSM", "AVGO"]:
        return {"bill_id": "S. 2714", "bill_name": "AI Safety & Innovation Act", "bill_sponsor": "Sen. Chuck Schumer (D-NY)", "impact_score": 88, "market_impact": "Bullish: Establishes government-backed AI infrastructure standards."}
    if t in ["XOM", "CVX", "BP", "SHEL", "OXY", "COP"]:
        return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs Act", "bill_sponsor": "Rep. Steve Scalise (R-LA)", "impact_score": 90, "market_impact": "Highly Bullish: Expands offshore drilling leases."}
    if t in ["COIN", "MARA", "RIOT", "HOOD", "SQ", "PYPL"]:
        return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "bill_sponsor": "Rep. Glenn Thompson (R-PA)", "impact_score": 85, "market_impact": "Bullish: Creates regulatory clarity for digital assets."}
    if t in ["LMT", "RTX", "NOC", "GD", "BA"]:
        return {"bill_id": "H.R. 8070", "bill_name": "Nat. Defense Authorization", "bill_sponsor": "Rep. Mike Rogers (R-AL)", "impact_score": 95, "market_impact": "Direct Beneficiary: Increases defense procurement budget."}
    if t in ["PFE", "MRK", "JNJ", "LLY"]:
        return {"bill_id": "H.R. 5525", "bill_name": "Health Appropriations", "bill_sponsor": "Cmte. On Appropriations", "impact_score": 60, "market_impact": "Neutral: Standard healthcare funding renewal."}

    # Default
    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "bill_sponsor": "Cmte. On Appropriations", "impact_score": 50, "market_impact": "Neutral: General market monitoring."}

# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v5.0 (Sector Scanner Online).")
    yield

app = FastAPI(title="AlphaInsider Pro", version="5.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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
    bill_sponsor: str
    market_impact: str

def get_real_market_data(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        # Price
        price = stock.fast_info.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        
        # Volume Logic
        history = stock.history(period="5d")
        if not history.empty:
            avg_vol = history['Volume'].mean()
            curr_vol = history['Volume'].iloc[-1]
            if curr_vol > avg_vol * 1.2: vol_str = "High (Buying)"
            elif curr_vol < avg_vol * 0.8: vol_str = "Low (Selling)"
            else: vol_str = "Neutral"
        else: vol_str = "Neutral"

        # Financials
        try:
            info = stock.info
            eps = info.get('trailingEps', 0)
            fin_str = "Profitable" if eps and eps > 0 else "Unprofitable"
        except: fin_str = "Stable"

        return {"price": price_str, "vol": vol_str, "fin": fin_str}
    except:
        return {"price": "N/A", "vol": "N/A", "fin": "N/A"}

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    main_ticker = ticker.upper()
    
    # 1. IDENTIFY COMPETITORS
    competitors = SECTOR_PEERS.get(main_ticker, ["SPY", "QQQ", "IWM", "DIA", "GLD"]) # Default to indices if unknown
    
    # Combine Main Ticker + Competitors
    all_tickers = [main_ticker] + competitors
    
    results = []
    
    for t in all_tickers:
        market = get_real_market_data(t)
        leg = get_legislative_intel(t)
        
        # SMART SCORING MODEL
        score = leg['impact_score']
        
        # If legislation is neutral (50), let Technicals decide the score
        if score == 50:
            if "Buying" in market['vol']: score += 20 # Bump to 70 (Buy)
            if "Selling" in market['vol']: score -= 10 # Drop to 40 (Sell)
            if market['fin'] == "Unprofitable": score -= 5
        
        # Final Rating
        if score >= 75: 
            rating = "STRONG BUY"
            timing = "Accumulate"
        elif score >= 65:
            rating = "BUY"
            timing = "Add Dip"
        elif score <= 40:
            rating = "SELL"
            timing = "Exit"
        else:
            rating = "HOLD"
            timing = "Wait"

        # Visual Tag
        sentiment = "Bullish" if "BUY" in rating else "Bearish"
        if rating == "HOLD": sentiment = "Neutral"

        results.append({
            "ticker": t,
            "price": market['price'],
            "volume_signal": market['vol'],
            "financial_health": market['fin'],
            "legislation_score": score,
            "timing_signal": timing,
            "sentiment": sentiment,
            "final_score": rating,
            "corporate_activity": "No Recent Filings", # Simplified for speed
            "congress_activity": "No Recent Activity",
            "bill_id": leg['bill_id'],
            "bill_name": leg['bill_name'],
            "bill_sponsor": leg['bill_sponsor'],
            "market_impact": leg['market_impact']
        })
        
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)