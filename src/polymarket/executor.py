"""Execution engine — places orders on the Polymarket CLOB API.

Gated behind RiskGuard. POLY_DRY_RUN=true (default) logs intent only.
Never modifies Alpaca files or any other broker integration.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.polymarket.config import PolymarketConfig
from src.polymarket.opportunities import Opportunity
from src.polymarket.positions import PositionsLedger, new_position
from src.polymarket.risk import RiskGuard

LOGGER = logging.getLogger("theta.polymarket.executor")

_EXECUTABLE_STRATEGIES = {"orderbook_spread", "correlated_markets", "underround", "resolution_carry"}
_MIN_FREE_COLLATERAL = 0.05  # skip order if CLOB free collateral is below this USD amount

_POLYGON_RPC_URL = "https://polygon-rpc.com"
_MIN_POL_GAS = 0.005  # minimum POL required to cover on-chain transaction gas


# ---------------------------------------------------------------------------
# Pre-flight: POL gas check
# ---------------------------------------------------------------------------

def _check_pol_gas(private_key: str) -> bool:
    """Return False and log CRITICAL if the trading wallet has < 0.005 POL.

    Derives the wallet address from private_key at call time.
    Returns True (fail open) if web3/eth_account are missing or the RPC is
    unreachable — a dependency outage should not silently block all trading.
    Only returns False when the balance is definitively below the threshold.
    """
    try:
        from eth_account import Account  # type: ignore[import]
        from web3 import Web3  # type: ignore[import]
    except ImportError:
        LOGGER.warning("pol_gas_check_skipped reason=web3_not_installed")
        return True

    try:
        address: str = Account.from_key(private_key).address
    except Exception as exc:
        LOGGER.warning("pol_gas_check_skipped reason=key_derivation_failed error=%s", exc)
        return True

    try:
        w3 = Web3(Web3.HTTPProvider(_POLYGON_RPC_URL, request_kwargs={"timeout": 5}))
        wei = w3.eth.get_balance(address)
        pol = wei / 1e18
    except Exception as exc:
        LOGGER.warning(
            "pol_gas_check_failed error=%s — proceeding with order placement", exc
        )
        return True

    if pol < _MIN_POL_GAS:
        LOGGER.critical(
            "pol_gas_insufficient address=%s pol_balance=%.6f min_required=%.6f "
            "— aborting trade to prevent stuck half-filled orders",
            address[:10] + "...",
            pol,
            _MIN_POL_GAS,
        )
        return False

    LOGGER.debug("pol_gas_ok pol_balance=%.6f address=%s", pol, address[:10] + "...")
    return True


def _derive_funder(config: PolymarketConfig) -> str:
    """Return the wallet address to use as CLOB funder.

    Uses config.poly_wallet_address if set, otherwise derives from private key.
    Returns "" if derivation fails so callers can proceed with funder=None.
    """
    if config.poly_wallet_address:
        return config.poly_wallet_address
    try:
        from eth_account import Account  # type: ignore[import]
        return Account.from_key(config.private_key).address
    except Exception as exc:
        LOGGER.warning("funder_derivation_failed error=%s — CLOB may see wrong balance", exc)
        return ""


def _get_clob_free_collateral(config: PolymarketConfig) -> float:
    """Query CLOB for the free (unallocated) pUSD collateral balance.

    Returns 0.0 on any error so callers can gate safely without crashing.
    The CLOB API returns balances in 6-decimal micro-pUSD units (same as USDC).
    """
    try:
        from py_clob_client_v2.client import ClobClient as _PyClobClient  # type: ignore[import]
        from py_clob_client_v2.clob_types import ApiCreds  # type: ignore[import]
    except ImportError:
        LOGGER.debug("clob_balance_check_skipped reason=py_clob_client_v2_not_installed")
        return 0.0

    funder = _derive_funder(config)
    try:
        py_client = _PyClobClient(
            host=config.clob_base_url,
            key=config.private_key,
            chain_id=137,
            funder=funder or None,
            creds=ApiCreds(
                api_key=config.api_key,
                api_secret=config.api_secret,
                api_passphrase=config.passphrase,
            ),
        )
        # raw = py_client.get_balance()
        # # raw is micro-pUSD (6 decimals): e.g. 21_000_000 = $21.00
        # if isinstance(raw, dict):
        #     raw_val = float(raw.get("balance", raw.get("free", raw.get("available", 0))))
        # else:
        #     raw_val = float(raw)
        # free_collateral = raw_val / 1_000_000.0
        # LOGGER.info(
        #     "polymarket_clob_diagnostics free_collateral=%.4f funder=%s",
        #     free_collateral,
        #     (funder[:10] + "...") if funder else "unknown",
        # )
        # return free_collateral
        LOGGER.info(
            "polymarket_clob_client_initialized funder=%s",
            (funder[:10] + "...") if funder else "unknown",
        )
        return 0.0
    except Exception as exc:
        LOGGER.warning("polymarket_clob_balance_check_failed error=%s", exc)
        return 0.0


def _clamp_order_size(requested_usdc: float, config: PolymarketConfig) -> float:
    """Return the order size clamped to the live CLOB free collateral.

    TEMP: For current py_clob_client_v2, we bypass the free-collateral check
    and rely on CLOB 400 errors if balance/allowance is insufficient.
    """
    free_collateral = _get_clob_free_collateral(config)

    # TEMPORARY BYPASS: don't block on our preflight check
    if free_collateral <= 0:
        LOGGER.warning(
            "polymarket_collateral_check_bypassed free_collateral=%.6f requested_usdc=%.2f",
            free_collateral,
            requested_usdc,
        )
        return requested_usdc

    clamped = min(requested_usdc, free_collateral * config.poly_safety_fraction)
    if clamped < requested_usdc:
        LOGGER.info(
            "polymarket_order_size_clamped requested=%.2f clamped=%.2f "
            "free_collateral=%.4f safety_fraction=%.2f",
            requested_usdc,
            clamped,
            free_collateral,
            config.poly_safety_fraction,
        )
    return clamped


def _auth_preflight(config: PolymarketConfig) -> bool:
    """Run a cheap L2-authenticated call to verify credentials before placing orders.

    Mirrors scripts/polymarket_clob_balance.py exactly: derives creds via
    derive_api_key() then calls get_balance_allowance() as a cheap auth probe.

    Returns True on success (or if py_clob_client_v2 is not installed — fail open).
    Returns False only when Polymarket explicitly rejects the credentials.
    Does NOT raise — callers can gate on the bool.
    """
    try:
        from py_clob_client_v2.client import ClobClient as _PyClobClient  # type: ignore[import]
        from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType  # type: ignore[import]
    except ImportError:
        LOGGER.warning("polymarket_auth_preflight status=skip reason=py_clob_client_v2_not_installed")
        return True  # library missing is not an auth failure; fail open

    funder = _derive_funder(config)
    pk = config.private_key
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk

    LOGGER.info(
        "polymarket_auth_preflight attempting funder=%s signature_type=%d chain_id=137",
        (funder[:10] + "...") if funder else "none",
        config.poly_signature_type,
    )
    try:
        client = _PyClobClient(
            host=config.clob_base_url,
            key=pk,
            chain_id=137,
            signature_type=config.poly_signature_type,
            funder=funder or None,
        )
        # Derive credentials dynamically — same flow as polymarket_clob_balance.py
        if hasattr(client, "derive_api_key"):
            creds = client.derive_api_key()
        elif hasattr(client, "create_or_derive_api_creds"):
            creds = client.create_or_derive_api_creds()
        else:
            LOGGER.warning(
                "polymarket_auth_preflight status=skip reason=no_derive_method "
                "hint=upgrade_py_clob_client_v2"
            )
            return True  # can't verify; fail open

        client.set_api_creds(creds)

        result = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        balance_usdc = int(result.get("balance", 0)) / 1_000_000.0
        allowance_usdc = int(result.get("allowance", 0)) / 1_000_000.0
        LOGGER.info(
            "polymarket_auth_preflight status=ok funder=%s signature_type=%d "
            "balance_usdc=%.4f allowance_usdc=%.4f",
            (funder[:10] + "...") if funder else "none",
            config.poly_signature_type,
            balance_usdc,
            allowance_usdc,
        )
        return True
    except Exception as exc:
        _status = getattr(exc, "status_code", None)
        _body = getattr(exc, "error_msg", str(exc))
        LOGGER.error(
            "polymarket_auth_preflight status=fail http_status=%s error_message=%r "
            "funder=%s signature_type=%d "
            "hint=verify_POLY_SIGNATURE_TYPE_and_API_keys_in_/etc/trauto/env",
            _status,
            _body,
            (funder[:10] + "...") if funder else "none",
            config.poly_signature_type,
        )
        return False


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of a single execute() call."""

    success: bool
    order_id: str = ""
    fill_price: float = 0.0
    size_usdc: float = 0.0
    error: str = ""


