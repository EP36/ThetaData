#!/usr/bin/env python3
"""Funding rate arbitrage monitor for Hyperliquid spot-perp.

Strategy:
  - Long spot BTC/ETH/SOL on Hyperliquid spot
  - Short equal size on Hyperliquid perp
  - Collect hourly funding when rate > 0.15%
  - Delta-neutral: price moves cancel out, profit = funding - fees

Break-even: 0.11%/hr (maker orders: spot 0.04%x2 + perp 0.015%x2)
Target:     >0.15%/hr for meaningful profit

Usage:
  cd /opt/trauto && source .venv/bin/activate
  python3 -m funding_arb.monitor            # scan loop
  python3 -m funding_arb.monitor --once     # single scan
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("theta.funding_arb")

# Env vars (set in /etc/trauto/env):
#   HL_MIN_FUNDING_RATE   float  default=0.0015  (0.15%/hr minimum to flag)
#   HL_MAX_POSITION_USD   float  default=50      (position size when executing)
#   HL_DRY_RUN            bool   default=true    (set false to enable HL execution)
#   HL_SCAN_INTERVAL_SEC  int    default=60      (seconds between scans)
#   COINBASE_API_KEY      str    (organizations/xxx/apiKeys/xxx)
#   COINBASE_API_SECRET   str    (EC private key PEM)
#   BASIS_DRY_RUN         bool   default=true    (set false to enable basis execution)
#   MIN_BASIS_PCT         float  default=1.0     (minimum annual % to trigger basis trade)

HL_BASE_URL       = "https://api.hyperliquid.xyz"
MAKER_FEE_SPOT    = 0.00040
MAKER_FEE_PERP    = 0.00015
ROUND_TRIP_FEES   = (MAKER_FEE_SPOT + MAKER_FEE_PERP) * 2   # 0.110%
MIN_RATE_DEFAULT  = 0.0015    # 0.15%/hr
SCAN_INTERVAL_SEC = 60
ELIGIBLE_ASSETS   = {"BTC", "ETH", "SOL", "HYPE", "WIF", "DOGE", "AVAX", "ONDO"}


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        for line in open("/etc/trauto/env"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    env.update({k: v for k, v in os.environ.items()})
    return env


def _hl_post(payload: dict[str, Any], timeout: float = 10.0) -> Any:
    resp = httpx.post(f"{HL_BASE_URL}/info", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_funding_rates() -> list[dict[str, Any]]:
    data = _hl_post({"type": "metaAndAssetCtxs"})
    meta, ctxs = data[0], data[1]
    results = []
    for i, ctx in enumerate(ctxs):
        name = meta["universe"][i]["name"]
        if name not in ELIGIBLE_ASSETS:
            continue
        rate = float(ctx.get("funding", 0))
        mark = float(ctx.get("markPx", 0))
        results.append({
            "asset":      name,
            "rate":       rate,
            "rate_pct":   rate * 100,
            "annual_pct": rate * 100 * 24 * 365,
            "mark_px":    mark,
        })
    results.sort(key=lambda x: x["rate"], reverse=True)
    return results


def get_predicted_rates() -> dict[str, float]:
    data = _hl_post({"type": "predictedFundings"})
    out: dict[str, float] = {}
    for item in data:
        asset = item[0]
        if asset not in ELIGIBLE_ASSETS:
            continue
        for src, details in item[1]:
            if src == "HlPerp" and "fundingRate" in details:
                out[asset] = float(details["fundingRate"])
    return out


def seconds_to_next_funding() -> int:
    now = datetime.now(timezone.utc)
    return 3600 - (now.minute * 60 + now.second)


def _hl_spot_price(asset: str) -> float:
    """Fetch spot price from Hyperliquid spotMetaAndAssetCtxs as fallback."""
    try:
        resp = httpx.post(
            f"{HL_BASE_URL}/info",
            json={"type": "spotMetaAndAssetCtxs"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        spot_meta, spot_ctxs = data[0], data[1]
        for token in spot_meta.get("tokens", []):
            if token.get("name") == asset:
                idx = token.get("index")
                if idx is not None and idx < len(spot_ctxs):
                    px = float(spot_ctxs[idx].get("midPx") or 0)
                    return px
                break
    except Exception as exc:
        LOGGER.debug("hl_spot_price_failed asset=%s error=%s", asset, exc)
    return 0.0


def calculate_basis_vs_spot(asset: str, mark_px: float) -> dict[str, Any]:
    """Compare perp mark price vs real Coinbase spot price (HL proxy as fallback).

    Returns basis in $ and % terms. A positive basis (contango) means perp > spot,
    which independently confirms positive funding is likely to persist.

    Fields: basis_usd, basis_pct, mark_px, spot_px, spot_source
    """
    spot_px     = 0.0
    spot_source = "none"

    # Primary: Coinbase real spot feed
    try:
        from funding_arb.coinbase_client import get_coinbase_client, get_spot_mid
        cb = get_coinbase_client()
        if cb is not None:
            px = get_spot_mid(asset)
            if px > 0:
                spot_px     = px
                spot_source = "coinbase"
    except Exception as exc:
        LOGGER.debug("coinbase_spot_lookup_failed asset=%s error=%s", asset, exc)

    # Fallback: Hyperliquid spot proxy
    if spot_px <= 0:
        px = _hl_spot_price(asset)
        if px > 0:
            spot_px     = px
            spot_source = "hyperliquid_proxy"

    if spot_px <= 0:
        return {
            "basis_usd":  0.0,
            "basis_pct":  0.0,
            "mark_px":    mark_px,
            "spot_px":    0.0,
            "spot_source": "none",
        }

    basis_usd = mark_px - spot_px
    basis_pct = (basis_usd / spot_px) * 100.0
    return {
        "basis_usd":   round(basis_usd, 4),
        "basis_pct":   round(basis_pct, 4),
        "mark_px":     mark_px,
        "spot_px":     spot_px,
        "spot_source": spot_source,
    }


def compare_carry(
    asset: str,
    funding_rate_pct: float,
    mark_px: float,
    pos_size_usd: float,
) -> dict[str, Any]:
    """Compare funding arb vs basis arb and return the better strategy.

    funding_rate_pct: current hourly funding rate as a percentage (e.g. 0.15 for 0.15%/hr)

    Returns:
        strategy:            "funding" | "basis" | "no_trade"
        funding_annual_pct:  annualized funding return %
        basis_annual_pct:    annualized basis return % (basis_pct * 52 weekly proxy)
        basis_pct:           raw spot-perp basis %
        spot_source:         "coinbase" | "hyperliquid_proxy" | "none"
        reason:              human-readable explanation
    """
    basis_info      = calculate_basis_vs_spot(asset, mark_px)
    basis_pct       = basis_info["basis_pct"]
    spot_source     = basis_info["spot_source"]
    funding_annual  = funding_rate_pct * 3 * 365      # 3 funding periods/day * 365
    basis_annual    = basis_pct * 52                  # weekly proxy: 52 weeks/year

    MIN_ANNUAL_PCT = float(os.getenv("MIN_BASIS_PCT", "1.0"))

    if funding_annual >= basis_annual and funding_annual > MIN_ANNUAL_PCT:
        strategy = "funding"
        reason   = (
            f"funding_annual={funding_annual:.2f}% > basis_annual={basis_annual:.2f}% "
            f"and > {MIN_ANNUAL_PCT}% threshold"
        )
    elif basis_annual > funding_annual and basis_annual > MIN_ANNUAL_PCT:
        strategy = "basis"
        reason   = (
            f"basis_annual={basis_annual:.2f}% > funding_annual={funding_annual:.2f}% "
            f"and > {MIN_ANNUAL_PCT}% threshold"
        )
    else:
        strategy = "no_trade"
        reason   = (
            f"neither strategy meets {MIN_ANNUAL_PCT}% threshold "
            f"(funding_annual={funding_annual:.2f}% basis_annual={basis_annual:.2f}%)"
        )

    result: dict[str, Any] = {
        "strategy":           strategy,
        "funding_annual_pct": round(funding_annual, 4),
        "basis_annual_pct":   round(basis_annual, 4),
        "basis_pct":          round(basis_pct, 4),
        "spot_source":        spot_source,
        "reason":             reason,
    }

    LOGGER.info(
        "fundingarb_carry_comparison asset=%s strategy=%s "
        "funding_annual=%.2f basis_annual=%.2f basis_pct=%.4f spot_source=%s",
        asset, strategy, funding_annual, basis_annual, basis_pct, spot_source,
    )
    return result


def calc_profit(rate: float, position_usd: float) -> dict[str, float]:
    gross   = rate * position_usd
    fees    = ROUND_TRIP_FEES * position_usd
    net     = gross - fees
    break_e = fees / (rate * position_usd) if rate > 0 else float("inf")
    return {
        "gross_usd":        round(gross, 4),
        "fees_usd":         round(fees, 4),
        "net_usd":          round(net, 4),
        "break_even_hours": round(break_e, 2),
    }


def scan_once(config: dict[str, str]) -> None:
    min_rate  = float(config.get("HL_MIN_FUNDING_RATE", MIN_RATE_DEFAULT))
    pos_usd   = float(config.get("HL_MAX_POSITION_USD", 50))
    dry_run   = config.get("HL_DRY_RUN", "true").lower() != "false"
    secs_left = seconds_to_next_funding()

    LOGGER.info(
        "funding_arb_scan min_rate=%.4f%% pos_usd=%.0f dry_run=%s next_funding_sec=%d",
        min_rate * 100, pos_usd, dry_run, secs_left,
    )

    try:
        rates     = get_funding_rates()
        predicted = get_predicted_rates()
    except Exception as exc:
        LOGGER.warning("funding_arb_fetch_failed error=%s", exc)
        return

    opps = 0
    for r in rates:
        asset     = r["asset"]
        cur_rate  = r["rate"]
        pred_rate = predicted.get(asset, 0.0)
        profit    = calc_profit(cur_rate, pos_usd)
        good      = cur_rate >= min_rate and pred_rate >= min_rate * 0.7

        LOGGER.info(
            "funding_arb_rate asset=%s rate=%.4f%% predicted=%.4f%% "
            "annual=%.1f%% net_per_cycle=$%.4f break_even_hrs=%.1f actionable=%s",
            asset, cur_rate * 100, pred_rate * 100,
            r["annual_pct"], profit["net_usd"],
            profit["break_even_hours"], good,
        )

        if good:
            opps += 1
            carry = compare_carry(asset, cur_rate * 100, r["mark_px"], pos_usd)
            LOGGER.info(
                "funding_arb_OPPORTUNITY asset=%s rate=%.4f%% net_usd=$%.4f "
                "basis_pct=%.4f%% spot_source=%s carry_strategy=%s "
                "time_to_funding_sec=%d — %s",
                asset, cur_rate * 100, profit["net_usd"],
                carry["basis_pct"], carry["spot_source"], carry["strategy"],
                secs_left,
                "ENTER NOW (within 15min window)" if secs_left <= 900 else "monitor",
            )
            LOGGER.info(
                "fundingarb_carry_selected asset=%s strategy=%s "
                "funding_annual=%.2f basis_annual=%.2f reason=%s",
                asset, carry["strategy"],
                carry["funding_annual_pct"], carry["basis_annual_pct"],
                carry["reason"],
            )

            if secs_left <= 900:  # only enter within 15min of funding
                private_key = config.get("HL_PRIVATE_KEY", "").strip()
                wallet      = config.get("HL_WALLET", "").strip()
                basis_dry_run = config.get("BASIS_DRY_RUN", "true").lower() != "false"

                if carry["strategy"] == "funding":
                    if not private_key or not wallet:
                        LOGGER.warning(
                            "funding_arb_execution_skipped reason=missing_credentials "
                            "set HL_PRIVATE_KEY and HL_WALLET in /etc/trauto/env"
                        )
                    else:
                        from funding_arb.executor import enter_arb
                        enter_arb(
                            private_key=private_key,
                            wallet=wallet,
                            asset=asset,
                            size_usd=pos_usd,
                            dry_run=dry_run,
                        )
                elif carry["strategy"] == "basis":
                    from funding_arb.executor import open_basis_trade
                    open_basis_trade(
                        private_key=private_key,
                        wallet=wallet,
                        asset=asset,
                        basis_pct=carry["basis_pct"],
                        pos_size_usd=pos_usd,
                        dry_run=basis_dry_run,
                    )
                else:
                    LOGGER.info(
                        "funding_arb_no_trade_taken asset=%s reason=%s",
                        asset, carry["reason"],
                    )

    if opps == 0:
        LOGGER.info(
            "funding_arb_no_opportunities min_rate=%.4f%% — rates below threshold",
            min_rate * 100,
        )

    LOGGER.info("funding_arb_scan_complete assets=%d opportunities=%d", len(rates), opps)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = _load_env()
    LOGGER.info("funding_arb_monitor_start interval_sec=%d", SCAN_INTERVAL_SEC)
    while True:
        scan_once(config)
        if args.once:
            break
        time.sleep(SCAN_INTERVAL_SEC)


def run_background(config: dict[str, str] | None = None) -> None:
    """Run the funding arb monitor in a background thread loop.

    Designed to be called via threading.Thread(target=run_background).
    Never raises — all errors are caught and logged.
    Reads config from /etc/trauto/env if config is None.
    """
    if config is None:
        config = _load_env()

    interval = int(config.get("HL_SCAN_INTERVAL_SEC", SCAN_INTERVAL_SEC))
    LOGGER.info("funding_arb_background_thread_start interval_sec=%d", interval)

    while True:
        try:
            scan_once(config)
        except Exception as exc:
            LOGGER.error("funding_arb_background_error error=%s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()
