"""Security primitives for password hashing and session tokens."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

DEFAULT_PASSWORD_ITERATIONS = 390_000


def normalize_email(value: str) -> str:
    """Normalize user identifier to lower-case email form."""
    return value.strip().lower()


def _password_material(password: str, pepper: str) -> bytes:
    """Create deterministic password material including secret pepper."""
    return f"{password}{pepper}".encode("utf-8")


def hash_password(
    password: str,
    pepper: str,
    iterations: int = DEFAULT_PASSWORD_ITERATIONS,
) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and return a serialized hash."""
    if not password:
        raise ValueError("password cannot be empty")
    if not pepper:
        raise ValueError("password pepper cannot be empty")
    if iterations <= 0:
        raise ValueError("password hash iterations must be positive")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        _password_material(password, pepper),
        salt,
        iterations,
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def verify_password(password: str, password_hash: str, pepper: str) -> bool:
    """Verify a plaintext password against a serialized PBKDF2 hash."""
    if not password or not password_hash or not pepper:
        return False

    parts = password_hash.split("$")
    if len(parts) != 4:
        return False
    algorithm, iterations_raw, salt_b64, digest_b64 = parts
    if algorithm != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
    except (ValueError, binascii.Error):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        _password_material(password, pepper),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def generate_session_token() -> str:
    """Generate a high-entropy opaque session token."""
    return secrets.token_urlsafe(48)


def hash_session_token(token: str, session_secret: str) -> str:
    """Return a stable HMAC digest for one session token."""
    if not token:
        raise ValueError("token cannot be empty")
    if not session_secret:
        raise ValueError("session secret cannot be empty")
    digest = hmac.new(
        key=session_secret.encode("utf-8"),
        msg=token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest
