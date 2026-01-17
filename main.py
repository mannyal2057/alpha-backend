import os
import json
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

# --- CONFIGURATION ---
CONGRESS_KEY = os.getenv("CONGRESS_API_KEY", "DEMO_KEY") 
SEC_HEADERS = { "User-Agent": "AlphaInsider/31.0 (admin@alphainsider.io)", "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov" }
DB_FILE = "paper_trading.json"

# --- CACHE ---
CIK_CACHE = {} 
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- TRADING DATABASE ENGINE ---
def load_db():
    if not os.path.exists(DB_FILE):
        # Initialize default portfolio with $100k
        default_db = {"cash": 100000.0, "holdings": {}, "history": []}
        with open(DB_FILE, "w") as f: json.dump(default_db, f)
        return default_db
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return {"cash": 100000.0, "holdings": {}, "history": []}

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)

# --- Pydantic Models for API ---
class TradeRequest(BaseModel):
    ticker: str
    action: str  # "BUY" or "SELL"
    quantity: int

# --- SECTOR PEERS & MAP (Kept from previous version) ---
SECTOR_PEERS = { "NVDA": ["AMD", "INTC", "AVGO", "QCOM"], "F": ["GM", "TM", "HMC", "TSLA"], "TSLA": ["RIVN", "LCID", "F", "GM"], "VERO": ["PODD", "DXCM", "MDT"], "SOFI": ["LC", "UPST", "COIN", "HOOD"], "COIN": ["HOOD", "MARA", "RIOT"], "SQ": ["PYPL", "COIN"], "BA": ["LMT", "RTX", "GD"], "PFE": ["MRK", "BMY", "LLY"], "AAL": ["DAL", "UAL", "LUV"], "AAPL": ["MSFT", "GOOGL", "AMZN"], "XOM": ["CVX", "SHEL", "BP"] }
SECTOR_MAP = { "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI"], "CRYPTO": ["COIN", "HOOD", "SQ", "MARA"], "DEFENSE": ["LMT", "RTX", "BA", "GD"], "ENERGY": ["XOM", "CVX", "KMI", "OXY"], "HEALTH": ["PFE", "LLY", "MRK", "VERO", "IBRX"], "EV": ["TSLA", "RIVN", "LCID", "F", "GM"], "FINANCE": ["JPM", "BAC", "V", "MA", "SOFI"] }
CONGRESS_TRADES_DB = { "NVDA": {"pol": "Rep. Pelosi", "type": "Purchase", "date": "2024-11-22"}, "MSFT": {"pol": "Rep. Khanna", "type": "Purchase", "date": "2024-12-15"}, "LMT": {"pol": "Rep. Rutherford", "type": "Purchase", "date": "2024-12-05"}, "RTX": {"pol": "Sen. Tuberville", "type": "Purchase", "date": "2024-11-28"} }
MARKET_UNIVERSE = ["NVDA", "AMD", "MSFT", "GOOGL", "AAPL", "META", "TSLA", "PLTR", "AI", "SOFI", "COIN", "HOOD", "PYPL", "SQ", "JPM", "BAC", "LMT", "RTX", "BA", "GE", "XOM", "CVX", "AA", "KMI", "AMZN", "WMT", "COST", "F", "GM", "RIVN", "LCID", "PFE", "LLY", "MRK", "IBRX", "MRNA", "VERO", "DXCM"]

# --- CORE FUNCTIONS (Legislative + Analysis) ---
def fetch_real_legislation():
    url = f"https://api.congress.gov/v3/bill?api_key={CONGRESS_KEY}&limit=25&sort=updateDate+desc"
    cleaned_bills = []
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            bills = r.json().get('bills', [])
            for b in bills:
                title = str(b.get('title', 'Unknown')).upper()
                bill_id = f"{b.get('type', 'HR').upper()} {b.get('number', '000')}"
                impact, score, sector = "Neutral: Monitoring.", 50, None
                if "INTELLIGENCE" in title or "TECHNOLOGY" in title: impact, score, sector = "Bullish: Tech investment.", 85, "AI"
                elif "DEFENSE" in title: impact, score, sector = "Direct Beneficiary: Military.", 92, "DEFENSE"
                elif "ENERGY" in title: impact, score, sector = "Bullish: Infrastructure.", 80, "ENERGY"
                elif "HEALTH" in title: impact, score, sector = "Neutral: Health funding.", 65, "HEALTH"
                elif "CRYPTO" in title: impact, score, sector = "Bullish: Crypto Regs.", 88, "CRYPTO"
                if sector: cleaned_bills.append({ "bill_id": bill_id, "bill_name": title[:60]+"...", "bill_sponsor": "Congress", "impact_score": score, "market_impact": impact, "sector": sector })
    except: pass
    if not cleaned_bills: cleaned_bills.append({ "bill_id": "H.R. 2882", "bill_name": "Appropriations Act", "bill_sponsor": "Rep. Granger", "impact_score": 60, "market_impact": "Neutral: Gov Funding.", "sector": "FINANCE" })
    return cleaned_bills

def get_legislative_intel(ticker: str):
    for bill in ACTIVE_BILLS_CACHE:
        if ticker in SECTOR_MAP.get(bill['sector'], []): return bill
    return {"bill_id": "N/A", "impact_score": 50, "market_impact": "No active legislation found.", "bill_sponsor": "N/A"}

