from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from config.settings import load_yaml


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    learning_rate: float
    batch_size: int
    epochs: int
    hidden_layers: int
    hidden_units: int
    dropout: float
    early_stopping: bool
    early_stopping_patience: int
    minimum_improvement: float
    random_seed: int
    class_weighting: bool
    overfitting_loss_gap: float

    def __post_init__(self) -> None:
        if self.learning_rate <= 0 or self.batch_size < 1 or self.epochs < 1:
            raise ValueError("learning rate, batch size, and epochs must be positive")
        if self.hidden_layers < 1 or self.hidden_units < 1:
            raise ValueError("neural network must contain at least one hidden unit/layer")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.early_stopping_patience < 1 or self.minimum_improvement < 0:
            raise ValueError("invalid early-stopping configuration")

    @classmethod
    def from_yaml(cls) -> "TrainingConfig":
        phase: dict[str, Any] = load_yaml().get("phase_5", {})
        required = tuple(cls.__dataclass_fields__)
        missing = [name for name in required if name not in phase]
        if missing:
            raise ValueError(f"missing Phase 5 training configuration: {', '.join(missing)}")
        return cls(**{name: phase[name] for name in required})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
