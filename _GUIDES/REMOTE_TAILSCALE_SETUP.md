# Remote access: permanent URL with Tailscale Funnel

This gives you ONE permanent `https://...ts.net` link you can open from your
desktop and your phone, from anywhere — no domain, no monthly fee, and the URL
never changes (unlike the old Cloudflare quick tunnel, which made a new random
URL every restart).

The manager UI controls a **live trading bot**, and Funnel is on the public
internet, so this setup keeps the `MGMT_PASSWORD` login in front of it.

---

## One-time setup (do this once)

1. Set a password. In `.env` add:
   ```
   MGMT_PASSWORD=pick-a-strong-password
   REMOTE_MODE=tailscale
   ```

2. Run the setup helper (PowerShell, in the project folder):
   ```powershell
   _SCRIPTS\SETUP_REMOTE_TAILSCALE.ps1
   ```
   It will:
   - install Tailscale (via `winget`) if it isn't already,
   - log you in (`tailscale up` — a browser opens the first time),
   - turn on Funnel for the dashboard port (`tailscale funnel --bg 7731`),
   - print your permanent URL and save it to `logs\remote_url.txt`.

3. First time only: if the script prints a **"Funnel is not enabled"** link,
   open it, click through to enable **Funnel** and **HTTPS** for your tailnet in
   the Tailscale admin console, then re-run the script. This is a one-time
   account setting.

---

## Daily use

Just start the system as usual:
```powershell
_SCRIPTS\START_AGENT.ps1
```
With `REMOTE_MODE=tailscale`, it re-applies Funnel and prints your **Local**,
**WiFi**, and **Remote** URLs. The Remote URL is the same every time — bookmark
it on both devices. Log in with **any username + your `MGMT_PASSWORD`**.

---

## Switching providers

In `.env`, set `REMOTE_MODE` to:
- `tailscale` — permanent URL (recommended).
- `cloudflare` — old behaviour: random `trycloudflare.com` URL each run (needs
  `cloudflared` installed).
- `off` — no public access; only `http://localhost:7731` and the same-WiFi URL.

---

## Troubleshooting

- **`tailscale` not found after install** — close and reopen PowerShell so PATH
  refreshes, then re-run the setup script.
- **URL didn't print** — run `tailscale funnel status` to see the active URL, or
  `tailscale status --json` and look at `Self.DNSName`.
- **Phone can't load it** — confirm Funnel is enabled in the admin console and
  that the dashboard is running locally (`http://localhost:7731` works on the PC).
- **Want it private instead of public** — use `tailscale serve 7731` instead of
  Funnel and install the Tailscale app on your phone; then only your own devices
  can reach it (no public exposure at all).
