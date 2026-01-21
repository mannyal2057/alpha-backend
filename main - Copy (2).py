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
POLYGON_KEY = os.getenv("POLYGON_API_KEY", "").strip()
CONGRESS_KEY = os.getenv("CONGRESS_KEY", "").strip()

# --- CACHE & STATE ---
SERVER_CACHE = {
    "buys": [], 
    "cheap": [], 
    "sells": [], 
    "legislation": [], 
    "last_update": None,
    "status": "Initializing"
}
EVENT_CACHE = {"ipos": [], "earnings": [], "economic": []}

# --- 1. SECTOR MAPPING (S&P 500 Comm Services Focus) ---
# We map these specific stocks to sectors that align with legislation keywords
SECTOR_MAP = { 
    "TECH": ["GOOGL", "META"],             # Alphabet, Meta
    "MEDIA": ["NFLX", "DIS", "WBD", "FOXA", "CMCSA"], # Netflix, Disney, Warner, Fox, Comcast
    "TELECOM": ["T", "VZ", "TMUS"]         # AT&T, Verizon, T-Mobile
}

# --- 2. KEYWORDS (Catalyst Triggers) ---
# Expanded to catch bills affecting these specific companies
KEYWORDS = {
    "TECH": ["artificial intelligence", "privacy", "data", "algorithm", "social media", "section 230", "antitrust"],
    "MEDIA": ["streaming", "copyright", "broadcasting", "sports", "entertainment", "intellectual property", "ticket"],
    "TELECOM": ["broadband", "spectrum", "fcc", "internet", "5g", "net neutrality", "connectivity"]
}

# --- 3. FAIL-SAFE DATA (S&P 500 Comm Services Universe) ---
# Used if live API limit is reached. Prices updated to approx current market values.
FAILSAFE_DATA = { 
    # TOP 5 (BEST/LARGEST)
    "GOOGL": [178.0, 1.2],  # Alphabet
    "META":  [595.0, 1.5],  # Meta Platforms
    "NFLX":  [885.0, 2.1],  # Netflix
    "TMUS":  [188.0, 0.8],  # T-Mobile
    "DIS":   [96.0, 1.1],   # Disney

    # UNDER $50 (VALUE/CHEAP)
    "VZ":    [41.5, 0.5],   # Verizon
    "CMCSA": [42.0, 0.9],   # Comcast
    "FOXA":  [43.0, 1.1],   # Fox Corp
    "T":     [22.5, 0.4],   # AT&T
    "WBD":   [8.5, 2.5]     # Warner Bros Discovery
}

MARKET_UNIVERSE = list(FAILSAFE_DATA.keys())

class PriceRequest(BaseModel): tickers: list[str]

# --- APP STARTUP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider S&P500 Comm Services Edition.")
    
    if not CONGRESS_KEY:
        print("⚠️ CRITICAL: CONGRESS_KEY is missing. Legislation feed will be empty.")
    
    asyncio.create_task(update_market_scanner())
    asyncio.create_task(update_legislation_feed())
    yield

app = FastAPI(title="AlphaInsider CommSvcs", version="Live.1.5", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- HELPER: Fetch Sponsor Details ---
async def get_sponsor_details(client, congress, bill_type, bill_number):
    try:
        url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type.lower()}/{bill_number}?api_key={CONGRESS_KEY}&format=json"
        resp = await client.get(url, timeout=5.0)
        
        if resp.status_code == 200:
            data = resp.json()
            sponsors = data.get('bill', {}).get('sponsors', [])
            if sponsors:
                sponsor = sponsors[0]
                raw_name = sponsor.get('name') or sponsor.get('fullName')
                if not raw_name and sponsor.get('lastName'):
                    raw_name = f"{sponsor.get('firstName', '')} {sponsor.get('lastName')}"
                if raw_name:
                    clean_name = raw_name.split(',')[0]
                    if "Rep" not in clean_name and "Sen" not in clean_name:
                        prefix = "Rep." if "hr" in bill_type.lower() else "Sen."
                        clean_name = f"{prefix} {clean_name}"
                    return clean_name
    except: pass
    return "See Text"

