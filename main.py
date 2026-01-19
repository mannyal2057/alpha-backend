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
FMP_KEY = os.getenv("FMP_API_KEY", "DEMO") 

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
ACTIVE_BILLS_CACHE = []

# --- GOLDEN DATA ---
TODAY = datetime.now().strftime("%Y-%m-%d")
STATIC_LEGISLATION = [
    { "bill_id": "H.R. 5077", "bill_name": "CREATE AI Act", "update_date": TODAY, "bill_sponsor": "Rep. Lucas", "market_impact": "Bullish: AI R&D Funding", "sector": "AI" },
    { "bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "update_date": TODAY, "bill_sponsor": "Rep. Rogers", "market_impact": "Direct Beneficiary: Military", "sector": "DEFENSE" }
]
STATIC_TRADES = {
    "NVDA": {"pol": "Rep. Pelosi", "type": "Purchase", "date": TODAY},
    "PLTR": {"pol": "Rep. Green", "type": "Purchase", "date": TODAY},
    "COIN": {"pol": "Rep. Fallon", "type": "Purchase", "date": TODAY}
}

# --- FAIL-SAFE DATABASE (The "Show" Data) ---
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
    print(f"💎 SYSTEM BOOT: AlphaInsider v51.0 (Truth Detector).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="51.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- DATA ENGINE ---
def get_live_data_fmp(ticker):
    try:
        # TIMEOUT SET TO 3 SECONDS
        url = f"https://financialmodelingprep.com/api/v3/quote/{ticker}?apikey={FMP_KEY}"
        r = requests.get(url, timeout=3) 
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                d = data[0]
                # RETURN REAL DATA
                return d.get('price', 0), d.get('volume', 0), d.get('changesPercentage', 0), False
        else:
            print(f"⚠️ [API FAIL] {ticker}: Status {r.status_code}")
    except Exception as e: 
        print(f"⚠️ [API ERROR] {ticker}: {str(e)}")
    
    # FALLBACK DATA ("Show" Data)
    base = FAILSAFE_DATA.get(ticker, [100.0, 1.0])
    p = base[0] * random.uniform(0.99, 1.01)
    sim_change = base[1] * random.uniform(-1.5, 1.5)
    return p, 5000000, sim_change, True

def analyze_stock(ticker: str):
    try:
        price, vol, change, is_sim = get_live_data_fmp(ticker)
        
        # Determine Source Label
        source_label = "FAILSAFE_BACKUP" if is_sim else "LIVE_API"

        beta = FAILSAFE_DATA.get(ticker, [100, 1.0])[1] if is_sim else (1.8 if abs(change) > 2.5 else 0.8)
        risk_val = (beta * 20) + (abs(change) * 5)
        risk = "High" if risk_val > 45 else "Medium" if risk_val > 25 else "Low"

        leg_score = 50
        leg = None
        for bill in ACTIVE_BILLS_CACHE:
            if ticker in SECTOR_MAP.get(bill['sector'], []): 
                leg = bill; leg_score = 85; break
        
        if ticker in STATIC_TRADES: leg_score += 20

        if leg_score >= 80 and risk == "Low": rating = "STRONG BUY"
        elif leg_score >= 60: rating = "BUY"
        elif risk == "High": rating = "SELL"
        else: rating = "HOLD"

        targets = f"${price*0.9:.0f} - ${price*1.1:.0f}"
        
        return { 
            "ticker": ticker, 
            "price": f"${price:.2f}", 
            "data_source": source_label, # <--- THE TRUTH
            "final_score": rating, 
            "sentiment": "Bullish" if rating in ["BUY", "STRONG BUY"] else "Bearish",
            "risk_level": risk, 
            "expected_move": f"+/- {beta*2.5:.1f}%",
            "targets": targets, 
            "volatility_regime": "High Beta" if beta > 1.3 else "Normal",
            "congress_activity": "Monitoring", 
            "bill_id": leg.get('bill_id', 'N/A') if leg else "N/A",
            "corporate_activity": f"Change {change:.2f}%"
        }
    except: return { "ticker": ticker, "price": "N/A", "data_source": "ERROR", "final_score": "HOLD" }

# --- SCANNER LOGIC ---
async def update_market_scanner():
    global ACTIVE_BILLS_CACHE
    while True:
        ACTIVE_BILLS_CACHE = STATIC_LEGISLATION
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
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
            else:
                sells.sort(key=lambda x: x.get('risk_level') == "High", reverse=True)
            
            SERVER_CACHE["sells"] = sells[:5]
        except: pass
        await asyncio.sleep(900)

# --- ENDPOINTS ---
@app.get("/api/debug")
def debug_api():
    masked = FMP_KEY[:4] + "****" if FMP_KEY and len(FMP_KEY) > 4 else "NOT FOUND"
    try:
        r = requests.get(f"https://financialmodelingprep.com/api/v3/quote/AAPL?apikey={FMP_KEY}", timeout=2)
        status = "Online (LIVE)" if r.status_code == 200 else f"Offline ({r.status_code})"
        return { "status": status, "key": masked, "code": r.status_code, "response": r.json() }
    except Exception as e: return { "status": "Connection Error", "error": str(e) }

@app.post("/api/prices")
def get_batch_prices(req: PriceRequest):
    data = {}
    for t in req.tickers:
        p, _, _, _ = get_live_data_fmp(t)
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