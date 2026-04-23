"""Polymarket CLOB API HTTP client with auth and retry logic."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.polymarket.config import PolymarketConfig

LOGGER = logging.getLogger("theta.polymarket.client")


@dataclass(slots=True)
class ClobClient:
    """HTTP client for the Polymarket CLOB API.

    GET endpoints (markets, orderbooks) are public. Auth headers are
    included on all requests for L1-authenticated endpoints in the future.
    """

    config: PolymarketConfig

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """Build L1 HMAC-SHA256 auth headers for a request."""
        ts = str(int(time.time()))
        message = ts + method.upper() + path + body
        signature = base64.b64encode(
            hmac.new(
                self.config.api_secret.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return {
            "POLY-API-KEY": self.config.api_key,
            "POLY-SIGNATURE": signature,
            "POLY-TIMESTAMP": ts,
            "POLY-PASSPHRASE": self.config.passphrase,
        }

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """GET with exponential-backoff retry (max_retries attempts after first failure)."""
        url = self.config.clob_base_url + path
        headers = self._auth_headers("GET", path)
        effective_timeout = timeout if timeout is not None else self.config.timeout_seconds
        effective_retries = max_retries if max_retries is not None else self.config.max_retries
        last_exc: Exception | None = None

        for attempt in range(effective_retries + 1):
            if attempt > 0:
                sleep_sec = 2 ** (attempt - 1)
                LOGGER.warning(
                    "polymarket_retry attempt=%d path=%s sleep_sec=%d",
                    attempt,
                    path,
                    sleep_sec,
                )
                time.sleep(sleep_sec)

            try:
                with httpx.Client(timeout=effective_timeout) as http:
                    resp = http.get(url, headers=headers, params=params)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                LOGGER.error(
                    "polymarket_http_error status=%d path=%s",
                    exc.response.status_code,
                    path,
                )
                last_exc = exc
                # 4xx errors are not transient — don't retry
                if exc.response.status_code < 500:
                    raise
            except httpx.RequestError as exc:
                LOGGER.error("polymarket_request_error path=%s error=%s", path, exc)
                last_exc = exc

        raise RuntimeError(
            f"polymarket request failed after {effective_retries + 1} attempts"
            f" path={path} last_error={last_exc}"
        )

    def fetch_markets(self, next_cursor: str = "") -> dict[str, Any]:
        """Fetch one page of markets from the CLOB API.

        NOTE: The CLOB /markets endpoint ignores all filter params (active,
        closed, accepting_orders) — every combination returns the same result.
        Filtering must be done client-side in _tradability_skip_reason().
        """
        params: dict[str, Any] = {"active": "true"}
        if next_cursor:
            params["next_cursor"] = next_cursor
        return self._get("/markets", params=params)

    def fetch_market_by_token(self, token_id: str) -> dict[str, Any]:
        """Resolve a token ID to its parent CLOB market."""
        return self._get(f"/markets-by-token/{token_id}")

    def fetch_orderbook(self, token_id: str, timeout: float | None = None) -> dict[str, Any]:
        """Fetch the L2 orderbook for a single token (YES or NO outcome)."""
        return self._get("/book", params={"token_id": token_id}, timeout=timeout, max_retries=0)

    def fetch_orderbook_with_client(
        self, http: "httpx.Client", token_id: str
    ) -> dict[str, Any]:
        """Fetch one orderbook reusing an existing httpx.Client (for concurrent batches)."""
        url = self.config.clob_base_url + "/book"
        headers = self._auth_headers("GET", "/book")
        resp = http.get(url, headers=headers, params={"token_id": token_id})
        resp.raise_for_status()
        return resp.json()

    def fetch_market_detail(self, condition_id: str) -> dict[str, Any]:
        """Fetch full market detail including resolution status and end date."""
        return self._get(f"/markets/{condition_id}")
