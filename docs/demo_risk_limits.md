# DEMO Risk Limits (Phase 16)

Every limit is configurable and every default is conservative. **None of these
numbers was fitted to the test set, and none should be.** They bound how wrong
the system may be; they are not parameters of the strategy.

Configuration lives in `config/settings.yaml` under `phase_16.limits`.

## The shipped defaults

| Limit | Default | What it bounds |
| --- | --- | --- |
| `max_risk_per_trade` | 0.005 | fraction of equity risked on one trade |
| `max_daily_loss` | 0.02 | daily drawdown against the day's starting equity |
| `max_total_drawdown` | 0.05 | drawdown against peak equity, across days |
| `max_open_positions` | 2 | concurrent open positions |
| `max_symbol_exposure` | 5 000 | notional in one symbol |
| `max_total_exposure` | 10 000 | notional across all symbols |
| `max_dca_levels` | 2 | DCA entries on one position |
| `max_total_dca_exposure` | 7 500 | aggregate DCA notional |
| `max_trades_per_day` | 5 | orders submitted in one trading day |
| `max_spread` | 0.0005 | spread at the moment of the order |
| `max_slippage` | 0.0003 | expected slippage |
| `max_margin_usage` | 0.30 | fraction of margin in use |
| `max_position_size` | 0.05 | lots on one order |
| `min_volume` | 0.01 | broker minimum |
| `volume_step` | 0.01 | broker lot step |
| `min_stop_distance` | 0.0005 | closest a stop may sit to entry |

A limit that cannot be evaluated is treated as breached, never as satisfied.
Every failing limit is reported at once rather than the first one found.

## Position sizing

There is no arbitrary lot size anywhere in this phase. A volume is derived:

```
risk_amount   = equity × risk_percent
loss_per_lot  = (stop_distance ÷ tick_size) × tick_value
volume        = risk_amount ÷ loss_per_lot
```

then clamped, in order, by `max_position_size`, the broker's `volume_max`, the
remaining symbol and total exposure room, and the margin budget; then floored to
the broker's `volume_step`.

The refusals matter more than the arithmetic:

| Situation | Result |
| --- | --- |
| no stop loss | volume 0, `NO_STOP_DISTANCE` |
| stop inside `min_stop_distance` | volume 0, `NO_STOP_DISTANCE` |
| no equity | volume 0, `NO_EQUITY` |
| no tick size or tick value | volume 0, `NO_TICK_ECONOMICS` |
| risk budget below one lot | volume 0, `BELOW_MINIMUM_VOLUME` |
| caller asks for more risk than the limit | clamped to the limit |

`BELOW_MINIMUM_VOLUME` is a refusal rather than a rounding up: trading the
broker's minimum anyway would exceed the configured risk, which is the one thing
sizing exists to prevent.

Tick economics come from the terminal when it is connected and from
`phase_16.symbol` otherwise, per field. Gold and EURUSD have different contract
sizes and tick values, so the same risk buys different lots.

## DCA

DCA is disabled by default (`DEMO_DCA_ENABLED=false`).

When it is enabled, every DCA order re-runs the **complete** gate chain — not a
shortened version of it. In addition, `DcaSafetyGate` bounds:

- the number of levels (`max_dca_levels`);
- the aggregate DCA notional (`max_total_dca_exposure`);
- the invalidation condition, which blocks further levels once it fires.

There is no martingale anywhere. Size comes from the sizer, never from a
multiplier on a loss, and because averaging down puts the stop further from the
new entry, the derived volume of a DCA level is *smaller* than the original.

## The trading day

A daily limit is meaningless until the day is pinned down, so the boundary is
explicit: `DEMO_TRADING_TIMEZONE` plus `DEMO_TRADING_DAY_RESET_HOUR`. Every day
state carries the trading day it belongs to.

- Crossing the boundary resets the starting equity and the trade count.
- Peak equity does **not** reset. Total drawdown spans days, so a new day does
  not forgive a drawdown.
- A restored state keeps its budget: a restart does not hand back a fresh daily
  allowance.

With `reset_hour = 22` in a UTC configuration, 21:00 UTC is still the previous
trading day and 22:00 UTC begins the next one.

## Changing a limit

Edit `config/settings.yaml`. Do not tune these against the test set, and do not
raise one because a trade was blocked — a blocked trade is the limit working. If
a limit is systematically wrong, say so in a research finding with evidence, the
way any other parameter change is justified in this project.
