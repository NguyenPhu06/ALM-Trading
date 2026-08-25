from __future__ import annotations

from features.intelligence import MarketStateSnapshot


class StableFeatureSchema:
    VERSION = "phase3.v1"

    @classmethod
    def extract(cls, snapshot: MarketStateSnapshot) -> dict[str, float]:
        if snapshot.feature_vector.calculation_version != cls.VERSION:
            raise ValueError("incompatible feature calculation version")
        if len(snapshot.feature_vector.names) != len(snapshot.feature_vector.values):
            raise ValueError("feature names and values are misaligned")
        return snapshot.feature_vector.as_dict()
