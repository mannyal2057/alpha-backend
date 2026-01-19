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
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}

# --- 1. EVENT CALENDAR & CONGRESS DATA (The Edge) ---
TODAY = datetime.now().strftime("%Y-%m-%d")
STATIC_LEGISLATION = [
    { "bill_id": "H.R. 5077", "bill_name": "CREATE AI Act", "market_impact": "Bullish", "sector": "AI", "conviction": 85 },
    { "bill_id": "H.R. 8070", "bill_name": "Defense Auth Act", "market_impact": "Bullish", "sector": "DEFENSE", "conviction": 90 },
    { "bill_id": "H.R. 4763", "bill_name": "Crypto Clarity Act", "market_impact": "Bullish", "sector": "CRYPTO", "conviction": 80 }
]
# "Smart Money" Insider/Congressional Trades
INSIDER_TRADES = {
    "NVDA": {"who": "Rep. Pelosi", "action": "BUY", "size": "Huge"},
    "PLTR": {"who": "Rep. Green", "action": "BUY", "size": "Medium"},
    "COIN": {"who": "Rep. Fallon", "action": "BUY", "size": "Large"},
    "TSLA": {"who": "Sen. Tuberville", "action": "SELL", "size": "Medium"}
}

# --- FAIL-SAFE DATA (Backup) ---
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

SECTOR_MAP = { "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI"], "CRYPTO": ["COIN", "HOOD"], "DEFENSE": ["LMT", "RTX", "BA"], "EV": ["TSLA", "RIVN", "F", "GM"], "FINANCE": ["JPM", "BAC", "SOFI"] }
MARKET_UNIVERSE = list(FAILSAFE_DATA.keys())

class PriceRequest(BaseModel): tickers: list[str]

# --- APP STARTUP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v58.0 (Combined Framework).")
    asyncio.create_task(update_market_scanner())
    yield

app = FastAPI(title="AlphaInsider Pro", version="58.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- 2. DATA FEED (Finnhub) ---
def get_market_data(ticker):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            d = r.json()
            if d.get('c', 0) > 0:
                # Return: Price, Change %, Volatility Proxy (Day Range %)
                day_range = (d['h'] - d['l']) / d['c'] * 100
                return d['c'], d['dp'], day_range, False
    except: pass
    
    # Backup
    base = FAILSAFE_DATA.get(ticker, [100.0, 1.0])
    p = base[0] * random.uniform(0.99, 1.01)
    sim_change = base[1] * random.uniform(-1.5, 1.5)
    return p, sim_change, abs(sim_change * 1.2), True

# --- 3. THE CORE SIGNAL STACK (Algorithm) ---
def analyze_stock(ticker: str):
    try:
        # A. INPUTS
        price, change_pct, volatility, is_sim = get_market_data(ticker)
        
        # B. SIGNAL 1: Insider + Congress (The Edge)
        edge_score = 0
        catalyst = "None"
        
        # Check Legislation
        for bill in STATIC_LEGISLATION:
            if ticker in SECTOR_MAP.get(bill['sector'], []): 
                edge_score += 40
                catalyst = f"Bill: {bill['bill_name']}"

        # Check Insider Trades
        if ticker in INSIDER_TRADES:
            trade = INSIDER_TRADES[ticker]
            if trade['action'] == "BUY":
                edge_score += 30
                catalyst = f"{trade['who']} BUY"
            else:
                edge_score -= 30
                catalyst = f"{trade['who']} SELL"

        # C. SIGNAL 2: Options/Regime (Simulated via Price Action)
        # We use Volatility to approximate Implied Volatility (IV)
        iv_proxy = volatility * 1.5
        expected_move_pct = iv_proxy # 1 Standard Deviation Move
        
        regime = "Normal"
        if iv_proxy > 4.0: regime = "High Volatility (Squeeze Risk)"
        elif iv_proxy < 1.0: regime = "Low Volatility (Compressed)"

        # D. OUTPUT CALCULATION
        # Combine Edge + Momentum (Change %)
        total_score = edge_score + (change_pct * 5)
        
        # Probability Weighted Scenario
        if total_score > 50:
            bias = "Bullish"
            probability = 75 + min(total_score/10, 15) # Max 90%
            scenario = "Breakout Likely"
        elif total_score < -30:
            bias = "Bearish"
            probability = 60 + min(abs(total_score)/10, 20)
            scenario = "Breakdown Likely"
        else:
            bias = "Neutral"
            probability = 50
            scenario = "Range Bound"

        # Risk Level
        risk = "High" if volatility > 3.0 or "High" in regime else "Medium" if volatility > 1.5 else "Low"
        
        # Rating Logic
        final_rating = "HOLD"
        if bias == "Bullish" and probability > 70: final_rating = "STRONG BUY"
        elif bias == "Bullish": final_rating = "BUY"
        elif bias == "Bearish" or risk == "High": final_rating = "SELL"

        # Targets
        target_up = price * (1 + (expected_move_pct/100))
        target_down = price * (1 - (expected_move_pct/100))

        return { 
            "ticker": ticker, 
            "price": f"${price:.2f}",
            "raw_price": price,
            "final_score": final_rating, # For the badges
            "data_source": "FINNHUB_LIVE" if not is_sim else "BACKUP",
            
            # --- THE COMBINED FRAMEWORK OUTPUTS ---
            "trade_bias": bias,
            "probability": f"{probability:.0f}%",
            "scenario": scenario,
            "expected_move": f"+/- {expected_move_pct:.1f}%",
            "risk_level": risk,
            "regime": regime,
            "key_catalyst": catalyst,
            "targets": f"${target_down:.0f} - ${target_up:.0f}"
        }
    except Exception as e:
        return { "ticker": ticker, "price": "N/A", "final_score": "HOLD", "error": str(e) }

# --- WORKER & ENDPOINTS ---
async def update_market_scanner():
    while True:
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futs = {executor.submit(analyze_stock, s): s for s in MARKET_UNIVERSE}
            for f in concurrent.futures.as_completed(futs): results.append(f.result())
        try:
            # Sort for Dashboard Lists
            buys = [x for x in results if x.get('final_score') in ["STRONG BUY", "BUY"]]
            buys.sort(key=lambda x: float(x.get('probability', '0%').strip('%')), reverse=True)
            SERVER_CACHE["buys"] = buys[:5]
            
            cheap = [x for x in results if x.get('raw_price', 999) < 50 and x.get('final_score') != "SELL"]
            cheap.sort(key=lambda x: float(x.get('probability', '0%').strip('%')), reverse=True)
            SERVER_CACHE["cheap"] = cheap[:5]
            
            # Smart Avoid List (Bearish Bias OR High Risk)
            buy_tickers = [b['ticker'] for b in SERVER_CACHE["buys"]]
            sells = [x for x in results if (x.get('trade_bias') == "Bearish" or x.get('risk_level') == "High")]
            sells = [s for s in sells if s['ticker'] not in buy_tickers]
            sells.sort(key=lambda x: x.get('risk_level') == "High", reverse=True)
            SERVER_CACHE["sells"] = sells[:5]
        except: pass
        await asyncio.sleep(900)

@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    return [analyze_stock(ticker.upper())]

@app.get("/api/scanner")
def get_scanner(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.post("/api/prices")
def get_prices(req: PriceRequest):
    res = {}
    for t in req.tickers:
        p, _, _, _ = get_market_data(t)
        res[t] = p
    return res

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)