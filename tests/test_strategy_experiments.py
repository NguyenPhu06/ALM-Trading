"""Experiment configuration and versioning (sections 2, 5, 6)."""
from datetime import timedelta

import pytest

from ai.edge.evidence import EvidenceSource
from ai.edge.evidence import EvidenceRefused
from research.experiments import (
    CATALOGUE,
    FEATURE_FAMILIES,
    ExperimentConfig,
    ExperimentRunner,
    ExperimentSpec,
    UnknownFeatureFamily,
    catalogue,
    compare,
    configured,
)
from tests.phase15_helpers import NOW, observation, series


# --------------------------------------------------- 2. configured, not coded
def test_every_documented_experiment_is_in_the_catalogue():
    assert set(CATALOGUE) == {"smc", "ichimoku", "rsi", "adx", "indicators",
                              "smc_indicators", "smc_nn", "smc_nn_indicators"}


def test_the_smc_experiment_is_liquidity_plus_structure():
    assert set(configured("smc").features) == {"liquidity", "market_structure"}


def test_the_combined_experiment_carries_every_component():
    config = configured("smc_nn_indicators")
    assert set(config.features) == {"liquidity", "market_structure", "nn", "ichimoku",
                                    "rsi", "adx"}
    assert config.uses_nn is True


def test_an_experiment_without_nn_says_so():
    assert configured("indicators").uses_nn is False


def test_the_catalogue_builds_every_configuration():
    assert len(catalogue()) == len(CATALOGUE)


def test_an_unknown_experiment_raises():
    with pytest.raises(KeyError):
        configured("moon_phase")


def test_an_unknown_feature_family_is_refused():
    with pytest.raises(UnknownFeatureFamily, match="astrology"):
        ExperimentConfig(name="bad", features=("astrology",))


def test_every_family_the_catalogue_uses_is_a_known_family():
    for features in CATALOGUE.values():
        assert set(features) <= set(FEATURE_FAMILIES)


def test_a_configuration_can_be_adjusted_without_editing_code():
    config = configured("smc", features=("liquidity",), description="liquidity only")
    assert config.features == ("liquidity",)
    assert config.description == "liquidity only"


# ------------------------------------------------------------ 5. versioning
def test_the_spec_records_every_documented_field():
    payload = ExperimentSpec(strategy_version="v1", config=configured("smc")).as_dict()
    for field in ("experiment_id", "strategy_version", "feature_version",
                  "model_version", "dataset_version", "label_version",
                  "training_range", "validation_range", "test_range", "timestamp"):
        assert field in payload, field


def test_the_same_configuration_reproduces_the_same_id():
    left = ExperimentSpec(strategy_version="v1", config=configured("smc"))
    right = ExperimentSpec(strategy_version="v1", config=configured("smc"))
    assert left.experiment_id == right.experiment_id


def test_the_timestamp_does_not_change_the_id():
    """Otherwise the ledger would count one hypothesis twice."""
    left = ExperimentSpec(strategy_version="v1", config=configured("smc"),
                          timestamp=NOW)
    right = ExperimentSpec(strategy_version="v1", config=configured("smc"),
                           timestamp=NOW + timedelta(days=3))
    assert left.experiment_id == right.experiment_id


@pytest.mark.parametrize("field,value", [
    ("strategy_version", "v2"), ("feature_version", "features_v9"),
    ("model_version", "mlp.v3"), ("dataset_version", "other"),
    ("label_version", "labels_v9"),
])
def test_changing_any_version_changes_the_id(field, value):
    base = ExperimentSpec(strategy_version="v1", config=configured("smc"))
    changed = ExperimentSpec(**{**{"strategy_version": "v1",
                                   "config": configured("smc")}, field: value})
    assert changed.experiment_id != base.experiment_id


def test_changing_the_configuration_changes_the_id():
    base = ExperimentSpec(strategy_version="v1", config=configured("smc"))
    other = ExperimentSpec(strategy_version="v1", config=configured("rsi"))
    assert base.experiment_id != other.experiment_id


def test_changing_a_date_range_changes_the_id():
    base = ExperimentSpec(strategy_version="v1", config=configured("smc"))
    shifted = ExperimentSpec(strategy_version="v1", config=configured("smc"),
                             test_range=(NOW, NOW + timedelta(days=7)))
    assert shifted.experiment_id != base.experiment_id


# ------------------------------------------------------------- running
def test_a_run_produces_metrics_and_an_id():
    result = ExperimentRunner(minimum_samples=30).run(configured("smc"), series(120))
    assert result.experiment_id
    assert result.metrics.sample_size == 120
    assert result.metrics.reliable


def test_a_small_run_is_flagged_not_hidden():
    result = ExperimentRunner(minimum_samples=100).run(configured("smc"), series(10))
    assert result.metrics.sample_size == 10
    assert not result.metrics.reliable
    assert "SAMPLE_BELOW_MINIMUM_100" in result.notes


def test_a_result_reports_zero_orders():
    result = ExperimentRunner().run(configured("smc"), series(50))
    assert result.as_dict()["orders_sent"] == 0


def test_a_result_names_its_evidence_source():
    result = ExperimentRunner().run(configured("smc"), series(50))
    assert result.evidence is EvidenceSource.FORWARD_OBSERVATION
    assert result.as_dict()["evidence"] == "FORWARD_OBSERVATION"


# ---------------------------------------------------- 6. forward data only
def test_a_backtest_observation_is_refused_by_name():
    rows = series(50)
    rows[7] = rows[7].labelled(evidence=EvidenceSource.BACKTEST)
    with pytest.raises(EvidenceRefused, match="BACKTEST"):
        ExperimentRunner().run(configured("smc"), rows)


def test_paper_evidence_is_refused_too():
    rows = [observation(1).labelled(evidence=EvidenceSource.PAPER)]
    with pytest.raises(EvidenceRefused):
        ExperimentRunner().run(configured("smc"), rows)


def test_one_mixed_row_is_enough_to_refuse_the_batch():
    """Mixing sources is refused per row, not averaged over."""
    rows = series(200) + [observation(999).labelled(
        evidence=EvidenceSource.DEMO_EXECUTION)]
    with pytest.raises(EvidenceRefused, match="DEMO_EXECUTION"):
        ExperimentRunner().run(configured("smc"), rows)


# --------------------------------------------------------------- comparing
def test_experiments_are_ranked_by_the_named_metric():
    runner = ExperimentRunner(minimum_samples=30)
    results = [runner.run(configured("smc"), series(120, mean=0.0002, seed=1)),
               runner.run(configured("rsi"), series(120, mean=0.0009, seed=2))]
    ranking = compare(results)
    assert ranking["best"] == "rsi"
    assert [item["name"] for item in ranking["ranking"]] == ["rsi", "smc"]


def test_an_unreliable_winner_is_reported_separately():
    runner = ExperimentRunner(minimum_samples=100)
    results = [runner.run(configured("smc"), series(150, mean=0.0002, seed=1)),
               runner.run(configured("rsi"), series(10, mean=0.9, seed=2))]
    ranking = compare(results)
    assert ranking["best"] == "rsi", "the raw winner is still reported"
    assert ranking["best_reliable"] == "smc", "but reliability is separate"


def test_the_ledger_counts_every_run():
    from research.multiple_testing import ExperimentLedger

    ledger = ExperimentLedger()
    runner = ExperimentRunner(ledger=ledger)
    runner.run(configured("smc"), series(50))
    runner.run(configured("rsi"), series(50))
    assert ledger.experiment_count == 2
    assert ledger.hypotheses_tested == 2
