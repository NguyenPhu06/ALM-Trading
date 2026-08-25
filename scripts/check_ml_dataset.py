from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.datasets import DatasetReadinessChecker
from config.settings import ROOT, load_yaml


def main() -> int:
    phase = load_yaml().get("phase_4", {})
    parser = argparse.ArgumentParser(description="Validate an exported Phase 4 ML dataset")
    parser.add_argument("metadata", nargs="?", default=None)
    parser.add_argument("--minimum-samples", type=int, default=int(phase.get("minimum_samples", 1000)))
    args = parser.parse_args()
    if args.metadata:
        path = Path(args.metadata)
    else:
        candidates = sorted((ROOT / "data" / "ml").glob("*_dataset_metadata.json"))
        path = candidates[-1] if candidates else ROOT / "data" / "ml" / "missing_dataset_metadata.json"
    report = DatasetReadinessChecker(minimum_samples=args.minimum_samples).check_files(path)
    print(report.status)
    print(json.dumps({"reasons": report.reasons, "samples": report.row_count, "features": report.feature_count}, indent=2))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
