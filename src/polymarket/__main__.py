"""Polymarket arb scanner — standalone entrypoint.

Run:
    python -m src.polymarket

Environment variables must be set (see src/polymarket/README.md or .env.example).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from src.dashboard.aggregator import is_poly_paused
from src.observability.logging import configure_logging
from src.polymarket.client import ClobClient
from src.polymarket.config import PolymarketConfig
from src.polymarket.feedback import load_feedback_records
from src.polymarket.monitor import monitor_positions
from src.polymarket.positions import make_ledger
from src.polymarket.runner import scan_and_execute
from src.polymarket.tuner import check_minimum_data, propose_tuning, write_proposal

LOGGER = logging.getLogger("theta.polymarket.main")

_TUNING_INTERVAL_HOURS = float(os.getenv("POLY_TUNING_INTERVAL_HOURS", "168"))
_SIGNAL_PARAMS_PATH = os.getenv("POLY_SIGNAL_PARAMS_PATH", "polymarket/signal_params.json")
_TUNER_PROPOSAL_PATH = "polymarket/signal_params_proposed.json"
_AI_ANALYSIS_INTERVAL_HOURS = float(os.getenv("AI_ANALYSIS_INTERVAL_HOURS", "24"))

# ---------------------------------------------------------------------------
# Opportunity observation persistence — lazy singleton, best-effort only
# ---------------------------------------------------------------------------
_OBS_REPO: Any = None  # PersistenceRepository | None


def _get_obs_repo() -> Any:
    """Return a cached PersistenceRepository, or None if DATABASE_URL is unset."""
    global _OBS_REPO
    if _OBS_REPO is not None:
        return _OBS_REPO
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        return None
    try:
        from src.persistence.store import DatabaseStore
        from src.persistence.repository import PersistenceRepository
        store = DatabaseStore(database_url=db_url)
        store.create_schema()
        _OBS_REPO = PersistenceRepository(store=store)
    except Exception as exc:
        LOGGER.warning("opportunity_observation_repo_init_failed error=%s", exc)
    return _OBS_REPO


def _persist_opportunity_observations(
    cycle_key: str,
    scores: list[Any],
    scan_opps: list[Any],
    exec_result: Any,
    dry_run: bool,
) -> None:
    """Write all scored opportunities for this cycle to Postgres. Never raises."""
    repo = _get_obs_repo()
    if repo is None:
        return
    try:
        # The top scan_opp is the one runner.py submitted for execution.
        selected_label: str | None = None
        if scan_opps and exec_result is not None:
            selected_label = scan_opps[0].market_question[:200]
        n = repo.record_opportunity_observations(
            cycle_key=cycle_key,
            scores=scores,
            selected_label=selected_label,
            execution_result=exec_result,
            dry_run=dry_run,
        )
        LOGGER.info(
            "opportunity_observations_persisted cycle=%s count=%d", cycle_key, n
        )
    except Exception as exc:
        LOGGER.warning(
            "opportunity_observation_persist_failed cycle=%s error=%s", cycle_key, exc
        )


def _run_tuning_cycle(config: PolymarketConfig) -> None:
    records = load_feedback_records(
        days=30,
        positions_path=config.positions_path,
        log_dir=config.poly_log_dir,
    )
    ok, reason = check_minimum_data(records)
    if not ok:
        LOGGER.info("polymarket_tuning_skipped reason=%s", reason)
        return
    result = propose_tuning(records, days=30, params_path=_SIGNAL_PARAMS_PATH)
    if not result.proposed_changes:
        LOGGER.info("polymarket_tuning_no_changes trade_count=%d", result.trade_count)
        return
    write_proposal(result, _TUNER_PROPOSAL_PATH)
    LOGGER.info(
        "polymarket_tuning_proposal_written changes=%d trade_count=%d",
        len(result.proposed_changes),
        result.trade_count,
    )


def _assert_wallet_key_match(config: PolymarketConfig) -> None:
    """Raise RuntimeError if POLY_WALLET doesn't match POLY_PRIVATE_KEY.

    For proxy wallets, POLY_WALLET_ADDRESS (the proxy/funder) is expected to
    differ from the signer EOA, so we only check POLY_WALLET here.

    Skipped silently when POLY_WALLET is unset or eth_account is missing.
    Called once on startup, before the scan loop begins.
    """
    # Use the signer EOA for this sanity check, not the proxy wallet.
    configured_signer = os.getenv("POLY_WALLET", "").strip()
    if not configured_signer:
        return

    try:
        from eth_account import Account  # type: ignore[import]
    except ImportError:
        LOGGER.warning("wallet_key_check_skipped reason=eth_account_not_installed")
        return

    try:
        derived: str = Account.from_key(config.private_key).address
    except Exception as exc:
        LOGGER.warning(
            "wallet_key_check_skipped reason=key_derivation_failed error=%s", exc
        )
        return

    if derived.lower() != configured_signer.lower():
        raise RuntimeError(
            "POLY_WALLET ({configured}) does not match the address "
            "derived from POLY_PRIVATE_KEY ({derived_prefix}...) — check your "
            ".env configuration before going live".format(
                configured=configured_signer,
                derived_prefix=derived[:10],
            )
        )

    LOGGER.info("polymarket_wallet_verified address=%s", derived[:10] + "...")
    _debug_clob_collateral(config)

def _run_ai_analysis_cycle() -> None:
    """Run the Phase 7 AI analysis (schedule-aware, idempotent)."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        LOGGER.info("polymarket_ai_analysis_skipped reason=DATABASE_URL_not_set")
        return
    from trauto.ai.loop import _run_scheduled_analysis
    result = _run_scheduled_analysis(db_url)
    LOGGER.info(
        "polymarket_ai_analysis_complete outcome=%s",
        result.get("outcome", result.get("reason", "unknown")),
    )


