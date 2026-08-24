from __future__ import annotations

import argparse
import logging

from database.session import SessionLocal
from features.pipeline import Phase1BPipeline
from logging_config import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate Phase 1B features from database candles")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--timeframe", default="M15")
    args = parser.parse_args()
    configure_logging()
    with SessionLocal() as session:
        result = Phase1BPipeline(session).run(args.symbol, args.timeframe)
    logging.getLogger(__name__).info("Phase 1B calculation complete: %s", result)
    print(result)


if __name__ == "__main__":
    main()
