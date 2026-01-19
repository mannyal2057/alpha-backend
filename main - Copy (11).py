import os
import random
import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

# --- LIBRARIES ---
try:
    from polygon import RESTClient
    POLYGON_AVAILABLE = True
except ImportError:
    POLYGON_AVAILABLE = False

# --- CONFIGURATION ---
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
POLYGON_KEY = os.getenv("POLYGON_API_KEY", "").strip()

# --- CACHE ---
SERVER_CACHE = {"buys": [], "cheap": [], "sells": [], "last_updated": None}
EVENT_CACHE = {"ipos": [], "earnings": [], "economic": []}

# --- 1. CORE DATA ---
TODAY = datetime.now().strftime("%Y-%m-%d")

# UPDATED: Includes 'bill_sponsor' for the frontend
STATIC_LEGISLATION = [
    { 
        "bill_id": "H.R. 5077", 
        "bill_name": "CREATE AI Act", 
        "bill_sponsor": "Rep. Eshoo", 
        "market_impact": "Bullish", 
        "sector": "AI", 
        "conviction": 85 
    },
    { 
        "bill_id": "H.R. 8070", 
        "bill_name": "Defense Auth Act", 
        "bill_sponsor": "Rep. Rogers", 
        "market_impact": "Bullish", 
        "sector": "DEFENSE", 
        "conviction": 90 
    },
    { 
        "bill_id": "H.R. 4763", 
        "bill_name": "Crypto Clarity Act", 
        "bill_sponsor": "Rep. Emmer", 
        "market_impact": "Bullish", 
        "sector": "CRYPTO", 
        "conviction": 80 
    }
]

INSIDER_TRADES = {
    "NVDA": {"who": "Rep. Pelosi", "action": "BUY", "size": "Huge"},
    "PLTR": {"who": "Rep. Green", "action": "BUY", "size": "Medium"},
    "COIN": {"who": "Rep. Fallon", "action": "BUY", "size": "Large"},
    "TSLA": {"who": "Sen. Tuberville", "action": "SELL", "size": "Medium"}
}

# --- FAIL-SAFE DATA ---
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

SECTOR_PEERS = {
    "NVDA": ["AMD", "INTC", "AVGO", "TSM"],
    "AMD":  ["NVDA", "INTC", "ARM", "TSM"],
    "AI":   ["PLTR", "SOFI", "SNOW", "PATH"],
    "PLTR": ["AI", "SNOW", "DDOG", "MDB"],
    "F":    ["GM", "TM", "TSLA", "RIVN"],
    "TSLA": ["RIVN", "LCID", "F", "GM"],
    "COIN": ["HOOD", "MARA", "RIOT", "MSTR"],
    "HOOD": ["COIN", "SCHW", "IBKR", "SOFI"],
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL"],
    "LMT":  ["RTX", "BA", "GD", "NOC"],
    "RTX":  ["LMT", "BA", "GE", "HON"],
    "XOM":  ["CVX", "SHEL", "BP", "COP"],
    "PFE":  ["MRK", "LLY", "JNJ", "ABBV"],
    "JPM":  ["BAC", "C", "WFC", "GS"]
}

# Used to map legislation to specific tickers
SECTOR_MAP = { 
    "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI"], 
    "CRYPTO": ["COIN", "HOOD"], 
    "DEFENSE": ["LMT", "RTX", "BA"], 
    "EV": ["TSLA", "RIVN", "F", "GM"], 
    "FINANCE": ["JPM", "BAC", "SOFI"] 
}

MARKET_UNIVERSE = list(FAILSAFE_DATA.keys())

class PriceRequest(BaseModel): tickers: list[str]

# --- APP STARTUP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider v65.0 (Optimization Complete).")
    asyncio.create_task(update_market_scanner())
    asyncio.create_task(update_event_calendar())
    yield

app = FastAPI(title="AlphaInsider Pro", version="65.0", lifespan=lifespan)

# CORS: Allow all for development flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- NEW ENGINE: NEWS SENTIMENT ---
def get_news_sentiment(ticker):
    try:
        start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={start}&to={end}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            news = r.json()
            if not news: return "Neutral", 0
            score = 0
            bullish_words = ["growth", "beat", "record", "jump", "buy", "upgrade", "positive", "high", "gain", "strong"]
            bearish_words = ["miss", "drop", "fall", "sell", "downgrade", "negative", "low", "loss", "weak", "sued"]
            for article in news[:5]:
                headline = article.get('headline', '').lower()
                for w in bullish_words:
                    if w in headline: score += 1
                for w in bearish_words:
                    if w in headline: score -= 1
            if score >= 1: return "Bullish", score
            elif score <= -1: return "Bearish", score
            else: return "Neutral", score
    except: pass
    return "Neutral", 0

