from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_sources.ingestion import MarketDataIngestionService
from data_sources.providers import create_provider
from database.session import SessionLocal
from logging_config import configure_logging


def parse_date(value: str, *, end: bool = False) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end and len(value) == 10:
        parsed = datetime.combine(parsed.date(), time.max, tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import authorized real FX market data")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    configure_logging()
    provider = create_provider(args.provider)
    try:
        with SessionLocal() as session:
            report = MarketDataIngestionService(session, provider).import_historical(
                args.symbol, args.timeframe, parse_date(args.start), parse_date(args.end, end=True),
            )
        print(report)
    finally:
        provider.disconnect()


if __name__ == "__main__":
    main()
