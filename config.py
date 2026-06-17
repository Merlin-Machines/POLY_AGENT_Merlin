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
    kelly_fraction: float = 0.25  # quarter-Kelly: sizing stays conservative even when active
    # BALANCED-ACTIVE preset (2026-06-03 tune). risk_schedule.py shifts these between
    # an aggressive and a balanced set at runtime; these are the aggressive/baseline values.
    # Sized for a SMALL (~$8-10) bankroll. Polymarket's order floor is ~$1 notional.
    max_trade_usdc: float = 1.5   # ~1-2 positions' worth per bet on a tiny account
    min_trade_usdc: float = 1.0   # must clear Polymarket's ~$1 minimum order
    min_liquidity: float = 250.0  # avoids thin books / bad-fill tail risk
    max_open_positions: int = 4   # a few concurrent positions on a small bankroll
    max_daily_loss: float = 4.0   # must be < total bankroll or it never triggers
    max_daily_trades: int = 60    # raised from 50: headroom for more churn
    max_consecutive_losses: int = 4      # pause new entries after N losing closes in a row
    loss_cooldown_minutes: float = 20.0  # how long to pause once that streak trips
    poll_interval: int = 30       # 45->30s: more re-evaluation cycles = more churn opportunity
    min_hours_to_expiry: float = 0.5
    max_hours_to_expiry: float = 48.0
    min_our_prob: float = 0.53    # 0.55->0.53: prob gate was rejecting most candidates
    max_our_prob: float = 0.95
    crypto_ml_filter_enabled: bool = os.getenv("CRYPTO_ML_FILTER_ENABLED", "0") == "1"
    crypto_ml_approval_threshold: float = float(os.getenv("CRYPTO_ML_APPROVAL_THRESHOLD", "0.55"))
    crypto_ml_model_path: str = os.getenv("CRYPTO_ML_MODEL_PATH", "data/ml_filter.pkl")
    crypto_ml_scaler_path: str = os.getenv("CRYPTO_ML_SCALER_PATH", "data/ml_scaler.pkl")
    crypto_ml_fail_open_dry_run: bool = os.getenv("CRYPTO_ML_FAIL_OPEN_DRY_RUN", "1") == "1"
    log_dir: str = "logs"
    data_dir: str = "data"

CFG = TradingConfig()