# --- 1. LEGISLATION FEED (Freshness Filter) ---
async def update_legislation_feed():
    while True:
        try:
            if not CONGRESS_KEY:
                SERVER_CACHE["status"] = "Missing API Key"
                await asyncio.sleep(60)
                continue

            url = f"https://api.congress.gov/v3/bill?limit=60&sort=updateDate+desc&api_key={CONGRESS_KEY}&format=json"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    bills = data.get("bills", [])
                    processed_bills = []
                    
                    # 30-Day Freshness Cutoff
                    cutoff_date = datetime.now() - timedelta(days=30)
                    
                    for bill in bills:
                        raw_date = bill.get("updateDate", "") or bill.get("introducedDate", "")
                        try:
                            bill_date = datetime.strptime(raw_date, "%Y-%m-%d")
                        except: continue

                        if bill_date < cutoff_date:
                            continue 

                        title = bill.get("title", "").lower()
                        if not title: continue
                        
                        detected_sector = "GENERAL"
                        market_impact = "Neutral"
                        
                        for sector, tags in KEYWORDS.items():
                            if any(tag in title for tag in tags):
                                detected_sector = sector
                                if any(x in title for x in ["authorize", "fund", "support", "grant"]):
                                    market_impact = "Bullish (Funding)"
                                elif any(x in title for x in ["ban", "restrict", "prohibit", "sanction"]):
                                    market_impact = "Bearish (Restriction)"
                                else:
                                    market_impact = "Watchlist (Regulation)"
                                break
                        
                        if detected_sector != "GENERAL":
                            sponsor_name = "See Text"
                            if bill.get('sponsors'):
                                raw = bill['sponsors'][0].get('name', '')
                                if raw: sponsor_name = raw.split(',')[0]
                            
                            if sponsor_name == "See Text" or sponsor_name == "":
                                sponsor_name = await get_sponsor_details(client, bill.get('congress'), bill.get('type'), bill.get('number'))

                            bill_obj = {
                                "id": f"H.R. {bill.get('number', '???')}" if bill.get('type') == 'HR' else f"S. {bill.get('number')}",
                                "name": bill.get("title", "Untitled Bill").title(),
                                "sponsor": sponsor_name, 
                                "impact": market_impact,
                                "sector": detected_sector,
                                "affected_stocks": SECTOR_MAP.get(detected_sector, []),
                                "date": raw_date
                            }
                            processed_bills.append(bill_obj)
                    
                    SERVER_CACHE["legislation"] = processed_bills
                    print(f"✅ Congress Feed Updated: {len(processed_bills)} active fresh bills.")
                
        except Exception as e:
            print(f"Legislation Update Failed: {e}")
        await asyncio.sleep(7200)

# --- 2. MARKET DATA ENGINE ---
async def get_market_price(ticker):
    # Try Live API
    if FINNHUB_KEY:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=2.0)
            if r.status_code == 200:
                d = r.json()
                if d.get('c', 0) > 0:
                    day_range = (d['h'] - d['l']) / d['c'] * 100
                    return d['c'], d['dp'], day_range, False
        except: pass
            
    # Fallback to Simulation
    base = FAILSAFE_DATA.get(ticker, [100.0, 1.0])
    p = base[0] * random.uniform(0.995, 1.005)
    change = base[1] * random.uniform(0.9, 1.1)
    return p, change, abs(change * 1.2), True

# --- 3. SIGNAL STACK ---
async def analyze_stock(ticker):
    price, change, vol, is_sim = await get_market_price(ticker)
    
    edge_score = 0
    catalyst = "None"
    
    active_sectors = [b['sector'] for b in SERVER_CACHE.get("legislation", [])]
    
    my_sector = "Unknown"
    for sec, stocks in SECTOR_MAP.items():
        if ticker in stocks:
            my_sector = sec
            break
            
    if my_sector in active_sectors:
        edge_score += 30
        catalyst = f"Live Bill in {my_sector}"

    total_score = edge_score + (change * 10)
    bias = "Bullish" if total_score > 0 else "Bearish"
    expected_move = vol * 1.2 
    
    risk_level = "High" if vol > 2.5 else "Medium"
    
    # Cheap Stock Bonus (Up to $55 to catch those near the border)
    if price < 55 and vol < 2.0 and bias == "Bullish":
        total_score += 20 
    
    return {
        "ticker": ticker,
        "price": f"${price:.2f}",
        "raw_price": price,
        "final_score": "BUY" if total_score > 25 else "SELL" if total_score < -25 else "HOLD",
        "trade_bias": bias,
        "probability": f"{50 + min(abs(total_score), 45):.0f}%",
        "expected_move": f"+/- {expected_move:.2f}%",
        "risk_level": risk_level,
        "key_catalyst": catalyst,
        "targets": f"${price*(1-expected_move/100):.2f} - ${price*(1+expected_move/100):.2f}"
    }

async def update_market_scanner():
    while True:
        try:
            tasks = [analyze_stock(t) for t in MARKET_UNIVERSE]
            results = await asyncio.gather(*tasks)
            
            # Buys
            buys = [x for x in results if x['trade_bias'] == "Bullish"]
            buys.sort(key=lambda x: x['raw_price'], reverse=True) 
            SERVER_CACHE["buys"] = buys[:5]

            # Cheap Stocks (Strictly under $55)
            cheap = [x for x in results if x.get('raw_price', 999) < 55]
            # Prioritize BUYs, then HOLDs
            cheap.sort(key=lambda x: (x['final_score'] == 'BUY', x['final_score'] == 'HOLD'), reverse=True)
            SERVER_CACHE["cheap"] = cheap[:5]

            # Sells
            sells = [x for x in results if x['trade_bias'] == "Bearish"]
            SERVER_CACHE["sells"] = sells[:5]
            
        except Exception as e:
            print(f"Scanner Error: {e}")
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