# --- DATA FEED ---
def get_market_data(ticker):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            d = r.json()
            if d.get('c', 0) > 0:
                day_range = (d['h'] - d['l']) / d['c'] * 100
                return d['c'], d['dp'], day_range, False
    except: pass
    base = FAILSAFE_DATA.get(ticker, [100.0, 1.0])
    p = base[0] * random.uniform(0.99, 1.01)
    sim_change = base[1] * random.uniform(-1.5, 1.5)
    return p, sim_change, abs(sim_change * 1.2), True

# --- OPTIONS ENGINE ---
def get_options_data(ticker, current_price):
    if not POLYGON_AVAILABLE or len(POLYGON_KEY) < 5:
        return 0, 0, "Simulated", "Standard"
    try:
        client = RESTClient(POLYGON_KEY)
        chain = client.list_snapshot_options_chain(ticker, params={"expiration_date": "gte:2024-01-01", "limit": 100})
        total_gex = 0
        atm_iv = 0
        found_data = False
        for contract in chain:
            if not contract.greeks or not contract.open_interest: continue
            found_data = True
            gamma = contract.greeks.gamma or 0
            oi = contract.open_interest or 0
            gex_val = (gamma * oi * 100 * current_price)
            if contract.details.contract_type == "call": total_gex += gex_val
            else: total_gex -= gex_val
            if abs(contract.details.strike_price - current_price) < (current_price * 0.02):
                atm_iv = contract.greeks.implied_volatility or 0
        if not found_data: return 0, 0, "Simulated (No Data)", "Standard"
        regime = "Neutral"
        if total_gex > 5000000: regime = "Positive GEX (Stabilizing)"
        elif total_gex < -5000000: regime = "Negative GEX (Volatile)"
        return atm_iv, total_gex, "Real Polygon Data", regime
    except: return 0, 0, "Simulated (API Limit)", "Standard"

# --- CORE SIGNAL STACK ---
def analyze_stock(ticker: str):
    try:
        price, change_pct, vol_proxy, is_sim = get_market_data(ticker)
        real_iv, gex, opt_source, regime = get_options_data(ticker, price)
        news_sentiment, news_score = get_news_sentiment(ticker) 
        
        # --- CALCULATION FIX: Rule of 16 ---
        if opt_source.startswith("Real"):
            # real_iv is annual (e.g. 0.45), divide by 16 for daily move
            daily_move_pct = (real_iv / 16) * 100 
            expected_move_pct = daily_move_pct 
            volatility_metric = real_iv * 100 # Keep raw IV for risk scoring
        else:
            volatility_metric = vol_proxy * 1.5
            expected_move_pct = vol_proxy * 1.5
            regime = "High Volatility" if vol_proxy > 4.0 else "Normal"

        edge_score = 0
        catalyst = "None"
        
        # 1. Legislation
        for bill in STATIC_LEGISLATION:
            if ticker in SECTOR_MAP.get(bill['sector'], []): 
                edge_score += 40
                catalyst = f"Bill: {bill['bill_name']}"
        
        # 2. News
        if news_sentiment == "Bullish": 
            edge_score += 15
            if catalyst == "None": catalyst = "Positive News Cycle"
        elif news_sentiment == "Bearish": 
            edge_score -= 15
            if catalyst == "None": catalyst = "Negative Headlines"

        # 3. Insider
        if ticker in INSIDER_TRADES:
            trade = INSIDER_TRADES[ticker]
            if trade['action'] == "BUY":
                edge_score += 30
                catalyst = f"{trade['who']} BUY"
            else:
                edge_score -= 30
                catalyst = f"{trade['who']} SELL"

        total_score = edge_score + (change_pct * 5)
        
        if regime == "Positive GEX (Stabilizing)":
            total_score *= 0.8
            scenario = "Range Bound (Pinned)"
        elif regime == "Negative GEX (Volatile)":
            total_score *= 1.2
            scenario = "Squeeze / Acceleration Risk"
        else:
            if total_score > 50: scenario = "Breakout Likely"
            elif total_score < -30: scenario = "Breakdown Likely"
            else: scenario = "Range Bound"

        bias = "Bullish" if total_score > 0 else "Bearish"
        if abs(total_score) < 15: bias = "Neutral"
        probability = 50 + min(abs(total_score)/2, 40)

        risk = "High" if volatility_metric > 4.0 or "Volatile" in regime else "Medium" if volatility_metric > 2.0 else "Low"
        
        final_rating = "HOLD"
        if bias == "Bullish" and probability > 70 and risk != "High": final_rating = "STRONG BUY"
        elif bias == "Bullish": final_rating = "BUY"
        elif bias == "Bearish" or risk == "High": final_rating = "SELL"

        targets = f"${price*(1-expected_move_pct/100):.2f} - ${price*(1+expected_move_pct/100):.2f}"

        return { 
            "ticker": ticker, 
            "price": f"${price:.2f}",
            "raw_price": price,
            "final_score": final_rating, 
            "data_source": "FINNHUB_LIVE" if not is_sim else "BACKUP",
            "news_sentiment": news_sentiment,
            "trade_bias": bias,
            "probability": f"{probability:.0f}%",
            "scenario": scenario,
            "expected_move": f"+/- {expected_move_pct:.2f}%",
            "risk_level": risk,
            "regime": regime,
            "key_catalyst": catalyst,
            "targets": targets
        }
    except Exception as e:
        return { "ticker": ticker, "price": "N/A", "final_score": "HOLD", "error": str(e) }

