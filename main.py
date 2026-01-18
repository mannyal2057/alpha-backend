import os
import random
import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import pandas as pd
import yfinance as yf
import numpy as np

# --- CONFIGURATION ---
CONGRESS_KEY = os.getenv("CONGRESS_API_KEY", "DEMO_KEY") 
SEC_HEADERS = { 
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}
SESSION = requests.Session()
SESSION.headers.update(SEC_HEADERS)

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- STATIC DATA ---
TODAY = datetime.now().strftime("%Y-%m-%d")
STATIC_LEGISLATION = [
    { "bill_id": "H.R. 5077", "bill_name": "CREATE AI Act", "update_date": TODAY, "bill_sponsor": "Rep. Lucas", "market_impact": "Bullish: AI R&D Funding", "sector": "AI" },
    { "bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "update_date": TODAY, "bill_sponsor": "Rep. Rogers", "market_impact": "Direct Beneficiary: Military", "sector": "DEFENSE" },
    { "bill_id": "H.R. 4763", "bill_name": "Crypto Clarity Act", "update_date": TODAY, "bill_sponsor": "Rep. McHenry", "market_impact": "Bullish: Digital Assets", "sector": "CRYPTO" }
]
STATIC_TRADES = {
    "NVDA": {"pol": "Rep. Pelosi", "type": "Purchase", "date": TODAY},
    "PLTR": {"pol": "Rep. Green", "type": "Purchase", "date": TODAY},
    "COIN": {"pol": "Rep. Fallon", "type": "Purchase", "date": TODAY}
}

SECTOR_MAP = { 
    "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI", "SMCI"], 
    "CRYPTO": ["COIN", "HOOD", "SQ", "MARA", "RIOT", "MSTR"], 
    "DEFENSE": ["LMT", "RTX", "BA", "GD", "GE"], 
    "ENERGY": ["XOM", "CVX", "KMI", "OXY"], 
    "HEALTH": ["PFE", "LLY", "MRK", "VERO", "IBRX"], 
    "EV": ["TSLA", "RIVN", "LCID", "F", "GM"], 
    "FINANCE": ["JPM", "BAC", "V", "MA", "SOFI"] 
}

# Explicitly "Volatile" stocks for Simulation Mode
VOLATILE_TICKERS = ["TSLA", "COIN", "RIVN", "LCID", "MARA", "AI", "NVDA", "PLTR"]

# Realistic Prices
DEMO_PRICES = { 
    "NVDA": 185.0, "AI": 13.0, "PLTR": 170.0, "MSFT": 460.0, "AMD": 230.0, "COIN": 310.0, 
    "LMT": 580.0, "AVGO": 1050.0, "INTC": 24.0, "SOFI": 14.0, "F": 11.5, "BA": 240.0,
    "RTX": 100.0, "HOOD": 35.0, "VERO": 8.0, "PFE": 25.0, "RIVN": 10.0, "LCID": 3.50,
    "TSLA": 415.0, "MARA": 18.0
}
MARKET_UNIVERSE = list(DEMO_PRICES.keys()) + ["GOOGL", "AAPL", "AMZN", "XOM", "CVX"]

class PriceRequest(BaseModel): tickers: list[str]

# --- ENGINES ---
def get_live_data(ticker):
    try:
        stock = yf.Ticker(ticker, session=SESSION)
        fast = stock.fast_info
        price = fast.last_price
        if not price or price <= 0: raise Exception("Invalid")
        return stock, price, fast.last_volume, False
    except:
        p = DEMO_PRICES.get(ticker, 100.0) * random.uniform(0.98, 1.02)
        return None, p, 5000000, True

def get_options_intel(stock, price, is_sim, ticker):
    # SIMULATION LOGIC: Force High Risk for specific stocks
    if is_sim:
        if ticker in VOLATILE_TICKERS:
            # High Risk Simulation
            return "$N/A", "$N/A", 5.5, 0.85, "Bearish (Put Skew)" # IV = 0.85 (High)
        else:
            # Low Risk Simulation
            return "$N/A", "$N/A", 2.0, 0.35, "Neutral" # IV = 0.35 (Low)

    # LIVE LOGIC
    try:
        exps = stock.options
        if not exps: return "N/A", "N/A", 0.0, 0.0, "Neutral"
        chain = stock.option_chain(exps[0])
        calls, puts = chain.calls, chain.puts
        
        atm_call = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]
        atm_put = puts.iloc[(puts['strike'] - price).abs().argsort()[:1]]
        
        call_iv = atm_call['impliedVolatility'].values[0]
        put_iv = atm_put['impliedVolatility'].values[0]
        avg_iv = (call_iv + put_iv) / 2
        
        skew = "Bullish" if (call_iv - put_iv) > 0.05 else "Bearish" if (call_iv - put_iv) < -0.05 else "Neutral"
        cost = (atm_call['lastPrice'].values[0] + atm_put['lastPrice'].values[0])
        move = (cost / price) * 100
        
        return "$N/A", "$N/A", move, avg_iv, skew
    except: return "N/A", "N/A", 0.0, 0.0, "Neutral"

