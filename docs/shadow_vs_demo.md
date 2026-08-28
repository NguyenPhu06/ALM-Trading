# SHADOW vs DEMO (Phase 17)

The question is not "did we make money". It is **where did the difference come
from**. A strategy that was right and filled badly needs a different response
from one that was wrong, and only an attribution tells them apart.

## The nine differences (section 6)

For each paired signal — one shadow outcome, one DEMO trade:

| Difference | Computed as |
| --- | --- |
| signal | side differs between shadow and DEMO |
| entry | DEMO entry − shadow expected entry |
| exit | DEMO exit − shadow expected exit |
| slippage | DEMO slippage − shadow slippage estimate |
| cost | DEMO total cost − shadow modelled cost |
| PnL | DEMO net − shadow net expected |
| MAE | DEMO MAE − shadow MAE |
| MFE | DEMO MFE − shadow MFE |
| time | DEMO duration − shadow duration |

Where a figure is unavailable the comparison says so rather than assuming zero. A
missing exit is not a flat exit.

## The classification

| Kind | What it means |
| --- | --- |
| `NONE` | shadow and DEMO agree within tolerance |
| `SIGNAL_ERROR` | different side — a different trade, not a bad fill |
| `EXECUTION_ERROR` | the entry filled outside tolerance |
| `MARKET_MOVEMENT` | the same exit rule fired at a different price |
| `SPREAD_ERROR` | the spread was wider than modelled |
| `SLIPPAGE_ERROR` | slippage beyond tolerance |
| `COST_ERROR` | commission and swap beyond tolerance |
| `TIMING_ERROR` | the trade lasted materially longer or shorter |

`NONE` is a real verdict, not a fallback. When the two agree, saying so is the
useful answer.

Two distinctions carry most of the value:

- **Entry difference is execution; exit difference is the market.** A bad entry
  is the broker; a different exit is price having gone somewhere else while the
  same exit rule was watching.
- **A different side is not an execution problem.** It is a different trade, and
  it points at the signal rather than the fill.

Several kinds can fire together and all of them are reported.

## Signals DEMO never took

A shadow signal whose DEMO twin never executed is recorded, not dropped
(`compare_unexecuted`). These rows are the population the gates removed — and
whether removing them helped is exactly what the performance gates cannot answer
if the rows do not exist.

## Tolerances

`config/settings.yaml` → `phase_17.comparison`:

| Setting | Default |
| --- | --- |
| `entry_tolerance` | 0.0002 |
| `exit_tolerance` | 0.0002 |
| `slippage_tolerance` | 0.0003 |
| `spread_tolerance` | 0.0002 |
| `cost_tolerance` | 0.5 |
| `time_tolerance_seconds` | 60 |
| `minimum_samples` | 30 |

## The aggregate

`ShadowDemoComparator.summarize()` reports the sample count, how many pairings
matched, a count per difference kind, and the mean and worst PnL difference.

`reliable` stays false below 30 pairings. A handful of paired trades is an
anecdote, and the honest label for it is `INSUFFICIENT_SAMPLES`.

## SHADOW vs PAPER vs DEMO

Three populations, three questions:

- **SHADOW** — what the decision would have produced, net of *modelled* cost.
- **PAPER** — what the simulation engine produced, with its own cost model.
- **DEMO** — what the broker actually produced, net of *real* cost.

The gap between SHADOW and DEMO is the part of the edge that the modelled costs
were quietly giving away. That is the number Phase 17 exists to measure.

## Endpoints

```
GET /validation/comparison        pairings with their attribution and summary
GET /dashboard/validation         shadow and DEMO side by side
```

## See also

- [shadow trading](shadow_trading.md)
- [execution quality](execution_quality.md)
- [demo validation](demo_validation.md)
