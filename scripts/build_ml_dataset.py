from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.datasets import DatasetExporter, DatasetReadinessChecker, HistoricalDatasetBuilder
from config.settings import ROOT, load_yaml
from database.repositories import CandleRepository, MLDatasetRepository
from database.session import SessionLocal


def main() -> int:
    config = load_yaml()
    phase = config.get("phase_4", {})
    parser = argparse.ArgumentParser(description="Build an immutable causal Phase 4 ML dataset")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--source", default=None, help="Optional single provider/source to avoid ambiguous duplicate feeds")
    parser.add_argument("--output", default=str(ROOT / "data" / "ml"))
    parser.add_argument("--include-sample", action="store_true")
    parser.add_argument("--allow-incomplete-timeframes", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--minimum-samples", type=int, default=int(phase.get("minimum_samples", 1000)))
    args = parser.parse_args()
    sample_sources = () if args.include_sample else tuple(config.get("market_data", {}).get("sample_sources", ("local_csv",)))
    try:
        with SessionLocal() as session:
            repository = CandleRepository(session)
            candles = {
                timeframe: repository.chronological(
                    symbol=args.symbol.upper(), timeframe=timeframe, source=args.source,
                    exclude_sources=sample_sources, closed_only=True,
                )
                for timeframe in HistoricalDatasetBuilder.TIMEFRAMES
            }
            builder = HistoricalDatasetBuilder(
                classification_threshold=float(phase.get("classification_threshold", 0.0005)),
                outcome_threshold=float(phase.get("outcome_threshold", 0.001)),
                train_ratio=float(phase.get("train_ratio", 0.70)),
                validation_ratio=float(phase.get("validation_ratio", 0.15)),
                require_complete_timeframes=not args.allow_incomplete_timeframes,
            )
            artifact = builder.build(args.symbol, candles)
            readiness = DatasetReadinessChecker(minimum_samples=args.minimum_samples).check(artifact)
            paths = DatasetExporter().export(artifact, args.output)
            persisted = {"features": 0, "labels": 0, "metadata": 0}
            if not args.no_persist:
                persisted = MLDatasetRepository(session).persist(artifact)
        print(json.dumps({
            "status": readiness.status, "reasons": readiness.reasons,
            "dataset_id": artifact.metadata.dataset_id, "dataset_hash": artifact.metadata.dataset_hash,
            "samples": artifact.metadata.row_count, "features": artifact.metadata.feature_count,
            "labels": artifact.metadata.label_count, "statistics": artifact.statistics,
            "paths": {key: str(value) for key, value in paths.items()}, "database": persisted,
        }, indent=2))
        return 0 if readiness.ready else 2
    except Exception as exc:
        print(json.dumps({"status": "DATASET NOT READY", "reasons": [str(exc)]}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
