"""Liquidity event study (section 19).

The rule that outranks every result: do not claim institutional activity.
"""
import inspect
import pathlib

import pytest

from research import liquidity_events
from research.liquidity_events import (
    DISCLAIMER,
    EVENT_TYPES,
    FORBIDDEN_CLAIMS,
    LiquidityEventStudy,
)
from tests.phase15_helpers import series


def study(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return LiquidityEventStudy(**kwargs)


def observations(count=40):
    rows = []
    for index, event in enumerate(EVENT_TYPES):
        rows += series(count, mean=0.0009 if index == 0 else 0.0001,
                       seed=index + 1, start=index * 1000, liquidity_event=event)
    rows += series(60, mean=0.0002, seed=99, start=90000, liquidity_event=None)
    return rows


# ------------------------------------------------------------ the seven events
def test_every_documented_event_is_studied():
    assert EVENT_TYPES == ("LIQUIDITY_SWEEP", "EQUAL_HIGH_SWEEP", "EQUAL_LOW_SWEEP",
                           "PREVIOUS_DAY_HIGH_SWEEP", "PREVIOUS_DAY_LOW_SWEEP",
                           "SESSION_HIGH_SWEEP", "SESSION_LOW_SWEEP")


def test_all_seven_events_appear_in_the_report():
    report = study().run(observations())
    assert set(report.events) == set(EVENT_TYPES)


def test_an_event_with_no_observations_is_still_reported():
    report = study().run(series(60, seed=1, liquidity_event="LIQUIDITY_SWEEP"))
    assert report.events["SESSION_HIGH_SWEEP"].metrics.sample_size == 0
    assert not report.events["SESSION_HIGH_SWEEP"].reliable


def test_observations_without_an_event_form_the_baseline():
    report = study().run(observations())
    assert report.baseline.sample_size == 60


def test_the_best_event_comes_from_the_measurements():
    assert study().run(observations()).best == "LIQUIDITY_SWEEP"


def test_a_thin_event_is_not_called_reliable():
    rows = series(4, seed=1, liquidity_event="EQUAL_LOW_SWEEP") + series(
        60, seed=2, start=1000)
    report = study().run(rows)
    assert not report.events["EQUAL_LOW_SWEEP"].reliable
    assert "EQUAL_LOW_SWEEP" not in report.reliable_events


def test_each_event_reports_follow_through_and_reversal():
    report = study().run(observations())
    result = report.events["LIQUIDITY_SWEEP"]
    assert result.follow_through_rate is not None
    assert result.reversal_rate is not None
    assert result.follow_through_rate + result.reversal_rate == pytest.approx(1.0)


def test_each_event_reports_its_excursions():
    result = study().run(observations()).events["LIQUIDITY_SWEEP"]
    assert result.average_mfe is not None
    assert result.average_mae is not None


def test_an_event_is_compared_against_the_baseline():
    report = study().run(observations())
    assert report.events["LIQUIDITY_SWEEP"].significance != {}


def test_a_significant_event_is_named():
    rows = (series(150, mean=0.0012, seed=1, liquidity_event="LIQUIDITY_SWEEP")
            + series(150, mean=0.0001, seed=2, start=1000))
    report = LiquidityEventStudy(minimum_samples=100).run(rows)
    assert "LIQUIDITY_SWEEP" in report.significant_events


def test_an_indistinguishable_event_is_not_named_significant():
    rows = (series(150, mean=0.00041, seed=1, liquidity_event="LIQUIDITY_SWEEP")
            + series(150, mean=0.0004, seed=2, start=1000))
    report = LiquidityEventStudy(minimum_samples=100).run(rows)
    assert "LIQUIDITY_SWEEP" not in report.significant_events


# ------------------------------------------- no institutional claims, ever
def test_the_report_carries_the_disclaimer():
    payload = study().run(observations()).as_dict()
    assert payload["disclaimer"] == DISCLAIMER
    assert "not evidence of institutional activity" in payload["disclaimer"]


def test_every_event_result_is_labelled_as_an_observed_pattern():
    payload = study().run(observations()).as_dict()
    for name, item in payload["events"].items():
        assert item["claim"] == "OBSERVED_PATTERN_ONLY", name


NEGATIONS = ("not", "never", "no ", "forbidden", "do not", "without")


def _prose(source: str) -> list[tuple[int, str]]:
    """Source lines with the FORBIDDEN_CLAIMS declaration itself removed."""
    lines = source.splitlines()
    inside = False
    kept: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        if line.startswith("FORBIDDEN_CLAIMS"):
            inside = True
        if inside:
            if line.rstrip().endswith(")"):
                inside = False
            continue
        kept.append((number, line))
    return kept


@pytest.mark.parametrize("phrase", FORBIDDEN_CLAIMS)
def test_every_use_of_a_forbidden_phrase_is_a_denial(phrase):
    """The words may appear — but only to rule the claim out.

    Checked over a three-line window, because a denial and the phrase it denies
    routinely land on different lines once prose is wrapped.
    """
    source = pathlib.Path("research/liquidity_events.py").read_text(encoding="utf-8")
    lines = _prose(source)
    offenders = []
    for index, (number, line) in enumerate(lines):
        if phrase.lower() not in line.lower():
            continue
        window = " ".join(text for _, text in
                          lines[max(index - 1, 0):index + 2]).lower()
        if any(word in window for word in NEGATIONS):
            continue
        offenders.append(f"{number}: {line.strip()}")
    assert offenders == [], offenders


def test_the_forbidden_list_names_the_claims_to_avoid():
    assert "institution" in FORBIDDEN_CLAIMS
    assert "smart money" in FORBIDDEN_CLAIMS


def test_the_rendered_report_makes_no_institutional_claim():
    payload = str(study().run(observations()).as_dict()).lower()
    for phrase in ("smart money", "bank bought", "fund bought", "whale"):
        assert phrase not in payload


def test_follow_through_is_described_as_price_not_intent():
    source = inspect.getsource(liquidity_events._rate)
    assert "description of price, not of intent" in source
