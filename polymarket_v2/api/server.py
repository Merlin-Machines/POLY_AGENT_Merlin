from fastapi import FastAPI

from polymarket_v2.app.settings import load_settings
from polymarket_v2.connectors.binance_account import BinanceAccountClient

app = FastAPI(title="polymarket_v2")


@app.get("/health")
def health() -> dict:
    settings = load_settings()
    binance = BinanceAccountClient(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
    )
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.env,
        "dry_run": settings.dry_run,
        "live_trading_enabled": settings.live_trading_enabled,
        "binance_configured": binance.status().configured,
    }
