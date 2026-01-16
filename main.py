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
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/9.0 (admin@alphainsider.io)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}

# --- SECTOR PEERS (EXPANDED TO 8 STOCKS) ---
SECTOR_PEERS = {
    # SEMICONDUCTORS / AI
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM", "MU", "ARM", "TXN"],
    "AMD":  ["NVDA", "INTC", "AVGO", "QCOM", "TSM", "MU", "ARM", "TXN"],
    
    # AUTOS / EV
    "F":    ["GM", "TM", "HMC", "TSLA", "RIVN", "LCID", "STLA", "VWAGY"],
    "TSLA": ["RIVN", "LCID", "F", "GM", "TM", "BYDDF", "NIO", "XPEV"],
    
    # FINTECH / CRYPTO
    "SOFI": ["LC", "UPST", "COIN", "HOOD", "PYPL", "SQ", "AFRM", "MQ"],
    "COIN": ["HOOD", "MARA", "RIOT", "MSTR", "SQ", "PYPL", "SOFI", "V"],
    
    # PHARMA / HEALTHCARE
    "PFE":  ["MRK", "BMY", "LLY", "JNJ", "ABBV", "AMGN", "GILD", "MRNA"],
    
    # BIOTECH (Specific for IBRX)
    "IBRX": ["MRNA", "NVAX", "BNTX", "GILD", "REGN", "VRTX", "BIIB", "CRSP"],
    
    # AIRLINES
    "AAL":  ["DAL", "UAL", "LUV", "SAVE", "JBLU", "ALK", "HA", "SKYW"],
    
    # BIG TECH
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META", "NFLX", "TSLA", "NVDA", "ORCL"],
    
    # OIL & GAS
    "XOM":  ["CVX", "SHEL", "BP", "TTE", "COP", "EOG", "OXY", "SLB"]
}

# --- LEGISLATIVE INTELLIGENCE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # 1. BIOTECH & HEALTH (IBRX, PFE, MRNA)
    if t in ["IBRX", "MRNA", "NVAX", "BNTX", "CRSP"]:
        return {"bill_id": "H.R. 5525", "bill_name": "Health Appropriations Act", "bill_sponsor": "Rep. Robert Aderholt (R-AL)", "impact_score": 65, "market_impact": "Neutral: Funding for NIH research grants."}
    
    # 2. TOP PICKS 
    if t == "LMT": return {"bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "bill_sponsor": "Rep. Rogers (R-AL)", "impact_score": 95, "market_impact": "Direct Beneficiary: Military procurement increase."}
    if t == "NVDA": return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t == "AA": return {"bill_id": "H.R. 3668", "bill_name": "Pipeline Review", "bill_sponsor": "Rep. Graves (R-LA)", "impact_score": 78, "market_impact": "Bullish: Lower industrial energy costs."}
    if t == "CALM": return {"bill_id": "H.R. 4368", "bill_name": "Ag Appropriations", "bill_sponsor": "Rep. Harris (R-MD)", "impact_score": 75, "market_impact": "Bullish: Domestic food subsidies."}
    
    # 3. UNDER $50 
    if t == "SOFI": return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "bill_sponsor": "Rep. Thompson (R-PA)", "impact_score": 85, "market_impact": "Bullish: Crypto-bank regulatory clarity."}
    if t == "F": return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 82, "market_impact": "Bullish: Slows EV mandates, helps legacy auto margins."}
    if t == "AAL": return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 84, "market_impact": "Bullish: Cheaper jet fuel improves operating margins."}
    if t == "KMI": return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 88, "market_impact": "Bullish: Fast-tracking of natural gas pipelines."}

    # 4. SELLS / AVOIDS
    if t in ["PLTR", "AI"]: return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 40, "market_impact": "Bearish: High compliance costs for software gov contracts."}
    if t in ["LCID", "RIVN"]: return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 30, "market_impact": "Bearish: Removes EV-only incentives."}

    # Default
    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "bill_sponsor": "Congress", "impact_score": 50, "market_impact": "Neutral: General monitoring."}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v9.0 (8-Stock Sector Scanner).")
    yield

app = FastAPI(title="AlphaInsider Pro", version="9.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- ENGINE 1: LIVE MARKET DATA ---
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

# --- ENGINE 2: LIVE SEC DATA ---
def get_live_sec_filings(ticker: str):
    try:
        cik_url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(cik_url, headers=SEC_HEADERS, timeout=1.5) # Reduced timeout for speed
        
        target_cik = None
        if r.status_code == 200:
            data = r.json()
            ticker_upper = ticker.upper()
            for key in data:
                if data[key]['ticker'] == ticker_upper:
                    target_cik = str(data[key]['cik_str']).zfill(10)
                    break
        
        if target_cik:
            sub_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
            r_sub = requests.get(sub_url, headers=SEC_HEADERS, timeout=1.5)
            if r_sub.status_code == 200:
                filings = r_sub.json().get('filings', {}).get('recent', {})
                df = pd.DataFrame(filings)
                insider_trades = df[df['form'] == '4']
                if not insider_trades.empty:
                    latest = insider_trades.iloc[0]
                    date = latest['filingDate']
                    return f"Form 4 (Trade) {date}" # Shortened text for UI
                
        return "No Recent Filings"
    except:
        return "No Recent Filings"

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    main_ticker = t
    
    # FETCH 8 COMPETITORS
    # If ticker is unknown, fallback to Big Tech list
    competitors = SECTOR_PEERS.get(main_ticker, ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD"])
    
    # Create list of 9 stocks (Main + 8 Peers)
    all_tickers = [main_ticker] + competitors[:8] 
    
    results = []
    for sym in all_tickers:
        m = get_real_market_data(sym)
        l = get_legislative_intel(sym)
        sec_data = get_live_sec_filings(sym)
        
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
            
            "corporate_activity": sec_data,
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