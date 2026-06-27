# Remote access: private permanent URL with Tailscale

This gives you ONE permanent `https://...ts.net` link you can open from your
desktop and your phone — **reachable only by your own devices**. Nothing is
exposed to the public internet, and the URL never changes.

"Private" here means Tailscale `serve`: only devices logged into your Tailscale
account (your PC and your phone) can reach the dashboard. The manager UI controls
a **live trading bot**, so this is the safest way to reach it remotely.

---

## One-time setup (do this once)

1. In `.env` set:
   ```
   REMOTE_MODE=tailscale
   # MGMT_PASSWORD is optional in private mode (see "Passwords" below)
   ```

2. Run the setup helper (PowerShell, in the project folder):
   ```powershell
   _SCRIPTS\SETUP_REMOTE_TAILSCALE.ps1
   ```
   It will:
   - install Tailscale (via `winget`) if it isn't already,
   - log you in (`tailscale up` — a browser opens the first time),
   - serve the dashboard port privately (`tailscale serve --bg 7731`),
   - print your permanent URL and save it to `logs\remote_url.txt`.

3. Install the **Tailscale app on your phone** (App Store / Play Store) and log
   in to the **same account**. That's what lets the phone reach the private URL.

4. First time only: if the script prints an **"HTTPS is not enabled"** link,
   open it and enable **MagicDNS + HTTPS** for your tailnet in the Tailscale
   admin console, then re-run the script. One-time account setting.

---

## Daily use

Start the system as usual:
```powershell
_SCRIPTS\START_AGENT.ps1
```
With `REMOTE_MODE=tailscale`, it re-applies the private serve and prints your
**Local**, **WiFi**, and **Remote** URLs. The Remote URL is the same every time —
bookmark it on both devices. The phone just needs Tailscale connected.

---

## Passwords

In private mode a password is **optional**: only your own authenticated devices
can reach the URL, so the tailnet itself is the gate. If you want an extra login
on top anyway, set `MGMT_PASSWORD=...` in `.env` and log in with any username +
that password. (For the public modes below, `MGMT_PASSWORD` is required.)

---

## Switching modes

In `.env`, set `REMOTE_MODE` to:
- `tailscale` — **private** permanent URL (recommended). Your devices only.
- `tailscale-public` — Tailscale **Funnel**: public permanent URL, anyone with
  the link can reach it. Requires `MGMT_PASSWORD`.
- `cloudflare` — public random `trycloudflare.com` URL each run (needs
  `cloudflared`). Requires `MGMT_PASSWORD`.
- `off` — no remote access; only `http://localhost:7731` and the same-WiFi URL.

---

## Troubleshooting

- **`tailscale` not found after install** — close and reopen PowerShell so PATH
  refreshes, then re-run the setup script.
- **URL didn't print** — run `tailscale serve status`, or `tailscale status --json`
  and look at `Self.DNSName`.
- **Phone can't load it** — make sure the Tailscale app is installed, logged into
  the same account, and toggled **on**. Confirm the dashboard runs locally
  (`http://localhost:7731` works on the PC).
- **Want it public instead** (any browser, no Tailscale app on the phone) — set
  `REMOTE_MODE=tailscale-public` and a `MGMT_PASSWORD`.