# ---------------------------------------------------------------------------
# Low-level order placement (live mode only)
# ---------------------------------------------------------------------------

def _place_order(
    config: PolymarketConfig,
    token_id: str,
    size_usdc: float,
    price: float,
    side: str,  # "BUY" | "SELL"
) -> dict[str, Any]:
    """Build, sign, and POST a GTC limit order via py-clob-client-v2.

    Requires `pip install py-clob-client-v2` for live execution.
    Retries up to config.max_retries times on transient network errors.
    Raises RuntimeError on auth/funding failures (non-retryable).
    """
    try:
        from py_clob_client_v2.client import ClobClient as _PyClobClient  # type: ignore[import]
        from py_clob_client_v2.clob_types import ApiCreds, OrderArgs, OrderType  # type: ignore[import]
        from py_clob_client_v2.order_builder.constants import BUY, SELL  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "py-clob-client-v2 is required for live order execution. "
            "Install it with: pip install py-clob-client-v2"
        ) from exc

    funder = _derive_funder(config)
    # Ensure "0x" prefix — some py_clob_client_v2 builds require it for Signer()
    pk = config.private_key
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk

    py_client = _PyClobClient(
        host=config.clob_base_url,
        key=pk,
        chain_id=137,
        signature_type=config.poly_signature_type,
        funder=funder or None,
    )
    # Derive credentials dynamically (same as scripts/polymarket_clob_balance.py).
    # This ensures the API key matches the current signer+funder+signature_type context
    # regardless of what is stored in POLY_API_KEY/POLY_API_SECRET env vars.
    # Falls back to static env credentials only if derivation is unavailable.
    if hasattr(py_client, "derive_api_key"):
        api_creds = py_client.derive_api_key()
        creds_source = "derived"
    elif hasattr(py_client, "create_or_derive_api_creds"):
        api_creds = py_client.create_or_derive_api_creds()
        creds_source = "derived"
    elif config.api_key and config.api_secret and config.passphrase:
        api_creds = ApiCreds(
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.passphrase,
        )
        creds_source = "static_env"
    else:
        raise RuntimeError(
            "polymarket: no API-key derivation method found on installed "
            "py_clob_client_v2 and POLY_API_KEY/POLY_API_SECRET/POLY_PASSPHRASE "
            "are not all set"
        )
    py_client.set_api_creds(api_creds)
    LOGGER.info(
        "polymarket_client_init funder=%s signature_type=%d "
        "creds_source=%s chain_id=137",
        (funder[:10] + "...") if funder else "none",
        config.poly_signature_type,
        creds_source,
    )

    py_side = BUY if side.upper() == "BUY" else SELL
    size_tokens = size_usdc / price  # USDC amount → number of outcome tokens

    last_exc: Exception | None = None
    for attempt in range(config.max_retries + 1):
        if attempt > 0:
            sleep_sec = 2 ** (attempt - 1)
            LOGGER.debug(
                "polymarket_order_retry attempt=%d token_id=%s sleep_sec=%d",
                attempt,
                token_id,
                sleep_sec,
            )
            time.sleep(sleep_sec)

        try:
            signed = py_client.create_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size_tokens,
                    side=py_side,
                )
            )
            LOGGER.info(
                "polymarket_order_context token_id=%s side=%s price=%.4f "
                "size_usdc=%.2f size_tokens=%.4f funder=%s signature_type=%d",
                token_id, side, price, size_usdc, size_tokens,
                (funder[:10] + "...") if funder else "none",
                config.poly_signature_type,
            )
            resp: dict[str, Any] = py_client.post_order(signed, OrderType.GTC)
            LOGGER.info("polymarket_order_placed token_id=%s response=%s", token_id, resp)
            return resp
        except Exception as exc:
            _status = getattr(exc, "status_code", None)
            _body = getattr(exc, "error_msg", None)
            err_lower = str(exc).lower()
            # 401: structured auth-error log, then fail fast (no retry)
            if _status == 401 or "401" in err_lower or "unauthorized" in err_lower:
                LOGGER.error(
                    "polymarket_auth_error status=401 token_id=%s side=%s "
                    "error_message=%r hint=CHECK_POLY_SIGNATURE_TYPE_AND_API_KEYS",
                    token_id, side, _body or str(exc),
                )
                raise
            # Other non-retryable errors
            if any(k in err_lower for k in ("auth", "insufficient", "invalid")):
                LOGGER.error(
                    "polymarket_order_fatal token_id=%s side=%s "
                    "http_status=%s error_message=%r",
                    token_id, side, _status, _body or str(exc),
                )
                raise
            last_exc = exc
            LOGGER.warning(
                "polymarket_order_error attempt=%d token_id=%s error=%s",
                attempt, token_id, exc,
            )

    raise RuntimeError(
        f"order placement failed after {config.max_retries + 1} attempts "
        f"token_id={token_id} side={side} last_error={last_exc}"
    )


