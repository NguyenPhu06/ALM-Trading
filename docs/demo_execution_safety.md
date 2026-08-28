# DEMO Execution Safety (Phase 16)

The one claim this document exists to support: **LIVE trading is impossible, and
a REAL account cannot execute.** Everything below is how that is enforced rather
than merely intended.

## Four independent refusals of a REAL account

A REAL account is refused in four places that do not depend on one another:

1. **Configuration.** `REAL_ACCOUNT_EXECUTION=true` and
   `LIVE_TRADING_ENABLED=true` are both refused at startup. The process does not
   run; the flag is not corrected.
2. **The account gate.** `DemoAccountValidator` returns `INVALID_ACCOUNT` with
   `ACCOUNT_IS_REAL`, and that verdict outranks every other — a REAL account
   reports as REAL even when the terminal has already disconnected.
3. **The Phase 11 guard.** `ExecutionGuard` refuses with `ACCOUNT_IS_REAL` and
   `SERVER_NOT_DEMO`.
4. **The execution client.** `MT5ExecutionClient` re-reads the account
   immediately before transmitting and refuses there too, so an approval that
   was valid a moment ago cannot be used against an account that has changed.

`UNKNOWN` is refused everywhere `REAL` is. Unknown is never treated as safe.

## Fail-closed by construction

Every gate that cannot evaluate its input blocks:

| Missing input | Verdict |
| --- | --- |
| no account | `ACCOUNT_NOT_VERIFIED_DEMO` |
| unverifiable trade mode | `ACCOUNT_UNKNOWN` |
| no data-quality verdict | `DATA_QUALITY_UNKNOWN` |
| no quote | `SPREAD_UNAVAILABLE`, `QUOTE_UNAVAILABLE` |
| no risk verdict | `RISK_ENGINE_UNAVAILABLE` |
| no trading-day state | `DAILY_RISK_STATE_UNAVAILABLE` |
| no strategy status | `STRATEGY_UNKNOWN` |
| unreadable idempotency store | `IDEMPOTENCY_STORE_UNAVAILABLE` |

The single deliberate exception is `ModelConfidenceGate`. The neural network is
advisory, so the absence of a prediction is not by itself a refusal unless
`phase_16.model.require_prediction` says it is. A *failed* model still blocks,
and a prediction below the configured confidence still blocks. The NN can refuse;
it can never approve past another gate.

## The kill switch

`EXECUTION_KILL_SWITCH=true` ships engaged, so execution ships blocked. The
switch:

- blocks every new entry and every exposure-increasing DCA, immediately;
- is reachable from the API, the dashboard, configuration and the emergency path;
- never releases itself — no timeout, no retry counter, no automatic recovery;
- requires a stated reason to release;
- **does not close open positions**, unless that is explicitly configured and
  separately authorised.

Engaging is always permitted, including when already engaged.

## Emergency shutdown

Eleven conditions engage the switch automatically (section 17): daily loss limit,
drawdown limit, too many execution errors, an unstable MT5 connection, stale
data, a reconciliation failure, an unexpected account type, an unexpected
broker or server, a spread above its limit, a model failure and a risk-engine
failure.

"Shut down" means new orders are blocked. Open positions are deliberately left
alone: liquidating them would be a second, larger and less reversible decision
taken by the same code that has just discovered it cannot trust its own inputs —
the connection may be unstable, the data stale, the account not what it claimed.
`demo_emergency_events.positions_closed` is a column that is always false, so the
invariant is visible in the data and not only in prose.

Recovery is never automatic. An operator releases the switch with a reason.

## What has no code path

- No live broker adapter, and no second adapter of any kind.
- No endpoint that changes the execution mode, opens a flag or arms execution.
  Arming is a configuration change; API access alone cannot do it.
- No automatic position closing, hedging, reversing or martingale sizing.
- No training, fitting or promotion anywhere on the execution path.
- No route matching `live`, `broker`, `exness` or `metatrader`; a test asserts it.

## The safety tests

`tests/test_real_account_block.py`, `tests/test_demo_account_guard.py`,
`tests/test_demo_execution_mode.py`, `tests/test_kill_switch.py`,
`tests/test_emergency_shutdown.py`, `tests/test_order_idempotency.py`,
`tests/test_order_validation.py`, `tests/test_risk_limits.py`,
`tests/test_dca_execution_guard.py` and `tests/test_phase9_safety_invariants.py`
cover the section 33 list:

| Condition | Result |
| --- | --- |
| REAL account | BLOCK |
| UNKNOWN account | BLOCK |
| kill switch engaged | BLOCK |
| execution disabled | BLOCK |
| stale data | BLOCK |
| bad data | BLOCK |
| risk failure | BLOCK |
| spread too high | BLOCK |
| drawdown exceeded | BLOCK |
| daily loss exceeded | BLOCK |
| duplicate signal | BLOCK |
| reconciliation failure | SAFE SHUTDOWN |
| NN failure | BLOCK |
| strategy failure | BLOCK |

## Test environment

Every test runs against `FakeExecutionModule`, a deterministic stand-in driven
through the real `MT5Connection`, `MT5ReadOnlyClient` and `MT5ExecutionClient`.
The tests therefore exercise the production code paths rather than a parallel
implementation, and no test depends on a broker.

Real MT5 integration tests stay separate in `tests/test_mt5_integration.py` and
skip when the package or terminal is unavailable.
