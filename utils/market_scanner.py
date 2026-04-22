import re, time, logging, requests, json
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
log = logging.getLogger(__name__)
_cache = ([], 0.0)

@dataclass
class ParsedMarket:
    market_id: str; condition_id: str; question: str; symbol: str
    threshold: float; direction: str; yes_token_id: str; no_token_id: str
    yes_price: float; no_price: float; liquidity: float; volume: float
    end_date: Optional[object]; hours_to_expiry: float

def fetch_markets(force=False):
    global _cache
    markets, ts = _cache
    if not force and markets and time.time()-ts < 120: return markets
    try:
        r = requests.get("https://gamma-api.polymarket.com/markets", params={"active":"true","closed":"false","limit":100,"tag_slug":"crypto"}, timeout=12)
        r.raise_for_status(); _cache = (r.json(), time.time()); return _cache[0]
    except Exception as e:
        log.error(f"Fetch failed: {e}"); return markets

def _parse(question):
    q = question.lower()
    sym = "BTC" if "btc" in q or "bitcoin" in q else "ETH" if "eth" in q or "ethereum" in q else None
    if not sym: return None
    direction = "above" if any(w in q for w in ["above","exceed","over","higher"]) else "below" if any(w in q for w in ["below","under","lower"]) else None
    if not direction: return None
    m = re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*([kKmM]?)', question)
    if not m: return None
    val = float(m.group(1).replace(",","")); mult = m.group(2).lower()
    if mult=="k": val*=1000
    if mult=="m": val*=1_000_000
    if sym=="BTC" and not (1000<val<1_000_000): return None
    if sym=="ETH" and not (100<val<100_000): return None
    return sym, val, direction

def _hours(end_str):
    if not end_str: return 999.0
    for fmt in ["%Y-%m-%dT%H:%M:%SZ","%Y-%m-%dT%H:%M:%S.%fZ","%Y-%m-%d"]:
        try:
            end = datetime.strptime(end_str, fmt).replace(tzinfo=timezone.utc)
            return max(0.0,(end-datetime.now(timezone.utc)).total_seconds()/3600)
        except: continue
    return 999.0

def parse_markets(raw):
    out = []
    for m in raw:
        r = _parse(m.get("question",""))
        if not r: continue
        sym, thresh, direction = r
        tids = m.get("clobTokenIds") or []
        if isinstance(tids,str):
            try: tids=json.loads(tids)
            except: tids=[]
        if len(tids)<2: continue
        outcomes=m.get("outcomes",[]); prices=m.get("outcomePrices",[])
        try:
            yi=next((i for i,o in enumerate(outcomes) if o.lower()=="yes"),0)
            ni=next((i for i,o in enumerate(outcomes) if o.lower()=="no"),1)
            yp,np_=float(prices[yi]),float(prices[ni])
        except: yp,np_=0.5,0.5
        if not (0.01<=yp<=0.99): continue
        out.append(ParsedMarket(market_id=m.get("id",""),condition_id=m.get("conditionId",""),
            question=m.get("question",""),symbol=sym,threshold=thresh,direction=direction,
            yes_token_id=tids[0],no_token_id=tids[1],yes_price=yp,no_price=np_,
            liquidity=float(m.get("liquidity") or 0),volume=float(m.get("volume") or 0),
            end_date=None,hours_to_expiry=_hours(m.get("endDate") or m.get("end_date_iso"))))
    log.info(f"Parsed {len(out)} markets"); return out
