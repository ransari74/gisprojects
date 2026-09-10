"""Compare all local experiment records (written by src/tracking.py) and
report the winning model, used both as a standalone comparison tool and as
the SageMaker Pipelines evaluation step.
"""
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiments-dir", type=Path, default=Path("./experiments"))
    parser.add_argument("--metric", default="val_auc")
    args = parser.parse_args()

    records = []
    for path in sorted(args.experiments_dir.glob("*.json")):
        with open(path) as f:
            records.append(json.load(f))

    if not records:
        print(f"No experiment records found in {args.experiments_dir}")
        return

    records.sort(key=lambda r: r["metrics"].get(args.metric, float("-inf")), reverse=True)

    print(f"{'run_name':<20} {args.metric:>10}  metrics")
    for r in records:
        metric_val = r["metrics"].get(args.metric)
        print(f"{r['run_name']:<20} {metric_val:>10.4f}  {r['metrics']}")

    best = records[0]
    print(f"\nBest model: {best['run_name']} ({args.metric}={best['metrics'].get(args.metric):.4f})")


if __name__ == "__main__":
    main()
