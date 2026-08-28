"""Persistence for the Phase 15 research lab.

Strategies upsert on their key, experiments upsert on their content-hashed
`experiment_id`. That second property is what keeps the multiple-testing ledger
honest across sessions: re-running an identical configuration updates one row
rather than adding a second hypothesis to the count.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    ResearchExperimentRecord,
    ResearchFindingRecord,
    ResearchStrategyRecord,
)
from database.repositories.mt5 import scrub


class ResearchRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------ strategies
    def save_strategy(self, record: Any) -> ResearchStrategyRecord:
        payload = record.as_dict()
        approval = payload.get("approval") or {}
        row = self.session.get(ResearchStrategyRecord, record.key)
        values = {
            "strategy_id": record.strategy_id,
            "strategy_version": record.strategy_version,
            "description": record.description, "status": str(record.status),
            "fingerprint": record.fingerprint,
            "features": ", ".join(record.features) or None,
            "timeframes": ", ".join(record.timeframes) or None,
            "approved_by": approval.get("approved_by"),
            "approved_at": _parse(approval.get("approved_at")),
            "updated_at": record.updated_at or _utcnow(),
            "record_json": scrub(payload),
        }
        if row is None:
            row = ResearchStrategyRecord(key=record.key,
                                         created_at=record.created_at or _utcnow(),
                                         **values)
            self.session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self.session.commit()
        return row

    def get_strategy(self, key: str) -> ResearchStrategyRecord | None:
        return self.session.get(ResearchStrategyRecord, key)

    def strategies(self, status: str | None = None,
                   limit: int = 200) -> list[ResearchStrategyRecord]:
        query = self.session.query(ResearchStrategyRecord)
        if status:
            query = query.filter(ResearchStrategyRecord.status == status)
        return query.order_by(desc(ResearchStrategyRecord.created_at)).limit(limit).all()

    def champion_strategy(self) -> ResearchStrategyRecord | None:
        return (self.session.query(ResearchStrategyRecord)
                .filter(ResearchStrategyRecord.status == "CHAMPION")
                .order_by(desc(ResearchStrategyRecord.updated_at)).first())

    def strategy_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.session.query(ResearchStrategyRecord.status).all():
            counts[row[0]] = counts.get(row[0], 0) + 1
        return counts

    # ----------------------------------------------------------- experiments
    def save_experiment(self, result: Any, *, strategy_key: str | None = None,
                        used_holdout: bool = False) -> ResearchExperimentRecord:
        spec = result.spec.as_dict()
        metrics = result.metrics.as_dict()
        row = self.session.get(ResearchExperimentRecord, result.experiment_id)
        values = {
            "name": result.name, "strategy_key": strategy_key,
            "strategy_version": spec.get("strategy_version", "v1"),
            "feature_version": spec.get("feature_version", ""),
            "model_version": spec.get("model_version"),
            "dataset_version": spec.get("dataset_version"),
            "label_version": spec.get("label_version", ""),
            "sample_size": int(metrics.get("sample_size", 0) or 0),
            "expectancy": _number(metrics.get("expectancy")),
            "win_rate": _number(metrics.get("win_rate")),
            "net_pnl": _number(metrics.get("net_pnl")),
            "profit_factor": _number(metrics.get("profit_factor")),
            "maximum_drawdown": _number(metrics.get("maximum_drawdown")),
            "sharpe_like": _number(metrics.get("sharpe_like")),
            "reliable": bool(metrics.get("reliable")),
            "evidence": str(result.evidence), "used_holdout": bool(used_holdout),
            "spec_json": scrub(spec), "metrics_json": scrub(metrics),
        }
        if row is None:
            row = ResearchExperimentRecord(experiment_id=result.experiment_id,
                                           created_at=_utcnow(), **values)
            self.session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self.session.commit()
        return row

    def experiments(self, limit: int = 200) -> list[ResearchExperimentRecord]:
        return (self.session.query(ResearchExperimentRecord)
                .order_by(desc(ResearchExperimentRecord.created_at)).limit(limit).all())

    def experiment_count(self) -> int:
        """Distinct configurations — the denominator for multiple testing."""
        return self.session.query(ResearchExperimentRecord).count()

    def best_experiment(self) -> ResearchExperimentRecord | None:
        return (self.session.query(ResearchExperimentRecord)
                .filter(ResearchExperimentRecord.reliable.is_(True),
                        ResearchExperimentRecord.expectancy.isnot(None))
                .order_by(desc(ResearchExperimentRecord.expectancy)).first())

    def holdout_usage(self) -> int:
        return (self.session.query(ResearchExperimentRecord)
                .filter(ResearchExperimentRecord.used_holdout.is_(True)).count())

    # -------------------------------------------------------------- findings
    def save_finding(self, *, study: str, subject: str, verdict: str,
                     payload: Any, sample_size: int = 0,
                     effect_size: float | None = None, significant: bool = False,
                     experiment_id: str | None = None,
                     reasons: Sequence[str] = ()) -> ResearchFindingRecord:
        row = ResearchFindingRecord(
            study=str(study), subject=str(subject), verdict=str(verdict),
            created_at=_utcnow(), sample_size=int(sample_size),
            effect_size=_number(effect_size), significant=bool(significant),
            experiment_id=experiment_id,
            reasons=", ".join(str(item) for item in reasons) or None,
            finding_json=scrub(payload.as_dict() if hasattr(payload, "as_dict")
                               else dict(payload)))
        self.session.add(row)
        self.session.commit()
        return row

    def findings(self, study: str | None = None,
                 limit: int = 200) -> list[ResearchFindingRecord]:
        query = self.session.query(ResearchFindingRecord)
        if study:
            query = query.filter(ResearchFindingRecord.study == study)
        return query.order_by(desc(ResearchFindingRecord.created_at)).limit(limit).all()

    def latest_finding(self, study: str) -> ResearchFindingRecord | None:
        return (self.session.query(ResearchFindingRecord)
                .filter(ResearchFindingRecord.study == study)
                .order_by(desc(ResearchFindingRecord.created_at)).first())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