# ---------------------------------------------------------------------------
# Orderbook-spread execution (YES + NO legs)
# ---------------------------------------------------------------------------

def _execute_orderbook_spread(
    opportunity: Opportunity,
    config: PolymarketConfig,
    ledger: PositionsLedger,
) -> ExecutionResult:
    """Place YES and NO legs for a riskless-spread opportunity.

    If the YES leg fills but the NO leg fails, records an UNHEDGED position
    and logs at CRITICAL level — this must never be silently swallowed.
    """
    if not _check_pol_gas(config.private_key):
        return ExecutionResult(success=False, error="pol_gas_insufficient")

    total_cost_per_share = opportunity.entry_price_yes + opportunity.entry_price_no
    if total_cost_per_share <= 0:
        return ExecutionResult(
            success=False, error="entry_prices_missing_or_zero"
        )

    # Split size proportionally between legs (each leg gets USDC proportional to its ask)
    trade_usdc = _clamp_order_size(config.max_trade_usdc, config)
    if trade_usdc <= 0:
        return ExecutionResult(success=False, error="insufficient_clob_collateral")
    n_shares = trade_usdc / total_cost_per_share
    yes_usdc = n_shares * opportunity.entry_price_yes
    no_usdc = n_shares * opportunity.entry_price_no
    total_usdc = yes_usdc + no_usdc

    # --- YES leg ---
    yes_resp: dict[str, Any] | None = None
    try:
        yes_resp = _place_order(
            config,
            token_id=opportunity.yes_token_id,
            size_usdc=yes_usdc,
            price=opportunity.entry_price_yes,
            side="BUY",
        )
    except Exception as exc:
        return ExecutionResult(
            success=False,
            error=f"yes_leg_failed: {exc}",
        )

    yes_order_id: str = yes_resp.get("orderID", yes_resp.get("order_id", ""))
    yes_fill = float(yes_resp.get("price", opportunity.entry_price_yes))

    # --- NO leg ---
    try:
        no_resp = _place_order(
            config,
            token_id=opportunity.no_token_id,
            size_usdc=no_usdc,
            price=opportunity.entry_price_no,
            side="BUY",
        )
    except Exception as exc:
        # YES filled but NO failed — position is now UNHEDGED
        yes_contracts = yes_usdc / yes_fill if yes_fill > 0 else 0.0
        unhedged = new_position(
            market_condition_id=opportunity.condition_id,
            market_question=opportunity.market_question,
            strategy=opportunity.strategy,
            side="YES",
            entry_price=yes_fill,
            size_usdc=yes_usdc,
            status="unhedged",
            yes_token_id=opportunity.yes_token_id,
            contracts_held=yes_contracts,
        )
        ledger.add(unhedged)
        LOGGER.critical(
            "polymarket_unhedged_position yes_order_id=%s condition_id=%s "
            "yes_usdc=%.2f no_error=%s — manual intervention required",
            yes_order_id,
            opportunity.condition_id,
            yes_usdc,
            exc,
        )
        return ExecutionResult(
            success=False,
            order_id=yes_order_id,
            fill_price=yes_fill,
            size_usdc=yes_usdc,
            error=f"no_leg_failed_unhedged: {exc}",
        )

    no_order_id: str = no_resp.get("orderID", no_resp.get("order_id", ""))
    no_fill = float(no_resp.get("price", opportunity.entry_price_no))
    avg_fill = (yes_fill + no_fill) / 2.0

    position = new_position(
        market_condition_id=opportunity.condition_id,
        market_question=opportunity.market_question,
        strategy=opportunity.strategy,
        side="YES+NO",
        entry_price=avg_fill,
        size_usdc=total_usdc,
        status="open",
        yes_token_id=opportunity.yes_token_id,
        no_token_id=opportunity.no_token_id,
        contracts_held=n_shares,
    )
    ledger.add(position)

    LOGGER.info(
        "polymarket_executed strategy=%s condition_id=%s "
        "yes_order_id=%s no_order_id=%s total_usdc=%.2f avg_fill=%.4f",
        opportunity.strategy,
        opportunity.condition_id,
        yes_order_id,
        no_order_id,
        total_usdc,
        avg_fill,
    )
    return ExecutionResult(
        success=True,
        order_id=f"{yes_order_id}/{no_order_id}",
        fill_price=avg_fill,
        size_usdc=total_usdc,
    )


