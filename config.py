import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

@dataclass
class TradingConfig:
    # Set DRY_RUN=1 to disable live trading
    # DRY_RUN=1 for testing, DRY_RUN=0 for LIVE with real account
    dry_run_mode: bool = os.getenv("DRY_RUN", "1") == "1"
    # When DRY_RUN=0, this private key is used for live trading.
    private_key: str = os.getenv("POLY_PRIVATE_KEY", "") if not dry_run_mode else ""
    api_key: str = os.getenv("POLY_API_KEY", "")
    api_secret: str = os.getenv("POLY_API_SECRET", "")
    api_passphrase: str = os.getenv("POLY_PASSPHRASE", "")
    funder_address: str = os.getenv("POLY_FUNDER_ADDRESS", "")
    signature_type: int = int(os.getenv("POLY_SIGNATURE_TYPE", "0"))
    # Strategy parameters tuned for weather trading (Neobrother, Hans323, Atte)
    min_edge: float = 0.02  # Standard edge threshold
    deep_discount_min_edge: float = 0.05  # Higher threshold for low-price bets
    kelly_fraction: float = 0.25
    # DRY RUN: $30 total capital allocation - AGGRESSIVE MODE
    max_trade_usdc: float = 4.0  # $4 per trade max
    min_trade_usdc: float = 0.80  # $0.80 per trade min (allows more trades)
    min_liquidity: float = 200.0  # AGGRESSIVE: Lower liquidity requirement ($200+)
    max_open_positions: int = 10  # Up to 10 concurrent positions
    max_daily_loss: float = 30.0  # Full $30 at risk per day
    max_daily_trades: int = 50  # AGGRESSIVE: Many more trades
    poll_interval: int = 45  # Check every 45s for new opportunities
    min_hours_to_expiry: float = 0.5
    max_hours_to_expiry: float = 48.0  # Focus on 24-48h markets (quick resolution)
    min_our_prob: float = 0.55  # Standard confidence threshold
    max_our_prob: float = 0.95
    log_dir: str = "logs"
    data_dir: str = "data"

CFG = TradingConfig()
