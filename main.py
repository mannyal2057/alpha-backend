import os
import random
import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# --- CONFIGURATION ---
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
CONGRESS_KEY = os.getenv("CONGRESS_KEY", "").strip()

# --- CACHE ---
SERVER_CACHE = {
    "buys": [], "cheap": [], "sells": [], 
    "legislation": [], "status": "Initializing"
}

# --- 1. SECTOR DEFINITIONS ---
# Used for Dynamic "Bill Hunting"
SECTOR_DATABASE = { 
    "AI_TECH":     ["NVDA", "AMD", "MSFT", "PLTR", "AI", "SMCI", "AVGO", "CRWD"], 
    "CRYPTO":      ["COIN", "HOOD", "MARA", "MSTR", "CLSK", "BITO"], 
    "DEFENSE":     ["LMT", "RTX", "BA", "NOC", "GD", "PLTR", "KTOS"], 
    "EV_AUTO":     ["TSLA", "RIVN", "F", "GM", "LCID", "ON", "QS"], 
    "FINANCE":     ["JPM", "BAC", "GS", "V", "MA", "PYPL", "SOFI"],
    "ENERGY":      ["XOM", "CVX", "OXY", "KMI", "VLO", "HAL"],
    "NUCLEAR":     ["CCJ", "URA", "LEU", "BWXT"],
    "PHARMA":      ["LLY", "NVO", "PFE", "MRK", "JNJ", "ABBV"],
    "CANNABIS":    ["TLRY", "CGC", "MSOS"],
    "REAL_ESTATE": ["O", "AMT", "PLD", "SPG"],
    "SEMIS":       ["TSM", "QCOM", "TXN", "MU", "INTC"]
}

FIXED_WATCHLIST = ["GOOGL", "META", "NFLX", "TMUS", "DIS", "VZ", "CMCSA", "FOXA", "T", "WBD"]

# --- 2. KEYWORDS ---
KEYWORDS = {
    "AI_TECH":     ["artificial intelligence", "computational", "cyber", "privacy", "semiconductor", "section 230", "algorithm"],
    "CRYPTO":      ["digital asset", "blockchain", "bitcoin", "stablecoin", "crypto", "ledger"],
    "DEFENSE":     ["defense", "military", "weapon", "national security", "ukraine", "israel", "taiwan", "drone"],
    "EV_AUTO":     ["electric vehicle", "battery", "charging", "emission", "epa", "am radio", "autonomous"],
    "FINANCE":     ["bank", "federal reserve", "interest rate", "sec ", "inflation", "credit card", "basel"],
    "ENERGY":      ["oil", "gas", "pipeline", "drilling", "carbon", "fracking", "lng"],
    "NUCLEAR":     ["nuclear", "uranium", "fission", "reactor", "atomic"],
    "PHARMA":      ["drug", "medicine", "fda", "medicare", "health", "insulin", "pharmacy"],
    "CANNABIS":    ["marijuana", "cannabis", "weed", "schedule iii", "banking", "safe banking"],
    "REAL_ESTATE": ["housing", "mortgage", "rent", "zoning", "property tax"],
    "SEMIS":       ["chips", "wafer", "foundry", "science act"]
}

# --- 3. FAIL-SAFE PRICES (UPDATED) ---
# Added QS, LCID, SOFI with accurate prices so they don't default to $50
FAILSAFE_DATA = { 
    # Tech / AI
    "NVDA": [185.0, 1.4], "MSFT": [460.0, 0.9], "AMD": [230.0, 1.4], "GOOGL": [178.0, 1.2],
    "META": [595.0, 1.5], "NFLX": [885.0, 2.1], "TMUS": [188.0, 0.8], "DIS": [96.0, 1.1],
    "PLTR": [170.0, 1.5], "AI": [13.0, 1.8], "AVGO": [1050.0, 1.1], "CRWD": [300.0, 1.5],
    
    # EV / Auto (FIXED)
    "TSLA": [415.0, 2.2], "RIVN": [10.5, 2.8], "LCID": [3.50, 3.0], "QS": [10.64, 2.5],
    "F": [11.5, 1.1], "GM": [45.0, 1.2], "ON": [70.0, 1.8],

    # Comm Services / Value
    "VZ": [41.5, 0.5], "CMCSA": [42.0, 0.9], "FOXA": [43.0, 1.1], "T": [22.5, 0.4], 
    "WBD": [8.5, 2.5], "CSCO": [48.0, 0.6], "AAL": [14.0, 1.5], "CCL": [16.0, 1.8],

    # Crypto / Finance
    "COIN": [310.0, 2.5], "HOOD": [35.0, 1.4], "MARA": [20.0, 4.0], "MSTR": [350.0, 3.0],
    "SOFI": [14.0, 1.8], "PYPL": [60.0, 1.2], "BAC": [35.0, 0.9],

    # Energy / Nuclear
    "XOM": [115.0, 0.8], "CCJ": [55.0, 2.0], "URA": [30.0, 1.5], "OXY": [58.0, 1.0],

    # Pharma / Cannabis
    "LLY": [800.0, 1.1], "PFE": [25.0, 0.6], "TLRY": [1.80, 4.0], "CGC": [3.50, 5.0]
}

class PriceRequest(BaseModel): tickers: list[str]

# --- APP STARTUP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider Accurate Pricing v2.2")
    asyncio.create_task(update_market_scanner())
    asyncio.create_task(update_legislation_feed())
    yield

