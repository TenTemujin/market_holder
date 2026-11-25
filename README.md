<p align="center"><img src="docs/assets/logo.svg" alt="Market Holder" width="640"></p>

<p align="center">
  <b>Multi-asset market simulator with a professional-terminal look.</b><br>
  Real market data, simulated execution, replay or live.
</p>

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.12%2B-ffa028?labelColor=000">
  <img alt="react" src="https://img.shields.io/badge/react-19-ffa028?labelColor=000">
  <img alt="tests" src="https://img.shields.io/badge/tests-155%20py%20%C2%B7%2034%20web-00d26a?labelColor=000">
  <img alt="status" src="https://img.shields.io/badge/status-early%20development-ff3b3b?labelColor=000">
</p>

---

> **Paper trading only.** No real orders, no real money. Quotes come from public sources, some of them unofficial and delayed; every quote on screen shows its source and delay, and simulated data is labelled as such. Not financial advice.

## What it does

- **Trade 140+ ready-made securities** (indices, US/Brazil/Europe/Asia stocks, ETFs, commodities, FX, crypto) or **search any security** by name or ticker.
- **Replay** a past period at any speed, or go **live** (crypto quotes in real time over WebSocket, other sources by closed bar). Both use the same code path; only the clock changes.
- **Realistic execution engine:** market, limit, stop and stop-limit orders, DAY/GTC, slippage, fees, margin, OCO groups and bracket orders. No lookahead: an order only matches candles at or after its timestamp. When stop and target fit in the same bar, the stop fills first (worst case for the trader).
- **Terminal-style interface:** command line (`AAPL US Equity GP`, `PETR4 BZ Equity GP`), F1..F10 panels, tabbed layouts you can save and load, quote tape, world clocks, one-click MKT buy/sell, blotter, live order book (Binance), price chart with fills and working orders.
- **Automatic FX:** securities in any currency are converted to your base currency using the rate at the session start.

## Quick start

Requirements: Python 3.12+, Node 20+.

```bash
# backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[api,dev]"      # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m uvicorn market_holder.api.app:create_app --factory --port 8000

# frontend (another terminal)
npm --prefix web install
npm --prefix web run dev                                  # proxies /api to :8000
```

Open the URL Vite prints, press **F10** (REPLAY), pick securities and **Create session**.

## Commands

| Task | Command |
|---|---|
| Backend tests | `pytest -q` |
| Lint | `ruff check .` |
| Web tests | `npm --prefix web test` |
| Typecheck | `npm --prefix web run typecheck` |
| Browser acceptance | `CHROME_PATH=<chromium> npm --prefix web run e2e` |

## Architecture

```
src/market_holder/
  domain/      Instrument, Bar, Tick, Order, Fill, Position, Portfolio
  engine/      execution, margin, P&L (imports no web or provider code)
  providers/   one module per data source, all implementing Provider
  clock/       ReplayClock and LiveClock
  api/         FastAPI REST + WebSocket
web/           React + Vite + lightweight-charts + flexlayout-react
tests/         hand-calculated engine tests
```

Symbols follow `CLASS:MARKET:TICKER`, e.g. `EQ:US:AAPL`, `EQ:B3:PETR4`, `CRYPTO:BINANCE:BTCUSDT`, `INDEX:YAHOO:GSPC`.

## Data sources

| Source | Covers | Official |
|---|---|---|
| Binance | crypto, real-time order book and quotes | yes |
| BCB (SGS, PTAX) | Brazilian rates and FX | yes |
| FRED | US rates and macro series | yes |
| Tesouro Direto | Brazilian government bonds | yes |
| Yahoo Finance | stocks, indices, FX, futures worldwide | **no** (undocumented API, may change or block) |

Known limits: Yahoo indices default to USD as currency, futures are all labelled `CME`, tickers with a dot (e.g. `BRK.B`) are skipped by search, and there is no news, alerts or options/futures simulation yet. See [PLANO.md](PLANO.md) for the roadmap.

## Disclaimer

Inspired by the conventions of professional trading terminals. Not affiliated with, endorsed by, or derived from any terminal vendor; no third-party brand, logo, font or code is used.
