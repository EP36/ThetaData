"""Risk guard — eight ordered checks that must all pass before execution."""

from __future__ import annotations

import os
import json
import logging
import urllib.request
from dataclasses import dataclass, field

from src.polymarket.config import PolymarketConfig
from src.polymarket.opportunities import Opportunity
from src.polymarket.positions import PositionsLedger
import httpx

LOGGER = logging.getLogger("theta.polymarket.risk")

_CONFIDENCE_SCORE: dict[str, float] = {
    "low": 0.0,
    "medium": 0.5,
    "high": 1.0,
}
_MIN_CONFIDENCE_SCORE = 0.5

# Polygon USDC balance check (mirrors src/api/services.py — kept local to avoid
# pulling the full API service layer into the polymarket execution path)
_POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
_POLYGON_USDC_CONTRACT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
_BALANCE_OF_SELECTOR = "0x70a08231"  # keccak256("balanceOf(address)")[:4]


def _fetch_polygon_usdc_balance(wallet_address: str) -> float | None:
    """Return USDC balance (in whole USDC units) for wallet_address on Polygon.

    Returns None on any failure — never raises.
    """
    if not wallet_address:
        return None
    padded = wallet_address.lower().removeprefix("0x").zfill(64)
    call_data = _BALANCE_OF_SELECTOR + padded
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": _POLYGON_USDC_CONTRACT, "data": call_data}, "latest"],
        "id": 1,
    }).encode()
    try:
        req = urllib.request.Request(
            _POLYGON_RPC_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with httpx.Client(timeout=5) as client:
            resp = client.get(url)
        body = resp.json()
        raw = int(body.get("result", "0x0"), 16)
        return raw / 1_000_000  # USDC has 6 decimals
    except Exception as exc:
        LOGGER.warning("usdc_balance_fetch_failed error=%s", exc)
        return None


def _derive_wallet_address(private_key: str) -> str | None:
    """Derive EVM wallet address from private key. Returns None on any failure."""
    try:
        from eth_account import Account  # type: ignore[import]
        return Account.from_key(private_key).address
    except Exception:
        return None


@dataclass(slots=True)
class RiskGuard:
    """Evaluates eight ordered risk checks before any order is placed.

    All checks must pass; the first failure short-circuits.
    Never raises for a failed check — logs and returns (False, reason).
    """

    config: PolymarketConfig
    ledger: PositionsLedger
    _paused: bool = field(default=False, repr=False)

    def pause(self) -> None:
        """Pause the bot — blocks all execution until resume() is called."""
        self._paused = True
        LOGGER.warning("polymarket_risk_bot_paused")

    def resume(self) -> None:
        """Resume execution after a pause."""
        self._paused = False
        LOGGER.info("polymarket_risk_bot_resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def check(
        self, opportunity: Opportunity, proposed_size_usdc: float
    ) -> tuple[bool, str]:
        """Run all risk checks in order. Returns (passed, reason_string).

        Checks:
          1. Bot is not paused
          2. USDC wallet balance >= proposed trade size
          3. edge_pct >= min_edge_pct
          4. confidence score >= 0.5
          5. proposed_size_usdc <= max_trade_usdc
          6. open positions < max_positions
          7. daily P&L has not breached -daily_loss_limit
          8. market volume_24h > min_volume_24h
        """
        # 1 — pause flag
        if self._paused:
            reason = "bot_paused"
            LOGGER.info(
                "polymarket_risk_fail check=pause reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 2 — USDC wallet balance
        wallet = _derive_wallet_address(self.config.private_key)
        if wallet is not None:
            usdc_balance = _fetch_polygon_usdc_balance(wallet)
            if usdc_balance is not None and usdc_balance < proposed_size_usdc:
                reason = (
                    f"usdc_balance={usdc_balance:.2f} "
                    f"< proposed_size={proposed_size_usdc:.2f}"
                )
                LOGGER.warning(
                    "polymarket_risk_fail check=usdc_balance reason=%s strategy=%s",
                    reason,
                    opportunity.strategy,
                )
                return False, reason

        # 3 — minimum edge
        if opportunity.edge_pct < self.config.min_edge_pct:
            reason = (
                f"edge_pct={opportunity.edge_pct:.4f} "
                f"< min={self.config.min_edge_pct}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=edge reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 4 — confidence threshold
        conf_score = _CONFIDENCE_SCORE.get(opportunity.confidence, 0.0)
        if conf_score < _MIN_CONFIDENCE_SCORE:
            reason = (
                f"confidence={opportunity.confidence} "
                f"score={conf_score} < {_MIN_CONFIDENCE_SCORE}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=confidence reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 5 — trade size
        if proposed_size_usdc > self.config.max_trade_usdc:
            reason = (
                f"proposed_size={proposed_size_usdc:.2f} "
                f"> max={self.config.max_trade_usdc}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=size reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 6 — open position count
        open_count = self.ledger.open_count()
        if open_count >= self.config.max_positions:
            reason = (
                f"open_positions={open_count} "
                f">= max={self.config.max_positions}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=positions reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 7 — daily loss limit
        daily_pnl = self.ledger.daily_pnl()
        if daily_pnl <= -self.config.daily_loss_limit:
            reason = (
                f"daily_pnl={daily_pnl:.2f} "
                f"<= -limit={-self.config.daily_loss_limit}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=daily_loss reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        # 8 — market liquidity (volume)
        # Use strict < so min_volume_24h=0 means "no minimum" (volume_24h=0 passes).
        if opportunity.volume_24h < self.config.min_volume_24h:
            reason = (
                f"volume_24h={opportunity.volume_24h:.0f} "
                f"< min={self.config.min_volume_24h:.0f}"
            )
            LOGGER.info(
                "polymarket_risk_fail check=volume reason=%s strategy=%s",
                reason,
                opportunity.strategy,
            )
            return False, reason

        LOGGER.info(
            "polymarket_risk_pass strategy=%s edge_pct=%.4f size_usdc=%.2f",
            opportunity.strategy,
            opportunity.edge_pct,
            proposed_size_usdc,
        )
        return True, "all_checks_passed"
