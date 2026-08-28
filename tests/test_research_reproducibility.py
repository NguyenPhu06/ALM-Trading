"""Reproducibility and reporting (sections 5 and 24).

An experiment that cannot be reproduced is an anecdote. These tests pin the two
properties that make one reproducible: a content-hashed identity, and a report
whose prose is generated from the same payload as its numbers.
"""
import json
import pathlib

import pytest

from research.experiments import ExperimentRunner, ExperimentSpec, configured
from research.metrics import evaluate
from research.reports import (
    HEADER_NOTE,
    REPORT_FILES,
    ResearchReporter,
    render_markdown,
)
from tests.phase15_helpers import NOW, series


def runner(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return ExperimentRunner(**kwargs)


# --------------------------------------------------------- reproducible runs
def test_the_same_inputs_reproduce_the_same_result():
    rows = series(120, seed=1)
    first = runner().run(configured("smc"), rows, strategy_version="v1")
    second = runner().run(configured("smc"), rows, strategy_version="v1")
    assert first.experiment_id == second.experiment_id
    assert first.metrics.as_dict() == second.metrics.as_dict()


def test_the_metrics_are_deterministic_for_a_fixed_input():
    rows = series(120, seed=2)
    assert evaluate(rows).as_dict() == evaluate(rows).as_dict()


def test_a_reordered_input_produces_the_same_summary_statistics():
    """Expectancy and win rate must not depend on row order."""
    rows = series(120, seed=3)
    shuffled = list(reversed(rows))
    left, right = evaluate(rows), evaluate(shuffled)
    assert left.expectancy == pytest.approx(right.expectancy)
    assert left.win_rate == pytest.approx(right.win_rate)
    assert left.sample_size == right.sample_size


def test_drawdown_does_depend_on_order_and_that_is_correct():
    """Drawdown is a path statistic; reversing the path may change it."""
    rows = series(120, seed=4)
    forward = evaluate(rows).maximum_drawdown
    backward = evaluate(list(reversed(rows))).maximum_drawdown
    assert forward is not None and backward is not None


def test_the_significance_test_is_seeded():
    from research.significance import SignificanceTester

    tester = SignificanceTester(minimum_samples=50)
    values = [row.net_pnl for row in series(150, mean=0.0009, seed=5)]
    first = tester.absolute(values, seed=42).as_dict()
    second = tester.absolute(values, seed=42).as_dict()
    assert first == second


def test_a_different_seed_may_change_the_interval_but_not_the_mean():
    from research.significance import SignificanceTester

    tester = SignificanceTester(minimum_samples=50)
    values = [row.net_pnl for row in series(150, mean=0.0009, seed=6)]
    assert (tester.absolute(values, seed=1).difference
            == pytest.approx(tester.absolute(values, seed=2).difference))


def test_the_spec_records_the_versions_needed_to_rerun():
    spec = ExperimentSpec(strategy_version="v1", config=configured("smc"),
                          dataset_version="ds-7", model_version="mlp.v2")
    payload = spec.as_dict()
    assert payload["dataset_version"] == "ds-7"
    assert payload["model_version"] == "mlp.v2"
    assert payload["config"]["features"] == list(configured("smc").features)


# ------------------------------------------------------------- 24. reporting
def test_every_documented_report_name_is_registered():
    for name in ("strategy_comparison", "regime_analysis", "session_analysis",
                 "nn_value_analysis", "ablation_analysis", "dca_analysis",
                 "time_exit_analysis", "champion_challenger"):
        assert name in REPORT_FILES, name


def test_a_report_is_written_as_json_and_markdown(tmp_path):
    reporter = ResearchReporter(tmp_path)
    paths = reporter.write(reporter.build("dca_analysis", {"recommended": "NO_DCA"}))
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert paths["json"].name == "dca_analysis.json"
    assert paths["markdown"].name == "dca_analysis.md"


def test_the_json_and_the_markdown_come_from_one_payload(tmp_path):
    """The prose cannot drift from the numbers if both are generated together."""
    reporter = ResearchReporter(tmp_path)
    reporter.write(reporter.build("dca_analysis", {"recommended": "DCA_1",
                                                   "tail_tolerance": 0.2}))
    payload = json.loads((tmp_path / "dca_analysis.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "dca_analysis.md").read_text(encoding="utf-8")
    assert payload["recommended"] == "DCA_1"
    assert "DCA_1" in markdown


def test_every_report_carries_the_evidence_header(tmp_path):
    reporter = ResearchReporter(tmp_path)
    reporter.write(reporter.build("regime_analysis", {"best": "BULL"}))
    markdown = (tmp_path / "regime_analysis.md").read_text(encoding="utf-8")
    assert HEADER_NOTE in markdown
    assert "Not a backtest" in markdown


def test_every_report_states_that_nothing_was_executed(tmp_path):
    reporter = ResearchReporter(tmp_path)
    reporter.write(reporter.build("regime_analysis", {"best": "BULL"}))
    payload = json.loads((tmp_path / "regime_analysis.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "regime_analysis.md").read_text(encoding="utf-8")
    assert payload["orders_sent"] == 0
    assert "ORDERS SENT: 0" in markdown


def test_an_unregistered_report_name_is_flagged_not_rejected(tmp_path):
    reporter = ResearchReporter(tmp_path)
    bundle = reporter.build("my_experiment", {"value": 1})
    assert bundle.payload["unregistered_report"] is True
    reporter.write(bundle)
    assert (tmp_path / "my_experiment.json").exists()


def test_generate_writes_an_index(tmp_path):
    index = ResearchReporter(tmp_path).generate({
        "regime_analysis": {"best": "BULL"},
        "session_analysis": {"best": "LONDON"}})
    assert set(index["reports"]) == {"regime_analysis", "session_analysis"}
    assert (tmp_path / "index.json").exists()
    assert index["orders_sent"] == 0


def test_a_table_payload_renders_as_a_markdown_table():
    markdown = render_markdown("regime_analysis", {
        "rows": [{"name": "BULL", "expectancy": 0.0004, "reliable": True},
                 {"name": "BEAR", "expectancy": -0.0002, "reliable": False}]})
    assert "| name | expectancy | reliable |" in markdown
    assert "| BULL |" in markdown
    assert "| yes |" in markdown


def test_a_missing_value_renders_as_a_dash():
    markdown = render_markdown("x", {"rows": [{"name": "BULL", "expectancy": None}]})
    assert "—" in markdown


def test_an_empty_list_renders_as_none_not_a_blank():
    markdown = render_markdown("x", {"improving": []})
    assert "_(none)_" in markdown


def test_nested_payloads_render_as_nested_headings():
    markdown = render_markdown("x", {"metrics": {"expectancy": 0.0004,
                                                 "win_rate": 0.55}})
    assert "## Metrics" in markdown
    assert "**Expectancy**" in markdown


def test_the_report_directory_is_created_on_demand(tmp_path):
    target = tmp_path / "nested" / "research"
    ResearchReporter(target).generate({"regime_analysis": {"best": "BULL"}})
    assert (target / "regime_analysis.json").exists()


def test_research_reports_are_gitignored():
    """A report is an output of a dataset, not source."""
    ignored = pathlib.Path(".gitignore").read_text(encoding="utf-8")
    assert "reports/research" in ignored