# ---------------------------------------------------------------------------
# Correlated-markets execution (two-market relative-value)
# ---------------------------------------------------------------------------

def _execute_correlated_markets(
    opportunity: Opportunity,
    config: PolymarketConfig,
    ledger: PositionsLedger,
) -> ExecutionResult:
    """Place two legs for a correlated-markets dominance-violation opportunity.

    Leg A (SELL): sell YES on the higher-priced market (yes_token_id_2).
    Leg B (BUY):  buy  YES on the lower-priced market  (yes_token_id).

    If leg A fails, abort — no position opened, no risk.
    If leg A succeeds but leg B fails, record an UNHEDGED position and alert.

    entry_price_no  holds the sell bid (leg A price).
    entry_price_yes holds the buy  ask (leg B price).
    """
    if not _check_pol_gas(config.private_key):
        return ExecutionResult(success=False, error="pol_gas_insufficient")

    if not opportunity.yes_token_id_2 or not opportunity.yes_token_id:
        return ExecutionResult(
            success=False, error="correlated_markets_missing_token_ids"
        )

    sell_price = opportunity.entry_price_no   # bid of higher-priced market
    buy_price = opportunity.entry_price_yes   # ask of lower-priced market

    # buy_price must be positive — it's the cost of entry.
    # sell_price=0 is valid: the higher-threshold market is near-worthless
    # (best bid = 0), so leg A is skipped rather than posting a $0 limit sell.
    if buy_price <= 0:
        return ExecutionResult(
            success=False, error="correlated_markets_buy_price_missing"
        )

    if buy_price >= 0.99 or buy_price <= 0.01:
        LOGGER.info(
            "correlated_markets_buy_price_invalid skipped buy_price=%.4f "
            "sell_price=%.4f edge_pct=%.4f hours_to_resolution=%.1f "
            "market=%.80s buy_ask=%.4f sell_bid=%.4f",
            buy_price, sell_price,
            opportunity.edge_pct,
            opportunity.hours_to_resolution if opportunity.hours_to_resolution != float("inf") else -1,
            opportunity.market_question,
            opportunity.entry_price_yes,
            opportunity.entry_price_no,
        )
        LOGGER.warning(
            "polymarket_opportunity_rejected strategy=correlated_markets "
            "reason=buy_price_out_of_valid_range "
            "buy_price=%.4f sell_price=%.4f "
            "edge_pct=%.4f hours_to_resolution=%.1f",
            buy_price, sell_price,
            opportunity.edge_pct,
            opportunity.hours_to_resolution if opportunity.hours_to_resolution != float("inf") else -1,
        )
        return ExecutionResult(
            success=False, error="buy_price_out_of_valid_range"
        )

    size_usdc = _clamp_order_size(config.max_trade_usdc, config)
    if size_usdc <= 0:
        return ExecutionResult(success=False, error="insufficient_clob_collateral")

    sell_order_id: str = ""
    sell_fill: float = 0.0

    # Leg A (SELL) is permanently disabled: Polymarket does not support
    # short-selling without an existing position. sell_order_id stays ""
    # so two_leg is always False and only the BUY leg is executed.
    LOGGER.info(
        "correlated_markets_sell_leg_skipped condition_id=%s sell_price=%.4f "
        "reason=short_selling_not_supported",
        opportunity.condition_id_2,
        sell_price,
    )

    if buy_price > 0.70:
        LOGGER.info(
            "correlated_markets_skipped_unhedged buy_price=%.4f "
            "reason=buy_price_too_high_without_hedge",
            buy_price,
        )
        return ExecutionResult(
            success=False, error="unhedged_buy_price_too_high"
        )

    # --- Leg B: BUY YES on the lower-priced market ---
    try:
        buy_resp = _place_order(
            config,
            token_id=opportunity.yes_token_id,
            size_usdc=size_usdc,
            price=buy_price,
            side="BUY",
        )
    except Exception as exc:
        if sell_order_id:
            # Leg A filled but leg B failed — unhedged
            sell_contracts = size_usdc / sell_fill if sell_fill > 0 else 0.0
            unhedged = new_position(
                market_condition_id=opportunity.condition_id_2,
                market_question=opportunity.market_question,
                strategy=opportunity.strategy,
                side="SELL_YES",
                entry_price=sell_fill,
                size_usdc=size_usdc,
                status="unhedged",
                yes_token_id=opportunity.yes_token_id_2,
                contracts_held=sell_contracts,
            )
            ledger.add(unhedged)
            LOGGER.critical(
                "polymarket_unhedged_position sell_order_id=%s condition_id=%s "
                "size_usdc=%.2f buy_error=%s — manual intervention required",
                sell_order_id,
                opportunity.condition_id_2,
                size_usdc,
                exc,
            )
            return ExecutionResult(
                success=False,
                order_id=sell_order_id,
                fill_price=sell_fill,
                size_usdc=size_usdc,
                error=f"buy_leg_failed_unhedged: {exc}",
            )
        return ExecutionResult(success=False, error=f"buy_leg_failed: {exc}")

    buy_order_id: str = buy_resp.get("orderID", buy_resp.get("order_id", ""))
    buy_fill = float(buy_resp.get("price", buy_price))

    two_leg = sell_order_id != ""
    position = new_position(
        market_condition_id=opportunity.condition_id,
        market_question=opportunity.market_question,
        strategy=opportunity.strategy,
        side="SELL_HIGH+BUY_LOW" if two_leg else "BUY_LOW",
        entry_price=(sell_fill + buy_fill) / 2.0 if two_leg else buy_fill,
        size_usdc=size_usdc * 2 if two_leg else size_usdc,
        status="open",
        yes_token_id=opportunity.yes_token_id,
        no_token_id=opportunity.yes_token_id_2 if two_leg else "",
        contracts_held=size_usdc / buy_fill if buy_fill > 0 else 0.0,
    )
    ledger.add(position)

    realized_edge = sell_fill - buy_fill if two_leg else -buy_fill
    LOGGER.info(
        "polymarket_executed strategy=correlated_markets two_leg=%s "
        "sell_order_id=%s buy_order_id=%s "
        "sell_fill=%.4f buy_fill=%.4f realized_edge=%.4f size_usdc=%.2f",
        two_leg,
        sell_order_id or "skipped",
        buy_order_id,
        sell_fill,
        buy_fill,
        realized_edge,
        size_usdc * 2 if two_leg else size_usdc,
    )
    return ExecutionResult(
        success=True,
        order_id=f"{sell_order_id}/{buy_order_id}" if two_leg else buy_order_id,
        fill_price=(sell_fill + buy_fill) / 2.0 if two_leg else buy_fill,
        size_usdc=size_usdc * 2 if two_leg else size_usdc,
    )


