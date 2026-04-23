import requests, time, logging, re, json, math, signal, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
(BASE/'logs').mkdir(exist_ok=True)
(BASE/'data').mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(str(BASE/'logs'/'agent.log')), logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

from config import CFG
from agent.executor import TradeExecutor
from agent.polymarket_tool_adapter import PolymarketToolAdapter
from manager import load_live_profile
from agent.poly_btc import PolyBTCRegistry

# City -> NWS station mapping for resolution source matching
CITIES = {
    'new york': {'nws': 'KNYC', 'aliases': ['nyc','new york city','manhattan']},
    'london':   {'nws': 'EGLC', 'aliases': ['london']},
    'chicago':  {'nws': 'KORD', 'aliases': ['chicago']},
    'los angeles': {'nws': 'KLAX', 'aliases': ['la','los angeles']},
    'miami':    {'nws': 'KMIA', 'aliases': ['miami']},
    'seoul':    {'nws': 'RKSS', 'aliases': ['seoul']},
    'tokyo':    {'nws': 'RJTT', 'aliases': ['tokyo']},
}
CITY_COORDS = {
    'new york': (40.71, -74.01), 'london': (51.51, -0.12),
    'chicago': (41.88, -87.63), 'los angeles': (34.05, -118.24),
    'miami': (25.77, -80.19), 'seoul': (37.57, 126.98), 'tokyo': (35.69, 139.69)
}
NEWS_CACHE = {}
POLY_TOOL = PolymarketToolAdapter(timeout=8)

# BTC strategy pack — initialised once at startup; executor wired in Agent.__init__
try:
    POLY_BTC_REGISTRY = PolyBTCRegistry(BASE / 'data')
    log.info('POLY_BTC_REGISTRY | initialised')
except Exception as _pbtc_err:
    POLY_BTC_REGISTRY = None
    log.warning(f'POLY_BTC_REGISTRY | init failed: {_pbtc_err}')


def _load_env():
    env = {}
    env_file = BASE / '.env'
    if not env_file.exists():
        return env
    for line in env_file.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        env[key.strip()] = value.strip()
    return env


def _max_numeric(values):
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    return max(clean) if clean else None


def get_nws_forecast(station):
    try:
        r = requests.get('https://api.weather.gov/stations/'+station+'/observations/latest',
            timeout=8, headers={'User-Agent':'PolyAgent/1.0 contact@poly.ai'})
        if r.status_code != 200: return None
        props = r.json()['properties']
        tc = props.get('temperature',{}).get('value')
        if tc is None: return None
        tf = tc*9/5+32
        return {'temp_f': round(tf,1), 'temp_c': round(tc,1), 'station': station}
    except Exception as e:
        log.debug('NWS failed '+station+': '+str(e))
        return None


def get_noaa_point_forecast(lat, lon):
    try:
        headers = {
            'User-Agent': 'PolyAgent/1.0 contact@poly.ai',
            'Accept': 'application/geo+json',
        }
        points = requests.get(f'https://api.weather.gov/points/{lat},{lon}', timeout=8, headers=headers)
        if points.status_code != 200:
            return None
        forecast_url = points.json().get('properties', {}).get('forecastHourly')
        if not forecast_url:
            return None
        forecast = requests.get(forecast_url, timeout=8, headers=headers)
        if forecast.status_code != 200:
            return None
        periods = forecast.json().get('properties', {}).get('periods') or []
        if not periods:
            return None
        first = periods[0]
        temps = [p.get('temperature') for p in periods]
        today_max = _max_numeric(temps[:12] or temps[:1])
        tomorrow_max = _max_numeric(temps[12:24] or temps[1:13])
        return {
            'temp_f': first.get('temperature'),
            'temp_f_today': today_max,
            'temp_f_tomorrow': tomorrow_max,
            'noaa_short_forecast': first.get('shortForecast', ''),
            'noaa_precip_prob': (first.get('probabilityOfPrecipitation') or {}).get('value'),
            'noaa_wind_speed': first.get('windSpeed', ''),
            'noaa_station_source': 'weather.gov points/hourly',
        }
    except Exception as e:
        log.debug(f'NOAA points failed {lat},{lon}: {str(e)}')
        return None


def get_openmeteo_forecast(lat, lon):
    try:
        url = 'https://api.open-meteo.com/v1/forecast'
        params = {'latitude':lat,'longitude':lon,'daily':'temperature_2m_max,temperature_2m_min',
                  'temperature_unit':'fahrenheit','timezone':'auto','forecast_days':3}
        r = requests.get(url, params=params, timeout=8)
        d = r.json()
        temps = d['daily']['temperature_2m_max']
        return {'temp_f_today': temps[0], 'temp_f_tomorrow': temps[1]}
    except: return None


def get_twc_hourly_forecast(lat, lon, api_key):
    if not api_key:
        return None
    try:
        url = 'https://api.weather.com/v3/wx/forecast/hourly/2day'
        params = {
            'geocode': f'{lat},{lon}',
            'format': 'json',
            'units': 'e',
            'language': 'en-US',
            'apiKey': api_key,
        }
        r = requests.get(url, params=params, timeout=8, headers={'User-Agent': 'PolyAgent/1.0'})
        if r.status_code != 200:
            return None
        data = r.json()
        temps = data.get('temperature') or []
        narratives = data.get('narrative') or []
        precip = data.get('precipChance') or []
        return {
            'twc_temp_f_hourly': temps[0] if temps else None,
            'twc_temp_f_today': _max_numeric(temps[:12] or temps[:1]),
            'twc_temp_f_tomorrow': _max_numeric(temps[12:24] or temps[1:13]),
            'twc_narrative': narratives[0] if narratives else '',
            'twc_precip_chance': precip[0] if precip else None,
        }
    except Exception as e:
        log.debug(f'Weather Company failed {lat},{lon}: {str(e)}')
        return None


