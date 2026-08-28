"""ValidationService — assembles the Phase 17 answers from stored evidence.

It reads. It computes. It reports. There is no execution client here, no guard
and no transport, and nothing in this class can arm a mode, release a kill
switch or reset a breaker without the section 23 checklist.

Every method degrades honestly on empty input: `INSUFFICIENT_DATA` rather than a
number, `reliable: false` rather than a confident-looking zero.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from validation.anomaly import AnomalyDetector, AnomalyReport
from validation.circuit_breaker import CircuitBreaker, RecoveryChecklist
from validation.comparison import DemoOutcomeView, ShadowDemoComparator
from validation.dca_validation import DCAValidator
from validation.even_hour import EvenHourValidator
from validation.gates import (
    AutomationEligibility, AutomationEligibilityEvaluator, PerformanceGateEvaluator,
)
from validation.quality import (
    calculate_execution_quality, calculate_model_quality, calculate_signal_quality,
)
from validation.reviews import ReviewBuilder
from validation.segments import SegmentAnalyzer
from validation.windows import EdgeStatus, RollingWindowEvaluator

logger = logging.getLogger(__name__)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _row(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    if hasattr(record, "as_dict"):
        return record.as_dict()
    if hasattr(record, "__table__"):
        return {column.name: getattr(record, column.name) for column in record.__table__.columns}
    return dict(record)


class ValidationService:
    """One place to ask every Phase 17 question."""

    def __init__(self, repository: Any = None, *, settings: Any = None,
                 breaker: CircuitBreaker | None = None, alerts: Any = None,
                 timezone_name: str = "UTC"):
        self.repository = repository
        self.settings = settings
        self.alerts = alerts
        self.breaker = breaker
        self.comparator = ShadowDemoComparator()
        self.segments = SegmentAnalyzer()
        self.windows = RollingWindowEvaluator()
        self.gates = PerformanceGateEvaluator()
        self.eligibility = AutomationEligibilityEvaluator(settings, evaluator=self.gates)
        self.anomalies = AnomalyDetector()
        self.even_hour = EvenHourValidator()
        self.dca = DCAValidator(settings=settings)
        self.reviews = ReviewBuilder(timezone_name=timezone_name)

    # ------------------------------------------------------------------ reads
    def _shadow_outcomes(self, limit: int = 500) -> list[dict[str, Any]]:
        if self.repository is None:
            return []
        rows = self.repository.recent_shadow_outcomes(limit)
        result = []
        for row in rows:
            payload = _row(row)
            payload.setdefault("net_pnl", payload.get("net_expected_pnl"))
            payload.setdefault("timestamp", payload.get("resolved_at"))
            result.append(payload)
        return result

    def _shadow_signals(self, limit: int = 500) -> list[dict[str, Any]]:
        if self.repository is None:
            return []
        return [_row(row) for row in self.repository.recent_shadow_signals(limit)]

    def _comparisons(self, limit: int = 200) -> list[dict[str, Any]]:
        if self.repository is None:
            return []
        return [_row(row) for row in self.repository.recent_comparisons(limit)]

    # ------------------------------------------------------------ section 5/6
    def compare(self, signal: Any, shadow: Any, journal_entry: Any) -> Any:
        """Pair one shadow outcome with the DEMO trade it mirrors."""
        comparison = self.comparator.compare(
            signal, shadow, DemoOutcomeView.from_journal(journal_entry))
        if self.repository is not None and hasattr(self.repository, "save_comparison"):
            try:
                self.repository.save_comparison(comparison)
            except Exception:
                logger.exception("failed to persist shadow/demo comparison")
        if not comparison.matched:
            self._alert("shadow_demo_divergence", comparison=comparison)
        return comparison

    def comparison_summary(self, limit: int = 200) -> dict[str, Any]:
        rows = self._comparisons(limit)
        if not rows:
            return ShadowDemoComparator.summarize([])
        from validation.comparison import DifferenceKind, ShadowDemoComparison

        rebuilt = [
            ShadowDemoComparison(
                shadow_signal_id=row.get("shadow_signal_id", ""),
                demo_execution_request_id=row.get("demo_execution_request_id", ""),
                symbol=row.get("symbol", ""),
                signal_difference=bool(row.get("signal_difference")),
                entry_difference=row.get("entry_difference"),
                exit_difference=row.get("exit_difference"),
                slippage_difference=row.get("slippage_difference"),
                cost_difference=row.get("cost_difference"),
                pnl_difference=row.get("pnl_difference"),
                mae_difference=row.get("mae_difference"),
                mfe_difference=row.get("mfe_difference"),
                time_difference=row.get("time_difference"),
                kinds=tuple(DifferenceKind(kind.strip())
                            for kind in str(row.get("kinds") or "").split(",") if kind.strip()),
                shadow_net_pnl=row.get("shadow_net_pnl"),
                demo_net_pnl=row.get("demo_net_pnl"))
            for row in rows]
        return ShadowDemoComparator.summarize(rebuilt)

    # -------------------------------------------------------------- section 7
    def execution_quality(self, records: Sequence[Any] | None = None, *,
                          reconciliation_failures: int = 0,
                          connection_failures: int = 0) -> dict[str, Any]:
        rows = [_row(record) for record in (records or [])]
        return calculate_execution_quality(
            rows, reconciliation_failures=reconciliation_failures,
            connection_failures=connection_failures).as_dict()

    # -------------------------------------------------------------- section 8
    def signal_quality(self, limit: int = 500) -> dict[str, Any]:
        from types import SimpleNamespace

        signals = [SimpleNamespace(**row) for row in self._shadow_signals(limit)]
        outcomes = [SimpleNamespace(**row) for row in self._shadow_outcomes(limit)]
        return calculate_signal_quality(signals, outcomes).as_dict()

    # -------------------------------------------------------------- section 9
    def model_quality(self, predictions: Sequence[Any] | None = None, *,
                      baseline: Sequence[Any] = ()) -> dict[str, Any]:
        rows = [_row(record) for record in (predictions or [])]
        return calculate_model_quality(rows, baseline=[_row(r) for r in baseline]).as_dict()

    # --------------------------------------------------------- sections 10-12
    def segment_performance(self, limit: int = 500) -> dict[str, Any]:
        return self.segments.all(self._shadow_outcomes(limit))

    # ------------------------------------------------------------- section 15
    def rolling_windows(self, *, now: datetime | None = None,
                        limit: int = 1000) -> dict[str, Any]:
        return self.windows.all(self._shadow_outcomes(limit), now=now)

    def edge_status(self, *, now: datetime | None = None) -> str:
        return str(self.rolling_windows(now=now).get("edge_status", EdgeStatus.INSUFFICIENT_DATA))

    # ------------------------------------------------------------- section 17
    def performance_gates(self, *, execution_quality: Mapping[str, Any] | None = None,
                          model_quality: Mapping[str, Any] | None = None,
                          window: str = "30d", now: datetime | None = None) -> dict[str, Any]:
        windows = self.rolling_windows(now=now)
        chosen = (windows.get("windows") or {}).get(window) or {}
        quality = dict(execution_quality or {})
        model = dict(model_quality or {})
        report = self.gates.evaluate(
            samples=chosen.get("samples"), drawdown=chosen.get("drawdown"),
            expectancy=chosen.get("expectancy"), profit_factor=chosen.get("profit_factor"),
            rejection_rate=quality.get("rejection_rate"),
            reconciliation_failure_rate=_rate(quality.get("reconciliation_failures"),
                                              quality.get("submitted")),
            high_confidence_failure_rate=model.get("high_confidence_failure_rate"),
            calibration_quality=model.get("calibration_quality"))
        if not report.passed:
            self._alert("performance_gate_failed", report=report)
        if self.repository is not None and hasattr(self.repository, "save_gate_report"):
            try:
                self.repository.save_gate_report(report)
            except Exception:
                logger.exception("failed to persist the performance gate report")
        return {**report.as_dict(), "window": window}

    # ------------------------------------------------------------- section 18
    def automation_eligibility(self, **observations: Any) -> AutomationEligibility:
        """Compute DEMO_AUTOMATION_ELIGIBLE. It never arms anything."""
        if self.breaker is not None:
            observations.setdefault("circuit_breaker_open", self.breaker.open)
        result = self.eligibility.evaluate(**observations)
        self._alert("automation_eligible", eligibility=result)
        return result

    # ------------------------------------------------------------- section 21
    def detect_anomalies(self, current: Mapping[str, Any],
                         baseline: Mapping[str, Any] | None) -> AnomalyReport:
        report = self.anomalies.detect(current, baseline)
        if report.detected:
            self._alert("anomaly_detected", report=report)
        return report

    # ---------------------------------------------------------- sections 22/23
    def reset_breaker(self, checklist: RecoveryChecklist, *, actor: str | None = None) -> Any:
        """Section 23. Refuses unless all four checks are satisfied."""
        if self.breaker is None:
            raise RuntimeError("no circuit breaker is attached to this service")
        return self.breaker.reset(checklist, actor=actor)

    # ---------------------------------------------------------- sections 19/20
    def daily_review(self, *, trading_day: date | None = None,
                     now: datetime | None = None, **overrides: Any) -> dict[str, Any]:
        moment = _aware(now or datetime.now(timezone.utc))
        day = trading_day or moment.date()
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        report = self.reviews.daily(
            trading_day=day, start=start, end=start + timedelta(days=1),
            signals=self._shadow_signals(), trades=self._shadow_outcomes(),
            edge_status=overrides.pop("edge_status", self.edge_status(now=moment)),
            circuit_breaker=str(self.breaker.state) if self.breaker else "CLOSED",
            **overrides)
        self._alert("validation_report", kind="daily", report=report)
        return report.as_dict()

    def weekly_review(self, *, week_start: date | None = None,
                      now: datetime | None = None, **overrides: Any) -> dict[str, Any]:
        moment = _aware(now or datetime.now(timezone.utc))
        start = week_start or (moment.date() - timedelta(days=moment.weekday()))
        report = self.reviews.weekly(
            week_start=start, segments=self.segment_performance(),
            edge_status=overrides.pop("edge_status", self.edge_status(now=moment)),
            **overrides)
        self._alert("validation_report", kind="weekly", report=report)
        return report.as_dict()

    # ------------------------------------------------------------- plumbing
    def _alert(self, method: str, **kwargs: Any) -> tuple[Any, ...]:
        if self.alerts is None:
            return ()
        handler = getattr(self.alerts, method, None)
        if handler is None:
            return ()
        try:
            return tuple(handler(**kwargs) or ())
        except Exception:
            logger.exception("validation alert %s failed", method)
            return ()


def _rate(count: Any, total: Any) -> float | None:
    try:
        count, total = float(count), float(total)
    except (TypeError, ValueError):
        return None
    return round(count / total, 6) if total else None
