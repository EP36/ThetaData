"""Risk controls for position sizing and loss limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
import logging

import numpy as np
import pandas as pd

from src.risk.models import OrderRiskRequest, PortfolioRiskState, RiskDecision

EPSILON = 1e-12
LOGGER = logging.getLogger("theta.risk.manager")

@dataclass(slots=True)
class RiskManager:
    """Apply position and drawdown constraints to target positions."""

    max_position_size: float
    max_daily_loss: float
    max_gross_exposure: float = 1.0
    max_open_positions: int = 10
    max_drawdown_pct: float = 0.30
    trading_start: str = "09:30"
    trading_end: str = "16:00"
    allow_after_hours: bool = False
    default_stop_loss_pct: float | None = None
    default_trailing_stop_pct: float | None = None
    kill_switch_enabled: bool = False
    kill_switch_triggered_at: pd.Timestamp | None = None
    peak_equity: float | None = None
    _trading_start_time: time = field(init=False, repr=False)
    _trading_end_time: time = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate risk parameters."""
        if self.max_position_size <= 0:
            raise ValueError("max_position_size must be positive")
        if self.max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")
        if self.max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be positive")
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        if self.max_drawdown_pct <= 0 or self.max_drawdown_pct >= 1:
            raise ValueError("max_drawdown_pct must be in (0, 1)")

        self._trading_start_time = self._parse_time(self.trading_start)
        self._trading_end_time = self._parse_time(self.trading_end)
        if self._trading_start_time >= self._trading_end_time:
            raise ValueError("trading_start must be earlier than trading_end")

        self._validate_optional_pct(self.default_stop_loss_pct, "default_stop_loss_pct")
        self._validate_optional_pct(
            self.default_trailing_stop_pct,
            "default_trailing_stop_pct",
        )

    @staticmethod
    def _parse_time(value: str) -> time:
        """Parse HH:MM formatted trading-hour time."""
        try:
            return time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid time format '{value}', expected HH:MM") from exc

    @staticmethod
    def _validate_optional_pct(value: float | None, field_name: str) -> None:
        """Validate optional percentage parameter in (0, 1)."""
        if value is None:
            return
        if value <= 0 or value >= 1:
            raise ValueError(f"{field_name} must be in (0, 1)")

    def enforce(
        self,
        timestamp: pd.Timestamp,
        target_position: float,
        day_start_equity: float,
        current_equity: float,
    ) -> float:
        """Return a risk-compliant position target.

        Args:
            timestamp: Current bar timestamp.
            target_position: Raw strategy target in [-1, 1].
            day_start_equity: Equity at start of current trading day.
            current_equity: Current portfolio equity.

        Returns:
            Risk-adjusted target position.
        """
        if self.kill_switch_enabled:
            return 0.0

        self._update_peak_equity(current_equity)
        if self._trigger_drawdown_kill_switch(timestamp=timestamp, current_equity=current_equity):
            LOGGER.warning(
                "risk_kill_switch_triggered reason=max_drawdown timestamp=%s current_equity=%.2f",
                timestamp,
                current_equity,
            )
            return 0.0

        daily_pnl = current_equity - day_start_equity
        if daily_pnl <= -self.max_daily_loss:
            self.kill_switch_enabled = True
            self.kill_switch_triggered_at = timestamp
            LOGGER.warning(
                "risk_kill_switch_triggered reason=max_daily_loss timestamp=%s daily_pnl=%.2f limit=%.2f",
                timestamp,
                daily_pnl,
                self.max_daily_loss,
            )
            return 0.0

        clipped = float(
            np.clip(target_position, -self.max_position_size, self.max_position_size)
        )
        return clipped

    def reset_kill_switch(self) -> None:
        """Manually reset kill switch after intervention."""
        self.kill_switch_enabled = False
        self.kill_switch_triggered_at = None

    def validate_order(
        self,
        request: OrderRiskRequest,
        state: PortfolioRiskState,
    ) -> RiskDecision:
        """Validate an order request against configured risk rules."""
        reasons: list[str] = []
        side = request.side.upper()

        if self.kill_switch_enabled:
            reasons.append("kill_switch_enabled")

        self._update_peak_equity(state.peak_equity)
        reference_peak = max(state.peak_equity, self.peak_equity or state.peak_equity)
        if self._trigger_drawdown_kill_switch(
            timestamp=request.timestamp,
            current_equity=state.equity,
            peak_equity=reference_peak,
        ):
            reasons.append("max_drawdown_exceeded")

        if state.equity <= 0:
            reasons.append("non_positive_equity")
        if request.price <= 0:
            reasons.append("non_positive_price")
        if request.quantity <= 0:
            reasons.append("non_positive_quantity")
        if side not in {"BUY", "SELL"}:
            reasons.append("invalid_side")

        if (state.equity - state.day_start_equity) <= -self.max_daily_loss:
            self.kill_switch_enabled = True
            self.kill_switch_triggered_at = request.timestamp
            reasons.append("max_daily_loss_exceeded")

        if not self.allow_after_hours:
            if not (self._trading_start_time <= request.timestamp.time() <= self._trading_end_time):
                reasons.append("outside_trading_hours")

        stop_loss_pct = (
            request.stop_loss_pct
            if request.stop_loss_pct is not None
            else self.default_stop_loss_pct
        )
        trailing_stop_pct = (
            request.trailing_stop_pct
            if request.trailing_stop_pct is not None
            else self.default_trailing_stop_pct
        )
        self._validate_request_optional_pct(stop_loss_pct, "stop_loss_pct", reasons)
        self._validate_request_optional_pct(
            trailing_stop_pct,
            "trailing_stop_pct",
            reasons,
        )

        can_evaluate_exposure = (
            side in {"BUY", "SELL"}
            and request.price > 0
            and request.quantity > 0
            and state.equity > 0
        )
        if can_evaluate_exposure:
            max_notional_per_symbol = self.max_position_size * state.equity
            current_symbol_notional = abs(state.open_positions.get(request.symbol, 0.0))
            requested_notional = request.notional

            if side == "BUY":
                projected_symbol_notional = current_symbol_notional + requested_notional
                projected_gross = state.gross_exposure + requested_notional
            else:
                projected_symbol_notional = max(current_symbol_notional - requested_notional, 0.0)
                projected_gross = max(state.gross_exposure - requested_notional, 0.0)

            if projected_symbol_notional > max_notional_per_symbol + EPSILON:
                reasons.append("max_position_size_exceeded")

            max_gross_notional = self.max_gross_exposure * state.equity
            if projected_gross > max_gross_notional + EPSILON:
                reasons.append("max_gross_exposure_exceeded")

            if side == "BUY":
                active_positions = sum(1 for value in state.open_positions.values() if value > EPSILON)
                is_new_position = current_symbol_notional <= EPSILON
                if is_new_position and active_positions >= self.max_open_positions:
                    reasons.append("max_open_positions_exceeded")

        decision = RiskDecision(
            approved=len(reasons) == 0,
            reasons=tuple(sorted(set(reasons))),
            kill_switch_enabled=self.kill_switch_enabled,
        )
        if not decision.approved:
            LOGGER.warning(
                "risk_order_rejected symbol=%s side=%s reasons=%s",
                request.symbol,
                side,
                ",".join(decision.reasons),
            )
        return decision

    def _update_peak_equity(self, current_equity: float) -> None:
        """Track highest observed equity for drawdown checks."""
        if self.peak_equity is None:
            self.peak_equity = current_equity
            return
        self.peak_equity = max(self.peak_equity, current_equity)

    def _trigger_drawdown_kill_switch(
        self,
        timestamp: pd.Timestamp,
        current_equity: float,
        peak_equity: float | None = None,
    ) -> bool:
        """Activate kill switch when drawdown limit is breached."""
        reference_peak = peak_equity if peak_equity is not None else self.peak_equity
        if reference_peak is None or reference_peak <= 0:
            return False

        drawdown = 1.0 - (current_equity / reference_peak)
        if drawdown >= self.max_drawdown_pct:
            self.kill_switch_enabled = True
            self.kill_switch_triggered_at = timestamp
            LOGGER.warning(
                "risk_drawdown_limit_breached timestamp=%s drawdown=%.6f threshold=%.6f",
                timestamp,
                drawdown,
                self.max_drawdown_pct,
            )
            return True
        return False

    @staticmethod
    def _validate_request_optional_pct(
        value: float | None,
        field_name: str,
        reasons: list[str],
    ) -> None:
        """Validate request-level stop/trailing percentages."""
        if value is None:
            return
        if value <= 0 or value >= 1:
            reasons.append(f"invalid_{field_name}")
