"""The explicit training job (section 30).

Learning happens here, never inside the observation loop and never during
inference. This script trains, evaluates, registers and stops. It does NOT
promote: promotion requires POST /ai/models/{id}/approve with a named human.

    python -m scripts.train_forward_model --horizon 1h
    python -m scripts.train_forward_model --horizon 4h --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.dataset import DatasetBuilder
from ai.model_registry import ModelRegistry, ModelState, ModelTask
from ai.training.forward_trainer import ForwardTrainer, TrainingDisabled
from database.models import FeatureSnapshotRecord, MarketCandle
from database.repositories.learning import LearningRepository
from database.session import SessionLocal
from logging_config import configure_logging


def load_observations(session, *, symbol: str, since: datetime) -> list[dict]:
    rows = (session.query(FeatureSnapshotRecord)
            .filter(FeatureSnapshotRecord.symbol == symbol.upper(),
                    FeatureSnapshotRecord.timestamp >= since)
            .order_by(FeatureSnapshotRecord.timestamp).all())
    observations = []
    for row in rows:
        payload = dict(row.snapshot_json or {})
        payload.setdefault("symbol", row.symbol)
        payload["timestamp"] = row.timestamp
        payload["cycle_id"] = row.cycle_id
        observations.append(payload)
    return observations


def load_candles(session, *, symbol: str, timeframe: str, since: datetime) -> list[dict]:
    rows = (session.query(MarketCandle)
            .filter(MarketCandle.symbol == symbol.upper(),
                    MarketCandle.timeframe == timeframe.upper(),
                    MarketCandle.timestamp >= since)
            .order_by(MarketCandle.timestamp).all())
    return [{"timestamp": row.timestamp, "open": float(row.open), "high": float(row.high),
             "low": float(row.low), "close": float(row.close)} for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a forward-observation model")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--timeframe", default="M5", help="timeframe of the future candles")
    parser.add_argument("--horizon", default="1h")
    parser.add_argument("--days", type=int, default=30, help="observation lookback window")
    parser.add_argument("--minimum-rows", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="build and evaluate without registering the model")
    args = parser.parse_args()
    configure_logging()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    session = SessionLocal()
    try:
        observations = load_observations(session, symbol=args.symbol, since=since)
        candles = load_candles(session, symbol=args.symbol, timeframe=args.timeframe,
                               since=since)
        if not observations:
            print("no forward observations found; run the observation cycle first")
            return
        if not candles:
            print("no future candles found; labels cannot be resolved")
            return

        builder = DatasetBuilder(minimum_rows=args.minimum_rows) if args.minimum_rows \
            else DatasetBuilder()
        dataset = builder.build(observations, candles, horizon=args.horizon,
                                symbol=args.symbol, timeframe=args.timeframe)

        print(f"dataset {dataset.dataset_id}")
        print(f"  rows={dataset.audit.row_count} features={len(dataset.feature_names)}")
        print(f"  split={len(dataset.train)}/{len(dataset.validation)}/{len(dataset.test)}")
        print(f"  classes={dataset.audit.class_distribution}")
        print(f"  quality_ok={dataset.quality.ok} codes={list(dataset.quality.codes)}")
        if dataset.refusals:
            print(f"  label refusals={dataset.refusals}")
        if not dataset.ok:
            print("dataset did not pass quality checks; refusing to train")
            return

        repository = LearningRepository(session)
        repository.save_dataset_audit(dataset.audit)

        try:
            report = ForwardTrainer().train(
                dataset, task=ModelTask(symbol=args.symbol.upper(),
                                        timeframe=args.timeframe.upper()))
        except TrainingDisabled as error:
            print(f"training disabled: {error}")
            return

        record = report.record
        print(f"model {report.model_id}")
        print(f"  test_accuracy={record.test_metrics.get('accuracy')}")
        print(f"  brier={record.calibration.get('brier_score')}")
        print(f"  beats_all_baselines={report.beats_all_baselines}")
        print(f"  walk_forward={record.walk_forward_metrics.get('mean_accuracy')} "
              f"stability={record.walk_forward_metrics.get('stability')}")
        print(f"  EDGE VERDICT: {record.edge_verdict}")

        if args.dry_run:
            print("dry run: model not registered")
            return

        registry = ModelRegistry(repository=repository)
        registry.register(record)
        registry.save_artifact(report.model_id, {
            "model_id": report.model_id, "model_version": record.model_version,
            "feature_version": record.feature_version,
            "feature_names": list(dataset.feature_names),
            "means": dict(dataset.scaler.means),
            "deviations": dict(dataset.scaler.standard_deviations),
            "parameters": report.parameters,
        })
        if record.edge_verdict == "EDGE_DETECTED" and report.beats_all_baselines:
            registry.transition(report.model_id, ModelState.VALIDATED,
                                note="passed edge and baseline checks")
            print("  state: VALIDATED")
        else:
            print("  state: EXPERIMENTAL (no edge, or does not beat baselines)")
        print("\nNOT PROMOTED. Promotion requires POST /ai/models/"
              f"{report.model_id}/approve with a named human approver.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
