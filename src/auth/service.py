"""Authentication service for single-user admin access control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.auth.security import (
    DEFAULT_PASSWORD_ITERATIONS,
    generate_session_token,
    hash_password,
    hash_session_token,
    normalize_email,
    verify_password,
)
from src.config.deployment import DeploymentSettings
from src.persistence import PersistenceRepository


class AuthenticationError(Exception):
    """Raised when credentials/session validation fails."""


class AuthorizationError(Exception):
    """Raised when a user lacks permission for an action."""


class LoginRateLimitError(Exception):
    """Raised when login attempts are temporarily blocked."""


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Authenticated user principal."""

    id: int
    email: str
    role: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Successful login/session creation payload."""

    token: str
    expires_at: datetime
    user: AuthenticatedUser


def _utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(tz=timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    """Normalize potentially-naive DB datetimes to UTC-aware values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(slots=True)
class AuthService:
    """Application auth/session service with brute-force protection."""

    repository: PersistenceRepository
    settings: DeploymentSettings

    def _login_identifier(self, email: str) -> str:
        normalized = normalize_email(email)
        if not normalized:
            raise AuthenticationError("Email is required")
        return normalized

    def _ip_value(self, ip_address: str | None) -> str:
        return (ip_address or "unknown").strip() or "unknown"

    def _to_user(self, row: dict[str, Any]) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=int(row["id"]),
            email=str(row["email"]),
            role=str(row["role"]),
            is_active=bool(row.get("is_active", False)),
        )

    def _record_login_failure(
        self,
        identifier: str,
        ip_address: str,
        reason: str,
    ) -> None:
        now = _utc_now()
        existing = self.repository.get_login_attempt(identifier=identifier, ip_address=ip_address)
        window_seconds = int(self.settings.auth_login_window_seconds)
        max_attempts = int(self.settings.auth_login_max_attempts)
        block_seconds = int(self.settings.auth_login_block_seconds)

        if existing is None:
            failure_count = 1
            window_started_at = now
        else:
            started_at = _ensure_utc(existing["window_started_at"])
            if started_at + timedelta(seconds=window_seconds) < now:
                failure_count = 1
                window_started_at = now
            else:
                failure_count = int(existing.get("failure_count", 0)) + 1
                window_started_at = started_at

        blocked_until: datetime | None = None
        if failure_count >= max_attempts:
            blocked_until = now + timedelta(seconds=block_seconds)

        self.repository.upsert_login_attempt(
            identifier=identifier,
            ip_address=ip_address,
            failure_count=failure_count,
            window_started_at=window_started_at,
            blocked_until=blocked_until,
        )
        self.repository.append_log_event(
            level="WARNING",
            logger_name="theta.auth",
            event="auth_login_failed",
            payload={
                "identifier": identifier,
                "ip_address": ip_address,
                "reason": reason,
                "failure_count": failure_count,
                "blocked_until": blocked_until.isoformat() if blocked_until else None,
            },
        )

    def _assert_login_not_blocked(self, identifier: str, ip_address: str) -> None:
        row = self.repository.get_login_attempt(identifier=identifier, ip_address=ip_address)
        if row is None:
            return
        blocked_until = row.get("blocked_until")
        if blocked_until is None:
            return
        blocked_until_utc = _ensure_utc(blocked_until)
        if blocked_until_utc <= _utc_now():
            return
        raise LoginRateLimitError(
            "Too many login attempts. Try again after "
            f"{blocked_until_utc.isoformat()}"
        )

    def login(
        self,
        email: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        """Validate credentials and create a new authenticated session."""
        if not self.settings.auth_enabled:
            raise AuthenticationError("Authentication is disabled")

        identifier = self._login_identifier(email)
        ip_value = self._ip_value(ip_address)

        try:
            self._assert_login_not_blocked(identifier=identifier, ip_address=ip_value)
        except LoginRateLimitError:
            self.repository.append_log_event(
                level="WARNING",
                logger_name="theta.auth",
                event="auth_login_blocked",
                payload={
                    "identifier": identifier,
                    "ip_address": ip_value,
                },
            )
            raise

        user_row = self.repository.get_user_by_email(identifier)
        if user_row is None:
            self._record_login_failure(identifier=identifier, ip_address=ip_value, reason="unknown_user")
            raise AuthenticationError("Invalid email or password")

        if not bool(user_row.get("is_active", False)):
            self._record_login_failure(identifier=identifier, ip_address=ip_value, reason="inactive_user")
            raise AuthenticationError("User is inactive")

        if not verify_password(password=password, password_hash=str(user_row["password_hash"]), pepper=self.settings.auth_password_pepper):
            self._record_login_failure(identifier=identifier, ip_address=ip_value, reason="invalid_password")
            raise AuthenticationError("Invalid email or password")

        self.repository.clear_login_attempt(identifier=identifier, ip_address=ip_value)

        token = generate_session_token()
        token_hash = hash_session_token(token=token, session_secret=self.settings.auth_session_secret)
        expires_at = _utc_now() + timedelta(minutes=int(self.settings.auth_session_ttl_minutes))

        self.repository.create_auth_session(
            user_id=int(user_row["id"]),
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip_value,
            user_agent=(user_agent or "").strip()[:255],
        )

        user = self._to_user(user_row)
        self.repository.append_log_event(
            level="INFO",
            logger_name="theta.auth",
            event="auth_login_succeeded",
            payload={
                "actor_user_id": user.id,
                "actor_email": user.email,
                "actor_role": user.role,
                "ip_address": ip_value,
            },
        )

        return LoginResult(token=token, expires_at=expires_at, user=user)

    def authenticate_token(self, token: str) -> tuple[AuthenticatedUser, datetime]:
        """Resolve and validate a bearer token to a user principal."""
        if not self.settings.auth_enabled:
            raise AuthenticationError("Authentication is disabled")

        token_hash = hash_session_token(token=token, session_secret=self.settings.auth_session_secret)
        row = self.repository.get_auth_session_by_token_hash(token_hash)
        if row is None:
            raise AuthenticationError("Invalid session")

        revoked_at = row.get("revoked_at")
        if revoked_at is not None:
            raise AuthenticationError("Session has been revoked")

        expires_at = _ensure_utc(row["expires_at"])
        if expires_at <= _utc_now():
            self.repository.revoke_auth_session(token_hash)
            raise AuthenticationError("Session expired")

        user_row = row["user"]
        user = self._to_user(user_row)
        if not user.is_active:
            self.repository.revoke_auth_session(token_hash)
            raise AuthenticationError("User is inactive")

        self.repository.touch_auth_session(token_hash)
        return user, expires_at

    def logout(self, token: str) -> None:
        """Revoke one active session token."""
        token_hash = hash_session_token(token=token, session_secret=self.settings.auth_session_secret)
        row = self.repository.get_auth_session_by_token_hash(token_hash)
        if row is None:
            return

        user_row = row["user"]
        self.repository.revoke_auth_session(token_hash)
        self.repository.append_log_event(
            level="INFO",
            logger_name="theta.auth",
            event="auth_logout",
            payload={
                "actor_user_id": int(user_row["id"]),
                "actor_email": str(user_row["email"]),
                "actor_role": str(user_row["role"]),
            },
        )

    def require_admin(self, user: AuthenticatedUser) -> None:
        """Enforce admin role for sensitive actions."""
        if user.role.strip().lower() != "admin":
            raise AuthorizationError("Admin role is required")

    def change_password(
        self,
        user: AuthenticatedUser,
        current_password: str,
        new_password: str,
    ) -> None:
        """Rotate password for an authenticated user."""
        if not current_password:
            raise ValueError("Current password is required")
        if not new_password:
            raise ValueError("New password is required")
        if len(new_password) < 12:
            raise ValueError("New password must be at least 12 characters")

        user_row = self.repository.get_user_by_email(user.email)
        if user_row is None or not bool(user_row.get("is_active", False)):
            raise AuthenticationError("Invalid session")

        existing_hash = str(user_row["password_hash"])
        if not verify_password(
            password=current_password,
            password_hash=existing_hash,
            pepper=self.settings.auth_password_pepper,
        ):
            self.repository.append_log_event(
                level="WARNING",
                logger_name="theta.auth",
                event="auth_password_change_failed",
                payload={
                    "actor_user_id": user.id,
                    "actor_email": user.email,
                    "actor_role": user.role,
                    "reason": "invalid_current_password",
                },
            )
            raise AuthenticationError("Current password is incorrect")

        if verify_password(
            password=new_password,
            password_hash=existing_hash,
            pepper=self.settings.auth_password_pepper,
        ):
            raise ValueError("New password must differ from the current password")

        next_hash = hash_password(
            password=new_password,
            pepper=self.settings.auth_password_pepper,
            iterations=DEFAULT_PASSWORD_ITERATIONS,
        )
        updated = self.repository.update_user_password_hash(
            user_id=user.id,
            password_hash=next_hash,
        )
        if not updated:
            raise AuthenticationError("Invalid session")

        self.repository.append_log_event(
            level="INFO",
            logger_name="theta.auth",
            event="auth_password_changed",
            payload={
                "actor_user_id": user.id,
                "actor_email": user.email,
                "actor_role": user.role,
            },
        )

    def bootstrap_admin(self, email: str, password: str) -> tuple[AuthenticatedUser, bool]:
        """Create/update initial admin user and return (user, created)."""
        normalized = normalize_email(email)
        if not normalized or "@" not in normalized:
            raise ValueError("bootstrap admin email must be a valid email")
        if len(password) < 12:
            raise ValueError("bootstrap admin password must be at least 12 characters")

        hashed = hash_password(
            password=password,
            pepper=self.settings.auth_password_pepper,
            iterations=DEFAULT_PASSWORD_ITERATIONS,
        )
        user_row, created = self.repository.upsert_bootstrap_admin(
            email=normalized,
            password_hash=hashed,
        )
        user = self._to_user(user_row)
        self.repository.append_log_event(
            level="INFO",
            logger_name="theta.auth",
            event="auth_bootstrap_admin",
            payload={
                "actor_user_id": user.id,
                "actor_email": user.email,
                "actor_role": user.role,
                "created": created,
            },
        )
        return user, created
