from __future__ import annotations

from datetime import date, datetime
from typing import Any

from data_sources.institutional.cot_parser import COTParseError


def _lookup(raw: dict[str, Any], *names: str, required: bool = False) -> Any:
    lowered = {str(key).lower(): value for key, value in raw.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    if required:
        raise COTParseError(f"missing required COT value: {names[0]}")
    return None


def _integer(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        raise COTParseError(f"invalid integer in COT field {field}") from None


def _date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%y%m%d"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
    raise COTParseError("invalid COT report date")


def normalize_cot_report(raw: dict[str, Any], *, source: str = "cftc_tff") -> dict[str, Any]:
    get = lambda *names, required=False: _lookup(raw, *names, required=required)
    result = {
        "report_date": _date(get("report_date_as_yyyy_mm_dd", "report_date_as_mm_dd_yyyy", "as_of_date_in_form_yymmdd", "report_date", required=True)),
        "market": str(get("market_and_exchange_names", "market", required=True)).strip(),
        "contract": str(get("contract_market_name", "cftc_contract_market_code", "cftc_contract_market_code_quotes", "contract", required=True)).strip(),
        "source": source,
        "dealer_long": _integer(get("dealer_positions_long_all", "dealer_long"), "dealer_long"),
        "dealer_short": _integer(get("dealer_positions_short_all", "dealer_short"), "dealer_short"),
        "dealer_spread": _integer(get("dealer_positions_spread_all", "dealer_spread"), "dealer_spread"),
        "asset_manager_long": _integer(get("asset_mgr_positions_long_all", "asset_mgr_positions_long", "asset_manager_long"), "asset_manager_long"),
        "asset_manager_short": _integer(get("asset_mgr_positions_short_all", "asset_mgr_positions_short", "asset_manager_short"), "asset_manager_short"),
        "asset_manager_spread": _integer(get("asset_mgr_positions_spread_all", "asset_mgr_positions_spread", "asset_manager_spread"), "asset_manager_spread"),
        "leveraged_money_long": _integer(get("lev_money_positions_long_all", "lev_money_positions_long", "leveraged_money_long"), "leveraged_money_long"),
        "leveraged_money_short": _integer(get("lev_money_positions_short_all", "lev_money_positions_short", "leveraged_money_short"), "leveraged_money_short"),
        "leveraged_money_spread": _integer(get("lev_money_positions_spread_all", "lev_money_positions_spread", "leveraged_money_spread"), "leveraged_money_spread"),
        "other_reportables_long": _integer(get("other_rept_positions_long_all", "other_rept_positions_long", "other_reportables_long"), "other_reportables_long"),
        "other_reportables_short": _integer(get("other_rept_positions_short_all", "other_rept_positions_short", "other_reportables_short"), "other_reportables_short"),
        "other_reportables_spread": _integer(get("other_rept_positions_spread_all", "other_rept_positions_spread", "other_reportables_spread"), "other_reportables_spread"),
        "non_reportables_long": _integer(get("nonrept_positions_long_all", "nonrept_positions_long", "non_reportables_long"), "non_reportables_long"),
        "non_reportables_short": _integer(get("nonrept_positions_short_all", "nonrept_positions_short", "non_reportables_short"), "non_reportables_short"),
        "non_reportables_spread": _integer(get("nonrept_positions_spread_all", "nonrept_positions_spread", "non_reportables_spread"), "non_reportables_spread"),
        "open_interest": _integer(get("open_interest_all", "open_interest"), "open_interest"),
        "raw_data_json": dict(raw),
    }
    if not result["market"] or not result["contract"]:
        raise COTParseError("COT market and contract cannot be blank")
    return result
