from dataclasses import dataclass
import os


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    env: str
    dry_run: bool
    execution_enabled: bool
    live_trading_enabled: bool
    poll_interval_seconds: int
    max_positions: int
    max_trade_usd: float
    edge_threshold: float
    polymarket_host: str
    binance_api_key: str
    binance_api_secret: str
    log_level: str


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "polymarket_v2"),
        env=os.getenv("APP_ENV", "dev"),
        dry_run=_as_bool(os.getenv("DRY_RUN", "1"), True),
        execution_enabled=_as_bool(os.getenv("EXECUTION_ENABLED", "0"), False),
        live_trading_enabled=_as_bool(os.getenv("LIVE_TRADING_ENABLED", "0"), False),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "45")),
        max_positions=int(os.getenv("MAX_POSITIONS", "10")),
        max_trade_usd=float(os.getenv("MAX_TRADE_USD", "4.0")),
        edge_threshold=float(os.getenv("EDGE_THRESHOLD", "0.02")),
        polymarket_host=os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com"),
        binance_api_key=os.getenv("BINANCE_API_KEY", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
