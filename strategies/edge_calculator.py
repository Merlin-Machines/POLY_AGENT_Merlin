import math, logging
from dataclasses import dataclass
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CFG
log = logging.getLogger(__name__)
ANNUAL_VOL = {"BTC":0.65,"ETH":0.80}

@dataclass
class EdgeResult:
    market: object; current_price: float; our_prob_yes: float; market_prob_yes: float
    edge_yes: float; edge_no: float; best_side: str; best_edge: float
    best_token_id: str; best_market_price: float; trade_size: float; confidence: str; reasoning: str

def _ncdf(x):
    s=1 if x>=0 else -1; x=abs(x); t=1/(1+0.2316419*x)
    c=(0.31938153,-0.356563782,1.781477937,-1.821255978,1.330274429)
    p=sum(c[i]*t**(i+1) for i in range(5))
    cdf=1-(1/math.sqrt(2*math.pi))*math.exp(-x*x/2)*p
    return cdf if s>0 else 1-cdf

def _prob(price,thresh,direction,hours,symbol):
    vol=ANNUAL_VOL.get(symbol,0.70); T=max(hours/8760,1/8760)
    d2=math.log(price/thresh)/(vol*math.sqrt(T))
    p=_ncdf(d2) if direction=="above" else 1-_ncdf(d2)
    return max(0.05,min(0.95,p))

def _size(edge,price):
    if price>=1 or price<=0: return CFG.min_trade_usdc
    return round(max(CFG.min_trade_usdc,min(CFG.max_trade_usdc,(edge/(1-price))*CFG.kelly_fraction*500)),2)

def calculate_edge(market,current_price):
    if not (CFG.min_hours_to_expiry<=market.hours_to_expiry<=CFG.max_hours_to_expiry): return None
    if market.liquidity<CFG.min_liquidity: return None
    op=_prob(current_price,market.threshold,market.direction,market.hours_to_expiry,market.symbol)
    if not (CFG.min_our_prob<=op<=CFG.max_our_prob): return None
    ey=op-market.yes_price; en=(1-op)-market.no_price
    if ey>=en: side,edge,price,tid="YES",ey,market.yes_price,market.yes_token_id
    else: side,edge,price,tid="NO",en,market.no_price,market.no_token_id
    if edge<CFG.min_edge: return None
    conf="HIGH" if edge>=0.10 and market.liquidity>=5000 else "MEDIUM" if edge>=0.06 else "LOW"
    dist=((current_price-market.threshold)/market.threshold)*100
    r=f"{market.symbol} ${current_price:,.0f} vs ${market.threshold:,.0f} ({dist:+.1f}%) {market.hours_to_expiry:.1f}h prob {op:.1%} vs {market.yes_price:.1%} edge {edge:.1%}"
    return EdgeResult(market=market,current_price=current_price,our_prob_yes=op,market_prob_yes=market.yes_price,
        edge_yes=ey,edge_no=en,best_side=side,best_edge=edge,best_token_id=tid,
        best_market_price=price,trade_size=_size(edge,price),confidence=conf,reasoning=r)

def find_best_opportunities(markets,prices,max_results=5):
    results=[]
    for m in markets:
        price=prices.get(m.symbol)
        if not price: continue
        r=calculate_edge(m,price)
        if r: results.append(r); log.info(f"{r.confidence} | {r.reasoning}")
    results.sort(key=lambda x:(x.confidence=="HIGH",x.best_edge),reverse=True)
    return results[:max_results]
