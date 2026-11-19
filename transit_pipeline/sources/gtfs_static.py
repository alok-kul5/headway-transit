"""Download the static GTFS schedule and store the files we use as parquet."""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import duckdb
import requests

from .. import config


@dataclass
class StaticLoadResult:
    changed: bool
    last_modified: str | None
    row_counts: dict[str, int]


def _marker(gtfs_dir: Path) -> Path:
    return gtfs_dir / "_source.json"


def remote_last_modified(url: str) -> str | None:
    r = requests.head(url, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    return r.headers.get("Last-Modified")


def zip_to_parquet(zip_bytes: bytes, gtfs_dir: Path, files=config.GTFS_FILES) -> dict[str, int]:
    """Write each wanted GTFS text file to `<name>.parquet`; returns row counts.

    Everything is read as text: GTFS times such as 25:10:00 are not valid
    clock times, and IDs with leading zeros must stay strings.
    """
    gtfs_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        missing = [f for f in files if f"{f}.txt" not in names]
        if missing:
            raise ValueError(f"GTFS feed is missing required files: {missing}")
        con = duckdb.connect()
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            for name in files:
                src = tmp / f"{name}.txt"
                src.write_bytes(zf.read(f"{name}.txt"))
                out = gtfs_dir / f"{name}.parquet"
                con.execute(
                    f"COPY (SELECT * FROM read_csv('{src.as_posix()}', header=true, all_varchar=true, "
                    "quote='\"', escape='\"', delim=',')) "
                    f"TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
                )
                counts[name] = con.execute(f"SELECT count(*) FROM '{out.as_posix()}'").fetchone()[0]
        con.close()
    return counts


def refresh(url: str = config.GTFS_STATIC_URL, gtfs_dir: Path = config.GTFS_DIR, force: bool = False) -> StaticLoadResult:
    """Re-download the feed only when the server says it has changed."""
    marker = _marker(gtfs_dir)
    previous = json.loads(marker.read_text()) if marker.exists() else {}
    last_modified = remote_last_modified(url)
    have_files = all((gtfs_dir / f"{f}.parquet").exists() for f in config.GTFS_FILES)

    if not force and have_files and last_modified and previous.get("last_modified") == last_modified:
        return StaticLoadResult(False, last_modified, previous.get("row_counts", {}))

    r = requests.get(url, timeout=config.HTTP_TIMEOUT * 3, headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    counts = zip_to_parquet(r.content, gtfs_dir)
    marker.write_text(json.dumps({"url": url, "last_modified": last_modified, "row_counts": counts}, indent=2))
    return StaticLoadResult(True, last_modified, counts)