def analyze_stock(ticker: str):
    try:
        stock, price, vol, is_sim = get_live_data(ticker)
        
        # Options Intel (Pass Ticker for Sim Logic)
        _, _, move_pct, iv, skew = get_options_intel(stock, price, is_sim, ticker)
        
        target_up = price * (1 + (move_pct/100))
        target_down = price * (1 - (move_pct/100))

        # Legislation Score
        leg_score = 50
        leg = None
        for bill in ACTIVE_BILLS_CACHE:
            if ticker in SECTOR_MAP.get(bill['sector'], []): 
                leg = bill; leg_score = 85; break
        
        congress_note = "No Recent Activity"
        if ticker in STATIC_TRADES:
            td = STATIC_TRADES[ticker]
            if td['type'] == "Purchase": leg_score += 20; congress_note = f"{td['pol']} Bought (+20)"

        # RISK CALCULATION
        # IV > 0.6 is High Risk
        risk_val = (iv * 100) 
        risk = "High" if risk_val > 60 else "Medium" if risk_val > 30 else "Low"
        
        # FINAL RATING LOGIC
        # If Risk is HIGH and no strong catalyst -> SELL
        if risk == "High" and leg_score < 80:
            rating = "SELL"
        elif leg_score >= 80 and risk != "High":
            rating = "STRONG BUY"
        elif leg_score >= 60:
            rating = "BUY"
        else:
            rating = "HOLD"

        return { 
            "ticker": ticker, "price": f"${price:.2f}", "raw_price": price,
            "final_score": rating, "sentiment": "Bullish" if rating != "HOLD" and rating != "SELL" else "Bearish",
            "risk_level": risk, "expected_move": f"+/- {move_pct:.1f}%",
            "targets": f"${target_down:.0f} - ${target_up:.0f}",
            "skew": skew, "congress_activity": congress_note,
            "bill_id": leg.get('bill_id', 'N/A') if leg else "N/A",
            "corporate_activity": "Data Unavailable"
        }
    except Exception as e:
        return { "ticker": ticker, "price": "N/A", "final_score": "HOLD", "sentiment": "Neutral", "risk_level": "Unknown", "expected_move": "N/A", "targets": "N/A", "skew": "N/A", "congress_activity": "N/A", "bill_id": "N/A", "corporate_activity": "Data Unavailable" }

async def update_market_scanner():
    global ACTIVE_BILLS_CACHE
    while True:
        ACTIVE_BILLS_CACHE = STATIC_LEGISLATION
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futs = {executor.submit(analyze_stock, s): s for s in MARKET_UNIVERSE}
            for f in concurrent.futures.as_completed(futs): results.append(f.result())
        try:
            # 1. BUYS (Score = BUY/STRONG BUY)
            buys = [x for x in results if x.get('final_score') in ["STRONG BUY", "BUY"]]
            buys.sort(key=lambda x: x.get('final_score') == "STRONG BUY", reverse=True)
            SERVER_CACHE["buys"] = buys[:5]
            
            # 2. CHEAP (Price < 50 AND Score = BUY)
            cheap = [x for x in results if x.get('raw_price', 999) < 50 and x.get('final_score') in ["STRONG BUY", "BUY"]]
            SERVER_CACHE["cheap"] = cheap[:5]
            
            # 3. SELLS / HIGH RISK (Score = SELL or Risk = High)
            # Ensure NO OVERLAP with Buys
            sells = [x for x in results if x.get('final_score') == "SELL" or x.get('risk_level') == "High"]
            # Remove any stocks that accidentally made it into 'buys'
            buy_tickers = [b['ticker'] for b in SERVER_CACHE["buys"]]
            sells = [s for s in sells if s['ticker'] not in buy_tickers]
            
            SERVER_CACHE["sells"] = sells[:5]
            
        except Exception as e: print(f"Scanner Logic Error: {e}")
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v44.0 (Simulated Volatility Fix).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="44.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.post("/api/prices")
def get_batch_prices(req: PriceRequest):
    data = {}
    for t in req.tickers:
        _, p, _, _ = get_live_data(t)
        data[t] = p
    return data

@app.get("/api/scanner")
def get_scanner_data(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    return [analyze_stock(ticker.upper())]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)