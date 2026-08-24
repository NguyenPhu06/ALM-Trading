from __future__ import annotations

import json

import pytest

from data_sources.institutional.cot_normalizer import normalize_cot_report
from data_sources.institutional.cot_parser import COTParseError, parse_cot_payload, validate_cot_columns


def sample_row() -> dict:
    return {
        "report_date_as_yyyy_mm_dd": "2026-08-18T00:00:00.000",
        "market_and_exchange_names": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
        "contract_market_name": "EURO FX", "open_interest_all": "1000",
        "dealer_positions_long_all": "100", "dealer_positions_short_all": "200",
        "dealer_positions_spread_all": "10", "asset_mgr_positions_long_all": "300",
        "asset_mgr_positions_short_all": "150", "asset_mgr_positions_spread_all": "20",
        "lev_money_positions_long_all": "120", "lev_money_positions_short_all": "250",
        "lev_money_positions_spread_all": "15", "other_rept_positions_long_all": "50",
        "other_rept_positions_short_all": "60", "other_rept_positions_spread_all": "5",
        "nonrept_positions_long_all": "80", "nonrept_positions_short_all": "70",
    }


def test_parse_validate_normalize_preserves_raw():
    content = json.dumps([sample_row()]).encode()
    rows = parse_cot_payload(content, "application/json")
    validate_cot_columns(rows)
    normalized = normalize_cot_report(rows[0])
    assert normalized["dealer_long"] == 100
    assert normalized["asset_manager_long"] == 300
    assert normalized["leveraged_money_short"] == 250
    assert normalized["raw_data_json"] == sample_row()


def test_missing_columns_rejected():
    with pytest.raises(COTParseError):
        validate_cot_columns([{"report_date": "2026-01-01"}])


def test_headerless_official_tff_format():
    values = [
        'EURO FX - CME', '260818', '08/18/2026', '099741', 'CME', '0', '099',
        '1000', '100', '200', '10', '300', '150', '20', '120', '250', '15',
        '50', '60', '5', '570', '685', '80', '70', 'unmodeled-value',
    ]
    content = (",".join(f'"{value}"' for value in values) + "\n").encode()
    rows = parse_cot_payload(content, "text/plain")
    validate_cot_columns(rows)
    normalized = normalize_cot_report(rows[0])
    assert normalized["contract"] == "099741"
    assert normalized["raw_data_json"]["unmodeled_field_25"] == "unmodeled-value"

