from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256

from ai.models.contracts import ModelPrediction
from features.intelligence.models import MarketStateSnapshot
from strategy.models import SetupDirection, SetupStatus, StrategyDecision, TradeSetup
from strategy.mtf import MultiTimeframeEngine, _direction
from strategy.risk import RiskEngine
from strategy.scoring import ScoreInput, StrategyScoringEngine
from strategy.session import TradingSessionEngine


class StrategyIntelligenceEngine:
    """Research-only setup evaluator. It cannot place or route orders."""

    def __init__(self, *, scoring: StrategyScoringEngine | None = None,
                 risk: RiskEngine | None = None, sessions: TradingSessionEngine | None = None,
                 ready_score: float = 65., simulation_score: float = 75.):
        self.mtf = MultiTimeframeEngine()
        self.scoring = scoring or StrategyScoringEngine()
        self.risk = risk or RiskEngine()
        self.sessions = sessions or TradingSessionEngine()
        self.ready_score = ready_score
        self.simulation_score = simulation_score

    def evaluate(self, snapshot: MarketStateSnapshot, *, entry_price: float,
                 prediction: ModelPrediction | None = None, require_even_hour: bool = False) -> StrategyDecision:
        if prediction is not None and prediction.timestamp > snapshot.timestamp:
            raise ValueError("future prediction cannot enter strategy decision")
        mtf = self.mtf.build(snapshot)
        htf_direction = _direction(mtf.higher_timeframe_bias)
        direction = SetupDirection.LONG if htf_direction > 0 else SetupDirection.SHORT if htf_direction < 0 else SetupDirection.NONE
        ltf = mtf.timeframes["M15"]
        structure_dir = _direction(ltf.structure or ltf.bos)
        structure = 1. if htf_direction and structure_dir == htf_direction else .4 if structure_dir == 0 else 0.
        sweep = snapshot.timeframes.get("M15").sweep if snapshot.timeframes.get("M15") else None
        liquidity = .8 if sweep and _direction(str(sweep.get("direction", sweep.get("event_type", "")))) == htf_direction else .5 if ltf.liquidity_context else .25
        indicators = ltf.indicators
        adx = float(indicators.get("adx") or 0.)
        indicator_direction = 0
        if indicators.get("price_above_cloud") or float(indicators.get("di_plus") or 0) > float(indicators.get("di_minus") or 0): indicator_direction += 1
        if indicators.get("price_below_cloud") or float(indicators.get("di_minus") or 0) > float(indicators.get("di_plus") or 0): indicator_direction -= 1
        indicator = .8 if htf_direction and indicator_direction == htf_direction and adx >= 20 else .5 if indicator_direction == 0 else .25
        nn_alignment = .5
        nn_confidence = 0.
        if prediction:
            nn_confidence = prediction.confidence
            target = prediction.prob_up if htf_direction > 0 else prediction.prob_down if htf_direction < 0 else prediction.prob_neutral
            nn_alignment = target
        volatility_state = ltf.volatility
        volatility = 0. if volatility_state == "EXTREME_VOLATILITY" else .65 if volatility_state in {"HIGH_VOLATILITY", "LOW_VOLATILITY"} else 1.
        session = self.sessions.context(snapshot.timestamp)
        session_quality = .4 if session.session.value == "OFF_SESSION" else 1.
        values = ScoreInput(structure, liquidity, 1. if mtf.alignment == "ALIGNED" else 0., indicator,
                            nn_alignment, volatility, session_quality)
        reasons = [f"HTF_{mtf.higher_timeframe_bias}", f"M15_STRUCTURE_{ltf.structure or 'UNKNOWN'}",
                   f"SESSION_{session.session.value}"]
        if sweep: reasons.append("LIQUIDITY_SWEEP_CONFIRMED")
        if adx >= 20: reasons.append("ADX_TRENDING_FEATURE")
        if prediction: reasons.append(f"NN_{prediction.predicted_class}_{prediction.confidence:.2f}")
        conflicts = list(mtf.conflicts)
        if require_even_hour and not session.is_even_hour_entry: conflicts.append("NOT_EVEN_HOUR_CHECKPOINT")
        score = self.scoring.score(values, reasons, tuple(conflicts))
        confidence = self.scoring.confidence(values, nn_confidence)
        quality = snapshot.data_quality
        quality_ok = not quality or bool(quality.get("valid", quality.get("ready", True)))
        risk = self.risk.evaluate(data_quality_ok=quality_ok, model_available=prediction is not None,
                                  volatility=volatility_state, structure_valid=direction is not SetupDirection.NONE)
        if not risk.risk_allowed or direction is SetupDirection.NONE:
            status = SetupStatus.INVALID
        elif conflicts:
            status = SetupStatus.WATCH
        elif score.score >= self.simulation_score:
            status = SetupStatus.EXECUTABLE_SIMULATION
        elif score.score >= self.ready_score:
            status = SetupStatus.READY
        else:
            status = SetupStatus.WATCH
        prefix = "WHY_INVALIDATED" if status is SetupStatus.INVALID else "WHY_READY" if status in {SetupStatus.READY, SetupStatus.EXECUTABLE_SIMULATION} else "WHY_WATCH"
        reason_codes = (prefix, *tuple(reasons), *tuple(conflicts), *(() if risk.risk_allowed else risk.reason_codes))
        setup_id = sha256(f"{snapshot.symbol}|{snapshot.timestamp.isoformat()}|{snapshot.calculation_version}".encode()).hexdigest()[:24]
        setup = TradeSetup(
            setup_id, snapshot.symbol, snapshot.timestamp, direction, entry_price, mtf.higher_timeframe_bias,
            mtf.alignment, dict(ltf.liquidity_context), {"structure": ltf.structure, "bos": ltf.bos, "choch": ltf.choch,
            "swing_high": ltf.swing_high, "swing_low": ltf.swing_low}, dict(indicators),
            asdict(prediction) if prediction else None, risk, score, confidence, status, tuple(reason_codes),
            model_version=prediction.model_version if prediction else None,
        )
        decision = "SIMULATE" if status is SetupStatus.EXECUTABLE_SIMULATION else "WAIT" if status in {SetupStatus.WATCH, SetupStatus.READY} else "INVALIDATE"
        return StrategyDecision(snapshot.timestamp, snapshot.symbol, decision, setup, tuple(reason_codes))

