# MMMMMerlin Polymarket Trading Agent

Autonomous Polymarket CLOB trading agent with weather + crypto strategies,
5-minute candle analysis, forced-trade fallback logic, and a live dashboard.

---

## 1. What's in this folder

```
polymarket_system_EXPORT/
├── agent/
│   ├── __init__.py
│   ├── main.py              # Main loop: market scan, opportunity analysis, exec
│   └── executor.py          # CLOB client wrapper (auth, order placement, state)
├── dashboard/
│   └── index.html           # Live dashboard UI (auto-refreshes via fetch)
├── strategies/
│   ├── __init__.py
│   └── edge_calculator.py
├── utils/
│   ├── __init__.py
│   ├── market_scanner.py
│   └── price_feed.py
├── config.py                # TradingConfig dataclass (reads .env)
├── dashboard_server.py      # Tiny Flask/HTTP server for the dashboard
├── setup_credentials.py     # One-shot helper to populate .env
├── .env                     # Private key + wallet config (EDIT THIS)
├── requirements.txt         # Python deps (pip install -r)
└── README.md                # (this file)
```

At runtime the agent creates `logs/` and `data/` for logs and state
(`trades.json`, `positions.json`). These are safe to delete to reset state.

Security note:
- This workspace copy was sanitized for portability.
- The original exported `.env` was removed and replaced with `.env.example`.
- Keep `DRY_RUN=1` until you have intentionally re-added credentials and verified
  every live-trading code path.

---

## 2. Prerequisites on the new computer

### 2a. Python
Python **3.10+** (tested on 3.11/3.12). Download from python.org if missing.
Verify:
```
python --version
```

### 2b. Git (optional, for version control)
Not required to run — just handy.

### 2c. Claude Code (if you want Claude to operate the repo)
- Install Claude Code: https://docs.anthropic.com/claude/docs/claude-code
- No special extensions required — standard Claude Code defaults are fine.
- MCP servers used during development (all optional):
  - `computer-use` (for driving the desktop — not needed to run the agent)
  - `Claude_in_Chrome` (for browser automation — not needed to run the agent)
  - `ccd_session` (chapter/task tooling — not needed)
- The agent itself runs purely from Python — Claude Code is only needed if
  you want AI-assisted editing/debugging.

---

## 3. One-time setup on the new computer

Open a terminal in this folder:

```bash
cd path/to/polymarket_system_EXPORT
```

### 3a. Create a virtual environment (recommended)
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

### 3b. Install Python dependencies
```bash
pip install -r requirements.txt
```

If that fails on any package, install them individually:
```bash
pip install py_clob_client==0.34.6
pip install eth-account==0.13.7
pip install web3==7.15.0
pip install requests==2.33.1
pip install python-dotenv==1.2.2
```

### 3c. Configure `.env`
Copy `.env.example` to `.env`, then confirm it has:
```
POLY_PRIVATE_KEY=<64-char hex, NO 0x prefix — magic-link EOA private key>
POLY_SIGNER_ADDRESS=0x...        # Address derived from POLY_PRIVATE_KEY
POLY_FUNDER_ADDRESS=0x...        # Polymarket proxy/Safe (holds USDC)
POLY_SIGNATURE_TYPE=1            # 1 = magic-link proxy, 2 = MetaMask proxy
DRY_RUN=0                        # 0 = LIVE, 1 = DRY RUN (no real orders)
```

To get the magic-link key: polymarket.com → Wallet → **Export Private Key**.

### 3d. Verify the private key matches the signer address
```bash
python -c "from eth_account import Account; import os; from dotenv import load_dotenv; load_dotenv(); a=Account.from_key(os.getenv('POLY_PRIVATE_KEY')); print('Derives to:', a.address)"
```
The printed address MUST match `POLY_SIGNER_ADDRESS`.

---

## 4. Running the agent

### 4a. Start the trading agent (main loop)
```bash
python -m agent.main
```

