from datetime import datetime, timezone
from decimal import Decimal
NOW=datetime(2026,8,25,10,tzinfo=timezone.utc)
def candle(timestamp=NOW,timeframe="M5",price="1.10",source="mock"):
    p=Decimal(price);return {"timestamp":timestamp,"symbol":"EURUSD","timeframe":timeframe,"open":p,"high":p+Decimal(".001"),"low":p-Decimal(".001"),"close":p+Decimal(".0002"),"volume":Decimal("10"),"tick_volume":Decimal("20"),"spread":Decimal(".0001"),"is_closed":True,"source":source,"provider":source,"provider_timestamp":timestamp}
def mtf_rows():return [candle(timeframe=tf) for tf in ("D1","H4","H1","M30","M15","M5")]
def quote():return {"timestamp":NOW,"symbol":"EURUSD","bid":1.1,"ask":1.1002,"mid_price":1.1001,"spread":.0002,"spread_percent":.0002/1.1001,"source":"mock"}
