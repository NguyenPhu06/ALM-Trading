from paper import validate_model_prediction
def test_invalid_or_nan_model_never_falls_back_to_trade():
    assert not validate_model_prediction(None);assert not validate_model_prediction({"prob_up":float("nan"),"prob_down":0,"prob_neutral":1})