def main() -> None:
    configure_logging()
    config = PolymarketConfig.from_env()
    _assert_wallet_key_match(config)

    # Startup auth preflight — detect credential/signature_type issues immediately.
    # Logs polymarket_auth_preflight status=ok|fail; does NOT abort startup on fail
    # so the scan loop still runs and the next journalctl shows the exact error body.
    try:
        from src.polymarket.executor import _auth_preflight
        _auth_preflight(config)
    except Exception as exc:
        LOGGER.warning("polymarket_startup_preflight_error error=%s", exc)

    LOGGER.info(
        "polymarket_runtime_mode active_trading_mode=%s active_venue=%s "
        "execution_adapter=polymarket_clob paper_trading=%s dry_run=%s "
        "live_trading=%s signal_provider=%s alpaca_trading_mode=%s "
        "poly_trading_mode=%s",
        config.trading_mode,
        config.trading_venue,
        False,
        config.dry_run,
        config.live_trading_enabled,
        config.signal_provider,
        config.alpaca_trading_mode,
        config.poly_trading_mode,
    )

    LOGGER.info(
        "polymarket_scanner_starting interval_sec=%d monitor_interval_sec=%d "
        "min_edge_pct=%.2f dry_run=%s max_trade_usdc=%.2f",
        config.scan_interval_sec,
        config.monitor_interval_sec,
        config.min_edge_pct,
        config.dry_run,
        config.max_trade_usdc,
    )

    client = ClobClient(config=config)
    ledger = make_ledger(config.positions_path)
    last_monitor_time = 0.0
    last_tuning_time = 0.0
    last_ai_time = 0.0

    while True:
        _cycle_key = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _scan_opps: list = []
        _exec_result: Any = None
        if is_poly_paused():
            LOGGER.info("polymarket_scan_skipped reason=dashboard_pause_flag")
        else:
            try:
                _scan_opps, _exec_result = scan_and_execute(config)
            except Exception as exc:
                LOGGER.error("polymarket_scan_error error=%s", exc)

        now = time.monotonic()
        if now - last_monitor_time >= config.monitor_interval_sec:
            try:
                monitor_positions(config, client, ledger)
            except Exception as exc:
                LOGGER.error("polymarket_monitor_error error=%s", exc)
            last_monitor_time = time.monotonic()

        now = time.monotonic()
        if now - last_tuning_time >= _TUNING_INTERVAL_HOURS * 3600:
            try:
                _run_tuning_cycle(config)
            except Exception as exc:
                LOGGER.error("polymarket_tuning_error error=%s", exc)
            last_tuning_time = time.monotonic()

        now = time.monotonic()
        if now - last_ai_time >= _AI_ANALYSIS_INTERVAL_HOURS * 3600:
            try:
                _run_ai_analysis_cycle()
            except Exception as exc:
                LOGGER.error("polymarket_ai_analysis_error error=%s", exc)
            last_ai_time = time.monotonic()

        # Cross-venue capital unification (REBALANCE_DRY_RUN=true by default).
        # Skip when no opps were gathered — evaluate() would find gap=0 for all
        # venue pairs anyway, and probe_all() would make 3 pointless HTTP calls.
        if _scan_opps:
            try:
                from src.capital.adapter import opportunity_to_score, funding_rate_to_score
                from src.capital.rebalance_orchestrator import run_rebalance_cycle
                _scores = [opportunity_to_score(o) for o in _scan_opps]
                try:
                    from funding_arb.monitor import get_funding_rates
                    for r in get_funding_rates():
                        if r.get("rate", 0) > 0:
                            _scores.append(funding_rate_to_score(r["asset"], r["rate"]))
                except Exception:
                    pass  # funding rates are best-effort
                run_rebalance_cycle(_scores)
                _persist_opportunity_observations(
                    cycle_key=_cycle_key,
                    scores=_scores,
                    scan_opps=_scan_opps,
                    exec_result=_exec_result,
                    dry_run=config.dry_run,
                )
            except Exception as exc:
                LOGGER.warning("rebalance_cycle_error error=%s", exc)

        try:
            from src.events.calendar import get_scan_multiplier
            multiplier = get_scan_multiplier()
        except Exception:
            multiplier = 1.0
        sleep_sec = max(30, int(config.scan_interval_sec * multiplier))
        LOGGER.info("polymarket_scan_sleeping seconds=%d event_multiplier=%.2f", sleep_sec, multiplier)
        time.sleep(sleep_sec)


if __name__ == "__main__":
    main()
from src.polymarket.client import _debug_clob_collateral
