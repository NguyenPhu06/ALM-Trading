from __future__ import annotations

import logging

from config.settings import ROOT, load_yaml
from data_quality import MarketDataValidator
from data_sources.market_data import LocalCsvProvider
from database.repositories import CandleRepository
from database.session import SessionLocal
from logging_config import configure_logging


def main() -> int:
    configure_logging()
    logger = logging.getLogger(__name__)
    config = load_yaml()["market"]
    logger.info("sample market data collector start")
    try:
        provider = LocalCsvProvider(ROOT / config["sample_file"])
        candles = provider.get_candles(config["default_symbol"], config["default_timeframe"])
        validator = MarketDataValidator()
        duplicates = validator.duplicate_keys(candles)
        if duplicates:
            raise ValueError(f"sample file contains {len(duplicates)} duplicate candle keys")
        gaps = validator.detect_gaps(candles)
        if gaps:
            logger.warning("sample market data contains %d gap(s); none were filled", len(gaps))
        with SessionLocal() as session:
            inserted, skipped = CandleRepository(session).add_many(candles)
        logger.info("sample market data collector success: inserted=%d duplicates=%d", inserted, skipped)
        print(f"Sample import complete: inserted={inserted}, duplicates_skipped={skipped}, gaps={len(gaps)}")
        return 0
    except Exception as exc:
        logger.exception("sample market data collector failure: %s", exc)
        print(f"Sample import failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

