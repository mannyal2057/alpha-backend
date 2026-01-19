import os
import random
import asyncio
import concurrent.futures
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

# --- CONFIGURATION ---
# We now look for FINNHUB_API_KEY. 
# If you haven't set it yet, it will default to DEMO (and likely fail/use backup).
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- GOLDEN DATA ---
TODAY = datetime.now().strftime("%Y-%m-%d")
STATIC_LEGISLATION = [
    { "bill_id": "H.R. 5077", "bill_name": "CREATE AI Act", "update_date": TODAY, "bill_sponsor": "Rep. Lucas", "market_impact": "Bullish: AI R&D Funding", "sector": "AI" },
    { "bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "update_date": TODAY, "bill_sponsor": "Rep. Rogers", "market_impact": "Direct Beneficiary: Military", "sector": "DEFENSE" }
]

# --- FAIL-SAFE DATABASE (Backup) ---
FAILSAFE_DATA = { 
    "NVDA": [185.0, 1.4], "AI": [13.0, 1.8], "PLTR": [170.0, 1.5], "MSFT": [460.0, 0.9], 
    "AMD": [230.0, 1.4], "COIN": [310.0, 2.5], "LMT": [580.0, 0.5], "AVGO": [1050.0, 1.1],
    "F": [11.5, 1.1], "SOFI": [14.0, 1.8], "TSLA": [415.0, 2.2], "RIVN": [10.5, 2.8],
    "HOOD": [35.0, 1.4], "VERO": [8.0, 0.8], "GOOGL": [190.0, 1.0], "AMZN": [220.0, 1.1],
    "PFE": [25.0, 0.6], "MRK": [120.0, 0.4], "INTC": [24.0, 1.2], "QCOM": [160.0, 1.1],
    "BA": [240.0, 1.1], "RTX": [100.0, 0.7], "JPM": [175.0, 0.8], "BAC": [35.0, 0.9],
    "XOM": [110.0, 0.6], "CVX": [150.0, 0.7], "KMI": [20.0, 0.5], "WMT": [160.0, 0.4],
    "COST": [720.0, 0.6], "GM": [45.0, 1.1], "LCID": [3.5, 3.0]
}

SECTOR_PEERS = { "NVDA": ["AMD", "INTC", "AVGO"], "AI": ["PLTR", "SOFI", "SNOW"], "F": ["GM", "TM", "RIVN"], "TSLA": ["RIVN", "LCID", "F"] }
SECTOR_MAP = { "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI"], "CRYPTO": ["COIN", "HOOD"], "DEFENSE": ["LMT", "RTX", "BA"], "EV": ["TSLA", "RIVN", "F", "GM"], "FINANCE": ["JPM", "BAC", "SOFI"] }
MARKET_UNIVERSE = list(FAILSAFE_DATA.keys())

class PriceRequest(BaseModel): tickers: list[str]

# --- APP STARTUP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    key_hash = FINNHUB_KEY[:5] + "..." if len(FINNHUB_KEY) > 5 else "MISSING"
    print(f"💎 SYSTEM BOOT: AlphaInsider v57.0 (Finnhub Integration).")
    print(f"🔑 FINNHUB KEY: {key_hash}")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="57.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- NEW DATA ENGINE (FINNHUB) ---
def get_live_data_finnhub(ticker):
    try:
        # FINNHUB QUOTE ENDPOINT
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=3)
        
        if r.status_code == 200:
            data = r.json()
            # Finnhub returns: 'c' (current), 'd' (change), 'dp' (change percent)
            # If 'c' is 0, the ticker might be invalid or permission denied
            if data.get('c', 0) > 0:
                return data.get('c'), 5000000, data.get('dp', 0.0), False
        elif r.status_code == 429:
            print(f"⚠️ [RATE LIMIT] Finnhub limit reached. Using Backup.")
        elif r.status_code == 403:
            print(f"⚠️ [AUTH FAIL] Finnhub Key Invalid.")
            
    except Exception as e: 
        print(f"⚠️ [API ERROR] {ticker}: {str(e)}")
    
    # Fallback to Backup Data
    base = FAILSAFE_DATA.get(ticker, [100.0, 1.0])
    p = base[0] * random.uniform(0.99, 1.01)
    sim_change = base[1] * random.uniform(-1.5, 1.5)
    return p, 5000000, sim_change, True

