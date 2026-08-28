# DEMO Validation (Phase 17)

Phase 17 answers one question: **does the current Champion Strategy and Neural
Network produce stable forward performance after real market execution costs?**

The honest answer is expected to be `INSUFFICIENT_DATA` for a long time, and
everything in this phase is built so that it says so rather than something more
encouraging.

## Four populations, kept apart

| | Sends orders | Cost model | What it tells you |
| --- | --- | --- | --- |
| **SHADOW** | no | modelled | what the decision would have produced |
| **PAPER** | no | simulated | what the simulation engine produced |
| **DEMO** | yes (gated) | real | what a broker actually produced |
| **LIVE** | **impossible** | — | — |

LIVE is not a mode that is switched off; it is a mode that does not exist.
`LIVE_TRADING_ENABLED=true` and `REAL_ACCOUNT_EXECUTION=true` are both refused at
startup, and there is no live adapter in the repository.

## What Phase 17 adds

| Section | Module | What it produces |
| --- | --- | --- |
| 2–4 | `validation/shadow.py` | shadow signals and outcomes |
| 5–6 | `validation/comparison.py` | SHADOW vs DEMO, attributed |
| 7–9 | `validation/quality.py` | execution, signal and model quality |
| 10–12 | `validation/segments.py` | regime, session, timeframe |
| 13 | `validation/even_hour.py` | checkpoint records and their verdict |
| 14 | `validation/dca_validation.py` | DCA level by level, vs NO_DCA |
| 15–16 | `validation/windows.py` | rolling windows and sample floors |
| 17–18 | `validation/gates.py` | performance gates, automation eligibility |
| 19–20 | `validation/reviews.py` | daily and weekly reports |
| 21 | `validation/anomaly.py` | nine change detectors |
| 22–23 | `validation/circuit_breaker.py` | the breaker and its recovery |

Nothing in `validation/` holds an execution client, a guard or a transport.
Two tests parse the package to prove it and to prove no module writes a setting.

## Even-hour validation (section 13)

Every configured checkpoint records what it saw: trend, liquidity, structure,
Ichimoku, RSI, ADX, the NN, the strategy, risk, the position state, the decision
and its reason. A checkpoint missing any of them is recorded as **incomplete**
rather than quietly scored.

Then the harder question: did those decisions improve outcomes? Each scored
checkpoint carries what happened and the counterfactual of having held, and the
verdict is one of `IMPROVES`, `NOT_PROVEN`, `HARMFUL`, `INSUFFICIENT_DATA`.

**The default is NOT_PROVEN.** The spec says "Do not assume they do", and a
positive mean inside the noise floor does not overturn it. Exits, holds and
counter-trend checkpoints are scored separately, because a policy that improves
exits while hurting holds is not an improvement.

## DCA validation (section 14)

DCA stays disabled by default and this phase does not change that. If a DCA
population exists it is measured level by level — initial entry, DCA 1, DCA 2,
DCA 3 — with each level's own volume, exposure, risk, MAE and MFE, plus the
aggregate exposure and risk.

Against NO_DCA, the decisive rule is implemented literally:

> **Reject DCA if the increased win rate is achieved only through materially
> increased tail risk.**

`tail_loss` is the mean of the worst 5% of outcomes — the number DCA hides. A
worse tail is rejected even when expectancy improved, and when the win rate also
rose the verdict names *why*: `WIN_RATE_BOUGHT_WITH_TAIL_RISK`. `NO_DCA` is the
default recommendation, and a favourable finding is not a switch.

## Daily and weekly reviews (sections 19–20)

The **daily** review is operational: signals, trades, wins, losses, net PnL,
drawdown, MAE, MFE, spread, slippage, execution/model/strategy failures, the
regime and session mix, the edge status, and the state of both stop mechanisms.
An empty day says `NO_TRADES` rather than reporting a confident-looking zero.

The **weekly** review is research: champion performance, strategy comparison, NN
and indicator contribution, DCA contribution, the three segment cuts, execution
quality, model drift and the edge status. It states in the payload that it is
forward observation and not a backtest.

## Database

Seven tables, added by migration `20260831_0020`:

`shadow_signals` · `shadow_outcomes` · `demo_comparisons` · `execution_quality` ·
`validation_runs` · `performance_gates` · `circuit_breaker_events`

Three columns are written as pinned constants rather than copied from a record,
so an upstream bug cannot record the opposite:

- `shadow_signals.orders_sent` — always 0
- `circuit_breaker_events.positions_closed` — always False
- `performance_gates.enabled_execution` — always False

No table has a credential column; every payload passes through `scrub()`.

## Endpoints

```
GET  /validation/shadow              GET  /validation/gates
GET  /validation/shadow/outcomes     GET  /validation/eligibility
GET  /validation/comparison          GET  /validation/circuit-breaker
GET  /validation/execution-quality   POST /validation/circuit-breaker/reset
GET  /validation/signal-quality      GET  /validation/review/daily
GET  /validation/segments            GET  /validation/review/weekly
GET  /validation/windows             GET  /dashboard/validation
```

One write, and it only closes the circuit breaker after a four-item checklist.

## Reading the results honestly

- `reliable: false` means it. Below the sample floor, the numbers are printed so
  you can watch them accumulate, not so you can act on them.
- `INSUFFICIENT_DATA` is not a failure of the system; it is the correct answer
  until there is evidence.
- An edge in one window and not the others is `UNSTABLE_EDGE`.
- A segment cell below its floor is not evidence, however good it looks.

**Still NO STATISTICAL EDGE DETECTED.**

## See also

- [shadow trading](shadow_trading.md) · [shadow vs demo](shadow_vs_demo.md)
- [execution quality](execution_quality.md) · [performance gates](performance_gates.md)
- [circuit breaker](circuit_breaker.md) · [demo operations](demo_operations.md)
