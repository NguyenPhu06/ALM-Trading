# Execution Quality (Phase 17)

Three questions, reported side by side on purpose:

- **Execution quality** — did the broker do what we asked, and at what cost?
- **Signal quality** — were the decisions any good?
- **Model quality** — was the network right, and right for the right reason?

A strategy with a positive expectancy and a 40% rejection rate is not working. A
network with 60% accuracy that is confidently wrong is more dangerous than one
with 52% accuracy that knows it is guessing. Reporting these together is what
makes those statements visible instead of averaged away.

## Execution quality (section 7)

| Metric | Notes |
| --- | --- |
| fill rate | filled + partially filled, over submitted |
| rejection rate | rejected + blocked, over submitted |
| average slippage | absolute, over the orders that reported one |
| worst slippage | the number that matters on a bad day |
| spread distribution | min / p50 / p90 / p99 / max |
| execution latency | same percentiles, in milliseconds |
| reconciliation failures | from the Phase 16 counters |
| connection failures | from the MT5 health monitor |

An unmeasured figure is **excluded, not counted as zero**: an unmeasured latency
is not a fast one. `reliable` stays false below 30 orders.

## Signal quality (section 8)

Counts come from the signals; performance comes from the resolved outcomes.

```
signal count · BUY · SELL · NEUTRAL
win rate · expectancy · profit factor · net PnL · MAE · MFE · drawdown
```

Unresolved signals are counted as signals and **excluded from performance**. They
are neither wins nor losses, and treating them as flat would quietly improve
every figure below them.

## Model quality (section 9)

```
NN accuracy · confidence calibration · high-confidence failures
false bullish · false bearish · false neutral
prediction drift · confidence drift · model drift
```

`calibration_gap` is mean confidence minus observed accuracy. A **positive** gap
is overconfidence, which is the direction that costs money; above the configured
threshold the report says `OVERCONFIDENT`. `calibration_quality` is `1 - |gap|`,
so a perfectly calibrated model scores 1.

A **high-confidence failure** is a wrong prediction made at or above the
configured confidence threshold (`phase_14.high_confidence_threshold`, default
0.75). It is tracked separately because a model that is wrong while sure is more
dangerous than one that is wrong while unsure.

Drift is measured only against a stated baseline. Without one there is no drift
claim, and the report says `None` rather than 0.

A prediction missing any of `predicted`, `actual` or `confidence` is excluded. An
unscored prediction is not a correct one.

## Regime, session and timeframe (sections 10–12)

Three cuts of the same population, each cell carrying its own sample size and its
own `reliable` flag. A cell below its floor is printed but **never counted as
evidence** — a strategy profitable overall can be losing in BEAR, and the only
way to see that is to refuse to average it away.

Section 12 is a warning as much as a measurement: **do not assume M5 is
superior.** Signals originate on one timeframe and execute on another, so both
are reported (`timeframe` and `signal_timeframe`) and neither table implies the
execution timeframe produced the edge.

`best` and `worst` are named only among cells that cleared their floor.

## Rolling windows (section 15)

24h · 3d · 7d · 14d · 30d · 60d · 90d, computed **where sufficient data exists**.

A window longer than the available history reports `WINDOW_NOT_COVERED` and
`INSUFFICIENT_DATA` rather than a number: a 90-day figure computed from four days
of trading is not a 90-day figure.

The overall edge status is the strictest reading across the rated windows. An
edge in one window and not the others is `UNSTABLE_EDGE`, not an edge.

## Minimum samples (section 16)

`config/settings.yaml` → `phase_17.minimums`:

| Floor | Default |
| --- | --- |
| `minimum_signals` | 100 |
| `minimum_winning_signals` | 20 |
| `minimum_losing_signals` | 20 |
| `minimum_regime_samples` | 30 |
| `minimum_session_samples` | 30 |
| `minimum_timeframe_samples` | 30 |

A population of only winners still misses a floor. A sample with no losses tells
you nothing about the downside.

## Endpoints

```
GET /validation/execution-quality
GET /validation/signal-quality
GET /validation/segments
GET /validation/windows
```

## See also

- [performance gates](performance_gates.md)
- [shadow vs demo](shadow_vs_demo.md)
- [demo validation](demo_validation.md)
