from __future__ import annotations

from strategy.models import RiskDecision


class RiskEngine:
    def __init__(self, *, max_position_size: float = 1., max_dca_entries: int = 3,
                 max_total_exposure: float = 3., max_drawdown_allowed: float = .02):
        self.max_position_size = max_position_size
        self.max_dca_entries = max_dca_entries
        self.max_total_exposure = max_total_exposure
        self.max_drawdown_allowed = max_drawdown_allowed

    def evaluate(self, *, data_quality_ok: bool, model_available: bool, volatility: str,
                 current_drawdown: float = 0., structure_valid: bool = True) -> RiskDecision:
        reasons: list[str] = []
        if not data_quality_ok: reasons.append("DATA_QUALITY_FAILURE")
        if not model_available: reasons.append("MODEL_UNAVAILABLE")
        if volatility == "EXTREME_VOLATILITY": reasons.append("EXTREME_VOLATILITY")
        if current_drawdown >= self.max_drawdown_allowed: reasons.append("MAX_DRAWDOWN_EXCEEDED")
        if not structure_valid: reasons.append("STRUCTURE_INVALIDATED")
        return RiskDecision(not reasons, self.max_position_size, self.max_dca_entries,
                            self.max_total_exposure, self.max_drawdown_allowed,
                            tuple(reasons or ["RISK_WITHIN_LIMITS"]))

