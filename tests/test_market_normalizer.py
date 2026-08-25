from data_sources.normalizer import QuoteNormalizer
from tests.phase7_helpers import NOW
def test_quote_normalizer_calculates_microstructure_without_order_book():
    value=QuoteNormalizer().normalize({"timestamp":NOW,"symbol":"EUR/USD","bid":"1.1","ask":"1.1002","tick_volume":"12"},source="licensed")
    assert value["spread"]>0 and value["mid_price"]>1.1
    assert "order_book" not in value
