"""Configuration centralisée — Observatoire desinfo."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(os.environ.get("DESINFO_ROOT", "/srv/desinfo"))
load_dotenv(ROOT / ".env", override=True)


class Settings:
    def __init__(self) -> None:
        self.root: Path = ROOT
        self.db_path: Path = Path(os.environ.get("DESINFO_DB", str(ROOT / "data" / "desinfo.db")))
        self.raw_dir: Path = ROOT / "data" / "raw"
        self.snapshots_dir: Path = ROOT / "data" / "snapshots"
        self.media_domains_path: Path = ROOT / "config" / "media_domains.yml"
        self.media_roster_path: Path = ROOT / "config" / "media_roster.yml"
        self.politicians_roster_path: Path = ROOT / "config" / "politicians_roster.yml"

        self.api_host: str = os.environ.get("DESINFO_API_HOST", "127.0.0.1")
        self.api_port: int = int(os.environ.get("DESINFO_API_PORT", "8700"))
        self.frontend_port: int = int(os.environ.get("DESINFO_FRONTEND_PORT", "8710"))
        self.default_window: str = os.environ.get("DESINFO_DEFAULT_WINDOW", "7d")
        self.bootstrap_days: int = int(os.environ.get("DESINFO_BOOTSTRAP_DAYS", "365"))
        self.roster_min_cn: int = int(os.environ.get("DESINFO_ROSTER_MIN_CN", "3"))
        self.debug: bool = os.environ.get("DESINFO_DEBUG", "0") in ("1", "true", "True")
        self.x_sync_windows: list[str] = [
            w.strip()
            for w in os.environ.get("DESINFO_X_SYNC_WINDOWS", "7d").split(",")
            if w.strip()
        ]
        # Cascade longer windows from daily counts (no X API) when coverage allows
        self.cascade_coverage: float = float(os.environ.get("DESINFO_CASCADE_COVERAGE", "0.7"))
        self.cascade_windows: list[str] = [
            w.strip()
            for w in os.environ.get("DESINFO_CASCADE_WINDOWS", "30d,90d,365d").split(",")
            if w.strip()
        ]

        self.cn_base_url: str = os.environ.get(
            "DESINFO_CN_BASE_URL",
            "https://ton.twimg.com/birdwatch-public-data",
        )

        self.x_api_key: str | None = os.environ.get("X_API_KEY") or None
        self.x_api_secret: str | None = os.environ.get("X_API_SECRET") or None
        self.x_bearer_token: str | None = os.environ.get("X_BEARER_TOKEN") or None
        self.export_max_per_hour: int = int(os.environ.get("DESINFO_EXPORT_MAX_PER_HOUR", "5"))
        self.export_hmac_secret: str = os.environ.get("DESINFO_EXPORT_HMAC_SECRET", "") or ""
        self.api_rate_limit_get: int = int(os.environ.get("DESINFO_API_RATE_LIMIT_GET", "120"))
        self.api_rate_limit_export: int = int(os.environ.get("DESINFO_API_RATE_LIMIT_EXPORT", "10"))
        self.public_url: str = os.environ.get(
            "DESINFO_PUBLIC_URL", "https://desinfo.electronlibre.info"
        )

    @property
    def x_api_configured(self) -> bool:
        return bool(self.x_bearer_token or (self.x_api_key and self.x_api_secret))


@lru_cache
def get_settings() -> Settings:
    return Settings()
