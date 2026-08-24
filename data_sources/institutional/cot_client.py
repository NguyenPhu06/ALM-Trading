from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import load_yaml
from data_sources.institutional.cot_normalizer import normalize_cot_report
from data_sources.institutional.cot_parser import parse_cot_payload, validate_cot_columns
from database.repositories import COTRepository


logger = logging.getLogger(__name__)


class COTClient:
    def __init__(self, url: str | None = None, *, limit: int | None = None, timeout: float | None = None):
        config = load_yaml()["cot"]
        self.url = url or config["url"]
        self.limit = limit or int(config.get("limit", 5000))
        self.timeout = timeout or float(config.get("timeout_seconds", 30))

    def download(self) -> tuple[bytes, str]:
        logger.info("COT collector start")
        headers = {"Accept": "application/json,text/csv,text/plain", "User-Agent": "ALM-Trading/1A CFTC-COT-Collector"}
        if "/api/v3/" in self.url:
            request_body = {
                "query": "SELECT * ORDER BY `report_date_as_yyyy_mm_dd` DESC",
                "page": {"pageNumber": 1, "pageSize": self.limit},
                "includeSynthetic": False,
            }
            response = httpx.post(self.url, json=request_body, timeout=self.timeout, follow_redirects=True, headers=headers)
        else:
            response = httpx.get(self.url, timeout=self.timeout, follow_redirects=True, headers=headers)
        response.raise_for_status()
        logger.info("COT download success: %d bytes", len(response.content))
        return response.content, response.headers.get("content-type", "application/json")

    def fetch_normalized(self) -> tuple[list[dict[str, Any]], list[str]]:
        content, content_type = self.download()
        raw_rows = parse_cot_payload(content, content_type)
        validate_cot_columns(raw_rows)
        valid: list[dict[str, Any]] = []
        failures: list[str] = []
        for index, row in enumerate(raw_rows):
            try:
                valid.append(normalize_cot_report(row))
            except Exception as exc:
                failures.append(f"row {index}: {exc}")
                logger.warning("COT data validation failure at row %d: %s", index, exc)
        return valid, failures


class COTCollector:
    def __init__(self, repository: COTRepository, client: COTClient | None = None):
        self.repository = repository
        self.client = client or COTClient()

    def run(self) -> dict[str, Any]:
        rows, failures = self.client.fetch_normalized()
        inserted, updated = self.repository.upsert_many(rows)
        logger.info("COT update success: inserted=%d updated=%d failures=%d", inserted, updated, len(failures))
        return {"downloaded": len(rows) + len(failures), "inserted": inserted, "updated": updated, "failures": failures}
