"""Multiple-testing protection (sections 15 and 16).

Test twenty strategies at the 5% level and one looks profitable by chance. The
ledger's job is to make that visible rather than let it pass as a discovery.
"""
import pytest

from research.multiple_testing import (
    ExperimentLedger,
    SelectionMethod,
    benjamini_hochberg,
    bonferroni,
)
from research.significance import (
    SignificanceTester,
    SignificanceVerdict,
    band,
    effect_size,
)
from tests.phase15_helpers import series


class FakeResult:
    def __init__(self, experiment_id, name):
        self.experiment_id = experiment_id
        self.name = name


# ------------------------------------------------------------ the correction
def test_bonferroni_raises_the_bar_with_the_number_of_tries():
    assert bonferroni(0.05, 1) == pytest.approx(0.05)
    assert bonferroni(0.05, 10) == pytest.approx(0.005)
    assert bonferroni(0.05, 100) == pytest.approx(0.0005)


def test_bonferroni_never_divides_by_zero():
    assert bonferroni(0.05, 0) == pytest.approx(0.05)


def test_benjamini_hochberg_controls_the_false_discovery_rate():
    report = benjamini_hochberg([0.001, 0.008, 0.039, 0.041, 0.9], alpha=0.05)
    assert report["tests"] == 5
    assert report["rejected"] >= 1
    assert report["threshold"] is not None


def test_benjamini_hochberg_rejects_nothing_when_nothing_is_small():
    report = benjamini_hochberg([0.4, 0.6, 0.9], alpha=0.05)
    assert report["rejected"] == 0


def test_benjamini_hochberg_on_no_tests_is_not_an_error():
    assert benjamini_hochberg([], alpha=0.05)["tests"] == 0


# ------------------------------------------------------------- the ledger
def test_the_ledger_counts_every_hypothesis():
    ledger = ExperimentLedger()
    for index in range(20):
        ledger.record(FakeResult(f"e{index}", f"strategy-{index}"), p_value=0.5)
    assert ledger.experiment_count == 20
    assert ledger.hypotheses_tested == 20


def test_re_running_the_same_configuration_counts_one_experiment():
    ledger = ExperimentLedger()
    ledger.record(FakeResult("same", "smc"), p_value=0.2)
    ledger.record(FakeResult("same", "smc"), p_value=0.2)
    assert ledger.experiment_count == 1
    assert ledger.hypotheses_tested == 2


def test_repeated_tests_on_one_configuration_are_warned_about():
    ledger = ExperimentLedger()
    ledger.record(FakeResult("same", "smc"), p_value=0.2)
    ledger.record(FakeResult("same", "smc"), p_value=0.2)
    assert "REPEATED_TESTS_ON_SAME_CONFIGURATION" in ledger.report().warnings


def test_a_lucky_winner_does_not_survive_the_correction():
    """The exact failure section 16 exists to prevent."""
    ledger = ExperimentLedger(alpha=0.05)
    for index in range(20):
        # One "significant" result out of twenty is what chance produces.
        ledger.record(FakeResult(f"e{index}", f"strategy-{index}"),
                      p_value=0.04 if index == 0 else 0.7)
    report = ledger.report()
    assert report.adjusted_alpha == pytest.approx(0.0025)
    assert report.survivors == ()
    assert "NO_RESULT_SURVIVES_MULTIPLE_TESTING_CORRECTION" in report.warnings


def test_a_genuinely_strong_result_does_survive():
    ledger = ExperimentLedger(alpha=0.05)
    for index in range(20):
        ledger.record(FakeResult(f"e{index}", f"strategy-{index}"),
                      p_value=0.0001 if index == 0 else 0.7)
    assert ledger.report().survivors == ("strategy-0",)


def test_best_of_n_selection_is_flagged():
    ledger = ExperimentLedger(selection_method=SelectionMethod.BEST_OF_N)
    ledger.record(FakeResult("e1", "smc"), p_value=0.01)
    assert "BEST_OF_N_SELECTION_INFLATES_APPARENT_EDGE" in ledger.report().warnings


