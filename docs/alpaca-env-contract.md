# Alpaca Environment Variable Contract

This repository uses one canonical Alpaca env scheme for market data and execution config.

- Live trading remains disabled by default (`LIVE_TRADING=false`).
- Worker execution remains paper-only unless explicitly enabled (`PAPER_TRADING=true` and `WORKER_ENABLE_TRADING=true`).

## Canonical Variables

| Variable | Web Service | Worker Service | Purpose | Source | Safe Initial Value |
|---|---|---|---|---|---|
| `ALPACA_API_KEY` | If using `DATA_PROVIDER=alpaca` | If using `DATA_PROVIDER=alpaca` | Alpaca API key used by market-data and execution config loading | Alpaca | Empty (when using synthetic data) |
| `ALPACA_API_SECRET` | If using `DATA_PROVIDER=alpaca` | If using `DATA_PROVIDER=alpaca` | Alpaca API secret used by market-data and execution config loading | Alpaca | Empty (when using synthetic data) |
| `ALPACA_DATA_BASE_URL` | Optional | Optional | Market-data API base URL | Alpaca/default | `https://data.alpaca.markets` |
| `ALPACA_DATA_FEED` | Optional | Optional | Market-data feed selector | Alpaca/default | `iex` |
| `ALPACA_BASE_URL` | Optional (recommended) | Recommended | Canonical execution base URL for Alpaca-compatible broker routing | Alpaca/default | `https://paper-api.alpaca.markets` |

## Temporary Backward Compatibility

`ALPACA_SECRET_KEY` is still accepted as a temporary fallback alias for `ALPACA_API_SECRET`.

- Canonical name: `ALPACA_API_SECRET`
- Migration recommendation: set `ALPACA_API_SECRET` on both services and remove `ALPACA_SECRET_KEY`

## Render Service Placement

- Web service:
  - Always set `DATA_PROVIDER` explicitly.
  - Set Alpaca market-data vars when web-triggered backtests should use real Alpaca bars.
- Worker service:
  - Set the same market-data vars if worker loops fetch Alpaca bars.
  - Set `ALPACA_BASE_URL` for canonical execution config consistency.

In production paper deployment, keep:
- `LIVE_TRADING=false`
- `PAPER_TRADING=false` until you explicitly want paper orders
- `WORKER_ENABLE_TRADING=false` until worker execution is intentionally turned on
