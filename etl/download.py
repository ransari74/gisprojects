"""Fetch the real open datasets registered in etl/config.py.

    python -m etl.download --list             # show the registry
    python -m etl.download --all              # fetch everything (~660 MB)
    python -m etl.download --project agriculture
    python -m etl.download --layer agri_fields

Downloads land in data/raw/. Files are skipped if already present unless
--force is given, and a partial download is written to a .part file first so an
interrupted run never leaves a truncated file that looks complete.

This is the fetch step only. Turning the downloads into rows needs GDAL, which
is a heavier dependency than the rest of the ETL: see the per-dataset notes
printed by --list, and docs/DATA_SOURCES.md for the exact ogr2ogr and
raster2pgsql invocations. `etl/generate.py` produces the same schema with no
network at all, and is what the demo runs on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from etl.config import DATASETS, MAX_LAT, MAX_LON, MIN_LAT, MIN_LON, Dataset

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
CHUNK = 1 << 20  # 1 MiB


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def target_path(dataset: Dataset) -> Path:
    name = dataset.url.split("?")[0].rstrip("/").split("/")[-1] or f"{dataset.layer}.bin"
    return RAW_DIR / dataset.project / name


def fetch(dataset: Dataset, *, force: bool = False, timeout: float = 120.0) -> Path | None:
    dest = target_path(dataset)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        print(f"  skip   {dest.relative_to(RAW_DIR)} ({human(dest.stat().st_size)}, already present)")
        return dest

    if "{" in dataset.url:
        # A tile template, not a file -- MapLibre or the tiler consumes these
        # directly and there is nothing to download.
        print(f"  n/a    {dataset.name}: tile template, consumed at request time")
        return None

    part = dest.with_suffix(dest.suffix + ".part")
    print(f"  get    {dataset.name}\n         {dataset.url}")

    try:
        with httpx.stream("GET", dataset.url, follow_redirects=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            written = 0
            with part.open("wb") as fh:
                for chunk in resp.iter_bytes(CHUNK):
                    fh.write(chunk)
                    written += len(chunk)
                    if total:
                        pct = 100 * written / total
                        print(f"\r         {human(written)} / {human(total)} ({pct:.0f}%)", end="")
                    else:
                        print(f"\r         {human(written)}", end="")
            print()
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        print(f"         FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None

    # Only now does the file get its real name, so an interrupted run cannot
    # leave something that looks like a complete download.
    part.replace(dest)
    print(f"         saved {dest.relative_to(RAW_DIR)} ({human(dest.stat().st_size)})")
    return dest


def show_registry() -> None:
    bbox = f"{MIN_LON},{MIN_LAT},{MAX_LON},{MAX_LAT}"
    print(f"Study area bbox (EPSG:4326): {bbox}\n")
    by_project: dict[str, list[Dataset]] = {}
    for dataset in DATASETS:
        by_project.setdefault(dataset.project, []).append(dataset)

    for project, datasets in by_project.items():
        print(f"{project.upper()}")
        for d in datasets:
            print(f"  {d.layer}")
            print(f"    {d.name}  [{d.license}]  {d.fmt}")
            print(f"    {d.url}")
            if d.notes:
                print(f"    note: {d.notes}")
        print()

    print("Loading these into PostGIS needs GDAL. Typical invocations:\n")
    print(f"  # vector, clipped to the study area")
    print(f"  ogr2ogr -f PostgreSQL PG:\"$DATABASE_URL\" input.gpkg \\")
    print(f"      -nln agri.fields -nlt MULTIPOLYGON -t_srs EPSG:4326 \\")
    print(f"      -clipsrc {MIN_LON} {MIN_LAT} {MAX_LON} {MAX_LAT}\n")
    print(f"  # raster sampled per feature centroid (soil, land cover)")
    print(f"  gdallocationinfo -valonly -wgs84 soil_ph.tif <lon> <lat>\n")
    print(f"  # contours from the DEM")
    print(f"  gdal_contour -a elevation_m -i 5 dem.tif contours.gpkg\n")
    print("See docs/DATA_SOURCES.md for the per-dataset detail.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="Show the registry and exit")
    parser.add_argument("--all", action="store_true", help="Fetch every registered dataset")
    parser.add_argument("--project", help="Fetch one project's datasets")
    parser.add_argument("--layer", help="Fetch one layer's dataset")
    parser.add_argument("--force", action="store_true", help="Re-download files already present")
    args = parser.parse_args()

    if args.list or not (args.all or args.project or args.layer):
        show_registry()
        return 0

    selected = [
        d
        for d in DATASETS
        if args.all
        or (args.project and d.project == args.project)
        or (args.layer and d.layer == args.layer)
    ]
    if not selected:
        print("Nothing matched. Try --list.", file=sys.stderr)
        return 1

    print(f"Fetching {len(selected)} dataset(s) into {RAW_DIR}\n")
    failures = 0
    for dataset in selected:
        if fetch(dataset, force=args.force) is None and "{" not in dataset.url:
            failures += 1

    print(f"\nDone. {len(selected) - failures} succeeded, {failures} failed.")
    if failures:
        print("Several hosts rate-limit or require a browser user-agent; see docs/DATA_SOURCES.md.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
