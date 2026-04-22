from dataclasses import dataclass
import os
import requests


@dataclass(frozen=True)
class BinanceStatus:
    configured: bool
    reason: str


class BinanceAccountClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET", "")

    def status(self) -> BinanceStatus:
        if not self.api_key or not self.api_secret:
            return BinanceStatus(False, "Missing API key/secret")
        return BinanceStatus(True, "API key and secret are set")

    def ping(self) -> bool:
        # Public endpoint connectivity check only; signed account calls added in later phase.
        response = requests.get("https://api.binance.com/api/v3/ping", timeout=8)
        return response.status_code == 200
