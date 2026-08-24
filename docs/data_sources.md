# Data sources and semantics

ALM distinguishes observations by timing and derivation so later research cannot accidentally treat slow or inferred values as live facts.

| Source/data | Class | Meaning |
|---|---|---|
| TradingView webhook | REAL-TIME event transport | Alert/event data created by configured TradingView logic; it is not a complete tick feed. |
| Market ticks (future adapter) | REAL-TIME | Licensed broker/exchange observations when implemented. |
| CFTC TFF COT | PERIODIC | Institutional Positioning reported weekly, normally reflecting Tuesday positions and published later. |
| Local CSV candles | HISTORICAL | Reproducible sample/imported OHLCV market data. |
| Broker/MT5/futures/exchange candles (future) | REAL-TIME or HISTORICAL | Classification depends on the licensed endpoint and request mode. |
| News (future) | REAL-TIME or HISTORICAL | Timestamped provider content; source latency must be recorded. |
| Open interest and volume (future) | PERIODIC or REAL-TIME | Provider-specific observations; semantics and latency must be documented per adapter. |
| Liquidity/structure events | INFERRED | ALM-derived market-structure estimates, not actual institutional orders. |
| Institutional pressure | INFERRED | Composite estimate from available public or licensed inputs; absent inputs remain `NULL`. |

## CFTC COT limitations

COT is periodic positioning data, not realtime institutional order flow and not “real-time whale orders.” The Phase 1A collector uses the official CFTC current TFF Futures Only feed because its Dealer, Asset Manager, Leveraged Money, Other Reportables, and Non-Reportables classifications match the database model. The configurable parser accepts the official headerless weekly text format as well as CSV/JSON exports. Raw source rows are retained. Publication delay, revisions, market-to-FX symbol mapping, and aggregation must be respected by features to prevent look-ahead bias.

ALM estimates institutional positioning or pressure using available public or licensed data. It cannot know which specific fund is buying a particular FX pair.

## Webhook authentication

The preferred mechanism is the `X-TradingView-Secret` header and constant-time comparison. If an alert setup cannot send headers, a `secret` JSON field is accepted when enabled. That fallback exposes the credential to more systems involved in payload construction; use HTTPS, a long random value, rotation, and restricted ingress. The `secret` field is removed before raw-payload audit storage and never logged.

The CFTC URL is configurable in `config/settings.yaml`; a future switch to the SODA API should source any `X-App-Token` from an environment secret rather than embedding credentials in configuration.

## Future adapters

`MarketDataProvider` defines candle/latest reads for Local CSV, future MT5, broker, and exchange implementations. `future_interfaces.py` defines read-only contracts for futures, news, open interest, volume, and order-book providers. Phase 1A contains no live connection and no order method. Each future adapter must perform raw → normalize → validate → repository, identify source and license, use UTC, preserve relevant raw data, expose latency, and reject malformed observations.