app = FastAPI(title="AlphaInsider", version="Live.2.2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

async def get_sponsor_details(client, congress, bill_type, bill_number):
    try:
        url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type.lower()}/{bill_number}?api_key={CONGRESS_KEY}&format=json"
        resp = await client.get(url, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            sponsors = data.get('bill', {}).get('sponsors', [])
            if sponsors: return sponsors[0].get('name', 'See Text').split(',')[0]
    except: pass
    return "See Text"

# --- 1. LEGISLATION FEED (Wide Net) ---
async def update_legislation_feed():
    while True:
        try:
            if not CONGRESS_KEY:
                await asyncio.sleep(60)
                continue

            url = f"https://api.congress.gov/v3/bill?limit=250&sort=updateDate+desc&api_key={CONGRESS_KEY}&format=json"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=20.0)
                if resp.status_code == 200:
                    data = resp.json()
                    bills = data.get("bills", [])
                    processed_bills = []
                    cutoff = datetime.now() - timedelta(days=90)
                    
                    for bill in bills:
                        try:
                            b_date = datetime.strptime(bill.get("updateDate", "") or bill.get("introducedDate", ""), "%Y-%m-%d")
                        except: continue
                        if b_date < cutoff: continue

                        title = bill.get("title", "").lower()
                        if not title: continue
                        
                        detected_sector = "GENERAL"
                        market_bias = "Neutral"
                        weight = 10 
                        
                        for sector, tags in KEYWORDS.items():
                            if any(tag in title for tag in tags):
                                detected_sector = sector
                                if any(x in title for x in ["authorize", "fund", "support", "grant"]):
                                    market_bias = "Bullish (Funding)"
                                    weight = 20
                                elif any(x in title for x in ["ban", "restrict", "prohibit", "sanction"]):
                                    market_bias = "Bearish (Regulation)"
                                    weight = -20
                                else: market_bias = "Watchlist"
                                break
                        
                        if detected_sector != "GENERAL":
                            affected = SECTOR_DATABASE.get(detected_sector, [])
                            processed_bills.append({
                                "id": f"{bill.get('type','BILL')} {bill.get('number')}",
                                "name": bill.get("title", "Untitled").title(),
                                "impact": market_bias,
                                "sector": detected_sector,
                                "weight": weight,
                                "affected_stocks": affected,
                                "date": bill.get("updateDate")
                            })
                    
                    SERVER_CACHE["legislation"] = processed_bills
        except: pass
        await asyncio.sleep(7200)

# --- 2. MARKET DATA ENGINE ---
async def get_market_price(ticker):
    # Try Live API first
    if FINNHUB_KEY:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=2.0)
            if r.status_code == 200:
                d = r.json()
                if d.get('c', 0) > 0:
                    return d['c'], d['dp'], (d['h']-d['l'])/d['c']*100, False
        except: pass
    
    # Fallback to Accurate Failsafe
    base = FAILSAFE_DATA.get(ticker, [50.0, 1.5]) # Default 50 if truly unknown
    p = base[0] * random.uniform(0.995, 1.005)
    return p, base[1], base[1]*1.2, True

# --- 3. SIGNAL STACK ---
async def analyze_stock(ticker):
    price, change, vol, is_sim = await get_market_price(ticker)
    edge_score = 0
    catalyst = "None"
    
    for bill in SERVER_CACHE.get("legislation", []):
        if ticker in bill["affected_stocks"]:
            edge_score += bill["weight"] * 2
            catalyst = f"Bill: {bill['id']}"
            
    total_score = edge_score + (change * 10)
    bias = "Bullish" if total_score > 0 else "Bearish"
    
    return {
        "ticker": ticker,
        "price": f"${price:.2f}",
        "raw_price": price,
        "final_score": "BUY" if total_score > 25 else "SELL" if total_score < -25 else "HOLD",
        "trade_bias": bias,
        "probability": f"{50 + min(abs(total_score), 45):.0f}%",
        "expected_move": f"+/- {vol*1.2:.2f}%",
        "risk_level": "High" if vol > 2.5 else "Medium",
        "key_catalyst": catalyst
    }

async def update_market_scanner():
    while True:
        try:
            stocks = set(FIXED_WATCHLIST)
            for b in SERVER_CACHE.get("legislation", []):
                stocks.update(b.get("affected_stocks", []))
            
            tasks = [analyze_stock(t) for t in list(stocks)]
            if tasks:
                results = await asyncio.gather(*tasks)
                
                buys = [x for x in results if x['trade_bias'] == "Bullish"]
                buys.sort(key=lambda x: x['raw_price'], reverse=True) 
                SERVER_CACHE["buys"] = buys[:6]

                cheap = [x for x in results if x.get('raw_price') < 55]
                cheap.sort(key=lambda x: (x['final_score'] == 'BUY'), reverse=True)
                SERVER_CACHE["cheap"] = cheap[:6]

                sells = [x for x in results if x['trade_bias'] == "Bearish"]
                SERVER_CACHE["sells"] = sells[:6]
        except: pass
        await asyncio.sleep(60)

# --- ENDPOINTS ---
@app.get("/api/legislation")
def get_legislation(): return SERVER_CACHE["legislation"]

@app.get("/api/scanner")
def get_scanner(mode: str = "buys"): return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
async def get_signals(ticker: str = "NVDA"):
    return [await analyze_stock(ticker.upper())]

@app.post("/api/prices")
async def get_prices(req: PriceRequest): 
    response = {}
    for t in req.tickers:
        p, _, _, _ = await get_market_price(t)
        response[t] = p
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)