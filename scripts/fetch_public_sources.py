#!/usr/bin/env python3
"""Laptop fallback for bronze/01: download the public sources locally, optionally upload to the volume.

Use this if the Databricks workspace can't reach the internet (Free Edition may restrict egress).

    python scripts/fetch_public_sources.py                       # download to ./data/public
    python scripts/fetch_public_sources.py --only svi_county_2022,places_county
    python scripts/fetch_public_sources.py --upload --profile Mekeli
    python scripts/fetch_public_sources.py --list                # show the catalog

--upload runs `databricks fs cp` into /Volumes/<catalog>/<bronze_schema>/<volume>/public/
(run notebooks/00_setup first so the volume exists). Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from hc.io import download  # noqa: E402  (stdlib-only at import time)
from hc.sources import select_sources  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="all", help="comma-separated source keys (default: all)")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "public"))
    ap.add_argument("--force", action="store_true", help="re-download files that already exist")
    ap.add_argument("--list", action="store_true", help="print the source catalog and exit")
    ap.add_argument("--upload", action="store_true", help="copy into the Databricks landing volume")
    ap.add_argument("--profile", help="Databricks CLI profile for --upload")
    ap.add_argument("--catalog", default="workspace")
    ap.add_argument("--bronze-schema", default="hc_bronze")
    ap.add_argument("--volume", default="landing")
    args = ap.parse_args()

    sources = select_sources(args.only)
    if args.list:
        for s in sources:
            print(f"{s.key:<26} {s.grain:<40} {s.publisher:<18} {s.title}")
        return 0

    failed = []
    for s in sources:
        dest = os.path.join(args.out, s.key, s.filename)
        if os.path.exists(dest) and not args.force:
            print(f"skip   {s.key:<26} (exists, {os.path.getsize(dest) / 1e6:,.1f} MB)")
            continue
        print(f"fetch  {s.key:<26} ...", end="", flush=True)
        try:
            size = download(s.url, dest)
            print(f" {size / 1e6:,.1f} MB")
        except Exception as exc:
            print(f" FAILED: {exc}")
            failed.append(s.key)

    if args.upload:
        if not args.profile:
            print("--upload needs --profile (run `databricks auth profiles` to list them)")
            return 2
        target = f"dbfs:/Volumes/{args.catalog}/{args.bronze_schema}/{args.volume}/public"
        for s in sources:
            local_dir = os.path.join(args.out, s.key)
            if not os.path.isdir(local_dir):
                continue
            cmd = ["databricks", "fs", "cp", "-r", "--overwrite", local_dir, f"{target}/{s.key}", "--profile", args.profile]
            print("upload", s.key, "->", f"{target}/{s.key}")
            subprocess.run(cmd, check=True)

    if failed:
        print(f"\nFailed: {failed}. Check the URLs/homepages in src/hc/sources.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
