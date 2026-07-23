"""HMAC signatures for export PDF requests (Next → FastAPI)."""
from __future__ import annotations

import hashlib
import hmac
import time


HEADER_TS = "X-Desinfo-Export-Ts"
HEADER_SIG = "X-Desinfo-Export-Sig"
DEFAULT_TTL_SEC = 300


def sign_payload(
    secret: str,
    *,
    ts: str,
    email: str,
    window: str,
    ip: str,
    kind: str = "media",
) -> str:
    msg = f"{ts}\n{email}\n{window}\n{ip}\n{kind}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_signature(
    secret: str,
    *,
    ts: str,
    email: str,
    window: str,
    ip: str,
    signature: str,
    kind: str = "media",
    ttl_sec: int = DEFAULT_TTL_SEC,
    now: float | None = None,
) -> bool:
    if not secret or not ts or not signature:
        return False
    try:
        ts_i = int(ts)
    except ValueError:
        return False
    now_f = time.time() if now is None else now
    if abs(now_f - ts_i) > ttl_sec:
        return False
    expected = sign_payload(
        secret, ts=ts, email=email, window=window, ip=ip, kind=kind
    )
    return hmac.compare_digest(expected, signature)
