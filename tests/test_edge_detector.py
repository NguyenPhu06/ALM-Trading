"""The statistical edge engine (sections 22 and 23).

Four verdicts, and positive PnL alone is never one of them.
"""
import pytest

from ai.edge import EdgeDetector, EdgeVerdict, EvidenceSource, REQUIRED_BASELINES
from ai.edge.evidence import EvidenceRefused
from tests.phase14_helpers import BASELINES, entries

WALK_FORWARD = [0.58, 0.60, 0.57]


def detector(**kwargs):
    kwargs.setdefault("minimum_samples", 100)
    kwargs.setdefault("minimum_segment_samples", 20)
    return EdgeDetector(**kwargs)


def evaluate(rows, *, baselines=None, **kwargs):
    kwargs.setdefault("walk_forward_scores", WALK_FORWARD)
    return detector().evaluate(rows, baselines=baselines or BASELINES, **kwargs)


# ------------------------------------------------------------ four verdicts
def test_every_documented_verdict_exists():
    assert {str(item) for item in EdgeVerdict} == {
        "EDGE_DETECTED", "NO_EDGE", "INSUFFICIENT_DATA", "UNSTABLE_EDGE"}


def test_a_consistent_profitable_series_is_an_edge():
    report = evaluate(entries(120, net=0.0004))
    assert report.verdict is EdgeVerdict.EDGE_DETECTED
    assert report.edge is True
    assert report.reasons == ()


def test_too_few_samples_is_insufficient_data():
    report = evaluate(entries(20, net=0.0004))
    assert report.verdict is EdgeVerdict.INSUFFICIENT_DATA
    assert "SAMPLE_BELOW_MINIMUM_100" in report.reasons
    assert report.edge is False


def test_a_losing_series_is_no_edge():
    report = evaluate(entries(120, net=-0.0004))
    assert report.verdict is EdgeVerdict.NO_EDGE
    assert "NEGATIVE_EXPECTANCY" in report.reasons


def test_an_inconsistent_but_profitable_series_is_unstable():
    rows = (entries(60, net=0.0020, sessions=("LONDON",))
            + entries(60, net=-0.0004, sessions=("ASIA",)))
    for index, row in enumerate(rows):
        row.observation_id = f"obs-{index}"
    report = evaluate(rows)
    assert report.verdict is EdgeVerdict.UNSTABLE_EDGE
    assert any("SESSION" in reason or "PERIOD" in reason for reason in report.reasons)
    assert report.edge is False, "an unstable edge is not an edge"


# ------------------------------------------------------- 23. the baselines
def test_every_documented_baseline_is_required():
    assert set(REQUIRED_BASELINES) == {"random", "majority", "buy_and_hold", "momentum",
                                       "rsi", "ichimoku", "adx", "regime"}


def test_a_missing_baseline_prevents_an_edge_claim():
    report = evaluate(entries(120, net=0.0004),
                      baselines={name: 0.0 for name in REQUIRED_BASELINES[:-1]})
    assert report.verdict is EdgeVerdict.NO_EDGE
    assert "DOES_NOT_BEAT_BASELINES" in report.reasons
    assert "regime:MISSING" in report.not_beaten


def test_failing_to_beat_one_baseline_prevents_an_edge_claim():
    baselines = {**BASELINES, "momentum": 0.9}
    report = evaluate(entries(120, net=0.0004), baselines=baselines)
    assert report.verdict is EdgeVerdict.NO_EDGE
    assert "momentum" in report.not_beaten


def test_beating_every_baseline_is_recorded():
    report = evaluate(entries(120, net=0.0004))
    assert set(report.beaten) >= set(REQUIRED_BASELINES)
    assert report.not_beaten == ()


def test_the_champion_must_also_be_beaten_when_one_exists():
    report = evaluate(entries(120, net=0.0004), champion_expectancy=0.9)
    assert "champion" in report.not_beaten
    assert report.verdict is EdgeVerdict.NO_EDGE


def test_a_beaten_champion_is_recorded():
    report = evaluate(entries(120, net=0.0004), champion_expectancy=0.00001)
    assert "champion" in report.beaten
    assert report.verdict is EdgeVerdict.EDGE_DETECTED


def test_no_champion_does_not_block_an_edge():
    report = evaluate(entries(120, net=0.0004), champion_expectancy=None)
    assert report.verdict is EdgeVerdict.EDGE_DETECTED


def test_positive_pnl_alone_is_not_an_edge():
    """Section 23's headline rule."""
    report = detector().evaluate(entries(120, net=0.0004), baselines={})
    assert report.metrics["net_pnl"] > 0
    assert report.verdict is EdgeVerdict.NO_EDGE


# ----------------------------------------------------------- 22. the metrics
def test_every_documented_metric_is_reported():
    report = evaluate(entries(120, net=0.0004))
    for name in ("samples", "expectancy", "win_rate", "profit_factor", "net_pnl",
                 "max_drawdown", "confidence_interval", "walk_forward_consistency"):
        assert name in report.metrics, name


def test_regime_session_and_timeframe_consistency_are_all_reported():
    report = evaluate(entries(120, net=0.0004))
    assert set(report.consistency) == {"regime", "session", "timeframe"}


def test_a_segment_below_the_floor_is_not_judged():
    rows = entries(120, net=0.0004, sessions=("LONDON",) * 10 + ("ASIA",))
    for index, row in enumerate(rows):
        row.observation_id = f"obs-{index}"
    session = evaluate(rows).consistency["session"]
    assert "ASIA" in session.segments
    assert "ASIA" not in session.negative + session.positive


def test_walk_forward_inconsistency_denies_an_edge():
    report = detector().evaluate(entries(120, net=0.0004), baselines=BASELINES,
                                 walk_forward_scores=[0.9, 0.1, 0.85])
    assert "WALK_FORWARD_INCONSISTENT" in report.reasons
    assert report.verdict is EdgeVerdict.NO_EDGE


def test_no_walk_forward_data_is_simply_absent():
    report = detector().evaluate(entries(120, net=0.0004), baselines=BASELINES)
    assert report.metrics["walk_forward_consistency"] is None
    assert report.verdict is EdgeVerdict.EDGE_DETECTED


# ------------------------------------------------------ 24. forward evidence
def test_a_backtest_cannot_be_used_to_claim_an_edge():
    with pytest.raises(EvidenceRefused, match="forward observation"):
        detector().evaluate(entries(120), baselines=BASELINES,
                            evidence=EvidenceSource.BACKTEST)


def test_paper_results_cannot_be_used_either():
    with pytest.raises(EvidenceRefused):
        detector().evaluate(entries(120), baselines=BASELINES,
                            evidence=EvidenceSource.PAPER)


def test_the_report_names_its_evidence_source():
    assert evaluate(entries(120)).as_dict()["evidence"] == "FORWARD_OBSERVATION"


def test_net_returns_are_read_not_gross():
    report = evaluate(entries(120, net=0.0004))
    assert report.metrics["expectancy"] == pytest.approx(0.0004)


def test_the_serialised_report_carries_the_verdict_and_the_reasons():
    payload = evaluate(entries(20)).as_dict()
    assert payload["verdict"] == "INSUFFICIENT_DATA"
    assert payload["edge"] is False
    assert payload["reasons"]
