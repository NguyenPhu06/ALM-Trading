"""Statistical edge evaluation over forward-observation evidence."""
from ai.edge.edge_detector import (
    REQUIRED_BASELINES,
    EdgeDetector,
    EdgeReport,
    EdgeVerdict,
    SegmentConsistency,
)
from ai.edge.evidence import (
    EVIDENCE_STRENGTH,
    PRIMARY_EVIDENCE,
    RETROSPECTIVE,
    EvidenceRefused,
    EvidenceSource,
    require_forward,
    stronger_than,
)

__all__ = [
    "EdgeDetector", "EdgeReport", "EdgeVerdict", "SegmentConsistency", "REQUIRED_BASELINES",
    "EvidenceSource", "EvidenceRefused", "require_forward", "stronger_than",
    "EVIDENCE_STRENGTH", "PRIMARY_EVIDENCE", "RETROSPECTIVE",
]
