"""Delete snapshot partitions (date=YYYY-MM-DD folders) older than N days."""

import argparse
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("root", type=Path)
p.add_argument("--days", type=int, default=60)
a = p.parse_args()

cutoff = (datetime.now(UTC) - timedelta(days=a.days)).strftime("%Y-%m-%d")
removed = 0
for folder in sorted(a.root.glob("date=*")) if a.root.exists() else []:
    if folder.name.split("=", 1)[1] < cutoff:
        shutil.rmtree(folder)
        removed += 1
print(f"pruned {removed} day(s) older than {cutoff}")
