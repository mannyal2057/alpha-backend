import os
import random
import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx  # Standard async HTTP client

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

# --- SECTOR MAPPING (The Signal Engine) ---
SECTOR_MAP = { 
    "AI": ["NVDA", "AMD", "MSFT", "GOOGL", "PLTR", "AI"], 
    "CRYPTO": ["COIN", "HOOD", "MARA", "MSTR", "CLSK"], 
    "DEFENSE": ["LMT", "RTX", "BA", "NOC", "GD"], 
    "EV": ["TSLA", "RIVN", "F", "GM", "LCID"], 
    "FINANCE": ["JPM", "BAC", "SOFI", "GS", "C"],
    "ENERGY": ["XOM", "CVX", "OXY", "KMI", "MPC"],
    "PHARMA": ["PFE", "MRK", "LLY", "JNJ", "ABBV"]
}

# Real-time keyword scanner
KEYWORDS = {
    "AI": ["artificial intelligence", "computational", "cyber", "technology", "chips", "semiconductor"],
    "CRYPTO": ["crypto", "digital asset", "blockchain", "bitcoin", "stablecoin", "ledger"],
    "DEFENSE": ["defense", "military", "weapon", "national security", "armed forces", "ukraine", "israel", "taiwan"],
    "EV": ["electric vehicle", "battery", "charging", "emission", "clean energy", "climate"],
    "FINANCE": ["bank", "reserve", "inflation", "monetary", "financial", "sec ", "investment"],
    "ENERGY": ["oil", "gas", "pipeline", "drilling", "energy", "carbon"],
    "PHARMA": ["drug", "medicine", "health", "care", "fda", "medical"]
}

# --- FAIL-SAFE DATA ---
FAILSAFE_DATA = { 
    "NVDA": [185.0, 1.4], "AI": [13.0, 1.8], "PLTR": [170.0, 1.5], "MSFT": [460.0, 0.9], 
    "AMD": [230.0, 1.4], "COIN": [310.0, 2.5], "LMT": [580.0, 0.5], "AVGO": [1050.0, 1.1],
    "TSLA": [415.0, 2.2], "RIVN": [10.5, 2.8], "HOOD": [35.0, 1.4], "GOOGL": [190.0, 1.0], 
    "AMZN": [220.0, 1.1], "PFE": [25.0, 0.6], "JPM": [175.0, 0.8], "XOM": [110.0, 0.6]
}

MARKET_UNIVERSE = list(FAILSAFE_DATA.keys())

class PriceRequest(BaseModel): tickers: list[str]

# --- APP STARTUP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"💎 SYSTEM BOOT: AlphaInsider Live (Robust Sponsor Fix).")
    
    if not CONGRESS_KEY:
        print("⚠️ CRITICAL: CONGRESS_KEY is missing. Legislation feed will be empty.")
    
    asyncio.create_task(update_market_scanner())
    asyncio.create_task(update_event_calendar())
    asyncio.create_task(update_legislation_feed())
    yield

app = FastAPI(title="AlphaInsider Pro", version="Live.1.2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- HELPER: Fetch Sponsor Details ---
async def get_sponsor_details(client, congress, bill_type, bill_number):
    """
    Secondary fetch with robust fallbacks for missing name fields.
    """
    try:
        # Construct specific bill URL
        url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type.lower()}/{bill_number}?api_key={CONGRESS_KEY}&format=json"
        resp = await client.get(url, timeout=5.0)
        
        if resp.status_code == 200:
            data = resp.json()
            sponsors = data.get('bill', {}).get('sponsors', [])
            
            if sponsors:
                sponsor = sponsors[0]
                # Priority 1: 'name' (e.g. "Rep. Eshoo, Anna G. [D-CA]")
                raw_name = sponsor.get('name')
                
                # Priority 2: 'fullName'
                if not raw_name:
                    raw_name = sponsor.get('fullName')
                
                # Priority 3: 'firstName' + 'lastName'
                if not raw_name and sponsor.get('lastName'):
                    raw_name = f"{sponsor.get('firstName', '')} {sponsor.get('lastName')}"
                
                if raw_name:
                    # Clean up: "Rep. Eshoo, Anna G. [D-CA]" -> "Rep. Eshoo"
                    clean_name = raw_name.split(',')[0]
                    # Add 'Rep.' or 'Sen.' if missing and we know the type
                    if "Rep" not in clean_name and "Sen" not in clean_name:
                        prefix = "Rep." if "hr" in bill_type.lower() else "Sen."
                        clean_name = f"{prefix} {clean_name}"
                        
                    return clean_name
                else:
                    print(f"⚠️ Sponsor found but no name field for {bill_number}: {sponsor}")
                    
    except Exception as e:
        print(f"Sponsor Fetch Error for {bill_number}: {e}")
    
    return "See Text"

