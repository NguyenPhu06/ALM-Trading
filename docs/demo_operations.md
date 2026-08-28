# DEMO Operations (Phases 16 and 17)

How to run controlled DEMO trading and its shadow validation, what to watch, and
what to do when something goes wrong.

## Before arming anything

1. Confirm the account is DEMO:
   `GET /mt5/account` — `trade_mode` must be `DEMO` (or `CONTEST`) and the server
   must match a configured DEMO pattern.
2. Confirm the posture:
   `GET /dashboard/demo-execution` — `execution_mode` should read `OBSERVATION`
   and `execution_state` `EXECUTION_BLOCKED`.
3. Confirm the limits are what you expect:
   `GET /execution/limits`.
4. Run the suite: `python -m pytest -q`.

## Arming, in order

Start with manual approval. Do not skip it — it is the mode that exists to
exercise the whole path with a person in it.

```env
DEMO_EXECUTION_MODE=DEMO_MANUAL_APPROVAL
DEMO_TRADING_ENABLED=true
MT5_EXECUTION_ENABLED=true
MT5_READ_ONLY=false
EXECUTION_KILL_SWITCH=false
```

Restart the API. `GET /execution/mode` should now report
`requires_human_approval: true` and `sends_orders: true`.

Then, and only after manual approval has produced a fill, a reconciliation and a
journal entry you are satisfied with:

```env
DEMO_EXECUTION_MODE=DEMO_AUTOMATED
DEMO_AUTOMATED_EXECUTION_ENABLED=true
```

`REAL_ACCOUNT_EXECUTION` and `LIVE_TRADING_ENABLED` stay `false`. Both are
refused at startup, so a mistake here stops the process rather than arming
something quietly.

## One order, manually approved

```bash
curl -X POST localhost:8000/execution/demo/propose -H 'content-type: application/json' -d '{
  "symbol": "EURUSD", "side": "BUY", "signal_id": "sig-2026-08-27-001",
  "entry_price": 1.10024, "stop_loss": 1.09500, "take_profit": 1.11000,
  "strategy_id": "smc", "strategy_version": "phase6.strategy.v1",
  "model_version": "model-1", "feature_version": "features_v1"
}'
```

There is no `volume` field. The size is derived from equity, risk and the stop
distance; a caller states the stop, not the lot size.

The response carries the state, the gate verdict and the derived size. If it is
`PROPOSED`, approve it:

```bash
curl -X POST localhost:8000/execution/proposals/<request_id>/approve \
  -H 'content-type: application/json' \
  -d '{"approved_by": "your name", "reason": "verified demo account"}'
```

An approval names a person and states a reason, and it expires — a proposal older
than `phase_16.proposal_ttl_seconds` is cancelled rather than approved, because
an approval given after the market moved is not a current approval.

To decline: `POST /execution/proposals/<id>/reject` with a reason.

## What to watch

`GET /dashboard/demo-execution`, or the CONTROLLED DEMO EXECUTION panel in the
Command Center, shows in one place:

account · broker · server · DEMO status · execution mode · kill switch ·
daily PnL · daily loss · drawdown · open positions · exposure · margin ·
risk per trade · current strategy · champion model · NN confidence · signal ·
execution decision · blocked reason · last order · last fill · last reconciliation.

Also useful:

```
GET /execution/daily-risk    the trading day, its budget and 30 days of history
GET /execution/positions     open positions with MAE, MFE and stop distances
GET /execution/journal       the trade journal
GET /execution/comparison    paper vs DEMO: spread, slippage, commission, swap
GET /execution/performance   win rate, expectancy, profit factor, rejection rate
GET /execution/emergency     emergency events
GET /execution/audit         the per-stage audit trail
```

## Stopping

Immediately, from the API:

```bash
curl -X POST localhost:8000/execution/kill-switch/engage \
  -H 'content-type: application/json' -d '{"reason": "operator stopped trading"}'
```

Blocking is always allowed. New orders stop at once; open positions are not
closed. Releasing needs a stated reason and is never automatic.

From configuration, for a restart-proof stop: set `EXECUTION_KILL_SWITCH=true`,
or `DEMO_EXECUTION_MODE=OBSERVATION`, or `MT5_EXECUTION_ENABLED=false`. Any one
of them blocks every order.

## When something goes wrong