def analyze_stock(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        try: price = stock.fast_info.last_price or 0.0
        except: price = 0.0
        price_str = f"${price:.2f}"
    except: return {"ticker": ticker, "raw_price": 0, "final_score": "HOLD", "legislation_score": 50}

    leg = get_legislative_intel(ticker)
    score = leg.get('impact_score', 50)
    
    # Congress Bonus
    congress_note = "No Recent Activity"
    trade_data = CONGRESS_TRADES_DB.get(ticker)
    if trade_data:
        if trade_data['type'] == "Purchase": score += 25; congress_note = f"{trade_data['pol']} (Bought) +25%"
        elif trade_data['type'] == "Sale": score -= 25; congress_note = f"{trade_data['pol']} (Sold) -25%"

    if score > 99: score = 99
    if score >= 75: rating = "STRONG BUY"
    elif score >= 60: rating = "BUY"
    elif score <= 45: rating = "SELL"
    else: rating = "HOLD"

    return { "ticker": ticker, "raw_price": price, "price": price_str, "legislation_score": score, "final_score": rating, "congress_activity": congress_note, "market_impact": leg.get('market_impact', 'N/A') }

# --- BACKGROUND WORKER ---
async def update_market_scanner():
    global ACTIVE_BILLS_CACHE
    while True:
        print("🔄 [BACKGROUND] Refreshing Intelligence...")
        bills = fetch_real_legislation()
        if bills: ACTIVE_BILLS_CACHE = bills
        
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ticker = {executor.submit(analyze_stock, sym): sym for sym in MARKET_UNIVERSE}
            for future in concurrent.futures.as_completed(future_to_ticker):
                try: results.append(future.result())
                except: pass
        
        results.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["buys"] = results[:5]
        cheap = [x for x in results if 0 < x['raw_price'] < 50]
        cheap.sort(key=lambda x: x['legislation_score'], reverse=True)
        SERVER_CACHE["cheap"] = cheap[:5]
        results.sort(key=lambda x: x['legislation_score'], reverse=False)
        SERVER_CACHE["sells"] = results[:5]
        SERVER_CACHE["last_updated"] = datetime.now().strftime("%H:%M:%S")
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v31.0 (Paper Trading Active).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="31.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- NEW TRADING ENDPOINTS ---
@app.get("/api/portfolio")
def get_portfolio():
    db = load_db()
    
    # Calculate Real-Time Value
    total_equity = db["cash"]
    holdings_view = []
    
    for ticker, data in db["holdings"].items():
        qty = data["qty"]
        avg_cost = data["avg_price"]
        
        # Get Live Price
        try: current_price = yf.Ticker(ticker).fast_info.last_price or avg_cost
        except: current_price = avg_cost
        
        market_value = qty * current_price
        total_equity += market_value
        
        unrealized_pl = market_value - (qty * avg_cost)
        pl_percent = (unrealized_pl / (qty * avg_cost)) * 100 if avg_cost > 0 else 0
        
        holdings_view.append({
            "ticker": ticker,
            "qty": qty,
            "avg_price": f"${avg_cost:.2f}",
            "current_price": f"${current_price:.2f}",
            "market_value": f"${market_value:.2f}",
            "pl": f"${unrealized_pl:.2f}",
            "pl_percent": f"{pl_percent:.1f}%"
        })
        
    start_cash = 100000.0
    total_return = ((total_equity - start_cash) / start_cash) * 100
    
    return {
        "cash": f"${db['cash']:.2f}",
        "equity": f"${total_equity:.2f}",
        "total_return": f"{total_return:.2f}%",
        "holdings": holdings_view,
        "history": db["history"][-10:] # Last 10 trades
    }

@app.post("/api/trade")
def execute_trade(trade: TradeRequest):
    db = load_db()
    ticker = trade.ticker.upper()
    qty = trade.quantity
    
    # Get Real Price
    try: price = yf.Ticker(ticker).fast_info.last_price
    except: raise HTTPException(status_code=400, detail="Stock not found")
    
    if not price: raise HTTPException(status_code=400, detail="Price unavailable")
    
    total_cost = price * qty
    
    if trade.action == "BUY":
        if db["cash"] < total_cost:
            raise HTTPException(status_code=400, detail="Insufficient Funds")
        
        # Update Cash
        db["cash"] -= total_cost
        
        # Update Holdings
        if ticker in db["holdings"]:
            old_qty = db["holdings"][ticker]["qty"]
            old_cost = db["holdings"][ticker]["avg_price"]
            new_qty = old_qty + qty
            new_avg = ((old_qty * old_cost) + total_cost) / new_qty
            db["holdings"][ticker] = {"qty": new_qty, "avg_price": new_avg}
        else:
            db["holdings"][ticker] = {"qty": qty, "avg_price": price}
            
    elif trade.action == "SELL":
        if ticker not in db["holdings"] or db["holdings"][ticker]["qty"] < qty:
            raise HTTPException(status_code=400, detail="Insufficient Shares")
            
        # Update Cash
        db["cash"] += total_cost
        
        # Update Holdings
        db["holdings"][ticker]["qty"] -= qty
        if db["holdings"][ticker]["qty"] == 0:
            del db["holdings"][ticker]
            
    # Save History
    db["history"].append({
        "ticker": ticker, "action": trade.action, "qty": qty, 
        "price": f"${price:.2f}", "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    
    save_db(db)
    return {"message": "Trade Executed", "new_cash": db["cash"]}

# --- EXISTING ENDPOINTS ---
@app.get("/api/scanner")
def get_scanner_data(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    if single: return [analyze_stock(ticker.upper())]
    competitors = SECTOR_PEERS.get(ticker.upper(), ["AAPL", "MSFT"])
    all_tickers = [ticker.upper()] + competitors[:5]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = {executor.submit(analyze_stock, s): s for s in all_tickers}
        for f in concurrent.futures.as_completed(futs): results.append(f.result())
    results.sort(key=lambda x: (x['ticker'] == ticker.upper()), reverse=True)
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)