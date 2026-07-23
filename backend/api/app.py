"""FastAPI public API — ranking + PDF export (HMAC-gated)."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.export_auth import HEADER_SIG, HEADER_TS, verify_signature
from backend.api.rate_limit import rate_limiter
from backend.config import get_settings
from backend.db import db_session, get_meta, init_db
from backend.export.pdf import build_ranking_pdf, validate_email
from backend.media_config import load_media_roster
from backend.politicians.config import load_politicians_roster
from backend.scoring.rank import WINDOW_DAYS

log = logging.getLogger("desinfo.api")

# (kind, window) -> (mtime, payload)
_snapshot_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
KINDS = ("media", "politicians")


def _next_x_sync_at(now: datetime | None = None) -> str:
    """Next weekly X harvest: Monday 06:00 UTC (desinfo-x-sync.timer)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    days_ahead = (0 - now.weekday()) % 7  # Monday = 0
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate.isoformat()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    settings = get_settings()
    if not settings.export_hmac_secret:
        log.warning("DESINFO_EXPORT_HMAC_SECRET unset — export PDF will reject all requests")
    yield


_settings0 = get_settings()
app = FastAPI(
    title="Observatoire de la désinformation",
    description="Palmarès Community Notes — médias FR",
    version="0.3.1",
    docs_url="/docs" if _settings0.debug else None,
    redoc_url="/redoc" if _settings0.debug else None,
    openapi_url="/openapi.json" if _settings0.debug else None,
    lifespan=lifespan,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


app.add_middleware(SecurityHeadersMiddleware)


class ExportRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    window: str | None = Field(default=None)
    kind: str = Field(default="media")
    consent: bool = Field(..., description="Consentement obligatoire")


def _resolve_kind(kind: str | None) -> str:
    key = (kind or "media").strip().lower()
    if key not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(KINDS)}")
    return key


def _resolve_window(window: str | None) -> str:
    settings = get_settings()
    key = (window or settings.default_window).strip().lower()
    if key not in WINDOW_DAYS:
        raise HTTPException(status_code=400, detail=f"window must be one of {list(WINDOW_DAYS)}")
    return key


def _snapshot_path(window: str, kind: str = "media") -> Path:
    settings = get_settings()
    if kind == "politicians":
        p = settings.snapshots_dir / f"latest_politicians_{window}.json"
        if p.exists():
            return p
        raise HTTPException(status_code=404, detail=f"No politicians snapshot for window={window}")
    p = settings.snapshots_dir / f"latest_{window}.json"
    if p.exists():
        return p
    if window == settings.default_window:
        latest = settings.snapshots_dir / "latest.json"
        if latest.exists():
            return latest
    raise HTTPException(status_code=404, detail=f"No snapshot for window={window}")


def _load_snapshot(window: str, kind: str = "media") -> dict[str, Any]:
    path = _snapshot_path(window, kind)
    cache_key = (kind, window)
    try:
        mtime = path.stat().st_mtime
    except OSError as e:
        raise HTTPException(status_code=404, detail=f"No snapshot for window={window}") from e
    cached = _snapshot_cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Corrupt snapshot: {e}") from e
    _snapshot_cache[cache_key] = (mtime, data)
    return data


def _client_ip(request: Request) -> str:
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real[:64]
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate(request: Request, *, kind: str) -> None:
    settings = get_settings()
    ip = _client_ip(request)
    if kind == "export":
        if not rate_limiter.allow(
            f"export:{ip}",
            limit=settings.api_rate_limit_export,
            window_sec=60.0,
        ):
            raise HTTPException(status_code=429, detail="Trop de requêtes — réessayez plus tard")
        if not rate_limiter.allow(
            f"export_hour:{ip}",
            limit=settings.export_max_per_hour,
            window_sec=3600.0,
        ):
            raise HTTPException(
                status_code=429,
                detail="Limite d'exports atteinte (réessayez dans une heure)",
            )
        return
    if not rate_limiter.allow(f"get:{ip}", limit=settings.api_rate_limit_get, window_sec=60.0):
        raise HTTPException(status_code=429, detail="Trop de requêtes — réessayez plus tard")


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    snap = settings.snapshots_dir / f"latest_{settings.default_window}.json"
    return {
        "ok": True,
        "snapshot": snap.exists(),
    }


