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
SEC_HEADERS = {"User-Agent": "AlphaInsider/7.0", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}

# --- SECTOR PEERS ---
SECTOR_PEERS = {
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM"],
    "F": ["GM", "TM", "HMC", "TSLA", "RIVN"],
    "SOFI": ["LC", "UPST", "COIN", "HOOD", "PYPL"],
    "PFE": ["MRK", "BMY", "LLY", "JNJ", "ABBV"],
    "AAL": ["DAL", "UAL", "LUV", "SAVE", "JBLU"] # Added Airline Peers
}

# --- LEGISLATIVE INTELLIGENCE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # 1. TOP PICKS (High Priced)
    if t == "LMT": return {"bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "bill_sponsor": "Rep. Rogers (R-AL)", "impact_score": 95, "market_impact": "Direct Beneficiary: Military procurement increase."}
    if t == "NVDA": return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t == "AA": return {"bill_id": "H.R. 3668", "bill_name": "Pipeline Review", "bill_sponsor": "Rep. Graves (R-LA)", "impact_score": 78, "market_impact": "Bullish: Lower industrial energy costs."}
    if t == "CALM": return {"bill_id": "H.R. 4368", "bill_name": "Ag Appropriations", "bill_sponsor": "Rep. Harris (R-MD)", "impact_score": 75, "market_impact": "Bullish: Domestic food subsidies."}
    
    # 2. UNDER $50 GEMS (BUYS)
    if t == "SOFI": return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "bill_sponsor": "Rep. Thompson (R-PA)", "impact_score": 85, "market_impact": "Bullish: Crypto-bank regulatory clarity."}
    if t == "F": return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 82, "market_impact": "Bullish: Slows EV mandates, helps legacy auto margins."}
    if t == "PFE": return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Cmte. Appropriations", "impact_score": 78, "market_impact": "Bullish: Secured recurring vaccine contracts."}
    
    # REPLACED GM WITH AAL (American Airlines)
    if t == "AAL": return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 84, "market_impact": "Bullish: Cheaper jet fuel improves operating margins."}
    
    if t == "KMI": return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 88, "market_impact": "Bullish: Fast-tracking of natural gas pipelines."}

    # 3. SELLS / AVOIDS
    if t in ["PLTR", "AI"]: return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 40, "market_impact": "Bearish: High compliance costs for software gov contracts."}
    if t in ["LCID", "RIVN", "TSLA"]: return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 30, "market_impact": "Bearish: Removes EV-only incentives."}
    if t == "GPRO": return {"bill_id": "S. 686", "bill_name": "RESTRICT Act", "bill_sponsor": "Sen. Warner (D-VA)", "impact_score": 20, "market_impact": "Bearish: Supply chain restrictions on electronics."}
    if t == "NFLX": return {"bill_id": "S. 686", "bill_name": "RESTRICT Act", "bill_sponsor": "Sen. Warner (D-VA)", "impact_score": 25, "market_impact": "Bearish: Data privacy restrictions."}
    if t == "AAPL": return {"bill_id": "H.R. 1", "bill_name": "Energy Act", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 40, "market_impact": "Neutral: Low impact on software margins."}
    if t == "ANGO": return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Cmte. Appropriations", "impact_score": 35, "market_impact": "Bearish: Reduced reimbursement rates."}

    # Default
    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "bill_sponsor": "Congress", "impact_score": 50, "market_impact": "Neutral: General monitoring."}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v7.0 (Price Filter Corrected).")
    yield

app = FastAPI(title="AlphaInsider Pro", version="7.0", lifespan=lifespan)
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
        price = stock.fast_info.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        
        history = stock.history(period="5d")
        if not history.empty:
            avg = history['Volume'].mean()
            curr = history['Volume'].iloc[-1]
            vol_str = "High (Buying)" if curr > avg * 1.2 else "Low (Selling)" if curr < avg * 0.8 else "Neutral"
        else: vol_str = "Neutral"

        try:
            eps = stock.info.get('trailingEps', 0)
            fin_str = "Profitable" if eps > 0 else "Unprofitable"
        except: fin_str = "Stable"
        
        return {"price": price_str, "vol": vol_str, "fin": fin_str}
    except: return {"price": "N/A", "vol": "N/A", "fin": "N/A"}

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    main_ticker = t
    
    # If using search, find competitors
    competitors = SECTOR_PEERS.get(main_ticker, [])
    all_tickers = [main_ticker] + competitors
    
    results = []
    for sym in all_tickers:
        m = get_real_market_data(sym)
        l = get_legislative_intel(sym)
        
        score = l['impact_score']
        
        # Scoring Logic
        if score >= 75: rating, timing = "STRONG BUY", "Accumulate"
        elif score >= 60: rating, timing = "BUY", "Add Dip"
        elif score <= 40: rating, timing = "SELL", "Exit"
        else: rating, timing = "HOLD", "Wait"

        results.append({
            "ticker": sym,
            "price": m['price'],
            "volume_signal": m['vol'],
            "financial_health": m['fin'],
            "legislation_score": score,
            "timing_signal": timing,
            "sentiment": "Bullish" if "BUY" in rating else "Bearish",
            "final_score": rating,
            "corporate_activity": "No Recent Filings",
            "congress_activity": "No Recent Activity",
            "bill_id": l['bill_id'],
            "bill_name": l['bill_name'],
            "bill_sponsor": l['bill_sponsor'],
            "market_impact": l['market_impact']
        })
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)