def get_weatherapi_rapidapi_forecast(lat, lon, api_key, host='weatherapi-com.p.rapidapi.com'):
    if not api_key:
        return None
    try:
        url = f'https://{host}/forecast.json'
        params = {
            'q': f'{lat},{lon}',
            'days': 2,
        }
        headers = {
            'X-RapidAPI-Key': api_key,
            'X-RapidAPI-Host': host,
            'User-Agent': 'PolyAgent/1.0',
        }
        r = requests.get(url, params=params, headers=headers, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        current = data.get('current') or {}
        forecast_days = (data.get('forecast') or {}).get('forecastday') or []
        today = ((forecast_days[0] or {}).get('day') or {}) if len(forecast_days) >= 1 else {}
        tomorrow = ((forecast_days[1] or {}).get('day') or {}) if len(forecast_days) >= 2 else {}
        return {
            'weatherapi_temp_f': current.get('temp_f'),
            'weatherapi_temp_f_today': today.get('maxtemp_f'),
            'weatherapi_temp_f_tomorrow': tomorrow.get('maxtemp_f'),
            'weatherapi_condition': (current.get('condition') or {}).get('text', ''),
            'weatherapi_precip_in': current.get('precip_in'),
        }
    except Exception as e:
        log.debug(f'WeatherAPI RapidAPI failed {lat},{lon}: {str(e)}')
        return None


def get_weather(city_key):
    city = CITIES.get(city_key, {})
    station = city.get('nws','')
    coords = CITY_COORDS.get(city_key)
    env = _load_env()
    result = {'sources': []}
    nws = get_nws_forecast(station) if station else None
    if nws:
        result.update(nws)
        result['sources'].append('nws-station')
    if coords:
        noaa = get_noaa_point_forecast(*coords)
        if noaa:
            result.update({k: v for k, v in noaa.items() if v is not None})
            result['sources'].append('noaa-point')
        twc = get_twc_hourly_forecast(*coords, env.get('WEATHERCOM_API_KEY', ''))
        if twc:
            result.update({k: v for k, v in twc.items() if v is not None})
            result['sources'].append('weather-company')
        weatherapi = get_weatherapi_rapidapi_forecast(
            *coords,
            env.get('WEATHERAPI_RAPIDAPI_KEY', ''),
            env.get('WEATHERAPI_RAPIDAPI_HOST', 'weatherapi-com.p.rapidapi.com'),
        )
        if weatherapi:
            result.update({k: v for k, v in weatherapi.items() if v is not None})
            result['sources'].append('weatherapi-rapidapi')
        om = get_openmeteo_forecast(*coords)
        if om:
            result.setdefault('temp_f_today', om.get('temp_f_today'))
            result.setdefault('temp_f_tomorrow', om.get('temp_f_tomorrow'))
            result['sources'].append('open-meteo')
    if result.get('temp_f') is None:
        result['temp_f'] = result.get('weatherapi_temp_f') or result.get('twc_temp_f_hourly') or result.get('temp_f_today')
    if result.get('temp_f_today') is None:
        result['temp_f_today'] = result.get('weatherapi_temp_f_today') or result.get('twc_temp_f_today')
    if result.get('temp_f_tomorrow') is None:
        result['temp_f_tomorrow'] = result.get('weatherapi_temp_f_tomorrow') or result.get('twc_temp_f_tomorrow')
    return result if result.get('sources') else None

def get_crypto_news(sym):
    cached = NEWS_CACHE.get(sym)
    now = datetime.now(timezone.utc)
    if cached and (now - cached['fetched_at']).total_seconds() < 600:
        return cached['payload']

    query = 'Bitcoin price crypto market' if sym == 'BTC' else 'Ethereum price crypto market'
    url = 'https://news.google.com/rss/search'
    params = {'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'}
    payload = {'sentiment': 'neutral', 'score': 0, 'headlines': []}
    try:
        r = requests.get(url, params=params, timeout=8, headers={'User-Agent': 'PolyAgent/1.0'})
        r.raise_for_status()
        root = ET.fromstring(r.text)
        items = root.findall('.//item')[:6]
        headlines = []
        score = 0
        positive_words = ('surge', 'rally', 'gain', 'bull', 'bullish', 'breakout', 'record', 'approval')
        negative_words = ('drop', 'falls', 'fall', 'bear', 'bearish', 'hack', 'lawsuit', 'liquidation', 'risk')
        for item in items:
            title = (item.findtext('title') or '').strip()
            if not title:
                continue
            headlines.append(title)
            lower = title.lower()
            score += sum(1 for word in positive_words if word in lower)
            score -= sum(1 for word in negative_words if word in lower)
        sentiment = 'bullish' if score > 1 else 'bearish' if score < -1 else 'neutral'
        payload = {'sentiment': sentiment, 'score': score, 'headlines': headlines[:3]}
    except Exception as e:
        log.debug(f'News fetch failed {sym}: {str(e)}')

    NEWS_CACHE[sym] = {'fetched_at': now, 'payload': payload}
    return payload

def detect_city(question):
    ql = question.lower()
    for city_key, info in CITIES.items():
        if city_key in ql or any(a in ql for a in info['aliases']):
            return city_key
    return None

def parse_temp_range(question):
    patterns = [
        r'(\d+)\s*(?:to|-)\s*(\d+)\s*(?:f|degrees|°)',
        r'between\s*(\d+)\s*and\s*(\d+)',
        r'(\d+)[-–](\d+)\s*(?:f|°|degrees)',
    ]
    for pat in patterns:
        m = re.search(pat, question.lower())
        if m:
            return (float(m.group(1)), float(m.group(2)))
    m = re.search(r'(\d+)\s*(?:f|degrees|°)', question)
    if m:
        val = float(m.group(1))
        if any(w in question.lower() for w in ['above','exceed','over','higher']): return (val, 999)
        if any(w in question.lower() for w in ['below','under','lower']): return (-999, val)
    return None

def parse_money_target(question):
    m = re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*([kmb])?\b', question.lower())
    if not m:
        return None
    base = float(m.group(1).replace(',', ''))
    suffix = (m.group(2) or '').lower()
    mult = {'k': 1_000, 'm': 1_000_000, 'b': 1_000_000_000}.get(suffix, 1)
    return base * mult

def is_crypto_question(text):
    ql = (text or '').lower()
    # Avoid false positives like "nETHerlands" while still matching btc/eth markets.
    return bool(re.search(r'\b(btc|bitcoin|eth|ethereum)\b', ql))

def pick_crypto_symbol(text):
    ql = (text or '').lower()
    return 'BTC' if re.search(r'\b(btc|bitcoin)\b', ql) else 'ETH'

def calc_range_prob(forecast_temp, temp_range, uncertainty=3.0):
    lo, hi = temp_range
    if lo == -999: lo = forecast_temp - 50
    if hi == 999: hi = forecast_temp + 50
    def norm_cdf(x):
        return 0.5*(1+math.erf(x/math.sqrt(2)))
    prob_below_hi = norm_cdf((hi - forecast_temp)/uncertainty)
    prob_below_lo = norm_cdf((lo - forecast_temp)/uncertainty)
    return max(0.05, min(0.95, prob_below_hi - prob_below_lo))

# ===== 5-MINUTE CANDLE ANALYSIS FOR CRYPTO =====
def get_5min_candles(sym):
    """Fetch 5-minute candles for BTC/ETH from Binance"""
    try:
        url = f'https://api.binance.com/api/v3/klines'
        params = {
            'symbol': sym + 'USDT',
            'interval': '5m',
            'limit': 20
        }
        r = requests.get(url, params=params, timeout=8)
        if r.status_code != 200: return None
        candles = r.json()
        return [{
            'time': int(c[0]),
            'open': float(c[1]),
            'high': float(c[2]),
            'low': float(c[3]),
            'close': float(c[4]),
            'volume': float(c[7])
        } for c in candles]
    except Exception as e:
        log.debug(f'Candle fetch failed {sym}: {str(e)}')
        return None

def analyze_candles(candles):
    """Technical analysis on 5-min candles - RSI/RA, momentum, trend, MACD, Bollinger."""
    if not candles or len(candles) < 5:
        return {
            'rsi': 50,
            'momentum': 0,
            'trend': 'neutral',
            'macd': 0.0,
            'macd_signal': 0.0,
            'macd_hist': 0.0,
            'macd_bias': 'neutral',
            'bollinger_upper': 0.0,
            'bollinger_middle': 0.0,
            'bollinger_lower': 0.0,
            'bollinger_bandwidth': 0.0,
            'bollinger_signal': 'neutral',
        }

    closes = [c['close'] for c in candles]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else sum(gains) / len(gains) if gains else 0
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else sum(losses) / len(losses) if losses else 0
    rs = avg_gain / avg_loss if avg_loss > 0 else 0
    rsi = 100 - (100 / (1 + rs)) if rs > 0 else 50
    momentum = ((closes[-1] - closes[-5]) / closes[-5] * 100) if closes[-5] > 0 else 0
    short_ma = sum(closes[-5:]) / 5
    long_ma = sum(closes[-15:]) / 15 if len(closes) >= 15 else short_ma
    trend = 'up' if short_ma > long_ma else 'down' if short_ma < long_ma else 'neutral'

    def ema(values, period):
        if not values:
            return []
        multiplier = 2 / (period + 1)
        series = [values[0]]
        for value in values[1:]:
            series.append((value - series[-1]) * multiplier + series[-1])
        return series

    macd_series = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    signal_series = ema(macd_series, 9)
    macd = macd_series[-1] if macd_series else 0.0
    macd_signal = signal_series[-1] if signal_series else 0.0
    macd_hist = macd - macd_signal
    macd_bias = 'bullish' if macd_hist > 0 else 'bearish' if macd_hist < 0 else 'neutral'
    lookback = closes[-20:] if len(closes) >= 20 else closes
    middle = sum(lookback) / len(lookback)
    variance = sum((value - middle) ** 2 for value in lookback) / len(lookback)
    std_dev = math.sqrt(variance)
    upper = middle + (2 * std_dev)
    lower = middle - (2 * std_dev)
    last = closes[-1]
    bandwidth = ((upper - lower) / middle) if middle else 0.0
    if last <= lower:
        bollinger_signal = 'bullish'
    elif last >= upper:
        bollinger_signal = 'bearish'
    else:
        bollinger_signal = 'neutral'

    return {
        'rsi': round(rsi, 1),
        'momentum': round(momentum, 2),
        'trend': trend,
        'macd': round(macd, 4),
        'macd_signal': round(macd_signal, 4),
        'macd_hist': round(macd_hist, 4),
        'macd_bias': macd_bias,
        'bollinger_upper': round(upper, 4),
        'bollinger_middle': round(middle, 4),
        'bollinger_lower': round(lower, 4),
        'bollinger_bandwidth': round(bandwidth, 4),
        'bollinger_signal': bollinger_signal,
    }

def get_price(sym):
    for url, key in [
        ('https://min-api.cryptocompare.com/data/price?fsym='+sym+'&tsyms=USD','USD'),
        ('https://api.coinbase.com/v2/prices/'+sym+'-USD/spot','data'),
    ]:
        try:
            d=requests.get(url,timeout=8).json()
            p=float(d['USD']) if key=='USD' else float(d['data']['amount'])
            if p>0: return p
        except: continue
    return None

def fetch_weather_markets():
    try:
        markets = POLY_TOOL.get_top_markets(limit=120, tag_slugs=['weather', 'crypto', 'finance'])
        log.info('Total markets: '+str(len(markets)))
        return markets
    except Exception:
        markets=[]
        for tag in ['weather','crypto','finance']:
            try:
                r=requests.get('https://gamma-api.polymarket.com/markets',
                    params={'active':'true','closed':'false','limit':100,'tag_slug':tag},timeout=12)
                r.raise_for_status(); markets.extend(r.json())
            except: pass
        seen=set(); unique=[]
        for m in markets:
            mid=m.get('id','')
            if mid not in seen: seen.add(mid); unique.append(m)
        log.info('Total markets: '+str(len(unique)))
        return unique

def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []

def build_market_snapshot(markets):
    snapshot = {}
    for m in markets:
        market_id = m.get('id', '')
        if not market_id:
            continue
        outcomes = _as_list(m.get('outcomes', []))
        oprices = _as_list(m.get('outcomePrices', []))
        try:
            yi = next((i for i, o in enumerate(outcomes) if o.lower() == 'yes'), 0)
            ni = next((i for i, o in enumerate(outcomes) if o.lower() == 'no'), 1)
            yes_price = float(oprices[yi])
            no_price = float(oprices[ni])
        except:
            continue
        h_left = None
        end_str = m.get('endDate') or m.get('end_date_iso')
        if end_str:
            for fmt in ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%d']:
                try:
                    end = datetime.strptime(end_str, fmt).replace(tzinfo=timezone.utc)
                    h_left = max(0.0, (end - datetime.now(timezone.utc)).total_seconds() / 3600)
                    break
                except:
                    continue
        snapshot[market_id] = {
            'question': m.get('question', ''),
            'yes_price': yes_price,
            'no_price': no_price,
            'hours_to_expiry': h_left,
        }
    return snapshot

def trading_enabled():
    try:
        flag_path = BASE / 'data' / 'trading_enabled.flag'
        if not flag_path.exists():
            return True
        raw = flag_path.read_text(encoding='utf-8', errors='ignore').strip().lower()
        return raw in ('1', 'true', 'on', 'yes')
    except Exception:
        return True

def strategy_mode():
    try:
        p = BASE / 'data' / 'strategy_mode.flag'
        if not p.exists():
            return 'conservative'
        mode = p.read_text(encoding='utf-8', errors='ignore').strip().lower()
        if mode in ('conservative', 'weather_only', 'crypto_only', 'legacy_aggressive', 'balanced'):
            return mode
    except Exception:
        pass
    return 'conservative'

def _new_rejection_summary():
    return {
        'markets_seen': 0,
        'crypto_candidates': 0,
        'weather_candidates': 0,
        'opportunities_found': 0,
        'entries_attempted': 0,
        'entries_placed': 0,
        'exits_attempted': 0,
        'exits_closed': 0,
        'rejected_liquidity': 0,
        'rejected_missing_token_ids': 0,
        'rejected_price_parse': 0,
        'rejected_hours_to_expiry': 0,
        'rejected_missing_candle_data': 0,
        'rejected_signal_alignment': 0,
        'rejected_prob_threshold': 0,
        'rejected_edge_threshold': 0,
        'rejected_spread_threshold': 0,
        'rejected_already_in_position': 0,
        'rejected_recently_closed': 0,
        'rejected_trade_limit': 0,
        'rejected_disabled_by_dashboard': 0,
    }


def _write_json(path: Path, payload):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def analyze(markets, prices, weather_cache, candle_data, news_data, mode='conservative', manager_profile=None):
    profile = manager_profile or {}
    filters = profile.get('market_filters', {})
    analysis_cfg = profile.get('analysis', {})
    entry_cfg = profile.get('entry', {})
    positioning_cfg = profile.get('positioning', {})
    exits_cfg = profile.get('exits', {})

    allow_weather = bool(filters.get('weather', True)) and mode != 'crypto_only'
    allow_crypto = bool(filters.get('crypto', True)) and mode != 'weather_only'
    alignment_required = int(analysis_cfg.get('alignment_required', 2) or 2)
    min_prob_crypto = float(entry_cfg.get('min_prob_crypto', 0.55 if mode == 'conservative' else 0.52))
    min_prob_weather = float(entry_cfg.get('min_prob_weather', 0.60 if mode == 'conservative' else 0.55))
    min_edge_crypto = float(entry_cfg.get('min_edge_crypto', 0.04 if mode == 'conservative' else 0.02))
    min_edge_weather = float(entry_cfg.get('min_edge_weather', 0.05 if mode == 'conservative' else 0.03))
    base_size = float(positioning_cfg.get('base_size_usdc', 1.0) or 1.0)
    max_size = float(positioning_cfg.get('max_size_usdc', 3.0) or 3.0)
    min_hours_to_expiry = max(CFG.min_hours_to_expiry, float(exits_cfg.get('avoid_expiry_minutes', 30) or 30) / 60.0)
    max_hours_to_expiry = float(exits_cfg.get('max_hours_to_expiry', CFG.max_hours_to_expiry) or CFG.max_hours_to_expiry)
    max_spread_pct = float(analysis_cfg.get('max_spread_pct', 0.35) or 0.35)
    # Crypto markets are often farther out than weather events; avoid filtering them all out.
    if allow_crypto and not allow_weather:
        max_hours_to_expiry = max(max_hours_to_expiry, 24.0 * 365.0)
    elif allow_crypto and allow_weather:
        max_hours_to_expiry = max(max_hours_to_expiry, 24.0 * 30.0)

    opps=[]
    telemetry = _new_rejection_summary()
    spread_cache = {}
    for m in markets:
        telemetry['markets_seen'] += 1
        q=m.get('question',''); ql=q.lower()
        liq=float(m.get('liquidity') or 0)
        is_weather_candidate = any(w in ql for w in ['temperature','degrees','high of','low of','warmer','cooler','temp','weather','precipitation','rainfall'])
        is_crypto_candidate = is_crypto_question(ql)
        if is_weather_candidate:
            telemetry['weather_candidates'] += 1
        if is_crypto_candidate:
            telemetry['crypto_candidates'] += 1
        if liq<200:
            telemetry['rejected_liquidity'] += 1
            continue  # Much lower liquidity threshold
        tids=m.get('clobTokenIds') or []
        tids = _as_list(tids)
        if len(tids)<2:
            telemetry['rejected_missing_token_ids'] += 1
            continue
        outcomes = _as_list(m.get('outcomes', []))
        oprices = _as_list(m.get('outcomePrices', []))
        try:
            yi=next((i for i,o in enumerate(outcomes) if o.lower()=='yes'),0)
            ni=next((i for i,o in enumerate(outcomes) if o.lower()=='no'),1)
            yp,np_=float(oprices[yi]),float(oprices[ni])
        except:
            telemetry['rejected_price_parse'] += 1
            continue
        if not(0.01<=yp<=0.99):
            telemetry['rejected_prob_threshold'] += 1
            continue
        h_left=0.0
        end_str=m.get('endDate') or m.get('end_date_iso')
        if end_str:
            for fmt in ['%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%d']:
                try:
                    end=datetime.strptime(end_str,fmt).replace(tzinfo=timezone.utc)
                    h_left=max(0.0,(end-datetime.now(timezone.utc)).total_seconds()/3600)
                    break
                except: continue
        else: h_left=24.0
        if not(min_hours_to_expiry <= h_left <= max_hours_to_expiry):
            telemetry['rejected_hours_to_expiry'] += 1
            continue

        op=None; market_type='unknown'; confidence_level='unknown'

        # ===== WEATHER MARKET ANALYSIS =====
        weather_words=['temperature','degrees','high of','low of','warmer','cooler','temp','weather','precipitation','rainfall']
        if any(w in ql for w in weather_words) and allow_weather:
            city=detect_city(q)
            if city:
                if city not in weather_cache:
                    weather_cache[city]=get_weather(city)
                wx=weather_cache.get(city)
                if wx:
                    temp=wx.get('temp_f_today') or wx.get('temp_f')
                    if temp:
                        rng=parse_temp_range(q)
                        if rng:
                            op=calc_range_prob(temp, rng)
                            confidence_level='LADDER'
                            if yp < 0.10 and op > 0.85:
                                confidence_level='DEEP_DISCOUNT'
                                op = min(0.95, op + 0.08)
                            market_type='WEATHER'
                            source_text = ','.join(wx.get('sources', []))
                            log.info('WEATHER | '+city+' '+str(temp)+'F | '+str(rng)+'F prob '+format(op,'.1%')+' vs '+format(yp,'.1%')+' | '+confidence_level+' | '+source_text)

        # ===== CRYPTO MARKET ANALYSIS WITH 5-MIN CANDLES =====
        elif is_crypto_question(ql) and allow_crypto:
            sym = pick_crypto_symbol(ql)
            price=prices.get(sym)
            if price and sym in candle_data:
                tech = candle_data[sym]
                rsi = tech['rsi']
                momentum = tech['momentum']
                trend = tech['trend']
                macd_hist = tech.get('macd_hist', 0.0)
                macd_bias = tech.get('macd_bias', 'neutral')
                bollinger_signal = tech.get('bollinger_signal', 'neutral')
                news_ctx = news_data.get(sym, {'sentiment': 'neutral', 'score': 0, 'headlines': []})
                news_sentiment = news_ctx.get('sentiment', 'neutral')

                bullish = 0
                bearish = 0
                if analysis_cfg.get('use_rsi', True) or analysis_cfg.get('use_ra', True):
                    if rsi <= 45:
                        bullish += 1
                    elif rsi >= 55:
                        bearish += 1
                if analysis_cfg.get('use_macd', True):
                    if macd_hist > 0:
                        bullish += 1
                    elif macd_hist < 0:
                        bearish += 1
                if analysis_cfg.get('use_trend', True):
                    if trend == 'up':
                        bullish += 1
                    elif trend == 'down':
                        bearish += 1
                if analysis_cfg.get('use_bollinger', True):
                    if bollinger_signal == 'bullish':
                        bullish += 1
                    elif bollinger_signal == 'bearish':
                        bearish += 1
                if momentum > 0.25:
                    bullish += 1
                elif momentum < -0.25:
                    bearish += 1
                if analysis_cfg.get('use_news_context', True):
                    if news_sentiment == 'bullish':
                        bullish += 1
                    elif news_sentiment == 'bearish':
                        bearish += 1

                direction = None
                signal_strength = max(bullish, bearish)
                if bullish > bearish and signal_strength >= alignment_required:
                    direction = 'above'
                elif bearish > bullish and signal_strength >= alignment_required:
                    direction = 'below'

                if direction:
                    val = parse_money_target(q)
                    if val and val > 100:
                        vol={'BTC':0.65,'ETH':0.80}.get(sym,0.70)
                        T=max(h_left/8760,1/8760)
                        d2=math.log(price/val)/(vol*math.sqrt(T)) if price > 0 and val > 0 else 0
                        def ncdf(x):
                            s=1 if x>=0 else -1; x=abs(x); t=1/(1+0.2316419*x)
                            c=(0.31938153,-0.356563782,1.781477937,-1.821255978,1.330274429)
                            poly=sum(c[i]*t**(i+1) for i in range(5))
                            cdf=1-(1/math.sqrt(2*math.pi))*math.exp(-x*x/2)*poly
                            return cdf if s>0 else 1-cdf
                        op=max(0.05,min(0.95,ncdf(d2) if direction=='above' else 1-ncdf(d2)))

                        op = min(0.98, op + signal_strength * 0.03)
                        if direction == 'above' and momentum > 0:
                            op = min(0.98, op + 0.03)
                        if direction == 'below' and momentum < 0:
                            op = min(0.98, op + 0.03)
                        if analysis_cfg.get('use_news_context', True):
                            if direction == 'above' and news_sentiment == 'bullish':
                                op = min(0.98, op + 0.02)
                            elif direction == 'below' and news_sentiment == 'bearish':
                                op = min(0.98, op + 0.02)
                            elif news_sentiment != 'neutral':
                                op = max(0.05, op - 0.02)

                        market_type='CRYPTO'
                        confidence_level=f'CANDLE|R:{rsi}|M:{momentum}%|MACD:{macd_hist}|BB:{bollinger_signal}|NEWS:{news_sentiment}'
                        log.info(
                            f'CRYPTO | {sym} ${val} | RA/RSI:{rsi} Mom:{momentum}% {trend} '
                            f'| MACD:{macd_hist} {macd_bias} | BB:{bollinger_signal} '
                            f'| News:{news_sentiment} score {news_ctx.get("score", 0)} '
                            f'| align {signal_strength}/{alignment_required} '
                            f'| prob {op:.1%} vs {yp:.1%}'
                        )
                else:
                    telemetry['rejected_signal_alignment'] += 1
            else:
                telemetry['rejected_missing_candle_data'] += 1

        if op is None:
            continue

        min_prob = min_prob_crypto if confidence_level.startswith('CANDLE') else min_prob_weather
        if not(min_prob<=op<=0.99):
            telemetry['rejected_prob_threshold'] += 1
            continue

        ey=op-yp; en=(1-op)-np_
        if ey>=en: side,edge,mprice,tid='YES',ey,yp,tids[yi]
        else: side,edge,mprice,tid='NO',en,np_,tids[ni]

        min_edge = min_edge_crypto if confidence_level.startswith('CANDLE') else min_edge_weather
        if edge<min_edge:
            telemetry['rejected_edge_threshold'] += 1
            continue

        if market_type == 'CRYPTO':
            spread = spread_cache.get(tid)
            if spread is None:
                spread = POLY_TOOL.get_spread(tid)
                spread_cache[tid] = spread
            if spread and float(spread.get('spread_pct', 0) or 0) > max_spread_pct:
                telemetry['rejected_spread_threshold'] += 1
                log.info(
                    f'SKIP SPREAD | {market_type} | {m.get("id","")[:8]} | '
                    f'spread {float(spread.get("spread_pct", 0) or 0):.2%} > {max_spread_pct:.2%}'
                )
                continue

        conf='HIGH' if edge>=0.10 else 'MEDIUM' if edge>=0.05 else 'LOW'
        if confidence_level == 'DEEP_DISCOUNT': conf = 'ASYMMETRIC'
        if confidence_level == 'LADDER': conf = 'LADDER'
        if confidence_level.startswith('CANDLE'): conf = 'TECHNICAL'

        growth_factor = 28 if market_type == 'WEATHER' else 36
        size=round(min(max_size,max(base_size,base_size+(edge*growth_factor))),2)

        log.info('OPPORTUNITY | '+market_type+' | '+conf+' | '+q[:40]+' | '+side+' edge '+format(edge,'.1%')+' $'+str(size))
        opps.append({'market_id':m.get('id',''),'question':q,'sym':market_type,'side':side,'edge':edge,'price':mprice,'tid':tid,'size':size,'conf':conf,'op':op,'yp':yp,'strategy':confidence_level})
    opps = sorted(opps,key=lambda x:(x['conf']=='HIGH',x['edge']),reverse=True)
    telemetry['opportunities_found'] = len(opps)
    return opps, telemetry

class Agent:
    def __init__(self):
        self.executor=TradeExecutor(CFG); self.running=False; self.cycle=0
        signal.signal(signal.SIGINT,self._stop); signal.signal(signal.SIGTERM,self._stop)
        if POLY_BTC_REGISTRY:
            POLY_BTC_REGISTRY.set_executor(self.executor)
    def _stop(self,*a): self.running=False
    def run_cycle(self):
        self.cycle+=1
        log.info('='*50+' Cycle #'+str(self.cycle)+' '+datetime.now(timezone.utc).strftime('%H:%M:%S UTC'))
        manager_profile = load_live_profile()
        mode = manager_profile.get('strategy_mode') or strategy_mode()
        log.info('MANAGER PROFILE: '+manager_profile.get('name', 'runtime-default'))
        log.info('STRATEGY MODE: '+mode)

        prices={s:p for s in ['BTC','ETH'] if (p:=get_price(s))}

        # Log prices for dashboard
        for sym, price in prices.items():
            if price:
                log.info(f'PRICE | {sym}: ${price:,.2f}')

        # Fetch 5-min candle data
        candle_data = {}
        for sym in ['BTC', 'ETH']:
            candles = get_5min_candles(sym)
            if candles:
                candle_data[sym] = analyze_candles(candles)
                log.info(
                    f'CANDLES | {sym} RA/RSI:{candle_data[sym]["rsi"]} '
                    f'Momentum:{candle_data[sym]["momentum"]}% Trend:{candle_data[sym]["trend"]} '
                    f'MACD:{candle_data[sym]["macd_hist"]} {candle_data[sym]["macd_bias"]} '
                    f'BB:{candle_data[sym]["bollinger_signal"]} BW:{candle_data[sym]["bollinger_bandwidth"]}'
                )

        news_data = {}
        if manager_profile.get('analysis', {}).get('use_news_context', True):
            for sym in ['BTC', 'ETH']:
                news_data[sym] = get_crypto_news(sym)
                if news_data[sym].get('headlines'):
                    log.info(f'NEWS | {sym} | {news_data[sym]["sentiment"]} | {news_data[sym]["headlines"][0][:100]}')

        weather_cache={}
        markets=fetch_weather_markets()
        if not markets: return
        market_snapshot = build_market_snapshot(markets)
        opps, telemetry = analyze(markets,prices,weather_cache,candle_data,news_data,mode,manager_profile)

        # ===== POLY BTC STRATEGY PACK (runs alongside main analyze) =====
        if POLY_BTC_REGISTRY and 'BTC' in candle_data and prices.get('BTC'):
            btc_markets = [m for m in markets if is_crypto_question(m.get('question',''))
                           and re.search(r'\b(btc|bitcoin)\b', m.get('question','').lower())]
            btc_pack_opps = POLY_BTC_REGISTRY.scan(
                btc_markets=btc_markets,
                candle_analysis=candle_data['BTC'],
                current_price=prices['BTC'],
                get_spread_fn=POLY_TOOL.get_spread,
            )
            if POLY_BTC_REGISTRY.orderbook_runtime:
                POLY_BTC_REGISTRY.orderbook_runtime.update_context(candle_data['BTC'], prices['BTC'])
                POLY_BTC_REGISTRY.orderbook_runtime.update_markets(btc_markets)
            if btc_pack_opps:
                log.info(f'POLY_BTC_PACK | {len(btc_pack_opps)} opp(s) prepended to cycle')
                opps = btc_pack_opps + opps  # pack strategies take priority

        closed = self.executor.check_exits(
            market_snapshot=market_snapshot,
            signal_map={opp['market_id']: opp for opp in opps},
            manager_profile=manager_profile,
        )
        telemetry['exits_attempted'] = int(self.executor.stats.get('exits_attempted_last_cycle', 0) or 0)
        telemetry['exits_closed'] = int(self.executor.stats.get('exits_closed_last_cycle', 0) or 0)
        recently_closed_ids: set = {mid for mid, _ in closed} if closed else set()
        if closed:
            for mid, reason in closed:
                log.info(f'Position closed: {reason}')

        # Continuous-trading fallback for live crypto modes when technical feeds return no setups.
        if not opps and manager_profile.get('entry', {}).get('continuous_trading') and mode in ('crypto_only', 'balanced', 'conservative'):
            min_edge_crypto = float(manager_profile.get('entry', {}).get('min_edge_crypto', 0.04) or 0.04)
            base_size = float(manager_profile.get('positioning', {}).get('base_size_usdc', 1.0) or 1.0)
            max_size = float(manager_profile.get('positioning', {}).get('max_size_usdc', 3.0) or 3.0)
            fallback_floor = max(0.01, min_edge_crypto * 0.5)
            for m in markets:
                if m.get('id', '') in self.executor.positions:
                    telemetry['rejected_already_in_position'] += 1
                    continue
                if m.get('id', '') in recently_closed_ids:
                    telemetry['rejected_recently_closed'] += 1
                    continue
                if self.executor.in_exit_cooldown(m.get('id', '')):
                    telemetry['rejected_recently_closed'] += 1
                    continue
                q = m.get('question', '')
                if not is_crypto_question(q):
                    continue
                outcomes = _as_list(m.get('outcomes', []))
                oprices = _as_list(m.get('outcomePrices', []))
                tids = _as_list(m.get('clobTokenIds', []))
                if len(outcomes) < 2 or len(oprices) < 2 or len(tids) < 2:
                    telemetry['rejected_missing_token_ids'] += 1
                    continue
                try:
                    yi = next((i for i, o in enumerate(outcomes) if str(o).lower() == 'yes'), 0)
                    ni = next((i for i, o in enumerate(outcomes) if str(o).lower() == 'no'), 1)
                    yp, np_ = float(oprices[yi]), float(oprices[ni])
                except Exception:
                    telemetry['rejected_price_parse'] += 1
                    continue
                if not (0.01 <= yp <= 0.99):
                    telemetry['rejected_prob_threshold'] += 1
                    continue
                val = parse_money_target(q)
                if not val or val <= 100:
                    continue
                sym = pick_crypto_symbol(q)
                price = prices.get(sym)
                if not price or price <= 0:
                    continue
                end_str = m.get('endDate') or m.get('end_date_iso')
                h_left = 8760.0  # default 1 year if no end date (crypto markets are long-dated)
                if end_str:
                    for fmt in ['%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%d']:
                        try:
                            end = datetime.strptime(end_str, fmt).replace(tzinfo=timezone.utc)
                            h_left = max(1.0, (end - datetime.now(timezone.utc)).total_seconds() / 3600)
                            break
                        except Exception:
                            continue

                vol = {'BTC': 0.65, 'ETH': 0.80}.get(sym, 0.70)
                T = max(h_left / 8760.0, 1 / 8760.0)
                d2 = math.log(price / val) / (vol * math.sqrt(T)) if price > 0 and val > 0 else 0

                def ncdf(x):
                    s = 1 if x >= 0 else -1
                    x = abs(x)
                    t = 1 / (1 + 0.2316419 * x)
                    c = (0.31938153, -0.356563782, 1.781477937, -1.821255978, 1.330274429)
                    poly = sum(c[i] * t ** (i + 1) for i in range(5))
                    cdf = 1 - (1 / math.sqrt(2 * math.pi)) * math.exp(-x * x / 2) * poly
                    return cdf if s > 0 else 1 - cdf

                # Derive direction from whether target is above or below current price.
                # Keyword matching ("above"/"over") misses "hit", "reach", "surpass" etc.
                direction_above = val >= price
                op = max(0.05, min(0.95, ncdf(d2) if direction_above else 1 - ncdf(d2)))
                ey = op - yp
                en = (1 - op) - np_
                if ey >= en:
                    side, edge, mprice, tid = 'YES', ey, yp, tids[yi]
                else:
                    side, edge, mprice, tid = 'NO', en, np_, tids[ni]
                if edge < fallback_floor:
                    telemetry['rejected_edge_threshold'] += 1
                    continue
                size = round(min(max_size, max(base_size, base_size + (edge * 18))), 2)
                opps.append({
                    'market_id': m.get('id', ''),
                    'question': q,
                    'sym': 'CRYPTO',
                    'side': side,
                    'edge': edge,
                    'price': mprice,
                    'tid': tid,
                    'size': size,
                    'conf': 'CONTINUOUS_FALLBACK',
                    'op': op,
                    'yp': yp,
                    'strategy': 'CONTINUOUS_FALLBACK',
                })
                log.info(f'CONTINUOUS FALLBACK | {sym} | {side} | edge {edge:.2%} | market {m.get("id","")[:8]}')
                if len(opps) >= 2:
                    break

        # ===== WEATHER PREDICTION TRADING (DRY-RUN: SYNTHETIC for testing) =====
        if CFG.dry_run_mode and mode == 'legacy_aggressive':
            # Generate synthetic weather trades for dry-run testing (ALWAYS - don't wait for API)
            synthetic_count = 0
            for city in ['new york', 'london', 'chicago']:
                # Use cached weather or fallback to synthetic temp
                wx = weather_cache.get(city)
                temp = wx.get('temp_f') if wx else None

                # If no real weather data, generate realistic synthetic temps based on city
                if not temp:
                    synthetic_temps = {'new york': 62, 'london': 58, 'chicago': 55}
                    temp = synthetic_temps.get(city, 60)
                    log.info(f'Using synthetic temp for {city}: {temp}F')

                # Create synthetic weather opportunity
                ranges = [
                    (temp - 5, temp + 5, 'HIGH TEMP RANGE'),
                    (temp - 10, temp, 'COOLER THAN AVG'),
                    (temp, temp + 10, 'WARMER THAN AVG'),
                ]

                for lo, hi, desc in ranges:
                    our_prob = 0.62 + (0.1 * (1 - abs(temp - (lo + hi)/2) / 20))  # Higher confidence if temp near range center
                    mkt_price = 0.48
                    edge = our_prob - mkt_price

                    size = round(min(2.5, edge * 150), 2)
                    log.info(f'WEATHER DRY-RUN | {city.upper()} | {desc} ({lo:.0f}-{hi:.0f}F) | Current:{temp:.0f}F | Prob:{our_prob:.0%} vs Mkt:{mkt_price:.0%} | Edge:{edge:.1%} ${size}')
                    synthetic_count += 1
                    opps.append({
                        'market_id': f'synthetic_weather_{city}_{self.cycle}_{desc.replace(" ","")}',
                        'question': f'{city.title()} temperature {lo:.0f}-{hi:.0f}F (current {temp:.0f}F)',
                        'sym': 'WEATHER',
                        'side': 'YES',
                        'edge': edge,
                        'price': mkt_price,
                        'tid': f'weather_{city}_{desc}',
                        'size': size,
                        'conf': 'WEATHER',
                        'op': our_prob,
                        'yp': mkt_price,
                        'strategy': 'WEATHER_SYNTHETIC'
                    })
            if synthetic_count > 0:
                log.info(f'Added {synthetic_count} synthetic weather opportunities')

        # ENHANCED: If no real opportunities, use fallback trading
        # Always available, doesn't depend on external candle data
        if not opps and mode == 'legacy_aggressive':
            log.info(f'Fallback trading active - scanning all {len(markets)} markets')
            for m in markets[:100]:  # Check ALL markets - be very aggressive
                q = m.get('question', '').lower()
                liq = float(m.get('liquidity') or 0)
                if liq < 50: continue  # Very low liquidity threshold

                outcomes = m.get('outcomes', [])
                oprices = _as_list(m.get('outcomePrices', []))
                outcomes = _as_list(outcomes)
                try:
                    yi = next((i for i, o in enumerate(outcomes) if o.lower() == 'yes'), 0)
                    ni = next((i for i, o in enumerate(outcomes) if o.lower() == 'no'), 1)
                    yp, np_ = float(oprices[yi]), float(oprices[ni])
                except: continue

                if not(0.05 <= yp <= 0.95): continue  # Very permissive probability range

                # Use contrarian strategy: bet opposite of market
                our_prob = 0.60  # Neutral baseline probability
                side = 'YES' if yp < 0.50 else 'NO'  # Contrarian: trade against market

                edge = abs(our_prob - yp)
                if edge >= 0.0001:  # ULTRA ULTRA AGGRESSIVE - 0.01% edge minimum
                    tids = m.get('clobTokenIds', [])
                    tids = _as_list(tids)
                    if len(tids) < 2: continue

                    mprice = yp if side == 'YES' else np_
                    tid = tids[yi] if side == 'YES' else tids[ni]
                    size = round(min(3.0, max(0.5, edge * 500)), 2)  # Bet more aggressively on thin edges

                    log.info(f'FALLBACK TRADE | {m.get("id")[:8]} | {side} | {q[:40]} | prob {our_prob:.1%} vs {mprice:.1%} | edge {edge:.2%} ${size}')
                    opps.append({'market_id': m.get('id'), 'question': m.get('question'),
                        'sym': 'POLYMARKET', 'side': side, 'edge': edge, 'price': mprice, 'tid': tid,
                        'size': size, 'conf': 'FALLBACK', 'op': our_prob, 'yp': mprice, 'strategy': 'FALLBACK_TRADE'})
                    if len(opps) >= 3: break  # Found enough opportunities, execute trades

        if not opps and mode == 'legacy_aggressive':
            # Try to find at least one valid market for forced trade
            for m in markets:
                try:
                    outcomes = _as_list(m.get('outcomes', []))
                    oprices = _as_list(m.get('outcomePrices', []))
                    if not oprices or len(oprices) < 2:
                        continue
                    yi = next((i for i, o in enumerate(outcomes) if o.lower() == 'yes'), 0)
                    ni = next((i for i, o in enumerate(outcomes) if o.lower() == 'no'), 1)
                    yp = float(oprices[yi])
                    if not (0.05 <= yp <= 0.95):
                        continue
                    tids = _as_list(m.get('clobTokenIds', []))
                    if len(tids) >= 2:
                        opps = [{'market_id': m.get('id'), 'question': m.get('question'),
                            'sym': 'FORCED', 'side': 'YES', 'edge': 0.05, 'price': yp, 'tid': tids[yi],
                            'size': 1.0, 'conf': 'FORCED', 'op': 0.60, 'yp': yp, 'strategy': 'FORCE_TRADE'}]
                        log.info(f'FORCED TRADE: {m.get("question")[:70]}')
                        break
                except:
                    continue
        else:
            log.info('Found '+str(len(opps))+' real opportunities')
        is_enabled = trading_enabled()
        if not is_enabled:
            log.warning('TRADING DISABLED BY DASHBOARD SWITCH - opportunities monitored only')
        max_entries = int(manager_profile.get('entry', {}).get('max_entries_per_cycle', 5) or 5)
        if len(opps) > max_entries:
            telemetry['rejected_trade_limit'] += (len(opps) - max_entries)
        for opp in opps[:max_entries]:
            class FO: pass
            fo=FO()
            class FM: pass
            fm=FM()
            fm.market_id=opp['market_id']; fm.question=opp['question']
            fm.symbol=opp['sym']; fm.yes_price=opp['yp']; fm.no_price=1-opp['yp']
            fm.liquidity=1000; fm.hours_to_expiry=24
            fm.yes_token_id=opp['tid']; fm.no_token_id=''
            fo.market=fm; fo.best_side=opp['side']; fo.best_edge=opp['edge']
            fo.best_market_price=opp['price']; fo.best_token_id=opp['tid']
            fo.trade_size=opp['size']; fo.confidence=opp['conf']
            fo.our_prob_yes=opp['op']; fo.market_prob_yes=opp['yp']
            telemetry['entries_attempted'] += 1
            if is_enabled:
                rec = self.executor.execute(fo, manager_profile=manager_profile)
                if rec.status in ('placed', 'dry_run'):
                    telemetry['entries_placed'] += 1
                elif rec.error == 'already_in':
                    telemetry['rejected_already_in_position'] += 1
                elif rec.error in ('Daily trade limit', 'Daily loss limit', 'Max positions'):
                    telemetry['rejected_trade_limit'] += 1
            else:
                telemetry['rejected_disabled_by_dashboard'] += 1

        stats = self.executor.stats
        idle_minutes = stats.get('idle_minutes_since_last_live_order')
        cycle_summary = {
            'cycle': self.cycle,
            'at': datetime.now(timezone.utc).isoformat(),
            'strategy_mode': mode,
            'runtime_mode': stats.get('mode'),
            'runtime_health_reason': stats.get('runtime_health_reason'),
            **telemetry,
            'blocked_entry_count': stats.get('blocked_entry_count', 0),
            'blocked_exit_count': stats.get('blocked_exit_count', 0),
            'exit_failure_count': stats.get('exit_failure_count', 0),
            'trapped_position_count': stats.get('trapped_position_count', 0),
            'unrealized_pnl_open': stats.get('unrealized_pnl_open', 0.0),
            'idle_minutes_since_last_live_order': idle_minutes,
        }
        rejection_summary = {
            'at': cycle_summary['at'],
            'cycle': self.cycle,
            **{k: v for k, v in telemetry.items() if k.startswith('rejected_')},
            'markets_seen': telemetry['markets_seen'],
            'crypto_candidates': telemetry['crypto_candidates'],
            'weather_candidates': telemetry['weather_candidates'],
            'opportunities_found': telemetry['opportunities_found'],
        }
        _write_json(BASE / 'data' / 'cycle_summary.json', cycle_summary)
        _write_json(BASE / 'data' / 'rejection_summary.json', rejection_summary)

        idle_text = 'n/a' if idle_minutes is None else f'{idle_minutes:.1f}'
        log.info(
            'CYCLE SUMMARY | '
            f'seen={telemetry["markets_seen"]} '
            f'crypto={telemetry["crypto_candidates"]} '
            f'opps={telemetry["opportunities_found"]} '
            f'reject_signal={telemetry["rejected_signal_alignment"]} '
            f'reject_prob={telemetry["rejected_prob_threshold"]} '
            f'reject_edge={telemetry["rejected_edge_threshold"]} '
            f'reject_spread={telemetry["rejected_spread_threshold"]} '
            f'placed={telemetry["entries_placed"]} '
            f'idle={idle_text}m'
        )
        log.info('Trades:'+str(stats['total_trades'])+' Open:'+str(stats['open_positions'])+' Deployed:$'+format(stats['deployed'],'.2f'))
    def run(self):
        self.running=True
        log.info('Agent STARTED | Weather+Crypto 5MIN CANDLES AGGRESSIVE | '+('DRY RUN' if self.executor.dry_run else 'LIVE'))
        while self.running:
            try: self.run_cycle()
            except Exception as e: log.error('Cycle error: '+str(e),exc_info=True)
            if self.running: time.sleep(CFG.poll_interval)
        log.info('Agent stopped.')

if __name__=='__main__':
    Agent().run()
