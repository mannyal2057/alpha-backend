import os
import random
import concurrent.futures
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/20.0 (admin@alphainsider.io)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}
CIK_CACHE = {} 

# --- THE SCANNER UNIVERSE (The Pool we search through) ---
MARKET_UNIVERSE = [
    # Tech / AI
    "NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI", "SMCI", "ARM",
    # Finance / Crypto
    "SOFI", "COIN", "HOOD", "PYPL", "SQ", "JPM", "BAC", "V", "MA",
    # Industrial / Defense
    "LMT", "RTX", "BA", "GE", "CAT", "DE", "HON",
    # Energy / Materials
    "XOM", "CVX", "AA", "KMI", "OXY", "COP", "SLB",
    # Consumer / Auto
    "AMZN", "WMT", "COST", "TGT", "F", "GM", "RIVN", "LCID",
    # Bio / Health
    "PFE", "LLY", "MRK", "UNH", "IBRX", "MRNA", "VERO", "DXCM"
]

# --- LEGISLATIVE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    # 1. POSITIVE IMPACT (Score > 70)
    if t in ["LMT", "RTX"]: return {"bill_id": "H.R. 8070", "impact_score": 95, "market_impact": "Direct Beneficiary: Defense spending increase."}
    if t in ["NVDA", "AMD", "MSFT"]: return {"bill_id": "S. 2714", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t in ["KMI", "AA", "XOM"]: return {"bill_id": "H.R. 1", "impact_score": 85, "market_impact": "Bullish: Energy infrastructure permits."}
    if t in ["SOFI", "COIN"]: return {"bill_id": "H.R. 4763", "impact_score": 85, "market_impact": "Bullish: Crypto/Fintech regulatory clarity."}
    if t in ["F", "GM"]: return {"bill_id": "H.R. 4468", "impact_score": 82, "market_impact": "Bullish: Slowing EV mandates helps margins."}
    
    # 2. NEGATIVE IMPACT (Score < 45)
    if t in ["PLTR", "AI"]: return {"bill_id": "S. 2714", "impact_score": 40, "market_impact": "Bearish: Compliance costs for AI software."}
    if t in ["LCID", "RIVN"]: return {"bill_id": "H.R. 4468", "impact_score": 30, "market_impact": "Bearish: Removal of EV-only subsidies."}
    if t in ["AAPL", "META", "GOOGL"]: return {"bill_id": "S. 2992", "impact_score": 42, "market_impact": "Bearish: Antitrust & App Store regulation."}
    
    # 3. NEUTRAL (Score ~50)
    return {"bill_id": "H.R. 5525", "impact_score": 50, "market_impact": "Neutral: General market monitoring."}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v20.0 (Live Market Scanner).")
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=3)
        if r.status_code == 200:
            data = r.json()
            for key in data:
                CIK_CACHE[data[key]['ticker']] = str(data[key]['cik_str']).zfill(10)
    except: pass
    yield

app = FastAPI(title="AlphaInsider Pro", version="20.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def analyze_stock(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        fast = stock.fast_info
        
        # Live Price
        price = fast.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        
        # Volume Check
        vol = fast.last_volume
        vol_str = "High (Buying)" if (vol and vol > 1000000) else "Neutral"
        
        # Financial Health
        try:
             eps = stock.info.get('trailingEps', 0)
             fin_str = "Profitable" if eps > 0 else "Unprofitable"
        except: fin_str = "Stable"
    except:
        price = 0.0
        price_str, vol_str, fin_str = "N/A", "N/A", "N/A"

    leg = get_legislative_intel(ticker)
    
    # Corporate Action (Simplified for Speed)
    action_text = "Monitoring..."
    cutoff_date = datetime.now() - timedelta(days=540)
    try:
        trades = stock.insider_transactions
        if trades is not None and not trades.empty:
            if 'Start Date' in trades.columns: trades = trades.sort_values(by='Start Date', ascending=False)
            latest = trades.iloc[0]
            trade_date = latest.get('Start Date') or latest.name
            if trade_date and pd.to_datetime(trade_date) > cutoff_date:
                who = str(latest.get('Insider', 'Exec')).split(' ')[-1]
                raw = str(latest.get('Text', '')).lower()
                act = "Sold" if "sale" in raw or "sold" in raw else "Bought"
                action_text = f"{who} ({act}) {pd.to_datetime(trade_date).strftime('%b %d')}"
    except: pass

    score = leg['impact_score']
    # Adjust Score based on Price Trend (Basic Technicals)
    if "High" in vol_str: score += 5
    
    if score >= 75: rating, timing = "STRONG BUY", "Accumulate"
    elif score >= 60: rating, timing = "BUY", "Add Dip"
    elif score <= 45: rating, timing = "SELL", "Exit"
    else: rating, timing = "HOLD", "Wait"

    return {
        "ticker": ticker,
        "raw_price": price or 0, # For sorting
        "price": price_str,
        "volume_signal": vol_str,
        "financial_health": fin_str,
        "legislation_score": score,
        "timing_signal": timing,
        "sentiment": "Bullish" if "BUY" in rating else "Bearish",
        "final_score": rating,
        "corporate_activity": action_text,
        "congress_activity": "No Recent Activity",
        "bill_id": leg.get('bill_id', 'N/A'),
        "bill_name": "Appropriations",
        "market_impact": leg.get('market_impact', 'N/A')
    }

@app.get("/api/scanner")
def run_market_scanner(mode: str = "buys"):
    """
    Scans the entire MARKET_UNIVERSE and returns sorted results.
    mode: 'buys' (Top Scores), 'cheap' (Top Scores under $50), 'sells' (Lowest Scores)
    """
    results = []
    
    # 1. SCAN ALL STOCKS IN PARALLEL
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        future_to_ticker = {executor.submit(analyze_stock, sym): sym for sym in MARKET_UNIVERSE}
        for future in concurrent.futures.as_completed(future_to_ticker):
            try:
                data = future.result()
                results.append(data)
            except: pass
            
    # 2. FILTER & SORT BASED ON MODE
    if mode == "buys":
        # Sort by Score Descending
        results.sort(key=lambda x: x['legislation_score'], reverse=True)
        return results[:5] # Top 5
        
    elif mode == "cheap":
        # Filter Price < 50, Then Sort by Score
        cheap_ones = [x for x in results if x['raw_price'] < 50 and x['raw_price'] > 0]
        cheap_ones.sort(key=lambda x: x['legislation_score'], reverse=True)
        return cheap_ones[:5] # Top 5
        
    elif mode == "sells":
        # Sort by Score Ascending (Lowest first)
        results.sort(key=lambda x: x['legislation_score'], reverse=False)
        return results[:5] # Bottom 5

    return results[:5]

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    # Keep this for the Search Bar functionality
    if single: return [analyze_stock(ticker.upper())]
    return [analyze_stock(ticker.upper())]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)