"""Hyperliquid spot + perp execution for funding rate arb.

Uses EIP-712 signed orders via the Hyperliquid L1 API.
All order placement is gated behind HL_DRY_RUN (default: true).

Auth:
  HL_PRIVATE_KEY  — Ethereum private key (hex, with or without 0x prefix)
  HL_WALLET       — Ethereum wallet address (checksummed)
  HL_DRY_RUN      — "false" to enable live execution (default: "true")
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from eth_account.messages import encode_defunct

LOGGER = logging.getLogger("theta.funding_arb.executor")

HL_BASE_URL = "https://api.hyperliquid.xyz"
HL_CHAIN_ID = 1337      # Hyperliquid L1 chain ID for EIP-712
SLIPPAGE    = 0.003     # 0.3% max slippage on market orders


@dataclass
class FillResult:
    success: bool
    asset: str
    side: str           # "spot_long" | "perp_short"
    size: float
    price: float
    order_id: str
    error: str = ""


def _get_nonce() -> int:
    return int(time.time() * 1000)


def _sign_order(private_key: str, order_payload: dict[str, Any]) -> str:
    """Sign an order payload using EIP-712 with eth_account."""
    from eth_account import Account
    from eth_account.structured_data import encode_structured_data

    structured_data = {
        "domain": {
            "name": "HyperliquidSignTransaction",
            "version": "1",
            "chainId": HL_CHAIN_ID,
        },
        "types": {
            "EIP712Domain": [
                {"name": "name",    "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "HyperliquidTransaction:Order": [
                {"name": "hyperliquidChain", "type": "string"},
                {"name": "asset",            "type": "uint32"},
                {"name": "isBuy",            "type": "bool"},
                {"name": "limitPx",          "type": "string"},
                {"name": "sz",               "type": "string"},
                {"name": "reduceOnly",       "type": "bool"},
                {"name": "cloid",            "type": "string"},
                {"name": "nonce",            "type": "uint64"},
            ],
        },
        "primaryType": "HyperliquidTransaction:Order",
        "message": order_payload,
    }
    account = Account.from_key(private_key)
    encoded = encode_structured_data(structured_data)
    signed  = account.sign_message(encoded)
    return signed.signature.hex()


def _hl_exchange_post(
    private_key: str,
    wallet: str,
    action: dict[str, Any],
    timeout: float = 10.0,
) -> Any:
    """POST to /exchange with a signed action.

    Returns the parsed JSON body as-is (may be a dict OR a plain string —
    Hyperliquid returns bare JSON strings such as "Order would immediately match"
    for certain rejection cases).  Callers must guard with isinstance(result, dict).
    """
    from eth_account import Account

    nonce = _get_nonce()

    # Hyperliquid uses personal_sign over SHA-256 of the serialised action+nonce
    account     = Account.from_key(private_key)
    payload_str = json.dumps(
        {"action": action, "nonce": nonce},
        separators=(",", ":"),
        sort_keys=True,
    )
    msg_hash = hashlib.sha256(payload_str.encode()).digest()
    signed   = account.sign_message(encode_defunct(primitive=msg_hash))

    body = {
        "action":       action,
        "nonce":        nonce,
        "signature":    {"r": hex(signed.r), "s": hex(signed.s), "v": signed.v},
        "vaultAddress": None,
    }

    resp = httpx.post(f"{HL_BASE_URL}/exchange", json=body, timeout=timeout)
    LOGGER.info(
        "hl_exchange_raw_response status=%d body=%s",
        resp.status_code, resp.text,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_order_id(result: Any) -> str:
    """Pull the filled order ID from an /exchange response dict.

    Returns "" for any non-dict response or any missing/unexpected structure.
    """
    if not isinstance(result, dict):
        return ""
    try:
        statuses = result["response"]["data"]["statuses"]
        return str(statuses[0]["filled"]["oid"])
    except (KeyError, IndexError, TypeError):
        return ""


def get_asset_index(asset: str) -> int | None:
    """Fetch the perp asset index from HL meta."""
    resp = httpx.post(f"{HL_BASE_URL}/info", json={"type": "meta"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    for i, u in enumerate(data.get("universe", [])):
        if u["name"] == asset:
            return i
    return None


def get_spot_token_index(asset: str) -> int | None:
    """Fetch the spot token index for an asset."""
    resp = httpx.post(f"{HL_BASE_URL}/info", json={"type": "spotMeta"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    for token in data.get("tokens", []):
        if token["name"] == asset:
            return token["index"]
    return None


def get_mark_price(asset: str) -> float | None:
    """Get current mark price for a perp asset."""
    resp = httpx.post(
        f"{HL_BASE_URL}/info", json={"type": "metaAndAssetCtxs"}, timeout=10
    )
    resp.raise_for_status()
    meta, ctxs = resp.json()
    for i, u in enumerate(meta["universe"]):
        if u["name"] == asset:
            return float(ctxs[i]["markPx"])
    return None


def place_perp_short(
    private_key: str,
    wallet: str,
    asset: str,
    size_usd: float,
    dry_run: bool = True,
) -> FillResult:
    """Open a perp short position on Hyperliquid."""
    try:
        mark_px = get_mark_price(asset)
        if mark_px is None or mark_px <= 0:
            return FillResult(
                success=False, asset=asset, side="perp_short",
                size=0, price=0, order_id="", error="mark_price_unavailable",
            )

        size      = round(size_usd / mark_px, 6)
        limit_px  = round(mark_px * (1 - SLIPPAGE), 6)  # slightly below for short IOC
        asset_idx = get_asset_index(asset)

        if asset_idx is None:
            return FillResult(
                success=False, asset=asset, side="perp_short",
                size=0, price=0, order_id="", error=f"asset_index_not_found_{asset}",
            )

        LOGGER.info(
            "hl_perp_short asset=%s size=%.4f mark_px=%.4f limit_px=%.4f dry_run=%s",
            asset, size, mark_px, limit_px, dry_run,
        )

        if dry_run:
            return FillResult(
                success=True, asset=asset, side="perp_short",
                size=size, price=mark_px, order_id="dry_run",
            )

        action = {
            "type": "order",
            "orders": [{
                "a": asset_idx,
                "b": False,         # False = sell/short
                "p": str(limit_px),
                "s": str(size),
                "r": False,         # reduceOnly
                "t": {"limit": {"tif": "Ioc"}},
            }],
            "grouping": "na",
        }

        result = _hl_exchange_post(private_key, wallet, action)
        if not isinstance(result, dict):
            LOGGER.error(
                "hl_perp_short_unexpected_response asset=%s "
                "type=%s raw=%r",
                asset, type(result).__name__, result,
            )
            return FillResult(
                success=False, asset=asset, side="perp_short",
                size=size, price=limit_px, order_id="",
                error=f"unexpected_response raw={result!r}",
            )
        order_id = _extract_order_id(result)
        LOGGER.info("hl_perp_short_placed asset=%s order_id=%s result=%s", asset, order_id, result)
        return FillResult(
            success=True, asset=asset, side="perp_short",
            size=size, price=limit_px, order_id=order_id,
        )

    except Exception as exc:
        LOGGER.error("hl_perp_short_error asset=%s error=%s", asset, exc)
        return FillResult(
            success=False, asset=asset, side="perp_short",
            size=0, price=0, order_id="", error=str(exc),
        )


def place_spot_long(
    private_key: str,
    wallet: str,
    asset: str,
    size_usd: float,
    dry_run: bool = True,
) -> FillResult:
    """Buy spot asset on Hyperliquid spot market."""
    try:
        mark_px = get_mark_price(asset)
        if mark_px is None or mark_px <= 0:
            return FillResult(
                success=False, asset=asset, side="spot_long",
                size=0, price=0, order_id="", error="mark_price_unavailable",
            )

        size      = round(size_usd / mark_px, 6)
        limit_px  = round(mark_px * (1 + SLIPPAGE), 6)
        token_idx = get_spot_token_index(asset)

        if token_idx is None:
            return FillResult(
                success=False, asset=asset, side="spot_long",
                size=0, price=0, order_id="", error=f"spot_token_not_found_{asset}",
            )

        # Spot asset index offset: 10000 + token_index
        spot_asset_idx = 10000 + token_idx

        LOGGER.info(
            "hl_spot_long asset=%s size=%.4f mark_px=%.4f limit_px=%.4f dry_run=%s",
            asset, size, mark_px, limit_px, dry_run,
        )

        if dry_run:
            return FillResult(
                success=True, asset=asset, side="spot_long",
                size=size, price=mark_px, order_id="dry_run",
            )

        action = {
            "type": "order",
            "orders": [{
                "a": spot_asset_idx,
                "b": True,          # True = buy
                "p": str(limit_px),
                "s": str(size),
                "r": False,
                "t": {"limit": {"tif": "Ioc"}},
            }],
            "grouping": "na",
        }

        result = _hl_exchange_post(private_key, wallet, action)
        if not isinstance(result, dict):
            LOGGER.error(
                "hl_spot_long_unexpected_response asset=%s "
                "type=%s raw=%r",
                asset, type(result).__name__, result,
            )
            return FillResult(
                success=False, asset=asset, side="spot_long",
                size=size, price=limit_px, order_id="",
                error=f"unexpected_response raw={result!r}",
            )
        order_id = _extract_order_id(result)
        LOGGER.info("hl_spot_long_placed asset=%s order_id=%s result=%s", asset, order_id, result)
        return FillResult(
            success=True, asset=asset, side="spot_long",
            size=size, price=limit_px, order_id=order_id,
        )

    except Exception as exc:
        LOGGER.error("hl_spot_long_error asset=%s error=%s", asset, exc)
        return FillResult(
            success=False, asset=asset, side="spot_long",
            size=0, price=0, order_id="", error=str(exc),
        )


def open_basis_trade(
    private_key: str,
    wallet: str,
    asset: str,
    basis_pct: float,
    pos_size_usd: float,
    dry_run: bool = True,
) -> bool:
    """Enter a basis arb trade: SHORT perp on HL + BUY spot on Coinbase (contango).

    Direction:
      basis_pct > 0 (perp > spot, contango): short perp on HL + buy spot on Coinbase
      basis_pct < 0 (perp < spot, backwardation): long perp only (Coinbase spot short
        not available in NY; perp-only leg logged as warning)
      basis_pct == 0: skip

    Returns True if both legs filled (or dry_run), False otherwise.
    """
    LOGGER.info(
        "coinbase_basis_trade_opening asset=%s basis_pct=%.4f pos_usd=%.2f dry_run=%s",
        asset, basis_pct, pos_size_usd, dry_run,
    )

    if basis_pct == 0:
        LOGGER.info("coinbase_basis_trade_skipped reason=basis_pct_zero asset=%s", asset)
        return False

    if dry_run:
        perp_side = "short" if basis_pct > 0 else "long"
        spot_side = "buy" if basis_pct > 0 else "none (backwardation — NY spot short unavailable)"
        LOGGER.info(
            "coinbase_basis_dryrun asset=%s basis_pct=%.4f perp_side=%s spot_side=%s pos_usd=%.2f",
            asset, basis_pct, perp_side, spot_side, pos_size_usd,
        )
        return True

    if basis_pct > 0:
        # Contango: short perp on HL first, then buy spot on Coinbase
        perp_result = place_perp_short(private_key, wallet, asset, pos_size_usd, dry_run=False)
        if not perp_result.success:
            LOGGER.error(
                "coinbase_basis_trade_perp_failed asset=%s error=%s",
                asset, perp_result.error,
            )
            return False

        # Spot leg on Coinbase
        try:
            from funding_arb.coinbase_client import execute_spot_market_buy
            spot_result = execute_spot_market_buy(asset, pos_size_usd)
            spot_filled = True
            spot_order_id = spot_result.get("order_id", "")
        except Exception as exc:
            LOGGER.critical(
                "coinbase_basis_partial_fill asset=%s perp_filled=%.4f spot_failed=%s "
                "— attempting to close HL perp leg",
                asset, perp_result.size, exc,
            )
            # Attempt to close the HL perp leg to avoid unhedged exposure
            try:
                _close_perp_short(private_key, wallet, asset, perp_result.size)
            except Exception as close_exc:
                LOGGER.critical(
                    "coinbase_basis_UNHEDGED_POSITION asset=%s perp_size=%.4f "
                    "close_attempt_failed=%s — manual intervention required",
                    asset, perp_result.size, close_exc,
                )
            return False

        LOGGER.info(
            "coinbase_basis_trade_opened asset=%s basis_pct=%.4f perp_side=short "
            "perp_order_id=%s spot_order_id=%s spot_filled=%s pos_usd=%.2f",
            asset, basis_pct, perp_result.order_id, spot_order_id, spot_filled, pos_size_usd,
        )
        return True

    else:
        # Backwardation: long perp only — spot short not available in NY
        LOGGER.warning(
            "coinbase_basis_backwardation_perp_only asset=%s basis_pct=%.4f "
            "reason=spot_short_unavailable_in_NY",
            asset, basis_pct,
        )
        perp_result = place_perp_short(private_key, wallet, asset, pos_size_usd, dry_run=False)
        if not perp_result.success:
            LOGGER.error(
                "coinbase_basis_trade_perp_failed asset=%s error=%s",
                asset, perp_result.error,
            )
            return False
        LOGGER.info(
            "coinbase_basis_trade_opened asset=%s basis_pct=%.4f perp_side=long "
            "perp_order_id=%s spot_filled=false pos_usd=%.2f",
            asset, basis_pct, perp_result.order_id, pos_size_usd,
        )
        return True


def _close_perp_short(
    private_key: str,
    wallet: str,
    asset: str,
    size: float,
) -> None:
    """Close an open perp short by placing a market buy (reduceOnly)."""
    mark_px = get_mark_price(asset)
    if mark_px is None or mark_px <= 0:
        raise RuntimeError(f"mark_price_unavailable for {asset}")
    asset_idx = get_asset_index(asset)
    if asset_idx is None:
        raise RuntimeError(f"asset_index_not_found for {asset}")
    limit_px = round(mark_px * (1 + SLIPPAGE), 6)
    action = {
        "type": "order",
        "orders": [{
            "a": asset_idx,
            "b": True,          # True = buy (close short)
            "p": str(limit_px),
            "s": str(round(size, 6)),
            "r": True,          # reduceOnly
            "t": {"limit": {"tif": "Ioc"}},
        }],
        "grouping": "na",
    }
    result = _hl_exchange_post(private_key, wallet, action)
    LOGGER.info("hl_perp_short_closed asset=%s size=%.4f result=%s", asset, size, result)


def close_basis_trade(
    private_key: str,
    wallet: str,
    asset: str,
    basis_pct: float,
    perp_side: str,
    spot_size: float,
    dry_run: bool = True,
) -> bool:
    """Close an open basis trade.

    perp_side: "short" | "long" — determines which direction to close the perp
    spot_size: base asset size held on Coinbase (0 if backwardation / no spot leg)

    Returns True if both legs closed successfully.
    """
    LOGGER.info(
        "coinbase_basis_trade_closing asset=%s perp_side=%s spot_size=%.6f dry_run=%s",
        asset, perp_side, spot_size, dry_run,
    )

    if dry_run:
        LOGGER.info(
            "coinbase_basis_close_dryrun asset=%s perp_side=%s spot_size=%.6f",
            asset, perp_side, spot_size,
        )
        return True

    success = True

    # Close HL perp leg
    try:
        mark_px = get_mark_price(asset)
        if mark_px is None or mark_px <= 0:
            raise RuntimeError("mark_price_unavailable")
        asset_idx = get_asset_index(asset)
        if asset_idx is None:
            raise RuntimeError(f"asset_index_not_found for {asset}")
        is_buy   = (perp_side == "short")   # closing a short = buy
        limit_px = round(mark_px * (1 + SLIPPAGE if is_buy else 1 - SLIPPAGE), 6)
        close_size = round(mark_px and mark_px > 0 and spot_size or 0, 6)
        # Use mark price to estimate contracts; caller should supply contracts not USD
        action = {
            "type": "order",
            "orders": [{
                "a": asset_idx,
                "b": is_buy,
                "p": str(limit_px),
                "s": "0",           # 0 = close entire position on HL
                "r": True,
                "t": {"limit": {"tif": "Ioc"}},
            }],
            "grouping": "na",
        }
        result = _hl_exchange_post(private_key, wallet, action)
        LOGGER.info("hl_basis_perp_closed asset=%s perp_side=%s result=%s", asset, perp_side, result)
    except Exception as exc:
        LOGGER.error("hl_basis_perp_close_failed asset=%s error=%s", asset, exc)
        success = False

    # Close Coinbase spot leg
    if spot_size > 0:
        try:
            from funding_arb.coinbase_client import execute_spot_market_sell
            execute_spot_market_sell(asset, spot_size)
        except Exception as exc:
            LOGGER.error("coinbase_basis_spot_close_failed asset=%s error=%s", asset, exc)
            success = False

    LOGGER.info(
        "coinbase_basis_trade_closed asset=%s perp_side=%s spot_size=%.6f success=%s",
        asset, perp_side, spot_size, success,
    )
    return success


def enter_arb(
    private_key: str,
    wallet: str,
    asset: str,
    size_usd: float,
    dry_run: bool = True,
) -> tuple[FillResult, FillResult]:
    """Enter the full arb: spot long + perp short simultaneously.

    If either leg fails, logs a CRITICAL warning (unhedged position).
    Returns (spot_result, perp_result).
    """
    LOGGER.info("hl_arb_enter asset=%s size_usd=%.2f dry_run=%s", asset, size_usd, dry_run)

    spot = place_spot_long(private_key, wallet, asset, size_usd, dry_run)
    perp = place_perp_short(private_key, wallet, asset, size_usd, dry_run)

    if spot.success and perp.success:
        LOGGER.info(
            "hl_arb_enter_success asset=%s spot_size=%.4f perp_size=%.4f",
            asset, spot.size, perp.size,
        )
    elif spot.success and not perp.success:
        LOGGER.critical(
            "hl_arb_UNHEDGED_POSITION asset=%s spot_filled=%.4f perp_failed=%s "
            "— manual intervention required",
            asset, spot.size, perp.error,
        )
    elif not spot.success and perp.success:
        LOGGER.critical(
            "hl_arb_UNHEDGED_POSITION asset=%s perp_filled=%.4f spot_failed=%s "
            "— manual intervention required",
            asset, perp.size, spot.error,
        )
    else:
        LOGGER.warning(
            "hl_arb_enter_failed asset=%s spot_error=%s perp_error=%s",
            asset, spot.error, perp.error,
        )

    return spot, perp
