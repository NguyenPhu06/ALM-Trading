# DEMO Trade Journal (Phase 16)

Every DEMO trade records the whole chain of custody: what the market looked like,
what the features said, what the network predicted, what the strategy decided,
what risk allowed, what was requested, what the broker did, how the position
lived, and why it ended — with the versions of everything attached.

The versions are the point. A journal entry without model, strategy and feature
versions cannot be replayed or attributed, so an entry reports whether it is
actually usable as evidence rather than assuming it is.

## What one entry holds

| Field | Source |
| --- | --- |
| `market_snapshot` | price, spread, session at the moment of the decision |
| `feature_snapshot` | the feature vector, at its stated `feature_version` |
| `nn_prediction` | direction probability, expected return/MFE/MAE, confidence |
| `strategy_decision` | the engine verdict and its reason codes |
| `risk_decision` | the risk verdict and its reason codes |
| `execution_request` | the full section 6 order contract |
| `execution_result` | the gate-chain verdict |
| `mt5_result` | the broker's answer |
| `position_lifecycle` | every monitored snapshot of the open position |
| `exit_reason` | one of the eight declared reasons |
| `pnl`, `gross_pnl` | net and gross |
| `mae`, `mfe` | maximum adverse and favourable excursion, in price terms |
| `session`, `regime` | the context it traded in |
| `model_version`, `strategy_version`, `feature_version` | provenance |
| `commission`, `swap`, `slippage` | execution reality |

`complete` is false and `missing` lists the gaps whenever a mandatory section or
version is absent.

## Excursions

MAE and MFE are the two numbers a broker never hands back: they exist only if
something watched the position while it was open. `PositionMonitor` keeps them as
running high-water marks in **price terms**, which is how the observation
pipeline records them for trades that were never executed — and that is what
makes the DEMO-versus-OBSERVATION comparison possible at all.

A recovery does not erase how far a trade went against you.

## Exit reasons

Eight, one of which is always recorded. Closing without a reason raises rather
than defaulting:

`STOP_LOSS`, `TAKE_PROFIT`, `TIME_EXIT`, `STRATEGY_EXIT`,
`STRUCTURE_INVALIDATION`, `LIQUIDITY_INVALIDATION`, `RISK_EMERGENCY_EXIT`,
`MANUAL_EXIT`.

### The even-hour policy

A checkpoint is when a position is *re-evaluated*, not when it is closed. The
clock changing is not itself a reason to be flat.

- **Between checkpoints**, only the conditions that do not wait for a clock
  apply: a stop, a target, a structural invalidation, a risk emergency, a manual
  exit, an explicit strategy exit.
- **At a checkpoint**, the configured exit policy runs: higher and lower
  timeframe trend, liquidity, structure, Ichimoku, RSI, ADX, the NN, the
  strategy, risk and time remaining.
- A **counter-trend** position is held to a stricter confidence bar than a
  with-trend one (`phase_12.time_exit.counter_trend_min_confidence`).

Liquidity is deliberately weighed at the checkpoint rather than immediately: a
single liquidity read is noisier than a structural break.

## AI feedback

When a trade closes, the outcome is sent to the observation/performance pipeline
and tagged `DEMO_EXECUTION`, so a real fill is never silently mixed into a
population of hypothetical observations.

That is the whole of it. Nothing fits a model, updates a weight, promotes a
champion or schedules a training run — `retrained` is a constant `false` on every
record, and a test asserts it. `AI_ONLINE_LEARNING_ENABLED` and
`AI_AUTOMATIC_TRAINING` remain refused at startup. The network learns only
through the controlled training pipeline, as a deliberate job.

## Storage

| Table | Holds |
| --- | --- |
| `demo_trade_journal` | one row per trade, updated in place |
| `demo_position_snapshots` | monitored snapshots of open positions |
| `observation_performance` | closed-trade outcomes, tagged `DEMO_EXECUTION` |

Every payload passes through `scrub()`, so no credential can reach these tables
even if a caller puts one in a context dict.

## Reading it back

```
GET /execution/journal              the journal, newest first
GET /execution/journal?closed=true  closed trades only
GET /execution/positions            open positions with MAE/MFE
GET /execution/performance          win rate, expectancy, profit factor, drawdown
```

Performance reports its sample size with every figure and `reliable` stays false
until there is enough of it. A handful of DEMO trades is an anecdote; the honest
label for it is `INSUFFICIENT_SAMPLES`, not a number with three decimal places.
