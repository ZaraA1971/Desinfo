"""Download Community Notes public dumps (dated ZIP shards, idempotent)."""
from __future__ import annotations

import hashlib
import logging
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from backend.config import get_settings

log = logging.getLogger("desinfo.ingest.download")

MAX_SHARDS = 20
BASE = "https://ton.twimg.com/birdwatch-public-data"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def candidate_dates(explicit: date | None = None) -> list[date]:
    if explicit:
        return [explicit]
    today = datetime.now(timezone.utc).date()
    return [today - timedelta(days=i) for i in range(0, 5)]


def download_file(url: str, dest: Path, client: httpx.Client) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code == 404:
                log.info("skip missing %s", url)
                return False
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        if dest.exists() and _sha256(tmp) == _sha256(dest):
            tmp.unlink(missing_ok=True)
            log.info("unchanged %s", dest.name)
            return True
        tmp.replace(dest)
        log.info("downloaded %s (%s bytes)", dest.name, dest.stat().st_size)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def extract_tsv_from_zip(zip_path: Path, dest_tsv: Path) -> Path:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n.endswith(".tsv")]
        if not names:
            raise RuntimeError(f"No .tsv inside {zip_path}")
        pick = next((n for n in names if Path(n).name == dest_tsv.name), names[0])
        tmp = Path(str(dest_tsv) + ".partial")
        with zf.open(pick) as src, open(tmp, "wb") as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(dest_tsv)
    log.info("extracted %s from %s", dest_tsv.name, zip_path.name)
    return dest_tsv


def resolve_dump_day(client: httpx.Client, day: date | None = None) -> date:
    """Find a date that has notes-00000.zip."""
    for d in candidate_dates(day):
        ymd = f"{d.year:04d}/{d.month:02d}/{d.day:02d}"
        url = f"{BASE}/{ymd}/notes/notes-00000.zip"
        try:
            r = client.head(url)
            if r.status_code == 200:
                return d
            # some CDNs dislike HEAD — try GET range
            r = client.get(url, headers={"Range": "bytes=0-0"})
            if r.status_code in (200, 206):
                return d
        except httpx.HTTPError as e:
            log.debug("probe %s failed: %s", url, e)
    raise RuntimeError(f"No CN dump day found under {BASE}")


def iter_shard_urls(day: date, folder: str, prefix: str) -> list[str]:
    ymd = f"{day.year:04d}/{day.month:02d}/{day.day:02d}"
    return [f"{BASE}/{ymd}/{folder}/{prefix}-{i:05d}.zip" for i in range(MAX_SHARDS)]


def download_and_extract_shard(
    url: str,
    out: Path,
    tsv_name: str,
    client: httpx.Client,
) -> Path | None:
    """Download one zip shard, extract TSV, delete zip. None if 404."""
    zip_dest = out / Path(url).name
    tsv_dest = out / tsv_name
    ok = download_file(url, zip_dest, client)
    if not ok:
        return None
    extract_tsv_from_zip(zip_dest, tsv_dest)
    zip_dest.unlink(missing_ok=True)
    return tsv_dest


def http_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(1200.0, connect=60.0), follow_redirects=True)
