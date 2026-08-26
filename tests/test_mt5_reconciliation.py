"""Account/position reconciliation and cross-source comparison. READ ONLY."""
from datetime import timedelta

from database.models import MT5AccountRecord, MT5AccountSnapshotRecord, MT5ConnectionEventRecord
from execution.mt5.quality import DATA_SOURCE_DISCREPANCY, compare_sources
from execution.mt5.service import MT5ReadOnlyService
from paper import PaperAccount
from tests.phase10_helpers import NOW, connected_client


def service(db_session, **kwargs):
    return MT5ReadOnlyService(db_session, client=connected_client(**kwargs))


def test_connecting_records_an_account_and_a_snapshot(db_session):
    service(db_session).connect()
    account = db_session.query(MT5AccountRecord).one()
    assert account.environment == "DEMO" and account.login_masked == "*****4321"
    assert db_session.query(MT5AccountSnapshotRecord).count() == 1
    assert db_session.query(MT5ConnectionEventRecord).count() == 1


def test_the_stored_account_row_holds_no_credential(db_session):
    service(db_session).connect()
    account = db_session.query(MT5AccountRecord).one()
    columns = {column.name for column in MT5AccountRecord.__table__.columns}
    assert not any(token in name for name in columns for token in ("password", "secret", "token"))
    assert "987654321" not in account.login_masked


def test_reconciliation_reports_both_books_without_changing_either(db_session):
    svc = service(db_session)
    svc.connect()
    paper = PaperAccount(initial_balance=1000.0)
    before = (paper.balance, paper.equity)
    result = svc.reconcile(paper)
    assert result["mt5"]["environment"] == "DEMO"
    assert result["paper"]["balance"] == 1000.0
    assert result["differences"]["balance"] == 10000.0 - 1000.0
    assert (paper.balance, paper.equity) == before, "reconciliation must not mutate the paper book"


def test_reconciliation_without_a_paper_account_still_reports_mt5(db_session):
    svc = service(db_session)
    svc.connect()
    result = svc.reconcile()
    assert result["paper"] is None and result["mt5"]["balance"] == 10000.0


def test_matching_sources_report_no_discrepancy():
    quote = {"mid_price": 1.10018, "spread": 0.00012, "timestamp": NOW}
    comparison = compare_sources(quote, dict(quote), symbol="EURUSD")
    assert not comparison.discrepancy
    assert comparison.as_dict()["code"] == "OK"


def test_a_price_divergence_is_reported_as_a_discrepancy():
    mt5 = {"mid_price": 1.10018, "timestamp": NOW}
    other = {"mid_price": 1.11500, "timestamp": NOW}
    comparison = compare_sources(mt5, other, symbol="EURUSD", price_tolerance=0.0010)
    assert comparison.discrepancy and "PRICE_DIVERGENCE" in comparison.reasons
    assert comparison.as_dict()["code"] == DATA_SOURCE_DISCREPANCY


def test_a_timestamp_divergence_is_reported():
    mt5 = {"mid_price": 1.1, "timestamp": NOW}
    other = {"mid_price": 1.1, "timestamp": NOW - timedelta(minutes=30)}
    comparison = compare_sources(mt5, other, symbol="EURUSD", timestamp_tolerance_seconds=120)
    assert comparison.discrepancy and "TIMESTAMP_DIVERGENCE" in comparison.reasons


def test_a_missing_source_is_reported_but_is_not_a_divergence():
    comparison = compare_sources({"mid_price": 1.1, "timestamp": NOW}, None, symbol="EURUSD")
    assert not comparison.discrepancy and "SOURCE_UNAVAILABLE" in comparison.reasons


def test_the_service_compares_mt5_against_another_provider(db_session):
    svc = service(db_session)
    svc.connect()
    result = svc.compare_with_provider("EURUSD", {"mid_price": 1.5, "timestamp": NOW},
                                       other_source="historical")
    assert result["discrepancy"] and result["other_source"] == "historical"
    assert result["code"] == DATA_SOURCE_DISCREPANCY