def test_the_selection_method_is_recorded():
    ledger = ExperimentLedger()
    ledger.select(SelectionMethod.PRE_REGISTERED)
    assert ledger.report().selection_method is SelectionMethod.PRE_REGISTERED


def test_the_report_carries_every_documented_field():
    ledger = ExperimentLedger()
    ledger.record(FakeResult("e1", "smc"), p_value=0.01)
    payload = ledger.report().as_dict()
    for field in ("experiment_count", "hypotheses_tested", "selection_method",
                  "holdout_usage"):
        assert field in payload, field


def test_holdout_usage_is_counted_and_warned_about():
    ledger = ExperimentLedger()
    ledger.record_holdout_use("first look")
    ledger.record_holdout_use("second look")
    report = ledger.report()
    assert report.holdout_usage == 2
    assert "HOLDOUT_USED_2_TIMES" in report.warnings


def test_many_tries_are_flagged_as_inflated():
    ledger = ExperimentLedger(alpha=0.05)
    for index in range(25):
        ledger.record(FakeResult(f"e{index}", f"s{index}"), p_value=0.5)
    assert ledger.report().inflated is True


def test_a_handful_of_tries_is_not_flagged_as_inflated():
    ledger = ExperimentLedger(alpha=0.05)
    for index in range(3):
        ledger.record(FakeResult(f"e{index}", f"s{index}"), p_value=0.5)
    assert ledger.report().inflated is False


# ------------------------------------------------- 15. statistical significance
def test_a_small_sample_never_declares_an_edge():
    """Section 15: do not declare edge from a small sample."""
    tester = SignificanceTester(minimum_samples=100)
    report = tester.absolute([0.0004] * 20)
    assert report.verdict is SignificanceVerdict.INSUFFICIENT_DATA
    assert not report.significant


def test_a_consistent_series_is_significant():
    tester = SignificanceTester(minimum_samples=100)
    report = tester.absolute([row.net_pnl for row in
                              series(200, mean=0.0009, deviation=0.0003, seed=1)])
    assert report.verdict is SignificanceVerdict.SIGNIFICANT
    assert report.confidence_interval["excludes_zero"] is True


def test_a_series_around_zero_is_not_significant():
    tester = SignificanceTester(minimum_samples=100)
    report = tester.absolute([row.net_pnl for row in
                              series(200, mean=0.0, deviation=0.0009, seed=2)])
    assert report.verdict is not SignificanceVerdict.SIGNIFICANT


def test_effect_size_is_reported_with_its_band():
    left = [row.net_pnl for row in series(150, mean=0.0002, deviation=0.0006, seed=3)]
    right = [row.net_pnl for row in series(150, mean=0.0012, deviation=0.0006, seed=4)]
    size = effect_size(left, right)
    assert size > 0
    assert band(size) in {"SMALL", "MEDIUM", "LARGE"}


def test_a_tiny_effect_is_not_significant_even_with_many_samples():
    """Statistically separable is not the same as economically meaningful."""
    tester = SignificanceTester(minimum_samples=100, minimum_effect=0.20)
    left = [row.net_pnl for row in series(500, mean=0.00040, deviation=0.0006, seed=5)]
    right = [row.net_pnl for row in series(500, mean=0.00042, deviation=0.0006, seed=6)]
    report = tester.compare(left, right)
    assert not report.significant


def test_a_degenerate_zero_variance_comparison_is_refused():
    """No pooled deviation means no magnitude to judge."""
    tester = SignificanceTester(minimum_samples=10)
    report = tester.compare([0.0002] * 100, [0.0009] * 100)
    assert report.effect_size is None
    assert "EFFECT_SIZE_UNAVAILABLE" in report.reasons
    assert not report.significant


def test_effect_size_is_none_on_a_tiny_sample():
    assert effect_size([0.1], [0.2]) is None


def test_the_band_of_an_unknown_effect_is_unknown():
    assert band(None) == "UNKNOWN"
