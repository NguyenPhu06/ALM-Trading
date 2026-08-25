from ai.training import analyze_class_imbalance


def test_class_imbalance_is_reported_and_weights_use_train_labels_only():
    report = analyze_class_imbalance([0] * 8 + [1] + [2])
    assert report.imbalanced is True
    assert report.counts == {"UP": 8, "DOWN": 1, "NEUTRAL": 1}
    assert report.class_weights["DOWN"] > report.class_weights["UP"]
