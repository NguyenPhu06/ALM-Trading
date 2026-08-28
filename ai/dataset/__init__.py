"""Phase 13 forward-observation dataset pipeline.

Note the deliberate distinction from `ai.datasets` (plural), which is the Phase 4
historical-candle pipeline. This package builds datasets from REAL FORWARD
OBSERVATION data and delegates splitting and scaling to the Phase 4 modules so
there is exactly one implementation of each.
"""
from ai.dataset.builder import BuiltDataset, DatasetBuilder, DatasetRow, Partition
from ai.dataset.features import FEATURE_GROUPS, FeatureExtractor, FeatureRow
from ai.dataset.labels import (
    HORIZONS, Direction, ForwardLabel, LabelRefusal, LabelResult, LabelingEngine,
    Outcome, TradingCosts, resolve_horizon,
)
from ai.dataset.quality import DatasetQualityChecker, LeakageCode, QualityReport
from ai.dataset.split import (
    ChronologicalSplit, ChronologicalSplitter, RandomSplitRefused, build_splitter,
    random_split, split_bounds,
)
from ai.dataset.versioning import (
    DATASET_SCHEMA_VERSION, FEATURE_VERSION, LABEL_VERSION, PREPROCESSING_VERSION,
    DatasetAudit, content_hash, dataset_id,
)

__all__ = [
    "BuiltDataset", "ChronologicalSplit", "ChronologicalSplitter", "DATASET_SCHEMA_VERSION",
    "DatasetAudit", "DatasetBuilder", "DatasetQualityChecker", "DatasetRow", "Direction",
    "FEATURE_GROUPS", "FEATURE_VERSION", "FeatureExtractor", "FeatureRow", "ForwardLabel",
    "HORIZONS", "LABEL_VERSION", "LabelRefusal", "LabelResult", "LabelingEngine",
    "LeakageCode", "Outcome", "PREPROCESSING_VERSION", "Partition", "QualityReport",
    "RandomSplitRefused", "TradingCosts", "build_splitter", "content_hash", "dataset_id",
    "random_split", "resolve_horizon", "split_bounds",
]
