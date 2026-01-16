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
# SEC requires a proper User-Agent. We use a generic admin email.
SEC_HEADERS = {
    "User-Agent": "AlphaInsider/10.0 (admin@alphainsider.io)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}

# --- GLOBAL CACHE (The Secret Sauce) ---
# We store the SEC ID list here so we don't download it 100 times.
CIK_CACHE = {}

# --- SECTOR PEERS (Updated with VERO) ---
SECTOR_PEERS = {
    # SEMICONDUCTORS / AI
    "NVDA": ["AMD", "INTC", "AVGO", "QCOM", "TSM", "MU", "ARM", "TXN"],
    "AMD":  ["NVDA", "INTC", "AVGO", "QCOM", "TSM", "MU", "ARM", "TXN"],
    
    # AUTOS / EV
    "F":    ["GM", "TM", "HMC", "TSLA", "RIVN", "LCID", "STLA", "VWAGY"],
    "TSLA": ["RIVN", "LCID", "F", "GM", "TM", "BYDDF", "NIO", "XPEV"],
    
    # MED-TECH / DEVICES (Added VERO)
    "VERO": ["PODD", "DXCM", "MDT", "EW", "BSX", "ISRG", "ABT", "ZBH"],
    "PODD": ["VERO", "DXCM", "MDT", "EW", "BSX", "ISRG", "ABT", "ZBH"],
    
    # FINTECH / CRYPTO
    "SOFI": ["LC", "UPST", "COIN", "HOOD", "PYPL", "SQ", "AFRM", "MQ"],
    "COIN": ["HOOD", "MARA", "RIOT", "MSTR", "SQ", "PYPL", "SOFI", "V"],
    
    # PHARMA / HEALTHCARE
    "PFE":  ["MRK", "BMY", "LLY", "JNJ", "ABBV", "AMGN", "GILD", "MRNA"],
    "IBRX": ["MRNA", "NVAX", "BNTX", "GILD", "REGN", "VRTX", "BIIB", "CRSP"],
    
    # AIRLINES
    "AAL":  ["DAL", "UAL", "LUV", "SAVE", "JBLU", "ALK", "HA", "SKYW"],
    
    # OIL & GAS
    "XOM":  ["CVX", "SHEL", "BP", "TTE", "COP", "EOG", "OXY", "SLB"]
}

# --- LEGISLATIVE INTELLIGENCE ENGINE ---
def get_legislative_intel(ticker: str):
    t = ticker.upper()
    
    # 1. MED-TECH (VERO)
    if t in ["VERO", "PODD", "DXCM", "MDT"]:
        return {"bill_id": "H.R. 5525", "bill_name": "Health Appropriations Act", "bill_sponsor": "Rep. Robert Aderholt (R-AL)", "impact_score": 60, "market_impact": "Neutral: Funding for FDA medical device approvals."}

    # 2. TOP PICKS 
    if t == "LMT": return {"bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "bill_sponsor": "Rep. Rogers (R-AL)", "impact_score": 95, "market_impact": "Direct Beneficiary: Military procurement increase."}
    if t == "NVDA": return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t == "AA": return {"bill_id": "H.R. 3668", "bill_name": "Pipeline Review", "bill_sponsor": "Rep. Graves (R-LA)", "impact_score": 78, "market_impact": "Bullish: Lower industrial energy costs."}
    
    # 3. UNDER $50 
    if t == "SOFI": return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "bill_sponsor": "Rep. Thompson (R-PA)", "impact_score": 85, "market_impact": "Bullish: Crypto-bank regulatory clarity."}
    if t == "F": return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 82, "market_impact": "Bullish: Slows EV mandates, helps legacy auto margins."}
    if t == "AAL": return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 84, "market_impact": "Bullish: Cheaper jet fuel improves operating margins."}
    if t == "PFE": return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Cmte. Appropriations", "impact_score": 78, "market_impact": "Bullish: Secured recurring vaccine contracts."}

    # 4. SELLS / AVOIDS
    if t in ["PLTR", "AI"]: return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 40, "market_impact": "Bearish: High compliance costs for software gov contracts."}
    if t in ["LCID", "RIVN"]: return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 30, "market_impact": "Bearish: Removes EV-only incentives."}

    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "bill_sponsor": "Congress", "impact_score": 50, "market_impact": "Neutral: General monitoring."}

# --- SYSTEM BOOT (CACHE LOADER) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v10.0 (SEC Cache Engine).")
    try:
        # Download the Master List ONCE at startup
        print("⏳ Downloading SEC CIK Database (This happens once)...")
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=5)
        if r.status_code == 200:
            data = r.json()
            for key in data:
                entry = data[key]
                # Map "NVDA" -> "0001045810"
                CIK_CACHE[entry['ticker']] = str(entry['cik_str']).zfill(10)
            print(f"✅ SEC Database Loaded: {len(CIK_CACHE)} companies indexed.")
        else:
            print("❌ Failed to load SEC Database.")
    except Exception as e:
        print(f"❌ SEC Boot Error: {e}")
    
    yield

app = FastAPI(title="AlphaInsider Pro", version="10.0", lifespan=lifespan)
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

# --- ENGINE 2: LIVE SEC DATA (OPTIMIZED) ---
def get_live_sec_filings(ticker: str):
    try:
        # 1. FAST LOOKUP (No download needed)
        target_cik = CIK_CACHE.get(ticker.upper())
        
        if target_cik:
            # 2. Fetch specific company filings (Fast)
            sub_url = f"https://data.sec.gov/submissions/CIK{target_cik}.json"
            r_sub = requests.get(sub_url, headers=SEC_HEADERS, timeout=2.0)
            
            if r_sub.status_code == 200:
                filings = r_sub.json().get('filings', {}).get('recent', {})
                df = pd.DataFrame(filings)
                
                # Check for Form 4 (Trades)
                trades = df[df['form'] == '4']
                if not trades.empty:
                    date = trades.iloc[0]['filingDate']
                    return f"Form 4 (Trade) {date}"
                
                # Check for 8-K (News)
                news = df[df['form'] == '8-K']
                if not news.empty:
                    date = news.iloc[0]['filingDate']
                    return f"8-K (News) {date}"

        return "No Recent Filings"
    except:
        return "No Recent Filings"

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    t = ticker.upper()
    
    # COMPETITORS: Default to Big Tech if unknown
    competitors = SECTOR_PEERS.get(t, ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD"])
    all_tickers = [t] + competitors[:8] 
    
    results = []
    for sym in all_tickers:
        m = get_real_market_data(sym)
        l = get_legislative_intel(sym)
        sec_data = get_live_sec_filings(sym) # Now fast & cached
        
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