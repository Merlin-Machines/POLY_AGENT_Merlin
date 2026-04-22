# polymarket_v2 scaffold

This folder is the clean V2 foundation for rebuilding the agent safely.

## Goals

- Keep `DRY_RUN` as the default runtime mode
- Separate strategy logic from execution and transport concerns
- Make connectors replaceable (Polymarket, Binance, weather feeds)
- Add an API layer for dashboard/control
- Create a clear path for testing and backtesting

## Layout

- `app/` bootstrap and typed settings
- `domain/` core models and enums
- `strategies/` signal generation interface + implementations
- `execution/` broker abstraction + dry-run broker
- `connectors/` data providers and exchange adapters
- `api/` service entrypoint

## Next steps

1. Implement `connectors/polymarket_clob.py` with explicit live gating.
2. Add `connectors/binance_market_data.py` for account and market reads.
3. Add SQLite persistence and structured event logs.
4. Add tests for strategies and risk rules before enabling live execution.
