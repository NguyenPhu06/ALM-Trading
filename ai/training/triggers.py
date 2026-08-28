"""Training triggers (section 11).

A trigger is a reason to *consider* training. It is never permission to train.
The defaults say so out loud:

    manual_training    = True     a human starts the job
    automatic_training = False    nothing else may

`AI_AUTOMATIC_TRAINING` is refused at startup by `config/settings.py`, so this
policy cannot be talked into returning `may_start_automatically = True` by
configuration alone. The field exists so that a future phase which wants
scheduled training has to change code, review it, and face the tests here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ai.training.retraining import RetrainingPolicy, RetrainingRequest, RetrainingTrigger
from config.settings import Settings, get_settings, load_yaml


@dataclass(frozen=True, slots=True)
class TriggerSettings:
    minimum_new_observations: int = 500
    scheduled_training: bool = False
    manual_training: bool = True
    automatic_training: bool = False
    performance_degradation: float = 0.10
    drift_detected: bool = True

    @classmethod
    def from_config(cls, settings: Settings | None = None) -> "TriggerSettings":
        settings = settings or get_settings()
        phase13 = load_yaml().get("phase_13", {}).get("retraining", {})
        config = load_yaml().get("phase_14", {}).get("triggers", {})
        return cls(
            minimum_new_observations=int(config.get(
                "minimum_new_observations",
                phase13.get("minimum_new_observations", 500))),
            scheduled_training=bool(config.get("scheduled_training", False)),
            manual_training=bool(config.get("manual_training", True)),
            # Never read from YAML alone: the settings flag is the authority and
            # it is validated at startup.
            automatic_training=bool(getattr(settings, "ai_automatic_training", False)),
            performance_degradation=float(config.get(
                "performance_degradation",
                phase13.get("performance_degradation", 0.10))),
            drift_detected=bool(config.get("drift_detected", True)))

    def as_dict(self) -> dict[str, Any]:
        return {"minimum_new_observations": self.minimum_new_observations,
                "scheduled_training": self.scheduled_training,
                "manual_training": self.manual_training,
                "automatic_training": self.automatic_training,
                "performance_degradation": self.performance_degradation,
                "drift_detected": self.drift_detected}


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    request: RetrainingRequest
    fired: tuple[RetrainingTrigger, ...] = ()
    suppressed: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def triggered(self) -> bool:
        return bool(self.fired)

    @property
    def may_start_automatically(self) -> bool:
        """Constant False in this phase, and asserted as such by the tests."""
        return False

    @property
    def requires_human(self) -> bool:
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "fired": [str(item) for item in self.fired],
            "suppressed": list(self.suppressed), "reasons": list(self.reasons),
            "may_start_automatically": False, "requires_human": True,
            "request": self.request.as_dict(), **self.context,
        }


class TrainingTriggerPolicy:
    """Evaluates triggers and reports what a human would be asked to approve."""

    def __init__(self, settings: Settings | None = None, *,
                 config: TriggerSettings | None = None,
                 policy: RetrainingPolicy | None = None):
        self.settings = settings or get_settings()
        self.config = config or TriggerSettings.from_config(self.settings)
        self.policy = policy or RetrainingPolicy(
            self.settings,
            minimum_new_observations=self.config.minimum_new_observations,
            performance_degradation=self.config.performance_degradation)

    def evaluate(self, *, new_observations: int = 0, last_training: datetime | None = None,
                 baseline_score: float | None = None, current_score: float | None = None,
                 drift_flagged: bool = False, manual: bool = False,
                 now: datetime | None = None) -> TriggerDecision:
        request = self.policy.evaluate(
            new_observations=new_observations, last_training=last_training,
            baseline_score=baseline_score, current_score=current_score,
            drift_flagged=drift_flagged, manual=manual, now=now)

        fired: list[RetrainingTrigger] = []
        suppressed: list[str] = []
        for trigger in request.triggers:
            if trigger is RetrainingTrigger.MANUAL and not self.config.manual_training:
                suppressed.append(f"{trigger}:MANUAL_TRAINING_DISABLED")
            elif trigger is RetrainingTrigger.SCHEDULED and not self.config.scheduled_training:
                suppressed.append(f"{trigger}:SCHEDULED_TRAINING_DISABLED")
            elif trigger is RetrainingTrigger.FEATURE_DRIFT and not self.config.drift_detected:
                suppressed.append(f"{trigger}:DRIFT_TRIGGER_DISABLED")
            else:
                fired.append(trigger)

        reasons = list(request.reasons)
        if fired:
            # Said in the decision itself so no caller has to infer it.
            reasons.append("HUMAN_APPROVAL_REQUIRED")
        return TriggerDecision(request, tuple(fired), tuple(suppressed), tuple(reasons),
                               context={"config": self.config.as_dict(),
                                        "training_enabled": self.settings.ai_training_enabled})
