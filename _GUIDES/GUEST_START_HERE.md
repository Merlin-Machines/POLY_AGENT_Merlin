# Poly Agent Gift - Quick Start

This folder is prepared so another guest can connect their own Polymarket account quickly.

## 0) Quick launch (recommended)

Run:
`OPEN_SETUP_GUIDE.cmd`

It opens the main setup guide, your `.env`, and the Polymarket auth reference.

## 1) First-time setup

1. Open PowerShell in this folder.
2. Run:
   `SETUP_FIRST_TIME.cmd`
3. Open `.env` and fill in:
   - `ACCOUNT_NAME`
   - `POLY_PRIVATE_KEY`
   - `POLY_SIGNER_ADDRESS`
   - `POLY_FUNDER_ADDRESS`
   - `POLY_SIGNATURE_TYPE`
4. Keep `DRY_RUN=1` until credentials are verified.
5. Run:
   `VERIFY_ENV_LINK.cmd`
6. For full details, open:
   `_GUIDES\ENV_SETUP_QUICK_GUIDE.txt`
7. For very simple steps, open:
   `_GUIDES\NON_TECH_SETUP_STEPS.txt`

## 2) Run

- Agent:
  `START_AGENT.cmd`
- Dashboard (new PowerShell):
  `START_DASHBOARD.cmd`
- Open:
  `http://localhost:7731`

## 3) Dashboard controls

- `TRADING: ON/OFF` button toggles execution through `data/trading_enabled.flag`.
- `Live Portfolio` pulls wallet value, cash, and position rows from Polymarket profile/data endpoints.
- `Redeem Alerts` highlights live redeemable positions plus older local positions that may need claim/redeem checks.

## 4) Safety defaults

- If `.env` is missing keys, dashboard shows setup-needed state.
- If `TRADING` is OFF, agent monitors opportunities but does not execute.
- Keep clock synced to avoid auth signature drift.

## 5) PowerShell note

The `.ps1` versions still work if you are already inside PowerShell.
For most guests, use the `.cmd` launchers first because Windows handles them more reliably from Explorer.