@app.get("/api/meta")
def meta(request: Request) -> dict[str, Any]:
    _check_rate(request, kind="get")
    settings = get_settings()
    roster = load_media_roster()
    politicians = load_politicians_roster()
    last_ingest = None
    windows_ready: dict[str, str] = {}
    politicians_windows_ready: dict[str, str] = {}

    try:
        with db_session() as conn:
            last_ingest = get_meta(conn, "last_ingest_at")
            rows = conn.execute(
                """
                SELECT window_key, COUNT(*) AS n
                FROM media_post_windows
                WHERE post_count > 0
                GROUP BY window_key
                """
            ).fetchall()
            posts_by_window = {r["window_key"]: int(r["n"]) for r in rows}
            prows = conn.execute(
                """
                SELECT window_key, COUNT(*) AS n
                FROM politician_post_windows
                WHERE post_count > 0
                GROUP BY window_key
                """
            ).fetchall()
            pol_posts = {r["window_key"]: int(r["n"]) for r in prows}
    except Exception as e:
        log.warning("meta db read failed: %s", e)
        posts_by_window = {}
        pol_posts = {}

    for w in WINDOW_DAYS:
        mode = "cn_only"
        try:
            mode = _load_snapshot(w, "media").get("metric_mode", "cn_only")
        except HTTPException:
            pass
        windows_ready[w] = mode if posts_by_window.get(w, 0) > 0 else "cn_only"

        pmode = "cn_only"
        try:
            pmode = _load_snapshot(w, "politicians").get("metric_mode", "cn_only")
        except HTTPException:
            pass
        politicians_windows_ready[w] = pmode if pol_posts.get(w, 0) > 0 else "cn_only"

    default_snap = None
    try:
        default_snap = _load_snapshot(settings.default_window, "media")
    except HTTPException:
        default_snap = None

    return {
        "default_window": settings.default_window,
        "windows": list(WINDOW_DAYS.keys()),
        "windows_ready": windows_ready,
        "politicians_windows_ready": politicians_windows_ready,
        "x_sync_windows": settings.x_sync_windows,
        "next_x_sync_at": _next_x_sync_at(),
        "roster_size": len(roster.get("media") or []),
        "politicians_roster_size": len(politicians.get("candidates") or []),
        "roster_generated_at": roster.get("generated_at"),
        "last_ingest_at": last_ingest,
        "last_snapshot_at": (default_snap or {}).get("generated_at"),
        "metric_mode": (default_snap or {}).get("metric_mode", "cn_only"),
        "kinds": list(KINDS),
    }


@app.get("/api/ranking")
def ranking(
    request: Request,
    window: str | None = Query(default=None),
    kind: str | None = Query(default="media"),
) -> dict[str, Any]:
    _check_rate(request, kind="get")
    return _load_snapshot(_resolve_window(window), _resolve_kind(kind))


@app.post("/api/export")
def export_pdf(body: ExportRequest, request: Request) -> Response:
    _check_rate(request, kind="export")
    settings = get_settings()

    if not body.consent:
        raise HTTPException(status_code=400, detail="Le consentement est obligatoire")

    window = _resolve_window(body.window)
    kind = _resolve_kind(body.kind)

    try:
        email = validate_email(body.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    ip = _client_ip(request)
    ts = request.headers.get(HEADER_TS) or ""
    sig = request.headers.get(HEADER_SIG) or ""
    if not settings.export_hmac_secret or not verify_signature(
        settings.export_hmac_secret,
        ts=ts,
        email=email,
        window=window,
        ip=ip,
        kind=kind,
        signature=sig,
    ):
        raise HTTPException(status_code=401, detail="Signature d'export invalide ou expirée")

    snapshot = _load_snapshot(window, kind)
    pdf_bytes = build_ranking_pdf(snapshot, email)
    now = datetime.now(timezone.utc).isoformat()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO exports(email, window_key, ip, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, f"{kind}:{window}", ip, now),
        )
    fname = f"desinfo_{kind}_{window}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    log.info("export pdf kind=%s window=%s ip=%s bytes=%s", kind, window, ip, len(pdf_bytes))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
