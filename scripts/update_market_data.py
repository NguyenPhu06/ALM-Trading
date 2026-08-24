from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_sources.ingestion import MarketDataIngestionService
from data_sources.providers import create_provider
from database.session import SessionLocal
from logging_config import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Incrementally update real FX market data")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()
    configure_logging()
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00")) if args.end else datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    provider = create_provider(args.provider)
    try:
        with SessionLocal() as session:
            report = MarketDataIngestionService(session, provider).update_incremental(
                args.symbol, args.timeframe, end=end.astimezone(timezone.utc),
            )
        print(report)
    finally:
        provider.disconnect()


if __name__ == "__main__":
    main()
