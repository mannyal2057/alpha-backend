import os
import random
import asyncio
from typing import List, Optional
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/15.0 (contact@alphainsider.io)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}
CIK_CACHE = {} 

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
    if t in ["VERO", "PODD", "DXCM"]: return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Rep. Aderholt (R-AL)", "impact_score": 60, "market_impact": "Neutral: FDA device funding."}
    if t in ["IBRX", "MRNA"]: return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Rep. Aderholt (R-AL)", "impact_score": 65, "market_impact": "Neutral: NIH research grants."}
    if t == "NVDA": return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t == "SOFI": return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "bill_sponsor": "Rep. Thompson (R-PA)", "impact_score": 85, "market_impact": "Bullish: Crypto-bank clarity."}
    if t == "F": return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 82, "market_impact": "Bullish: Slows EV mandates."}
    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "bill_sponsor": "Congress", "impact_score": 50, "market_impact": "Neutral: General monitoring."}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v15.0 (Date Filters + Buy/Sell Logic).")
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=3)
        if r.status_code == 200:
            data = r.json()
            for key in data:
                CIK_CACHE[data[key]['ticker']] = str(data[key]['cik_str']).zfill(10)
    except: pass
    yield

app = FastAPI(title="AlphaInsider Pro", version="15.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- ENGINE 1: MARKET DATA ---
def get_real_market_data(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        vol = stock.fast_info.last_volume
        vol_str = "High (Buying)" if vol > 1000000 else "Neutral"
        fin_str = "Stable" 
        return {"price": price_str, "vol": vol_str, "fin": fin_str}
    except: return {"price": "N/A", "vol": "N/A", "fin": "N/A"}

# --- ENGINE 2: HYBRID CORPORATE ACTION ---
def get_corporate_action(ticker: str, is_primary: bool):
    # FILTER: Ignore trades older than 18 months (approx 540 days)
    cutoff_date = datetime.now() - timedelta(days=540)
    
    # STRATEGY A: YFINANCE (Detailed Buy/Sell) - Only for Primary Ticker or big stocks
    # This gives us the "Text" field we need.
    if is_primary:
        try:
            stock = yf.Ticker(ticker)
            trades = stock.insider_transactions
            if trades is not None and not trades.empty:
                latest = trades.iloc[0]
                
                # Check Date
                trade_date = None
                if 'Start Date' in latest: trade_date = latest['Start Date']
                elif isinstance(latest.name, pd.Timestamp): trade_date = latest.name
                
                if trade_date and pd.to_datetime(trade_date) > cutoff_date:
                    t_str = str(trade_date).split(' ')[0]
                    # EXTRACT BUY/SELL TEXT
                    text = latest.get('Text', 'Trade')
                    who = latest.get('Insider', 'Exec')
                    # Shorten names for UI
                    if " " in str(who): who = str(who).split(" ")[-1] # Last name only
                    
                    return f"{who} ({text}) on {t_str}"
        except: pass

    # STRATEGY B: SEC DIRECT (Fast Date Check) - For Competitors
    try:
        target_cik = CIK_CACHE.get(ticker.upper())
        if target_cik:
            sub_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
            r = requests.get(sub_url, headers=SEC_HEADERS, timeout=1.0)
            if r.status_code == 200:
                filings = r.json().get('filings', {}).get('recent', {})
                df = pd.DataFrame(filings)
                if not df.empty:
                    trades = df[df['form'] == '4']
                    if not trades.empty:
                        raw_date = trades.iloc[0]['filingDate']
                        # Date Check
                        if pd.to_datetime(raw_date) > cutoff_date:
                             return f"Form 4 (Trade) {raw_date}"
    except: pass

    # STRATEGY C: FALLBACK
    return "Monitoring..."

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    competitors = SECTOR_PEERS.get(t, ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD"])
    all_tickers = [t] + competitors[:8] 
    
    results = []
    
    for sym in all_tickers:
        is_primary = (sym == t) # Only prioritize the searched stock
        
        m = get_real_market_data(sym)
        l = get_legislative_intel(sym)
        action_text = get_corporate_action(sym, is_primary)
        
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
            "corporate_activity": action_text,
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