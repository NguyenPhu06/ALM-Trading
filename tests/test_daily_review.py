"""The daily review (section 19).

An operational report: what happened today, what broke, and whether the system is
still healthy. Every figure is drawn from the trading day it names, and an empty
day says so rather than reporting a confident-looking zero.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from validation.reviews import ReviewBuilder
from tests.phase17_helpers import trades

DAY = date(2026, 8, 27)
START = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)
END = START + timedelta(days=1)


def review(**overrides):
    payload = dict(trading_day=DAY, start=START, end=END)
    payload.update(overrides)
    return ReviewBuilder().daily(**payload)


def day_trades(count=10, **kwargs):
    kwargs.setdefault("start", START + timedelta(hours=1))
    kwargs.setdefault("step", timedelta(hours=1))
    return trades(count, **kwargs)


# ---------------------------------------------------------------- the fields
def test_the_report_carries_every_declared_field():
    """Section 19, field for field."""
    payload = review().as_dict()
    for name in ("signals", "trades", "wins", "losses", "net_pnl", "drawdown", "mae", "mfe",
                 "spread", "slippage", "execution_failures", "model_failures",
                 "strategy_failures", "regimes", "sessions", "edge_status"):
        assert name in payload


def test_the_report_names_its_trading_day_and_timezone():
    payload = review().as_dict()
    assert payload["trading_day"] == "2026-08-27"
    assert payload["timezone"] == "UTC"


# ---------------------------------------------------------------- the counting
def test_trades_inside_the_day_are_counted():
    report = review(trades=day_trades(10))
    assert report.trades == 10
    assert report.wins + report.losses == 10


def test_trades_outside_the_day_are_excluded():
    outside = trades(10, start=START - timedelta(days=3), step=timedelta(hours=1))
    assert review(trades=outside).trades == 0


def test_the_boundary_is_half_open():
    """A trade at exactly midnight belongs to the day starting there."""
    at_start = trades(1, start=START, step=timedelta(hours=1))
    at_end = trades(1, start=END, step=timedelta(hours=1))
    assert review(trades=at_start).trades == 1
    assert review(trades=at_end).trades == 0


def test_the_net_pnl_and_drawdown_are_computed():
    rows = day_trades(9)
    report = review(trades=rows)
    assert report.net_pnl == pytest.approx(sum(row["net_pnl"] for row in rows))
    assert report.drawdown >= 0


def test_the_worst_mae_and_best_mfe_are_reported():
    rows = day_trades(5)
    rows[0]["mae"] = -0.01
    rows[1]["mfe"] = 0.02
    report = review(trades=rows)
    assert report.mae == pytest.approx(-0.01)
    assert report.mfe == pytest.approx(0.02)


def test_the_spread_and_slippage_are_averaged():
    report = review(trades=day_trades(5))
    assert report.spread == pytest.approx(0.00012)
    assert report.slippage == pytest.approx(0.00005)


def test_the_regime_and_session_mix_is_counted():
    rows = day_trades(6, regime="BULL") + day_trades(4, regime="BEAR", session="ASIA")
    report = review(signals=rows)
    assert report.regimes == {"BEAR": 4, "BULL": 6}
    assert report.sessions == {"ASIA": 4, "LONDON": 6}


# ---------------------------------------------------------------- the failures
def test_the_failure_counts_are_carried_through():
    report = review(execution_failures=2, model_failures=1, strategy_failures=3)
    assert report.execution_failures == 2
    assert report.model_failures == 1 and report.strategy_failures == 3


def test_the_stop_mechanisms_are_reported():
    report = review(circuit_breaker="OPEN", kill_switch="ENGAGED")
    assert report.circuit_breaker == "OPEN" and report.kill_switch == "ENGAGED"


def test_anomalies_are_listed():
    report = review(anomalies=["ABNORMAL_SPREAD", "EXECUTION_LATENCY"])
    assert list(report.anomalies) == ["ABNORMAL_SPREAD", "EXECUTION_LATENCY"]


# ---------------------------------------------------------------- empty days
def test_an_empty_day_says_so():
    report = review()
    assert report.trades == 0 and report.signals == 0
    assert "NO_TRADES" in report.reasons and "NO_SIGNALS" in report.reasons


def test_an_empty_day_defaults_to_insufficient_data():
    assert review().edge_status == "INSUFFICIENT_DATA"


def test_the_edge_status_is_whatever_it_is_told():
    """The review reports the verdict; it does not compute a friendlier one."""
    assert review(edge_status="NO_EDGE").edge_status == "NO_EDGE"


# ---------------------------------------------------------------- the service
def test_the_service_builds_a_daily_review(db_session):
    from database.repositories.validation import ValidationRepository
    from tests.phase16_helpers import settings
    from validation.service import ValidationService

    service = ValidationService(ValidationRepository(db_session), settings=settings())
    report = service.daily_review(trading_day=DAY, now=START + timedelta(hours=12))
    assert report["trading_day"] == "2026-08-27"
    assert report["edge_status"] == "INSUFFICIENT_DATA"


def test_the_service_alerts_the_report(db_session):
    from database.models import DashboardAlertRecord
    from database.repositories import AlertRepository
    from database.repositories.validation import ValidationRepository
    from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter
    from tests.phase16_helpers import settings
    from validation.service import ValidationService

    router = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(
        AlertRepository(db_session))))
    service = ValidationService(ValidationRepository(db_session), settings=settings(),
                                alerts=router)
    service.daily_review(trading_day=DAY, now=START + timedelta(hours=12))
    types = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert "VALIDATION_REPORT" in types


def test_the_daily_endpoint_reports_a_blocked_posture(client):
    body = client.get("/validation/review/daily").json()["data"]
    assert body["edge_status"] == "INSUFFICIENT_DATA"
    assert body["kill_switch"] == "ENGAGED"
    assert body["circuit_breaker"] == "CLOSED"
