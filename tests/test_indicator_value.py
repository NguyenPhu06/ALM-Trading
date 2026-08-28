"""Incremental indicator value (section 14).

Each component is measured on its own arm. The answer for most of them, most of
the time, should be "not proven" — that is what an honest ablation looks like.
"""
import pytest

from research.ablation import COMPONENT_ARMS, AblationStudy, ComponentVerdict
from tests.phase15_helpers import ablation_arms, series


def study(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return AblationStudy(**kwargs)


def value(**kwargs):
    return study().component_value(ablation_arms(**kwargs))


def test_every_documented_component_is_measured():
    """Section 14's list: Ichimoku, RSI, ADX, ATR, Liquidity, Market Structure, NN."""
    components = value()["components"]
    for name in ("ichimoku", "rsi", "adx", "atr", "liquidity", "market_structure", "nn"):
        assert name in components, name


def test_each_component_reports_its_own_arm():
    components = value()["components"]
    for name, arm in COMPONENT_ARMS.items():
        assert components[name]["arm"] == arm


def test_each_component_reports_the_documented_deltas():
    payload = value()["components"]["nn"]
    for field in ("delta_expectancy", "delta_win_rate", "delta_drawdown",
                  "effect_size", "effect_band", "sample_size"):
        assert field in payload, field


def test_a_component_that_adds_nothing_is_not_proven():
    payload = value(better=(), worse=())["components"]["ichimoku"]
    assert payload["verdict"] != str(ComponentVerdict.IMPROVES)


def test_a_component_that_helps_is_proven():
    payload = value(better=("BASELINE+NN",))
    assert "nn" in payload["proven"]
    assert payload["components"]["nn"]["verdict"] == str(ComponentVerdict.IMPROVES)


def test_a_component_that_hurts_is_named_harmful():
    payload = value(worse=("BASELINE+RSI",))
    assert "rsi" in payload["harmful"]


def test_components_are_ranked_by_incremental_contribution():
    payload = value(better=("BASELINE+NN",), worse=("BASELINE+ADX",))
    assert payload["ranking"][0] == "nn"
    assert payload["ranking"][-1] == "adx"


def test_the_most_valuable_component_is_named():
    assert value(better=("BASELINE+LIQUIDITY",))["most_valuable"] == "liquidity"


def test_more_indicators_are_not_assumed_better():
    """Three indicators added, none of them proven."""
    payload = value(better=(), worse=())
    proven = set(payload["proven"])
    assert not proven & {"ichimoku", "rsi", "adx"}


def test_the_mtf_regime_component_is_reported_through_its_arm_when_present():
    """mtf has no dedicated arm; it must not be silently reported as proven."""
    payload = value()
    assert "mtf" not in payload["components"]
    assert "mtf" not in payload["proven"]


def test_a_missing_arm_is_reported_as_not_run():
    layout = ablation_arms()
    layout.pop("BASELINE+ICHIMOKU")
    payload = study().component_value(layout)
    assert payload["components"]["ichimoku"]["verdict"] == \
        str(ComponentVerdict.INSUFFICIENT_DATA)
    assert payload["components"]["ichimoku"]["reason"] == "ARM_NOT_RUN"


def test_a_thin_arm_does_not_earn_a_verdict():
    layout = ablation_arms(count=150)
    layout["BASELINE+ATR"] = series(4, mean=0.9, seed=42, start=9000)
    payload = AblationStudy(minimum_samples=100).component_value(layout)
    assert payload["components"]["atr"]["verdict"] == \
        str(ComponentVerdict.INSUFFICIENT_DATA)
    assert "atr" not in payload["proven"]


def test_the_analysis_disclaims_causality():
    assert "does not establish" in value()["disclaimer"]


def test_effect_band_is_reported_alongside_the_delta():
    payload = value(better=("BASELINE+NN",))["components"]["nn"]
    assert payload["effect_band"] in {"NEGLIGIBLE", "SMALL", "MEDIUM", "LARGE", "UNKNOWN"}
    assert payload["delta_expectancy"] > 0
