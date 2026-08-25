from backtest.strategy_analysis import walk_forward_folds

def test_walk_forward_has_separate_ordered_windows():
    folds = walk_forward_folds(100, train=40, validation=20, test=20)
    assert folds and all(f.train[1] <= f.validation[0] and f.validation[1] <= f.test[0] for f in folds)

