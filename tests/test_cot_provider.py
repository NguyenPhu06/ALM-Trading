from datetime import date
from data_sources.cot_provider import COTProvider
def test_cot_is_delayed_and_calculates_position_statistics():
    rows=[{"report_date":date(2026,8,14),"asset":"EURO FX","noncommercial_long":100,"noncommercial_short":80,"open_interest":300},{"report_date":date(2026,8,21),"asset":"EURO FX","noncommercial_long":130,"noncommercial_short":90,"open_interest":330}]
    result=COTProvider().calculate(rows,"EURO FX");assert result.net_position==40 and result.net_change==20 and "not realtime" in result.latency_notice
