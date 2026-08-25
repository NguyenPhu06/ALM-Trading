from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DCAPlan:
    max_entries: int
    entry_spacing: float
    position_size: float
    max_exposure: float
    max_drawdown: float


@dataclass(frozen=True, slots=True)
class DCADecision:
    allowed: bool
    reason: str
    next_size: float


class DCAEngine:
    """Chỉ đánh giá bổ sung vị thế mô phỏng, không chứa kết nối broker."""

    def evaluate(self, plan: DCAPlan, *, entries: int, exposure: float, drawdown: float,
                 adverse_distance: float, regime_valid: bool, structure_valid: bool,
                 risk_allowed: bool) -> DCADecision:
        if not structure_valid: return DCADecision(False, "NO_MORE_DCA_STRUCTURE_INVALIDATED", 0.)
        if not regime_valid: return DCADecision(False, "NO_MORE_DCA_REGIME_INVALIDATED", 0.)
        if not risk_allowed: return DCADecision(False, "NO_MORE_DCA_RISK_BLOCKED", 0.)
        if entries >= plan.max_entries: return DCADecision(False, "NO_MORE_DCA_MAX_ENTRIES", 0.)
        if drawdown >= plan.max_drawdown: return DCADecision(False, "NO_MORE_DCA_MAX_DRAWDOWN", 0.)
        if adverse_distance < plan.entry_spacing: return DCADecision(False, "WAIT_DCA_SPACING", 0.)
        size = min(plan.position_size, plan.max_exposure - exposure)
        if size <= 0: return DCADecision(False, "NO_MORE_DCA_MAX_EXPOSURE", 0.)
        return DCADecision(True, "DCA_SIMULATION_ALLOWED", size)

