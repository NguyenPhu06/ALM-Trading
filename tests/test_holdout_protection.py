"""Holdout protection (section 17).

The failure mode: check the holdout, adjust a parameter, check again. After a
few rounds the holdout is training data wearing a different name. The guard
cannot stop a second look — it makes every look counted, and refuses to call the
result final once the budget is spent.
"""
from datetime import timedelta

import pytest

from research.holdout import HoldoutGuard, HoldoutViolation
from research.multiple_testing import ExperimentLedger
from tests.phase15_helpers import NOW, observation, series


def guard(**kwargs):
    kwargs.setdefault("ratio", 0.2)
    kwargs.setdefault("budget", 1)
    return HoldoutGuard(**kwargs)


def ordered(count=200):
    """Observations in time order, oldest first."""
    return [observation(index, resolved_at=NOW - timedelta(hours=count - index))
            for index in range(count)]


# ----------------------------------------------------------------- the split
def test_the_split_reserves_the_configured_share():
    research, holdout = guard(ratio=0.2).split(ordered(200))
    assert len(research) == 160
    assert len(holdout) == 40


def test_the_holdout_is_the_most_recent_tail():
    """Chronological, always — a random holdout would leak the future."""
    research, holdout = guard().split(ordered(200))
    assert max(row.resolved_at for row in research) < min(row.resolved_at
                                                          for row in holdout)


def test_the_split_is_reported_with_its_boundaries():
    instance = guard()
    instance.split(ordered(200))
    payload = instance.last_split.as_dict()
    assert payload["research_rows"] == 160
    assert payload["holdout_rows"] == 40
    assert payload["holdout_ratio"] == pytest.approx(0.2)
    assert payload["research_end"] < payload["holdout_start"]


def test_the_split_orders_unsorted_input():
    rows = list(reversed(ordered(100)))
    research, holdout = guard().split(rows)
    assert max(row.resolved_at for row in research) < min(row.resolved_at
                                                          for row in holdout)


def test_an_empty_set_splits_into_nothing():
    assert guard().split([]) == ([], [])


def test_a_tiny_set_still_reserves_at_least_one_row():
    research, holdout = guard(ratio=0.2).split(ordered(3))
    assert len(holdout) >= 1


# ------------------------------------------------------------- the budget
def test_reading_the_holdout_requires_a_reason():
    instance = guard()
    _, holdout = instance.split(ordered(100))
    with pytest.raises(ValueError, match="stated reason"):
        instance.peek(holdout, reason="  ")


def test_the_first_read_is_allowed():
    instance = guard()
    _, holdout = instance.split(ordered(100))
    assert len(instance.peek(holdout, reason="final evaluation")) == len(holdout)
    assert instance.spent


def test_a_second_read_is_refused():
    """The exact failure this section exists to prevent."""
    instance = guard(budget=1)
    _, holdout = instance.split(ordered(100))
    instance.peek(holdout, reason="final evaluation")
    with pytest.raises(HoldoutViolation, match="already spent"):
        instance.peek(holdout, reason="just one more look")


def test_the_refusal_names_the_previous_reads():
    instance = guard(budget=1)
    _, holdout = instance.split(ordered(100))
    instance.peek(holdout, reason="final evaluation")
    with pytest.raises(HoldoutViolation, match="final evaluation"):
        instance.peek(holdout, reason="second")


def test_a_larger_budget_allows_more_reads_and_still_counts_them():
    instance = guard(budget=2)
    _, holdout = instance.split(ordered(100))
    instance.peek(holdout, reason="first")
    instance.peek(holdout, reason="second")
    assert instance.remaining == 0
    report = instance.report()
    assert report["usage"] == 2
    assert report["final_result_valid"] is False
    assert report["warning"] == "HOLDOUT_READ_MORE_THAN_ONCE"


def test_every_read_is_recorded_with_its_reason():
    instance = guard(budget=3)
    _, holdout = instance.split(ordered(100))
    instance.peek(holdout, reason="first look")
    instance.peek(holdout, reason="second look")
    reasons = [item["reason"] for item in instance.report()["accesses"]]
    assert reasons == ["first look", "second look"]


def test_a_single_read_keeps_the_final_result_valid():
    instance = guard()
    _, holdout = instance.split(ordered(100))
    instance.peek(holdout, reason="final evaluation")
    assert instance.report()["final_result_valid"] is True
    assert instance.report()["warning"] is None


# ------------------------------------------------------------- the guards
def test_assert_untouched_passes_before_any_read():
    instance = guard()
    instance.split(ordered(100))
    assert instance.assert_untouched() is None


def test_assert_untouched_raises_after_a_read():
    instance = guard()
    _, holdout = instance.split(ordered(100))
    instance.peek(holdout, reason="final")
    with pytest.raises(HoldoutViolation, match="already read"):
        instance.assert_untouched()


def test_research_data_reaching_into_the_holdout_is_detected():
    instance = guard()
    research, holdout = instance.split(ordered(200))
    assert not instance.contains_holdout(research)
    assert instance.contains_holdout(research + holdout[:1])


def test_contains_holdout_is_false_before_a_split():
    assert guard().contains_holdout(ordered(10)) is False


# ----------------------------------------------------- ledger integration
def test_a_read_is_reported_to_the_experiment_ledger():
    ledger = ExperimentLedger()
    instance = guard(ledger=ledger)
    _, holdout = instance.split(ordered(100))
    instance.peek(holdout, reason="final evaluation")
    assert ledger.holdout_usage == 1
    assert ledger.report().holdout_usage == 1


def test_the_report_carries_the_split_and_the_budget():
    instance = guard()
    instance.split(ordered(200))
    payload = instance.report()
    assert payload["ratio"] == pytest.approx(0.2)
    assert payload["budget"] == 1
    assert payload["split"]["holdout_rows"] == 40
