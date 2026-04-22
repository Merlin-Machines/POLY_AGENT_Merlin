# Polymarket System: Architecture Map and V2 Rebuild Plan

## 1. What the current system is

This export is a Python-based Polymarket trading bot plus a local dashboard.
It mixes market discovery, signal generation, execution, persistence, and UI
serving in a small set of files.

Core pieces:

- `agent/main.py`
  Runs the polling loop, fetches market and pricing data, generates weather and
  crypto opportunities, creates synthetic/fallback trades in dry-run mode, and
  passes selected trades to the executor.
- `agent/executor.py`
  Wraps Polymarket CLOB auth and order placement, tracks open positions and
  trade history, and persists state to JSON files under `data/`.
- `config.py`
  Loads environment variables and risk parameters into a dataclass.
- `dashboard_server.py`
  Serves the dashboard and reads local files (`logs/agent.log`,
  `data/trades.json`, `data/positions.json`) to build simple API responses.
- `dashboard/index.html`
  A single-page dashboard UI that polls the local HTTP server.
- `strategies/edge_calculator.py`
  A more structured edge calculator for threshold-style markets, but it is not
  the primary engine used by `agent/main.py`.
- `utils/`
  Lightweight helpers for market scanning and price feed access.

## 2. Runtime flow

1. `config.py` loads env vars and builds `CFG`.
2. `agent/main.py` instantiates `TradeExecutor(CFG)`.
3. `TradeExecutor` switches to live mode only when a private key is present.
4. Each cycle, the agent:
   - checks open positions for time-based exits
   - fetches BTC and ETH spot prices
   - fetches 5-minute crypto candles
   - fetches active Polymarket markets from `gamma-api.polymarket.com`
   - estimates probabilities for weather and crypto questions
   - falls back to synthetic or contrarian trade generation when few signals exist
   - executes up to five candidate opportunities
5. The executor writes updated trade and position state to `data/`.
6. The dashboard server reads logs and state files and exposes local JSON APIs.
7. The dashboard page polls those APIs and renders account, trade, and log data.

## 3. External dependencies

Primary external services:

- Polymarket Gamma API for market discovery
- Polymarket CLOB API for order placement
- Weather.gov and Open-Meteo for weather observations and forecast data
- Binance for 5-minute crypto candles
- CryptoCompare and Coinbase for fallback spot prices

Python dependencies:

- `py_clob_client`
- `eth-account`
- `web3`
- `requests`
- `python-dotenv`

## 4. Current design strengths

- Very fast to run and inspect
- Simple file-based persistence
- Dashboard is easy to host locally
- Dry-run mode exists
- Signal sources are easy to understand

## 5. Current design problems

- Hardcoded absolute paths point to a specific local machine
- Live trading can be enabled by credential presence alone
- Strategy logic, orchestration, and fallback behavior are tightly coupled
- Dashboard reads log files rather than a clean application state API
- No clear domain models for markets, signals, orders, fills, or exits
- Minimal testing and no simulation/backtest boundary
- Aggressive fallback logic can place trades with weak justification
- Weather and crypto logic live inside one monolithic file

## 6. Recommended V2 shape

Build V2 as a modular system with explicit layers:

- `app/`
  Startup, config loading, dependency wiring
- `domain/`
  Core models: Market, Signal, Opportunity, Position, Order, Fill, Portfolio
- `connectors/`
  Polymarket, weather, price feeds, storage
- `strategies/`
  Separate strategy modules:
  - `weather_ranges.py`
  - `crypto_thresholds.py`
  - `fallback_disabled.py` or `sandbox_only.py`
- `risk/`
  Position sizing, daily loss checks, max exposure, market filters
- `execution/`
  Order creation, retries, dry-run/live broker interface
- `storage/`
  SQLite or Postgres-backed persistence instead of raw JSON
- `api/`
  Small FastAPI service for dashboard and control actions
- `dashboard/`
  Frontend consuming the API instead of logs
- `tests/`
  Strategy unit tests, connector contract tests, and dry-run integration tests

## 7. V2 development order

Phase 1: Safe foundation

- Remove hardcoded absolute paths
- Make dry-run the default everywhere
- Split configuration into a typed settings module
- Replace `.env` secrets with `.env.example`
- Add a proper `.gitignore`

Phase 2: Separate concerns

- Move weather logic out of `agent/main.py`
- Move crypto logic out of `agent/main.py`
- Isolate opportunity scoring from execution
- Remove synthetic forced-trade behavior from production paths

Phase 3: Stable state and observability

- Replace JSON state files with SQLite
- Add structured logs
- Expose a proper API for stats, trades, positions, and health

Phase 4: Safer trading controls

- Add a broker abstraction with explicit dry-run and live implementations
- Require an explicit `LIVE_TRADING_ENABLED=true` gate in addition to keys
- Add preflight checks before any live order
- Add paper-trade replay and backtesting inputs

Phase 5: Better dashboard

- Keep the current aesthetic direction
- Rebuild on top of a clean API
- Show strategy source, signal reasons, and risk state
- Add a clear live-vs-dry badge and last-successful-feed timestamps

## 8. Immediate next build target

The best next move is not to keep extending the current monolith. Build a
`polymarket_v2` skeleton beside this export and migrate one concern at a time:

1. config and app bootstrap
2. domain models
3. market feed connector
4. strategy interface
5. dry-run executor
6. API and dashboard

This preserves the original export as a reference while giving us a cleaner path
to a travel-friendly and eventually cloud-hostable system.