def analyze_stock(ticker: str):
    try:
        price, vol, change, is_sim = get_live_data_finnhub(ticker)
        
        source = "FINNHUB_API" if not is_sim else "BACKUP_DATA"
        beta = FAILSAFE_DATA.get(ticker, [100, 1.0])[1] if is_sim else 1.2 
        
        risk_val = (beta * 20) + (abs(change) * 5)
        risk = "High" if risk_val > 45 else "Medium" if risk_val > 25 else "Low"

        leg_score = 50
        leg = None
        for bill in ACTIVE_BILLS_CACHE:
            if ticker in SECTOR_MAP.get(bill['sector'], []): 
                leg = bill; leg_score = 85; break

        if leg_score >= 80 and risk == "Low": rating = "STRONG BUY"
        elif leg_score >= 60: rating = "BUY"
        elif risk == "High": rating = "SELL"
        else: rating = "HOLD"

        targets = f"${price*0.9:.0f} - ${price*1.1:.0f}"
        
        return { 
            "ticker": ticker, 
            "price": f"${price:.2f}", 
            "data_source": source,
            "final_score": rating, 
            "sentiment": "Bullish" if rating in ["BUY", "STRONG BUY"] else "Bearish",
            "risk_level": risk, 
            "expected_move": f"+/- {beta*2.5:.1f}%",
            "targets": targets, 
            "congress_activity": "Monitoring", 
            "corporate_activity": f"Change {change:.2f}%"
        }
    except: return { "ticker": ticker, "price": "N/A", "data_source": "ERROR", "final_score": "HOLD" }

# --- MANUAL KEY TESTER ---
@app.get("/api/test_key")
def manual_key_test(key: str):
    masked = key[:4] + "..." if len(key) > 5 else "KEY"
    url = f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}"
    try:
        r = requests.get(url, timeout=4)
        status = "WORKING" if r.status_code == 200 else f"FAILED ({r.status_code})"
        return { "provider": "Finnhub", "key": masked, "status": status, "response": r.json() if r.status_code == 200 else r.text }
    except Exception as e: return { "status": "ERROR", "detail": str(e) }

# --- ENDPOINTS ---
@app.post("/api/prices")
def get_batch_prices(req: PriceRequest):
    data = {}
    for t in req.tickers:
        p, _, _, _ = get_live_data_finnhub(t)
        data[t] = p
    return data

@app.get("/api/scanner")
def get_scanner_data(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA", single: bool = False):
    return [analyze_stock(ticker.upper())]

async def update_market_scanner():
    global ACTIVE_BILLS_CACHE
    while True:
        ACTIVE_BILLS_CACHE = STATIC_LEGISLATION
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor: # Lower threads to respect rate limit
            futs = {executor.submit(analyze_stock, s): s for s in MARKET_UNIVERSE}
            for f in concurrent.futures.as_completed(futs): results.append(f.result())
        try:
            buys = [x for x in results if x.get('final_score') in ["STRONG BUY", "BUY"]]
            buys.sort(key=lambda x: x.get('final_score') == "STRONG BUY", reverse=True)
            SERVER_CACHE["buys"] = buys[:5]
            
            cheap = [x for x in results if float(x.get('price', '$0').replace('$','')) < 50 and x.get('final_score') != "SELL"]
            cheap.sort(key=lambda x: x.get('final_score') == "STRONG BUY", reverse=True)
            SERVER_CACHE["cheap"] = cheap[:5]
            
            buy_tickers = [b['ticker'] for b in SERVER_CACHE["buys"]]
            sells = [x for x in results if (x.get('final_score') == "SELL" or x.get('risk_level') == "High")]
            sells = [s for s in sells if s['ticker'] not in buy_tickers]
            if len(sells) < 3:
                all_sorted = sorted(results, key=lambda x: float(x.get('expected_move', '0').split(' ')[1].replace('%','')), reverse=True)
                sells = [s for s in all_sorted if s['ticker'] not in buy_tickers][:5]
            else: sells.sort(key=lambda x: x.get('risk_level') == "High", reverse=True)
            SERVER_CACHE["sells"] = sells[:5]
        except: pass
        await asyncio.sleep(900)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)