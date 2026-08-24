from __future__ import annotations

import logging

from config.settings import load_yaml
from data_sources.institutional import COTCollector
from database.repositories import COTRepository
from database.session import SessionLocal
from logging_config import configure_logging


def main() -> int:
    configure_logging()
    logger = logging.getLogger(__name__)
    if not load_yaml().get("cot", {}).get("enabled", True):
        print("COT update skipped: collector disabled")
        return 0
    try:
        with SessionLocal() as session:
            result = COTCollector(COTRepository(session)).run()
        print(
            "COT update complete: "
            f"downloaded={result['downloaded']}, inserted={result['inserted']}, "
            f"updated={result['updated']}, failures={len(result['failures'])}"
        )
        return 0
    except Exception as exc:
        logger.exception("COT collector failure: %s", exc)
        print(f"COT source unavailable or update failed; system remains available: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