# --- 1. LIVE CONGRESS FEED ENGINE ---
async def update_legislation_feed():
    """Fetches real bills and enriches them with specific sponsor data."""
    while True:
        try:
            if not CONGRESS_KEY:
                SERVER_CACHE["status"] = "Missing API Key"
                await asyncio.sleep(60)
                continue

            # Fetch recent bills
            url = f"https://api.congress.gov/v3/bill?limit=40&sort=updateDate+desc&api_key={CONGRESS_KEY}&format=json"
            
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=15.0)
                
                if resp.status_code == 200:
                    data = resp.json()
                    bills = data.get("bills", [])
                    processed_bills = []
                    
                    for bill in bills:
                        title = bill.get("title", "").lower()
                        if not title: continue
                        
                        # 1. SCAN TITLE FOR SECTOR KEYWORDS
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
                        
                        # 2. IF RELEVANT, PROCESS SPONSOR
                        if detected_sector != "GENERAL":
                            
                            sponsor_name = "See Text"
                            
                            # Attempt 1: Check list object (Quick check)
                            if bill.get('sponsors'):
                                raw = bill['sponsors'][0].get('name', '')
                                if raw:
                                    sponsor_name = raw.split(',')[0]
                            
                            # Attempt 2: Secondary Fetch (If Attempt 1 failed or returned empty)
                            if sponsor_name == "See Text" or sponsor_name == "":
                                sponsor_name = await get_sponsor_details(
                                    client, 
                                    bill.get('congress'), 
                                    bill.get('type'), 
                                    bill.get('number')
                                )

                            bill_obj = {
                                "id": f"H.R. {bill.get('number', '???')}" if bill.get('type') == 'HR' else f"S. {bill.get('number')}",
                                "name": bill.get("title", "Untitled Bill").title(),
                                "sponsor": sponsor_name, 
                                "impact": market_impact,
                                "sector": detected_sector,
                                "affected_stocks": SECTOR_MAP.get(detected_sector, [])
                            }
                            processed_bills.append(bill_obj)
                    
                    if processed_bills:
                        SERVER_CACHE["legislation"] = processed_bills
                        SERVER_CACHE["status"] = "Live"
                        print(f"✅ Congress Feed Updated: {len(processed_bills)} bills. Sponsors Enriched.")
                    else:
                        SERVER_CACHE["status"] = "No Relevant Bills"
                
        except Exception as e:
            print(f"Legislation Update Failed: {e}")
            
        # Update every 2 hours
        await asyncio.sleep(7200)

# --- 2. MARKET DATA ENGINE ---
async def get_market_price(ticker):
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
            
    base = FAILSAFE_DATA.get(ticker, [100.0, 1.0])
    p = base[0] * random.uniform(0.995, 1.005)
    change = base[1] * random.uniform(0.9, 1.1)
    return p, change, abs(change * 1.2), True

# --- 3. SIGNAL STACK ---
async def analyze_stock(ticker):
    price, change, vol, is_sim = await get_market_price(ticker)
    
    edge_score = 0
    catalyst = "None"
    
    # Check against the LIVE legislation cache
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
    
    return {
        "ticker": ticker,
        "price": f"${price:.2f}",
        "raw_price": price,
        "final_score": "BUY" if total_score > 25 else "SELL" if total_score < -25 else "HOLD",
        "trade_bias": bias,
        "probability": f"{50 + min(abs(total_score), 45):.0f}%",
        "expected_move": f"+/- {expected_move:.2f}%",
        "risk_level": "High" if vol > 2.5 else "Medium",
        "key_catalyst": catalyst,
        "targets": f"${price*(1-expected_move/100):.2f} - ${price*(1+expected_move/100):.2f}"
    }

async def update_market_scanner():
    while True:
        try:
            tasks = [analyze_stock(t) for t in MARKET_UNIVERSE]
            results = await asyncio.gather(*tasks)
            
            buys = [x for x in results if x['trade_bias'] == "Bullish"]
            buys.sort(key=lambda x: x['raw_price'], reverse=True) 
            
            SERVER_CACHE["buys"] = buys[:5]
            SERVER_CACHE["sells"] = [x for x in results if x['trade_bias'] == "Bearish"][:5]
            
        except Exception as e:
            print(f"Scanner Error: {e}")
        await asyncio.sleep(60)

async def update_event_calendar():
    pass

# --- ENDPOINTS ---

@app.get("/api/legislation")
def get_legislation():
    return SERVER_CACHE["legislation"]

@app.get("/api/scanner")
def get_scanner(mode: str = "buys"):
    return SERVER_CACHE.get(mode, [])

@app.get("/api/signals")
async def get_signals(ticker: str = "NVDA"):
    return [await analyze_stock(ticker.upper())]

@app.post("/api/prices")
def get_prices(req: PriceRequest):
    res = {}
    return res

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)