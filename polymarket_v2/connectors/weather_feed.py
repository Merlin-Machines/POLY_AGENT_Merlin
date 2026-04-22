import math
import re
import requests


CITIES = {
    "new york": {"nws": "KNYC", "aliases": ["nyc", "new york city", "manhattan"], "coords": (40.71, -74.01)},
    "london": {"nws": "EGLC", "aliases": ["london"], "coords": (51.51, -0.12)},
    "chicago": {"nws": "KORD", "aliases": ["chicago"], "coords": (41.88, -87.63)},
    "los angeles": {"nws": "KLAX", "aliases": ["la", "los angeles"], "coords": (34.05, -118.24)},
    "miami": {"nws": "KMIA", "aliases": ["miami"], "coords": (25.77, -80.19)},
    "seoul": {"nws": "RKSS", "aliases": ["seoul"], "coords": (37.57, 126.98)},
    "tokyo": {"nws": "RJTT", "aliases": ["tokyo"], "coords": (35.69, 139.69)},
}


def detect_city(question: str) -> str | None:
    lowered = question.lower()
    for city_name, cfg in CITIES.items():
        if city_name in lowered or any(alias in lowered for alias in cfg["aliases"]):
            return city_name
    return None


def get_weather(city_name: str) -> dict | None:
    city_cfg = CITIES.get(city_name)
    if not city_cfg:
        return None

    weather: dict = {}
    nws = _get_nws(city_cfg["nws"])
    if nws:
        weather.update(nws)
    forecast = _get_open_meteo(city_cfg["coords"][0], city_cfg["coords"][1])
    if forecast:
        weather.update(forecast)
    return weather or None


def parse_temp_range(question: str) -> tuple[float, float] | None:
    lowered = question.lower()
    patterns = (
        r"(\d+)\s*(?:to|-)\s*(\d+)\s*(?:f|degrees)",
        r"between\s*(\d+)\s*and\s*(\d+)",
        r"(\d+)-(\d+)\s*(?:f|degrees)",
    )
    for pattern in patterns:
        matched = re.search(pattern, lowered)
        if matched:
            return (float(matched.group(1)), float(matched.group(2)))

    single = re.search(r"(\d+)\s*(?:f|degrees)", lowered)
    if not single:
        return None
    value = float(single.group(1))
    if any(word in lowered for word in ("above", "exceed", "over", "higher")):
        return (value, 999)
    if any(word in lowered for word in ("below", "under", "lower")):
        return (-999, value)
    return None


def calc_range_prob(forecast_temp_f: float, temp_range: tuple[float, float], uncertainty: float = 3.0) -> float:
    low, high = temp_range
    if low == -999:
        low = forecast_temp_f - 50
    if high == 999:
        high = forecast_temp_f + 50

    prob_below_high = _norm_cdf((high - forecast_temp_f) / uncertainty)
    prob_below_low = _norm_cdf((low - forecast_temp_f) / uncertainty)
    return max(0.05, min(0.95, prob_below_high - prob_below_low))


def _get_nws(station: str) -> dict | None:
    try:
        response = requests.get(
            f"https://api.weather.gov/stations/{station}/observations/latest",
            timeout=8,
            headers={"User-Agent": "PolyAgent/2.0"},
        )
        if response.status_code != 200:
            return None
        props = response.json()["properties"]
        temp_c = props.get("temperature", {}).get("value")
        if temp_c is None:
            return None
        temp_f = temp_c * 9 / 5 + 32
        return {"temp_f": round(temp_f, 1), "temp_c": round(temp_c, 1), "station": station}
    except Exception:
        return None


def _get_open_meteo(lat: float, lon: float) -> dict | None:
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "forecast_days": 3,
            },
            timeout=8,
        )
        daily = response.json()["daily"]["temperature_2m_max"]
        return {"temp_f_today": daily[0], "temp_f_tomorrow": daily[1]}
    except Exception:
        return None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

