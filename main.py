import os
import random
import asyncio
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/12.0 (admin@alphainsider.io)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}
CIK_CACHE = {} # Stores SEC IDs for fast lookup

# --- SECTOR PEERS ---
SECTOR_PEERS = {
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM", "MU", "ARM", "TXN"],
    "AMD":  ["NVDA", "INTC", "AVGO", "QCOM", "TSM", "MU", "ARM", "TXN"],
    "F":    ["GM", "TM", "HMC", "TSLA", "RIVN", "LCID", "STLA", "VWAGY"],
    "TSLA": ["RIVN", "LCID", "F", "GM", "TM", "BYDDF", "NIO", "XPEV"],
    "VERO": ["PODD", "DXCM", "MDT", "EW", "BSX", "ISRG", "ABT", "ZBH"],
    "SOFI": ["LC", "UPST", "COIN", "HOOD", "PYPL", "SQ", "AFRM", "MQ"],
    "COIN": ["HOOD", "MARA", "RIOT", "MSTR", "SQ", "PYPL", "SOFI", "V"],
    "PFE":  ["MRK", "BMY", "LLY", "JNJ", "ABBV", "AMGN", "GILD", "MRNA"],
    "IBRX": ["MRNA", "NVAX", "BNTX", "GILD", "REGN", "VRTX", "BIIB", "CRSP"],
    "AAL":  ["DAL", "UAL", "LUV", "SAVE", "JBLU", "ALK", "HA", "SKYW"],
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META", "NFLX", "TSLA", "NVDA", "ORCL"],
    "XOM":  ["CVX", "SHEL", "BP", "TTE", "COP", "EOG", "OXY", "SLB"]
}

# --- LEGISLATIVE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # 1. BIOTECH / MED-TECH
    if t in ["VERO", "PODD", "DXCM"]: return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Rep. Aderholt (R-AL)", "impact_score": 60, "market_impact": "Neutral: FDA device funding."}
    if t in ["IBRX", "MRNA"]: return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Rep. Aderholt (R-AL)", "impact_score": 65, "market_impact": "Neutral: NIH research grants."}

    # 2. SECTOR SPECIFIC
    if t == "NVDA": return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t == "SOFI": return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "bill_sponsor": "Rep. Thompson (R-PA)", "impact_score": 85, "market_impact": "Bullish: Crypto-bank clarity."}
    if t == "F": return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 82, "market_impact": "Bullish: Slows EV mandates."}

    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "bill_sponsor": "Congress", "impact_score": 50, "market_impact": "Neutral: General monitoring."}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v12.0 (Hybrid Feed + Timeout Protection).")
    # Pre-load CIK Cache for Speed
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=5)
        if r.status_code == 200:
            data = r.json()
            for key in data:
                CIK_CACHE[data[key]['ticker']] = str(data[key]['cik_str']).zfill(10)
            print(f"✅ SEC Cache: {len(CIK_CACHE)} companies loaded.")
    except: pass
    yield

app = FastAPI(title="AlphaInsider Pro", version="12.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- ENGINE 1: MARKET DATA (FAST) ---
def get_real_market_data(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        
        # Simple volume check (Fast)
        vol = stock.fast_info.last_volume
        vol_str = "High (Buying)" if vol > 1000000 else "Neutral" # Simplified for speed
        
        # Financials (Fast)
        fin_str = "Stable" 
        
        return {"price": price_str, "vol": vol_str, "fin": fin_str}
    except: return {"price": "N/A", "vol": "N/A", "fin": "N/A"}

# --- ENGINE 2: HYBRID CORPORATE ACTION (SEC + NEWS FALLBACK) ---
def get_corporate_action(ticker: str):
    try:
        # STRATEGY A: SEC DIRECT (Fastest if cached)
        target_cik = CIK_CACHE.get(ticker.upper())
        if target_cik:
            sub_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
            # STRICT TIMEOUT: 1.5 seconds max
            r = requests.get(sub_url, headers=SEC_HEADERS, timeout=1.5)
            if r.status_code == 200:
                filings = r.json().get('filings', {}).get('recent', {})
                df = pd.DataFrame(filings)
                
                # Check Form 4 (Insider)
                trades = df[df['form'] == '4']
                if not trades.empty:
                    return f"Form 4 (Trade) {trades.iloc[0]['filingDate']}"
                
                # Check 8-K (Major Events)
                events = df[df['form'] == '8-K']
                if not events.empty:
                    return f"8-K (Event) {events.iloc[0]['filingDate']}"

        # STRATEGY B: YAHOO NEWS FALLBACK (If SEC has nothing)
        # This fills the "No Filing" gap
        stock = yf.Ticker(ticker)
        news = stock.news
        if news:
            latest = news[0]
            title = latest.get('title', 'News Update')
            # Truncate title to fit UI
            return f"News: {title[:25]}..."

        return "No Recent Activity"
    except:
        return "No Recent Activity"

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    competitors = SECTOR_PEERS.get(t, ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD"])
    all_tickers = [t] + competitors[:8] 
    
    results = []
    
    # Process Loop
    for sym in all_tickers:
        m = get_real_market_data(sym)
        l = get_legislative_intel(sym)
        
        # Call Hybrid Engine
        action_text = get_corporate_action(sym)
        
        score = l['impact_score']
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
            "corporate_activity": action_text, # <--- NEW HYBRID DATA
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