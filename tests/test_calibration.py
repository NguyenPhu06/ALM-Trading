import numpy as np

from ai.evaluation import calibration_report


def test_calibration_report_groups_probability_and_observed_frequency():
    labels = np.asarray([0, 0, 1, 1, 2, 2])
    probabilities = np.asarray([
        [0.8, 0.1, 0.1], [0.7, 0.2, 0.1], [0.2, 0.7, 0.1],
        [0.2, 0.6, 0.2], [0.1, 0.2, 0.7], [0.1, 0.1, 0.8],
    ])
    report = calibration_report(labels, probabilities, bins=5)
    assert set(report.bins_by_class) == {"UP", "DOWN", "NEUTRAL"}
    assert all(0 <= value <= 1 for value in report.expected_calibration_error.values())
    assert report.warning == "MODEL_CONFIDENCE_IS_UNCALIBRATED"