| Symptom | Where to look | What it usually means |
| --- | --- | --- |
| every order blocked | `blocked_by` on the dashboard | a flag is closed, or the switch is engaged |
| `ACCOUNT_IS_REAL` | `GET /mt5/account` | the terminal is logged into the wrong account — stop |
| `ACCOUNT_UNKNOWN` | terminal permissions | AutoTrading off, or the API barred |
| `DATA_STALE` / `DATA_QUALITY_FAILED` | `GET /mt5/data-quality` | the feed is behind or broken |
| `MAX_DAILY_LOSS_EXCEEDED` | `GET /execution/daily-risk` | the day's budget is spent; it resets at the boundary |
| `DUPLICATE_EXECUTION_REQUEST` | `GET /execution/audit` | the same signal was submitted twice |
| `BELOW_MINIMUM_VOLUME` | the sizing block in the response | the risk budget does not buy one lot |
| kill switch engaged unexpectedly | `GET /execution/emergency` | an emergency condition fired |

A blocked order is the system working. Before relaxing a limit because a trade
was refused, read the reason — the gate chain reports every failing check at
once, so the first one is rarely the only one.

## Shadow validation (Phase 17)

Shadow recording is on by default and sends nothing. Every DEMO candidate — taken
or blocked — produces a shadow record, so the population the gates removed stays
visible.

To run the pipeline with no broker at all, set `DEMO_EXECUTION_MODE=SHADOW`. It
needs none of the broker flags open, because it reaches no broker.

```
GET /dashboard/validation            shadow and DEMO side by side
GET /validation/comparison           where the difference came from
GET /validation/windows              24h/3d/7d/14d/30d/60d/90d
GET /validation/gates                the eight performance gates
GET /validation/eligibility          DEMO_AUTOMATION_ELIGIBLE (advisory only)
GET /validation/review/daily         today's operational report
GET /validation/review/weekly        the research report
```

Read `reliable` before reading the numbers. Below the sample floor they are there
to be watched accumulating, not acted on.

## The circuit breaker

Separate from the kill switch, and deliberately so: releasing the switch must not
be a way around the recovery checklist.

```
GET /validation/circuit-breaker      state, triggers and what recovery requires
```

When it is open, new orders are blocked and open positions are untouched.
Recovering takes four things — a health check, a risk check, account validation
and a named human — and then, separately, releasing the kill switch:

```bash
curl -X POST localhost:8000/validation/circuit-breaker/reset \
  -H 'content-type: application/json' -d '{
    "health_check": true, "risk_check": true, "account_validation": true,
    "approved_by": "your name", "reason": "verified healthy after recovery"
  }'

curl -X POST localhost:8000/execution/kill-switch/release \
  -H 'content-type: application/json' -d '{"reason": "verified healthy after recovery"}'
```

`DEMO_AUTOMATED` never resumes by itself. There is no timeout and no retry
counter, so waiting achieves nothing.

## Before considering automation

`GET /validation/eligibility` computes `DEMO_AUTOMATION_ELIGIBLE` from ten checks
plus the performance gates. Being eligible **changes nothing**: arming automation
is still a configuration change plus a restart, and `DEMO_AUTOMATION_APPROVED`
records the human decision without being sufficient on its own.

If a check reads `unknown`, that is not a pass — it means the input was never
measured, and the honest response is to measure it.

## Daily routine

1. Check the trading day rolled over: `GET /execution/daily-risk`.
2. Check the account is still DEMO and still connected.
3. Read yesterday's journal and comparison. The comparison is the honest measure
   of how much of the modelled edge execution reality is taking.
4. Keep the sample size in mind. Below 30 closed DEMO trades, every performance
   figure reports `reliable: false`, and it means it.
5. Read `GET /validation/review/daily`, then compare shadow with DEMO. The gap is
   the part of the modelled edge that execution reality is taking.

## Migration

```bash
alembic upgrade head    # 20260830_0019 and 20260831_0020
```

Phase 16 adds `demo_execution_proposals`, `demo_trade_journal`, `demo_daily_risk`,
`demo_position_snapshots`, `demo_paper_comparisons` and `demo_emergency_events`.

Phase 17 adds `shadow_signals`, `shadow_outcomes`, `demo_comparisons`,
`execution_quality`, `validation_runs`, `performance_gates` and
`circuit_breaker_events`.

None of the thirteen has a credential column.