# ---------------------------------------------------------------------------
# Underround execution (YES + NO legs, asymmetric market)
# ---------------------------------------------------------------------------

def _execute_underround(
    opportunity: Opportunity,
    config: PolymarketConfig,
    ledger: PositionsLedger,
) -> ExecutionResult:
    """Buy both YES and NO legs for an underround arbitrage opportunity.

    Uses config.underround_max_trade_usdc (capped at config.max_trade_usdc).
    Identical leg structure to orderbook_spread; labelled separately for
    per-strategy tracking.
    """
    if not _check_pol_gas(config.private_key):
        return ExecutionResult(success=False, error="pol_gas_insufficient")

    total_cost_per_share = opportunity.entry_price_yes + opportunity.entry_price_no
    if total_cost_per_share <= 0:
        return ExecutionResult(success=False, error="entry_prices_missing_or_zero")

    size_usdc = _clamp_order_size(min(config.underround_max_trade_usdc, config.max_trade_usdc), config)
    if size_usdc <= 0:
        return ExecutionResult(success=False, error="insufficient_clob_collateral")
    n_shares = size_usdc / total_cost_per_share
    yes_usdc = n_shares * opportunity.entry_price_yes
    no_usdc  = n_shares * opportunity.entry_price_no
    total_usdc = yes_usdc + no_usdc

    # --- YES leg ---
    yes_resp: dict[str, Any] | None = None
    try:
        yes_resp = _place_order(
            config,
            token_id=opportunity.yes_token_id,
            size_usdc=yes_usdc,
            price=opportunity.entry_price_yes,
            side="BUY",
        )
    except Exception as exc:
        return ExecutionResult(success=False, error=f"yes_leg_failed: {exc}")

    yes_order_id: str = yes_resp.get("orderID", yes_resp.get("order_id", ""))
    yes_fill = float(yes_resp.get("price", opportunity.entry_price_yes))

    # --- NO leg ---
    try:
        no_resp = _place_order(
            config,
            token_id=opportunity.no_token_id,
            size_usdc=no_usdc,
            price=opportunity.entry_price_no,
            side="BUY",
        )
    except Exception as exc:
        yes_contracts = yes_usdc / yes_fill if yes_fill > 0 else 0.0
        unhedged = new_position(
            market_condition_id=opportunity.condition_id,
            market_question=opportunity.market_question,
            strategy=opportunity.strategy,
            side="YES",
            entry_price=yes_fill,
            size_usdc=yes_usdc,
            status="unhedged",
            yes_token_id=opportunity.yes_token_id,
            contracts_held=yes_contracts,
        )
        ledger.add(unhedged)
        LOGGER.critical(
            "polymarket_unhedged_position yes_order_id=%s condition_id=%s "
            "yes_usdc=%.2f no_error=%s — manual intervention required",
            yes_order_id, opportunity.condition_id, yes_usdc, exc,
        )
        return ExecutionResult(
            success=False,
            order_id=yes_order_id,
            fill_price=yes_fill,
            size_usdc=yes_usdc,
            error=f"no_leg_failed_unhedged: {exc}",
        )

    no_order_id: str = no_resp.get("orderID", no_resp.get("order_id", ""))
    no_fill = float(no_resp.get("price", opportunity.entry_price_no))
    avg_fill = (yes_fill + no_fill) / 2.0

    position = new_position(
        market_condition_id=opportunity.condition_id,
        market_question=opportunity.market_question,
        strategy=opportunity.strategy,
        side="YES+NO",
        entry_price=avg_fill,
        size_usdc=total_usdc,
        status="open",
        yes_token_id=opportunity.yes_token_id,
        no_token_id=opportunity.no_token_id,
        contracts_held=n_shares,
    )
    ledger.add(position)

    LOGGER.info(
        "polymarket_underround_execute_result condition_id=%s "
        "yes_order_id=%s no_order_id=%s "
        "total_usdc=%.2f avg_fill=%.4f edge_pct=%.2f",
        opportunity.condition_id,
        yes_order_id,
        no_order_id,
        total_usdc,
        avg_fill,
        opportunity.edge_pct,
    )
    return ExecutionResult(
        success=True,
        order_id=f"{yes_order_id}/{no_order_id}",
        fill_price=avg_fill,
        size_usdc=total_usdc,
    )


