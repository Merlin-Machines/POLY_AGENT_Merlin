# Runtime Handoff

This document anchors the runtime side of the project so GitHub can be the
shared coordination layer between operator intent, Chat dev work, and Codex.

## Current Repo Roles

- `POLY_AGENT_Merlin`
  - live runtime repo
  - current execution loop
  - current dashboard/control surface
  - current manager runtime profile logic

- `vault`
  - cleaner repo-side manager/interface work
  - shared collaboration repo for MGMT UI and manager abstractions
  - current shared draft PR: `https://github.com/Merlin-Machines/vault/pull/2`

## Runtime Map

- `agent/main.py`
  - market scan loop
  - crypto and weather opportunity analysis
  - news and weather context
  - runtime cycle logging

- `agent/executor.py`
  - dry-run/live execution wrapper
  - local position tracking
  - exit handling
  - DCA and stop/flat-exit behavior

- `dashboard_server.py`
  - current runtime control surface
  - dashboard API
  - manager API bridge
  - integration status endpoint
  - `/mgmt` manager page serving

- `manager.py`
  - manager directive profile state
  - live vs baseline handling
  - validation, replay, review, and profile diff logic

- `dashboard/manager.html`
  - separate MGMT operator surface
  - live directives
  - safe knobs
  - validation and review display
  - integration visibility
  - TradingView widget

## Current Direction

- Manager directly guides the live agent rather than blocking on approval-only
  flows.
- Safe runtime knobs stay operator-visible and update the live manager profile.
- Code-level strategy changes still belong in a dev workflow, then can be
  promoted back into runtime safely.

## Recent Runtime Work

- added a dedicated `/mgmt` control-room UI
- wired NOAA weather.gov data
- wired optional Weather Company API support
- wired optional WeatherAPI via RapidAPI support
- wired TradingView widget embedding
- aligned manager state around live directives and saved baselines

## Collaboration Guidance

1. Use this repo for runtime behavior and control-surface truth.
2. Use `vault` for cleaner manager/interface architecture work.
3. Use PRs as the main discussion surface when work crosses repo boundaries.
4. When porting ideas between repos, note the source repo and intended target.

## Immediate Shared Reference

- Runtime repo: `https://github.com/Merlin-Machines/POLY_AGENT_Merlin`
- Shared manager repo: `https://github.com/Merlin-Machines/vault`
- Shared manager draft PR: `https://github.com/Merlin-Machines/vault/pull/2`