Expected log on a healthy startup:
```
[INFO] ClobClient init | EOA signer + funder=0x... sig_type=1
[INFO] Polymarket CLOB connected | API creds derived: <key>...
[INFO] Agent STARTED | Weather+Crypto 5MIN CANDLES AGGRESSIVE | LIVE
[INFO] ========== Cycle #1 ==========
[INFO] PRICE | BTC: $...
[INFO] PRICE | ETH: $...
[INFO] Total markets: 100
[INFO] FORCED TRADE: <market question>
[INFO] LIVE YES $1 <symbol> order_id=<id>
```

If you see `DRY RUN` in the startup line, the client failed to auth and the
agent fell back to simulation. Check the lines above it for the error.

### 4b. Start the dashboard (optional, separate terminal)
```bash
python dashboard_server.py
```
Then open:
```
http://localhost:8080/
```
Or just double-click `dashboard/index.html` — it works as a static file too.

### 4c. Stop the agent
`Ctrl+C` in the agent terminal. State is saved to `data/` on every cycle.

---

## 5. Troubleshooting

### `401 Invalid L1 Request headers`
- System clock is wrong → Windows: Settings → Date & Time → toggle
  "Set time automatically" off then on. Or `w32tm /resync` in admin PowerShell.
- Wallet has never traded on Polymarket → place one small manual trade on
  polymarket.com to activate CLOB for this account.
- Account is locked → contact Polymarket support (discord.gg/polymarket → #support).
- Wrong key → the key must be the **magic-link EOA** export, not MetaMask.

### Agent starts but says `DRY RUN`
This means `_init_client` threw. Scroll up in the log for the real error.
Most common: auth failure (see above).

### `ModuleNotFoundError: py_clob_client`
You didn't activate the venv or didn't run `pip install -r requirements.txt`.

### FORCED TRADE keeps logging but no real order
That means auth failed and it's in DRY RUN. Fix auth, then restart.

### Clock drift
Polymarket rejects signatures whose timestamp is > ~5 minutes from server time.
Keep your system clock synced.

---

## 6. Kill switches / resetting state

- **Kill all python**:
  ```
  # Windows
  taskkill /F /IM python.exe
  # Mac/Linux
  pkill -9 python
  ```
- **Clear Python bytecode cache** (fixes "old code still running" bugs):
  ```
  # Windows (Git Bash or PowerShell)
  find . -type d -name __pycache__ -exec rm -rf {} +
  ```
- **Reset agent state** (clears open positions + trade history):
  ```
  rm -rf data/
  ```
- **Switch to DRY RUN** (no real orders, for testing): set `DRY_RUN=1` in `.env`.

---

## 7. Key account/wallet reference (as of export)

| Field                    | Value                                        |
|--------------------------|----------------------------------------------|
| Polymarket profile addr  | `0x3a42c601c99B290Ec2EA050b17a822408EFF03de` |
| Proxy / funder (USDC)    | `0x3a42c601c99B290Ec2EA050b17a822408EFF03de` |
| Magic-link signer (EOA)  | `0xD5ea025A9b0b523250020f65C4AB8C751a36c4f5` |
| Signature type           | `1` (magic-link proxy)                       |
| Account name             | mmmmmerlin                                   |

> Never commit `.env` to git. If a real private key was previously included in
> the export, treat it as exposed and rotate it on polymarket.com before using
> any live setup again.

---

## 8. Full reset / clean restart sequence

Copy-paste friendly:

```bash
# kill anything running
taskkill /F /IM python.exe 2>nul

# enter folder
cd C:\path\to\polymarket_system_EXPORT

# activate venv
venv\Scripts\activate

# clear bytecode
find . -type d -name __pycache__ -exec rm -rf {} +

# launch
python -m agent.main
```

---

## 9. Known blockers (as of export)

The only reason the agent wasn't placing live trades at export time was a
**Polymarket account-side lock** — neither the web UI, mobile app, nor the
CLOB API would accept trades for this wallet. Once the account is unlocked
(via Polymarket support), `python -m agent.main` will place a trade on the
first cycle. No code change needed.
