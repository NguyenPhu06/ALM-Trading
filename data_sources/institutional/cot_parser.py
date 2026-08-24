from __future__ import annotations

import csv
import io
import json
from typing import Any


class COTParseError(ValueError):
    pass


TFF_POSITIONAL_COLUMNS = [
    "market_and_exchange_names", "as_of_date_in_form_yymmdd", "report_date_as_mm_dd_yyyy",
    "cftc_contract_market_code", "cftc_market_code", "cftc_region_code", "cftc_commodity_code",
    "open_interest_all", "dealer_positions_long_all", "dealer_positions_short_all",
    "dealer_positions_spread_all", "asset_mgr_positions_long_all", "asset_mgr_positions_short_all",
    "asset_mgr_positions_spread_all", "lev_money_positions_long_all", "lev_money_positions_short_all",
    "lev_money_positions_spread_all", "other_rept_positions_long_all", "other_rept_positions_short_all",
    "other_rept_positions_spread_all", "tot_rept_positions_long_all", "tot_rept_positions_short_all",
    "nonrept_positions_long_all", "nonrept_positions_short_all",
]


def parse_cot_payload(content: bytes, content_type: str = "application/json") -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig")
    try:
        if "json" in content_type.lower() or text.lstrip().startswith(("[", "{")):
            payload = json.loads(text)
            if isinstance(payload, dict):
                payload = payload.get("data", [payload])
            if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
                raise COTParseError("COT JSON must contain a list of objects")
            return payload
        parsed_rows = list(csv.reader(io.StringIO(text)))
        if not parsed_rows:
            raise COTParseError("COT CSV contains no records")
        normalized_header = {column.strip().lower() for column in parsed_rows[0]}
        if normalized_header.intersection({"market_and_exchange_names", "report_date_as_yyyy_mm_dd"}):
            return list(csv.DictReader(io.StringIO(text)))
        # The official current FinFutWk.txt feed is headerless and follows the
        # published TFF long-format variable order. Preserve every trailing
        # value for audit even when Phase 1A does not model that field yet.
        rows: list[dict[str, Any]] = []
        for values in parsed_rows:
            names = TFF_POSITIONAL_COLUMNS + [f"unmodeled_field_{index}" for index in range(len(TFF_POSITIONAL_COLUMNS) + 1, len(values) + 1)]
            rows.append(dict(zip(names, values)))
        return rows
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        raise COTParseError(f"unable to parse COT payload: {exc}") from exc


def validate_cot_columns(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise COTParseError("COT response contains no records")
    keys = {str(key).lower() for key in rows[0]}
    required_groups = {
        "report date": {"report_date_as_yyyy_mm_dd", "report_date_as_mm_dd_yyyy", "as_of_date_in_form_yymmdd", "report_date"},
        "market": {"market_and_exchange_names", "market"},
        "contract": {"contract_market_name", "cftc_contract_market_code", "cftc_contract_market_code_quotes", "contract"},
        "open interest": {"open_interest_all", "open_interest"},
        "dealer long": {"dealer_positions_long_all", "dealer_long"},
        "asset manager long": {"asset_mgr_positions_long_all", "asset_mgr_positions_long", "asset_manager_long"},
        "leveraged money long": {"lev_money_positions_long_all", "lev_money_positions_long", "leveraged_money_long"},
    }
    missing = [label for label, aliases in required_groups.items() if not keys.intersection(aliases)]
    if missing:
        sample = ", ".join(sorted(keys)[:12])
        raise COTParseError(f"COT response missing required columns: {', '.join(missing)}; received: {sample}")