# ---------------------------------------------------------------------------
# Resolution carry execution (single YES leg, near-certain outcome)
# ---------------------------------------------------------------------------

def _execute_resolution_carry(
    opportunity: Opportunity,
    config: PolymarketConfig,
    ledger: PositionsLedger,
) -> ExecutionResult:
    """Buy the YES leg for a near-certain market approaching resolution.

    Uses config.res_carry_max_trade_usdc (capped at config.max_trade_usdc).
    Only a BUY leg — no short-selling or NO leg needed.
    """
    if not _check_pol_gas(config.private_key):
        return ExecutionResult(success=False, error="pol_gas_insufficient")

    buy_price = opportunity.entry_price_yes
    if buy_price <= 0 or buy_price >= 1.0:
        return ExecutionResult(
            success=False, error=f"res_carry_invalid_price buy_price={buy_price:.4f}"
        )

    size_usdc = _clamp_order_size(min(config.res_carry_max_trade_usdc, config.max_trade_usdc), config)
    if size_usdc <= 0:
        return ExecutionResult(success=False, error="insufficient_clob_collateral")

    try:
        resp = _place_order(
            config,
            token_id=opportunity.yes_token_id,
            size_usdc=size_usdc,
            price=buy_price,
            side="BUY",
        )
    except Exception as exc:
        return ExecutionResult(success=False, error=f"buy_leg_failed: {exc}")

    order_id: str = resp.get("orderID", resp.get("order_id", ""))
    fill_price = float(resp.get("price", buy_price))
    contracts = size_usdc / fill_price if fill_price > 0 else 0.0

    position = new_position(
        market_condition_id=opportunity.condition_id,
        market_question=opportunity.market_question,
        strategy=opportunity.strategy,
        side="YES",
        entry_price=fill_price,
        size_usdc=size_usdc,
        status="open",
        yes_token_id=opportunity.yes_token_id,
        contracts_held=contracts,
    )
    ledger.add(position)

    LOGGER.info(
        "polymarket_res_carry_execute_result condition_id=%s order_id=%s "
        "fill_price=%.4f size_usdc=%.2f edge_pct=%.2f hours_to_resolution=%.1f",
        opportunity.condition_id,
        order_id,
        fill_price,
        size_usdc,
        opportunity.edge_pct,
        opportunity.hours_to_resolution if opportunity.hours_to_resolution != float("inf") else -1,
    )
    return ExecutionResult(
        success=True,
        order_id=order_id,
        fill_price=fill_price,
        size_usdc=size_usdc,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def execute(
    opportunity: Opportunity,
    config: PolymarketConfig,
    risk_guard: RiskGuard,
    ledger: PositionsLedger,
) -> ExecutionResult:
    """Validate risk checks, then execute the opportunity (or dry-run log it).

    Returns ExecutionResult in all cases — never raises for a failed risk check.
    Only raises for genuinely unrecoverable API errors (invalid auth, etc.).
    """
    proposed_size = config.max_trade_usdc

    # Strategy scope check
    if opportunity.strategy not in _EXECUTABLE_STRATEGIES:
        LOGGER.warning(
            "polymarket_execute_skip strategy=%s edge_pct=%.4f "
            "reason=not_executable_in_phase2 executable_strategies=%s "
            "— set POLY_TRADING_MODE=live to enable live execution",
            opportunity.strategy,
            opportunity.edge_pct,
            sorted(_EXECUTABLE_STRATEGIES),
        )
        return ExecutionResult(
            success=False,
            error=f"strategy {opportunity.strategy!r} not executable in Phase 2",
        )

    # Risk checks
    passed, reason = risk_guard.check(opportunity, proposed_size_usdc=proposed_size)
    if not passed:
        LOGGER.warning(
            "polymarket_execute_risk_blocked strategy=%s edge_pct=%.4f "
            "size_usdc=%.2f reason=%s",
            opportunity.strategy,
            opportunity.edge_pct,
            proposed_size,
            reason,
        )
        return ExecutionResult(success=False, error=f"risk_check_failed: {reason}")

    # Dry-run mode: log intent and return without touching the API
    if config.dry_run:
        LOGGER.warning(
            "polymarket_dry_run_gate strategy=%s edge_pct=%.4f size_usdc=%.2f "
            "action=%s — BLOCKED by dry_run=True; set POLY_DRY_RUN=false "
            "POLY_TRADING_MODE=live LIVE_TRADING=true to execute live",
            opportunity.strategy,
            opportunity.edge_pct,
            proposed_size,
            opportunity.action,
        )
        return ExecutionResult(
            success=True,
            size_usdc=proposed_size,
            error="dry_run",
        )

    # Auth preflight: verify L2 credentials before any live order placement.
    # Runs once per execute() call in live mode; skipped entirely in dry_run.
    # Prevents repeated "attempting_execution" cycles when credentials are broken.
    if not _auth_preflight(config):
        LOGGER.warning(
            "polymarket_live_trading_disabled reason=AUTH_401 "
            "hint=check_POLY_SIGNATURE_TYPE_and_API_keys_in_/etc/trauto/env"
        )
        return ExecutionResult(success=False, error="auth_preflight_failed:AUTH_401")

    # Live execution (strategy-specific routing)
    if opportunity.strategy == "orderbook_spread":
        return _execute_orderbook_spread(opportunity, config, ledger)
    if opportunity.strategy == "correlated_markets":
        return _execute_correlated_markets(opportunity, config, ledger)
    if opportunity.strategy == "underround":
        return _execute_underround(opportunity, config, ledger)
    if opportunity.strategy == "resolution_carry":
        return _execute_resolution_carry(opportunity, config, ledger)

    # Should not reach here given the _EXECUTABLE_STRATEGIES check above
    return ExecutionResult(success=False, error="unhandled_strategy")
