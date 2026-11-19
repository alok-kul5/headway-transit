"""Copy the raw snapshots collected by GitHub Actions (the `data` branch) into data/raw."""

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

subprocess.run(["git", "fetch", "-q", "origin", "data"], cwd=ROOT, check=True)
with tempfile.TemporaryDirectory() as tmp:
    archive = Path(tmp) / "data.tar"
    subprocess.run(["git", "archive", "-o", str(archive), "FETCH_HEAD"], cwd=ROOT, check=True)
    shutil.unpack_archive(archive, tmp)
    for name in ("trip_updates", "weather"):
        src = Path(tmp) / name
        if src.exists():
            shutil.copytree(src, RAW / name, dirs_exist_ok=True)
n = len(list((RAW / "trip_updates").glob("*/*.parquet")))
print(f"{n} snapshots in {RAW / 'trip_updates'}")