def get_related_tickers(ticker):
    if ticker in SECTOR_PEERS: return SECTOR_PEERS[ticker]
    for sector, stocks in SECTOR_MAP.items():
        if ticker in stocks: return [s for s in stocks if s != ticker][:4]
    return ["SPY", "QQQ", "IWM", "DIA"]

async def update_event_calendar():
    while True:
        try:
            start = datetime.now().strftime("%Y-%m-%d")
            end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            ipo_url = f"https://finnhub.io/api/v1/calendar/ipo?from={start}&to={end}&token={FINNHUB_KEY}"
            r_ipo = requests.get(ipo_url)
            if r_ipo.status_code == 200:
                data = r_ipo.json()
                if "ipoCalendar" in data: EVENT_CACHE["ipos"] = data["ipoCalendar"][:5]
            earn_url = f"https://finnhub.io/api/v1/calendar/earnings?from={start}&to={end}&token={FINNHUB_KEY}"
            r_earn = requests.get(earn_url)
            if r_earn.status_code == 200:
                data = r_earn.json()
                if "earningsCalendar" in data: EVENT_CACHE["earnings"] = data["earningsCalendar"][:5]
            next_month = (datetime.now() + timedelta(days=30)).strftime("%B")
            EVENT_CACHE["economic"] = [
                {"event": "FOMC Rate Decision", "date": f"Est. {next_month} 15th", "impact": "High"},
                {"event": "CPI Inflation Data", "date": f"Est. {next_month} 10th", "impact": "High"}
            ]
        except: pass
        await asyncio.sleep(3600)

async def update_market_scanner():
    while True:
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futs = {executor.submit(analyze_stock, s): s for s in MARKET_UNIVERSE}
            for f in concurrent.futures.as_completed(futs): results.append(f.result())
        try:
            buys = [x for x in results if x.get('final_score') in ["STRONG BUY", "BUY"]]
            buys.sort(key=lambda x: float(x.get('probability', '0%').strip('%')), reverse=True)
            SERVER_CACHE["buys"] = buys[:5]
            cheap = [x for x in results if x.get('raw_price', 999) < 50 and x.get('final_score') != "SELL"]
            cheap.sort(key=lambda x: float(x.get('probability', '0%').strip('%')), reverse=True)
            SERVER_CACHE["cheap"] = cheap[:5]
            buy_tickers = [b['ticker'] for b in SERVER_CACHE["buys"]]
            sells = [x for x in results if (x.get('trade_bias') == "Bearish" or x.get('risk_level') == "High")]
            sells = [s for s in sells if s['ticker'] not in buy_tickers]
            sells.sort(key=lambda x: x.get('risk_level') == "High", reverse=True)
            SERVER_CACHE["sells"] = sells[:5]
        except: pass
        await asyncio.sleep(900)

# --- ENDPOINTS ---
@app.get("/api/signals")
def get_signals(ticker: str = "NVDA"):
    main_res = analyze_stock(ticker.upper())
    results = [main_res]
    peers = get_related_tickers(ticker.upper())
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futs = {executor.submit(analyze_stock, p): p for p in peers}
        for f in concurrent.futures.as_completed(futs): results.append(f.result())
    return results

@app.get("/api/scanner")
def get_scanner(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.get("/api/events")
def get_events(): return EVENT_CACHE

# --- LEGISLATION ENDPOINT (FIXED) ---
@app.get("/api/legislation")
def get_legislation():
    # enhance the static data with live "affected_stocks" lists
    enhanced_legislation = []
    
    for bill in STATIC_LEGISLATION:
        bill_data = bill.copy()
        sector = bill.get("sector")
        # Lookup stocks in the map, default to empty list if sector missing
        affected = SECTOR_MAP.get(sector, [])
        bill_data["affected_stocks"] = affected
        enhanced_legislation.append(bill_data)
        
    return enhanced_legislation

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