from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

UserRole = Literal["customer", "admin"]
DEFAULT_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    name: str
    email: str
    role: UserRole


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = stored_hash.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError:
        return False
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return hmac.compare_digest(derived, expected)


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def issue_token(
    user: AuthenticatedUser,
    secret: str,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
) -> str:
    payload = {
        "sub": user.user_id,
        "role": user.role,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64_encode(payload_bytes)
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64_encode(sig)}"


def verify_token(token: str, secret: str) -> dict[str, Any] | None:
    if "." not in token:
        return None
    payload_b64, sig_b64 = token.split(".", 1)
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        provided_sig = _b64_decode(sig_b64)
    except ValueError:
        return None
    if not hmac.compare_digest(expected_sig, provided_sig):
        return None
    try:
        data = json.loads(_b64_decode(payload_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < int(time.time()):
        return None
    return data
