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
    "User-Agent": "AlphaInsider/19.0 (admin@alphainsider.io)",
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
    # 1. TOP BUYS (BLUE CHIPS)
    if t == "LMT": return {"bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "bill_sponsor": "Rep. Rogers (R-AL)", "impact_score": 95, "market_impact": "Direct Beneficiary: Military procurement increase."}
    if t == "NVDA": return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 88, "market_impact": "Bullish: AI Infrastructure standards."}
    if t == "AA": return {"bill_id": "H.R. 3668", "bill_name": "Pipeline Review", "bill_sponsor": "Rep. Graves (R-LA)", "impact_score": 78, "market_impact": "Bullish: Lower industrial energy costs."}
    if t == "CALM": return {"bill_id": "H.R. 4368", "bill_name": "Ag Appropriations", "bill_sponsor": "Rep. Harris (R-MD)", "impact_score": 75, "market_impact": "Bullish: Domestic food subsidies."}
    # 2. TOP BUYS (UNDER $50)
    if t == "SOFI": return {"bill_id": "H.R. 4763", "bill_name": "Fin. Innovation Act", "bill_sponsor": "Rep. Thompson (R-PA)", "impact_score": 85, "market_impact": "Bullish: Crypto-bank regulatory clarity."}
    if t == "F": return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 82, "market_impact": "Bullish: Slows EV mandates, helps legacy auto margins."}
    if t == "PFE": return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Cmte. Appropriations", "impact_score": 78, "market_impact": "Bullish: Secured recurring vaccine contracts."}
    if t == "AAL": return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 84, "market_impact": "Bullish: Cheaper jet fuel improves operating margins."}
    if t == "KMI": return {"bill_id": "H.R. 1", "bill_name": "Lower Energy Costs", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 88, "market_impact": "Bullish: Fast-tracking of natural gas pipelines."}
    # 3. SELLS
    if t in ["PLTR", "AI"]: return {"bill_id": "S. 2714", "bill_name": "AI Safety Act", "bill_sponsor": "Sen. Schumer (D-NY)", "impact_score": 40, "market_impact": "Bearish: High compliance costs for software gov contracts."}
    if t in ["LCID", "RIVN"]: return {"bill_id": "H.R. 4468", "bill_name": "Choice in Auto Sales", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 30, "market_impact": "Bearish: Removes EV-only incentives."}
    if t == "NFLX": return {"bill_id": "S. 686", "bill_name": "RESTRICT Act", "bill_sponsor": "Sen. Warner (D-VA)", "impact_score": 25, "market_impact": "Bearish: Data privacy restrictions."}
    if t == "AAPL": return {"bill_id": "H.R. 1", "bill_name": "Energy Act", "bill_sponsor": "Rep. Scalise (R-LA)", "impact_score": 40, "market_impact": "Neutral: Low impact on software margins."}
    if t == "TSLA": return {"bill_id": "H.R. 4468", "bill_name": "Auto Sales Act", "bill_sponsor": "Rep. Walberg (R-MI)", "impact_score": 35, "market_impact": "Bearish: Removal of EV subsidies increases competition."}
    if t == "ANGO": return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Cmte. Appropriations", "impact_score": 35, "market_impact": "Bearish: Reduced reimbursement rates."}
    # 4. MED-TECH
    if t in ["VERO", "PODD", "DXCM"]: return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Rep. Aderholt (R-AL)", "impact_score": 60, "market_impact": "Neutral: FDA device funding."}
    if t in ["IBRX", "MRNA"]: return {"bill_id": "H.R. 5525", "bill_name": "Health Approps", "bill_sponsor": "Rep. Aderholt (R-AL)", "impact_score": 65, "market_impact": "Neutral: NIH research grants."}

    return {"bill_id": "H.R. 5525", "bill_name": "Appropriations Act", "bill_sponsor": "Congress", "impact_score": 50, "market_impact": "Neutral: General monitoring."}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v19.0 (Fast Lane Optimization).")
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=3)
        if r.status_code == 200:
            data = r.json()
            for key in data:
                CIK_CACHE[data[key]['ticker']] = str(data[key]['cik_str']).zfill(10)
    except: pass
    yield

app = FastAPI(title="AlphaInsider Pro", version="19.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- CORE ANALYSIS ---
def analyze_stock(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        fast = stock.fast_info
        price = fast.last_price
        price_str = f"${price:.2f}" if price else "$0.00"
        vol_str = "High (Buying)" if (fast.last_volume or 0) > 1000000 else "Neutral"
        try:
             eps = stock.info.get('trailingEps', 0)
             fin_str = "Profitable" if eps > 0 else "Unprofitable"
        except: fin_str = "Stable"
    except:
        price_str, vol_str, fin_str = "N/A", "N/A", "N/A"

    leg = get_legislative_intel(ticker)
    
    # Corporate Action Check
    action_text = "Monitoring..."
    cutoff_date = datetime.now() - timedelta(days=540)

    try:
        trades = stock.insider_transactions
        if trades is not None and not trades.empty:
            if 'Start Date' in trades.columns:
                trades = trades.sort_values(by='Start Date', ascending=False)
            latest = trades.iloc[0]
            trade_date = None
            if 'Start Date' in latest: trade_date = latest['Start Date']
            elif isinstance(latest.name, pd.Timestamp): trade_date = latest.name
            
            if trade_date and pd.to_datetime(trade_date) > cutoff_date:
                date_fmt = pd.to_datetime(trade_date).strftime('%b %d')
                raw_text = str(latest.get('Text', 'Trade'))
                who = str(latest.get('Insider', 'Exec')).split(' ')[-1]
                action = "Sold" if "Sale" in raw_text or "Sold" in raw_text else "Bought"
                action_text = f"{who} ({action}) {date_fmt}"
        
        # SEC Fallback
        if action_text == "Monitoring...":
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
                            if pd.to_datetime(raw_date) > cutoff_date:
                                nice_date = pd.to_datetime(raw_date).strftime('%b %d')
                                action_text = f"Form 4 (Trade) {nice_date}"
    except: pass

    score = leg['impact_score']
    if score >= 75: rating, timing = "STRONG BUY", "Accumulate"
    elif score >= 60: rating, timing = "BUY", "Add Dip"
    elif score <= 40: rating, timing = "SELL", "Exit"
    else: rating, timing = "HOLD", "Wait"

    return {
        "ticker": ticker,
        "price": price_str,
        "volume_signal": vol_str,
        "financial_health": fin_str,
        "legislation_score": score,
        "timing_signal": timing,
        "sentiment": "Bullish" if "BUY" in rating else "Bearish",
        "final_score": rating,
        "corporate_activity": action_text,
        "congress_activity": "No Recent Activity",
        "bill_id": leg['bill_id'],
        "bill_name": leg['bill_name'],
        "bill_sponsor": leg['bill_sponsor'],
        "market_impact": leg['market_impact']
    }

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    t = ticker.upper()
    
    # --- FAST LANE FOR TOP PICKS PAGE ---
    if single:
        data = analyze_stock(t)
        return [data] # Return single item list

    # --- NORMAL MODE FOR HOME PAGE (Sector Scanner) ---
    competitors = SECTOR_PEERS.get(t, ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD"])
    all_tickers = [t] + competitors[:8]
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(analyze_stock, sym): sym for sym in all_tickers}
        for future in concurrent.futures.as_completed(future_to_ticker):
            try:
                results.append(future.result())
            except: pass
    
    results.sort(key=lambda x: (x['ticker'] == t, x['legislation_score']), reverse=True)
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)