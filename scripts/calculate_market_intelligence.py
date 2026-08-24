from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.session import SessionLocal
from features.intelligence import MarketIntelligenceService
from logging_config import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate and persist causal Phase 3 market intelligence")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
    if as_of and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    configure_logging()
    with SessionLocal() as session:
        service = MarketIntelligenceService(session)
        snapshot = service.calculate(args.symbol, as_of=as_of)
        rows = service.persist(snapshot)
    print({"symbol": snapshot.symbol, "timestamp": snapshot.timestamp.isoformat(), "bias": snapshot.bias.value, "trade_state": snapshot.trade_state, "rows": rows})


if __name__ == "__main__":
    main()
