"""Feature ablation (section 3).

"Do not assume that more indicators are better." The tests below state that as
an executable claim: a component that adds nothing is reported as adding
nothing, and one that hurts is reported as harmful.
"""
import pytest

from research.ablation import (
    ABLATION_ARMS,
    COMPONENT_ARMS,
    AblationStudy,
    ComponentVerdict,
)
from tests.phase15_helpers import ablation_arms, series


def study(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return AblationStudy(**kwargs)


def test_every_documented_arm_is_named():
    assert ABLATION_ARMS == ("BASELINE", "BASELINE+LIQUIDITY",
                             "BASELINE+MARKET_STRUCTURE", "BASELINE+ICHIMOKU",
                             "BASELINE+RSI", "BASELINE+ADX", "BASELINE+ATR",
                             "BASELINE+NN", "FULL_MODEL")


def test_every_component_has_an_isolating_arm():
    assert set(COMPONENT_ARMS) == {"liquidity", "market_structure", "ichimoku", "rsi",
                                   "adx", "atr", "nn"}
    assert set(COMPONENT_ARMS.values()) <= set(ABLATION_ARMS)


def test_a_baseline_arm_is_required():
    with pytest.raises(KeyError, match="BASELINE"):
        study().run({"BASELINE+RSI": series(50)})


def test_every_arm_is_evaluated():
    report = study().run(ablation_arms())
    assert set(report.arms) == set(ABLATION_ARMS)


# ------------------------------------------------------- does it earn its place
def test_a_component_that_helps_is_reported_as_improving():
    report = study().run(ablation_arms(better=("BASELINE+NN",)))
    assert report.arms["BASELINE+NN"].verdict is ComponentVerdict.IMPROVES
    assert "BASELINE+NN" in report.improving


def test_a_component_that_hurts_is_reported_as_harmful():
    report = study().run(ablation_arms(worse=("BASELINE+RSI",)))
    assert report.arms["BASELINE+RSI"].verdict is ComponentVerdict.HARMFUL
    assert "BASELINE+RSI" in report.harmful


def test_a_component_that_changes_nothing_does_not_claim_improvement():
    """The default answer: adding a component proves nothing on its own."""
    report = study().run(ablation_arms(better=(), worse=()))
    for name in ("BASELINE+ICHIMOKU", "BASELINE+ADX", "BASELINE+ATR"):
        assert report.arms[name].verdict is not ComponentVerdict.IMPROVES


def test_a_thin_arm_is_insufficient_data_not_a_pass():
    layout = ablation_arms(count=150)
    layout["BASELINE+ATR"] = series(5, mean=0.05, seed=99, start=9000)
    report = AblationStudy(minimum_samples=100).run(layout)
    assert report.arms["BASELINE+ATR"].verdict is ComponentVerdict.INSUFFICIENT_DATA
    assert "BASELINE+ATR" not in report.improving


def test_the_baseline_arm_is_never_its_own_improvement():
    report = study().run(ablation_arms())
    assert report.arms["BASELINE"].verdict is ComponentVerdict.NO_IMPROVEMENT


def test_each_arm_reports_its_deltas_against_the_baseline():
    report = study().run(ablation_arms(better=("BASELINE+NN",)))
    deltas = report.arms["BASELINE+NN"].deltas
    for name in ("expectancy", "win_rate", "maximum_drawdown", "average_mae",
                 "average_mfe"):
        assert name in deltas, name
    assert deltas["expectancy"] > 0


def test_each_arm_reports_its_significance():
    report = study().run(ablation_arms(better=("BASELINE+NN",)))
    payload = report.arms["BASELINE+NN"].significance
    assert payload["significant"] is True
    assert payload["effect_band"] in {"SMALL", "MEDIUM", "LARGE"}


def test_the_best_arm_is_chosen_among_reliable_ones():
    report = study().run(ablation_arms(better=("BASELINE+NN",)))
    assert report.best_arm == "BASELINE+NN"


def test_full_model_is_not_assumed_best():
    """FULL_MODEL wins only if the numbers say so."""
    report = study().run(ablation_arms(better=("BASELINE+NN",)))
    assert report.best_arm != "FULL_MODEL"


def test_the_report_states_that_more_is_not_assumed_better():
    payload = study().run(ablation_arms()).as_dict()
    assert "not assumed better" in payload["note"]


# ------------------------------------------------- 14. incremental component value
def test_component_value_covers_every_component():
    value = study().component_value(ablation_arms())
    assert set(value["components"]) == set(COMPONENT_ARMS)


def test_component_value_ranks_by_incremental_expectancy():
    value = study().component_value(ablation_arms(better=("BASELINE+NN",),
                                                  worse=("BASELINE+RSI",)))
    assert value["most_valuable"] == "nn"
    assert value["ranking"][-1] == "rsi"


def test_a_harmful_component_is_listed_as_harmful():
    value = study().component_value(ablation_arms(worse=("BASELINE+RSI",)))
    assert "rsi" in value["harmful"]
    assert "rsi" not in value["proven"]


def test_a_missing_arm_is_reported_not_skipped():
    layout = ablation_arms()
    layout.pop("BASELINE+ATR")
    value = study().component_value(layout)
    assert value["components"]["atr"]["reason"] == "ARM_NOT_RUN"


def test_component_value_disclaims_causality():
    value = study().component_value(ablation_arms())
    assert "does not establish that the component causes" in value["disclaimer"]


def test_component_value_reports_effect_size_per_component():
    value = study().component_value(ablation_arms(better=("BASELINE+NN",)))
    assert value["components"]["nn"]["effect_size"] is not None
    assert value["components"]["nn"]["sample_size"] == 150
