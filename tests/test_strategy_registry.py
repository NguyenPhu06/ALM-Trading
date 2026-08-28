"""Strategy registry (section 1)."""
import pytest

from research.registry import (
    ALLOWED_TRANSITIONS,
    ApprovalToken,
    PromotionRefused,
    StrategyRegistry,
    StrategyStatus,
    TransitionRefused,
    strategy,
)
from tests.phase15_helpers import registry_with, validated


def smc(version="v1"):
    return strategy("smc", "Liquidity + market structure", version=version,
                    features=("liquidity", "market_structure"),
                    timeframes=("H1", "M15"), entry_rules=("sweep+bos",),
                    exit_rules=("time_exit",), dca_rules=("max_3_levels",),
                    risk_rules=("max_1pct",))


# ----------------------------------------------------------- the declaration
def test_a_strategy_records_every_documented_field():
    payload = smc().as_dict()
    for field in ("strategy_id", "strategy_version", "description", "features",
                  "timeframes", "entry_rules", "exit_rules", "dca_rules", "risk_rules",
                  "status"):
        assert field in payload, field


def test_every_documented_status_exists():
    assert {str(item) for item in StrategyStatus} == {
        "EXPERIMENTAL", "TESTING", "VALIDATED", "CHAMPION", "REJECTED", "RETIRED"}


def test_a_new_strategy_starts_experimental():
    assert smc().status is StrategyStatus.EXPERIMENTAL


def test_a_registry_entry_is_not_executable():
    """The registry stores a description of rules, not something that runs."""
    assert smc().as_dict()["executes"] is False


def test_the_key_combines_id_and_version():
    assert smc("v2").key == "smc:v2"


def test_identical_declarations_share_a_fingerprint():
    assert smc("v1").fingerprint == smc("v2").fingerprint


def test_a_different_declaration_changes_the_fingerprint():
    other = strategy("smc", "different", features=("rsi",))
    assert other.fingerprint != smc().fingerprint


def test_the_registry_reports_duplicate_declarations():
    registry = registry_with(smc("v1"), smc("v2"))
    duplicates = registry.duplicates()
    assert len(duplicates) == 1
    assert sorted(next(iter(duplicates.values()))) == ["smc:v1", "smc:v2"]


# --------------------------------------------------------- the state machine
def test_registering_twice_is_refused():
    registry = registry_with(smc())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(smc())


def test_the_documented_path_is_walkable():
    registry = registry_with(smc())
    registry.transition("smc:v1", StrategyStatus.TESTING)
    registry.transition("smc:v1", StrategyStatus.VALIDATED)
    assert registry.get("smc:v1").status is StrategyStatus.VALIDATED


def test_skipping_testing_is_refused():
    registry = registry_with(smc())
    with pytest.raises(TransitionRefused):
        registry.transition("smc:v1", StrategyStatus.VALIDATED)


def test_going_backwards_is_refused():
    registry = registry_with(smc())
    validated(registry, "smc:v1")
    with pytest.raises(TransitionRefused):
        registry.transition("smc:v1", StrategyStatus.TESTING)


@pytest.mark.parametrize("terminal", ["REJECTED", "RETIRED"])
def test_terminal_states_have_no_exit(terminal):
    assert ALLOWED_TRANSITIONS[StrategyStatus(terminal)] == frozenset()


def test_an_unknown_strategy_raises():
    with pytest.raises(KeyError):
        StrategyRegistry().get("missing:v1")


# -------------------------------------------------------- 4. no auto promote
def test_transition_cannot_reach_champion():
    """CHAMPION is reachable only through promote(), which needs a human."""
    registry = registry_with(smc())
    validated(registry, "smc:v1")
    with pytest.raises(PromotionRefused, match="ApprovalToken"):
        registry.transition("smc:v1", StrategyStatus.CHAMPION)


def test_promotion_requires_a_named_human():
    with pytest.raises(ValueError, match="named human"):
        ApprovalToken("", "reason")


def test_promotion_requires_a_stated_reason():
    with pytest.raises(ValueError, match="stated reason"):
        ApprovalToken("nvphu", "  ")


def test_promotion_refuses_anything_that_is_not_a_token():
    registry = registry_with(smc())
    validated(registry, "smc:v1")
    with pytest.raises(PromotionRefused, match="ApprovalToken"):
        registry.promote("smc:v1", "just trust me")


def test_an_experimental_strategy_cannot_be_promoted():
    registry = registry_with(smc())
    with pytest.raises(PromotionRefused, match="VALIDATED"):
        registry.promote("smc:v1", ApprovalToken("nvphu", "too early"))


def test_a_validated_strategy_is_promoted_with_approval():
    registry = registry_with(smc())
    validated(registry, "smc:v1")
    promoted = registry.promote("smc:v1", ApprovalToken("nvphu", "beat the incumbent"))
    assert promoted.is_champion
    assert promoted.approval.approved_by == "nvphu"
    assert registry.champion().key == "smc:v1"


def test_promoting_a_successor_retires_the_incumbent():
    registry = registry_with(smc("v1"), smc("v2"))
    validated(registry, "smc:v1")
    registry.promote("smc:v1", ApprovalToken("nvphu", "first"))
    validated(registry, "smc:v2")
    registry.promote("smc:v2", ApprovalToken("nvphu", "better"))
    assert registry.get("smc:v1").status is StrategyStatus.RETIRED
    assert registry.champion().key == "smc:v2"
    assert "SUPERSEDED_BY:smc:v2" in registry.get("smc:v1").notes


# ------------------------------------------------------ 10. rejection
def test_rejection_records_a_reason():
    registry = registry_with(smc())
    rejected = registry.reject("smc:v1", "negative expectancy over 400 observations")
    assert rejected.status is StrategyStatus.REJECTED
    assert any("REJECTED:" in note for note in rejected.notes)


def test_rejection_without_a_reason_is_refused():
    registry = registry_with(smc())
    with pytest.raises(ValueError, match="stated reason"):
        registry.reject("smc:v1", "  ")


def test_a_rejected_strategy_cannot_come_back():
    registry = registry_with(smc())
    registry.reject("smc:v1", "no edge")
    with pytest.raises(TransitionRefused):
        registry.transition("smc:v1", StrategyStatus.TESTING)


# ------------------------------------------------------------- reads
def test_challengers_are_the_testing_and_validated_strategies():
    registry = registry_with(smc("v1"), smc("v2"))
    registry.transition("smc:v1", StrategyStatus.TESTING)
    validated(registry, "smc:v2")
    assert {record.key for record in registry.challengers()} == {"smc:v1", "smc:v2"}


def test_the_summary_counts_every_status():
    registry = registry_with(smc("v1"), smc("v2"))
    registry.reject("smc:v2", "no edge")
    summary = registry.summary()
    assert summary["total"] == 2
    assert summary["by_status"] == {"EXPERIMENTAL": 1, "REJECTED": 1}
    assert summary["champion"] is None


def test_the_registry_persists_through_its_repository(db_session):
    from database.models import ResearchStrategyRecord
    from database.repositories.research import ResearchRepository

    registry = StrategyRegistry(repository=ResearchRepository(db_session))
    registry.register(smc())
    validated(registry, "smc:v1")
    registry.promote("smc:v1", ApprovalToken("nvphu", "verified"))

    rows = db_session.query(ResearchStrategyRecord).all()
    assert len(rows) == 1
    assert rows[0].status == "CHAMPION"
    assert rows[0].approved_by == "nvphu"
    assert rows[0].fingerprint == smc().fingerprint
