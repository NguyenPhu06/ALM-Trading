# Controlled DEMO Trading (Phase 16)

Phase 16 enables tightly controlled automated execution **on a verified MT5 DEMO
account only**. LIVE trading is not supported, not configurable and not reachable
from any code path in this repository.

The purpose is to validate the complete lifecycle — decision → risk → execution →
reconciliation → learning — against real broker execution, where spreads,
slippage, commission, swap and rejections are real rather than modelled.

## Default state

After installing Phase 16, nothing changes about what the system does. It
observes.

| Setting | Default |
| --- | --- |
| `DEMO_EXECUTION_MODE` | `OBSERVATION` |
| `LIVE_TRADING_ENABLED` | `false` (refused at startup if true) |
| `REAL_ACCOUNT_EXECUTION` | `false` (refused at startup if true) |
| `DEMO_TRADING_ENABLED` | `false` |
| `MT5_EXECUTION_ENABLED` | `false` |
| `EXECUTION_KILL_SWITCH` | `true` (engaged) |
| `DEMO_AUTOMATED_EXECUTION_ENABLED` | `false` |
| `DEMO_DCA_ENABLED` | `false` |

Reaching a broker requires changing five of these deliberately, connecting a
verified DEMO account, and passing twelve gates per order.

## Execution modes

| Mode | Sends orders | Needs a human | What it is for |
| --- | --- | --- | --- |
| `OBSERVATION` | no | — | calculate everything, send nothing (the default) |
| `PAPER` | no | — | simulate the fill in the paper engine |
| `DEMO_MANUAL_APPROVAL` | yes | yes | exercise the whole path with a person in it |
| `DEMO_AUTOMATED` | yes | no | automated execution, DEMO only |
| `LIVE_DISABLED` | no | — | the permanent marker that live is off |

There is **no implicit switching**. The mode is whatever configuration says it
is; a closed gate blocks the *order*, never the *mode*. An unknown mode string is
refused at startup rather than coerced to a default — a typo in `DEMO_AUTOMATED`
must not become a running system in some other mode.

`DEMO_AUTOMATED` additionally requires `DEMO_AUTOMATED_EXECUTION_ENABLED=true`,
so automated execution takes two deliberate settings rather than one.

## The path one order walks

```
signal
  ↓  deterministic execution_request_id           (idempotency, section 12)
  ↓  position sizing from equity/risk/stop        (section 8)
  ↓  twelve gates, all evaluated, all fail-closed (section 5)
  ↓  execution proposal, recorded                 (section 4)
  ↓  human approval  [DEMO_MANUAL_APPROVAL only]
  ↓  ExecutionGuard approval                      (Phase 11)
  ↓  MT5 DEMO
  ↓  execution result                             (section 13)
  ↓  reconciliation                               (section 15)
  ↓  trade journal                                (section 20)
  ↓  daily risk + emergency check                 (sections 17, 24)
  ↓  AI feedback on close                         (section 30)
```

Every stage is persisted before the next begins, so a refusal is as fully
audited as a fill.

## The gate chain

Twelve gates, in a fixed order, every one of them fail-closed:

1. `DemoAccountValidator` — verified DEMO account, DEMO server, known permissions
2. `DataQualityGate` — no failing timeframe, no stale feed
3. `SpreadGate` — spread and expected slippage inside their limits
4. `RiskGate` — risk engine verdict, risk per trade, margin usage
5. `DrawdownGate` — daily loss, total drawdown, trades per day
6. `ExposureGate` — open positions, symbol exposure, total exposure
7. `DcaSafetyGate` — DCA enabled, levels, aggregate exposure, invalidation
8. `StrategyGate` — Champion Strategy only
9. `ModelConfidenceGate` — advisory; can refuse, can never approve past a gate
10. `SessionGate` — configured trading sessions
11. `ExecutionGuard` — the Phase 11 guard, unchanged
12. `KillSwitch` — engaged blocks every new entry and every DCA

Every gate runs even after one has already blocked, and all reasons are reported
at once. A partial answer ("blocked by the spread") hides the fact that the
account was also unverified, and an operator who fixes only the reported problem
would be surprised twice.

Mode and idempotency are folded into the same verdict. They are not gates in the
section 5 list, but neither is a decision the gates may override.

## What Phase 16 does not do

- It does not trade live, and it has no live adapter to trade with.
- It does not close positions automatically on an emergency. The kill switch
  blocks new orders; liquidation is a separate, separately authorised decision.
- It does not retrain a model after a trade. A closed DEMO trade is recorded in
  the observation/performance store and nothing else.
- It does not let a challenger or experimental strategy execute unless that is
  explicitly enabled for testing.
- It does not let the neural network bypass any gate. The NN is advisory.

## Arming DEMO execution

Manual approval, which is where to start:

```env
DEMO_EXECUTION_MODE=DEMO_MANUAL_APPROVAL
DEMO_TRADING_ENABLED=true
MT5_EXECUTION_ENABLED=true
MT5_READ_ONLY=false
EXECUTION_KILL_SWITCH=false
```

Automated, only after manual approval has been exercised end to end:

```env
DEMO_EXECUTION_MODE=DEMO_AUTOMATED
DEMO_AUTOMATED_EXECUTION_ENABLED=true
```

`REAL_ACCOUNT_EXECUTION` and `LIVE_TRADING_ENABLED` stay `false`. Both are
refused at startup if set, so a wrong flag stops the process rather than
silently arming something.

## Endpoints

| Endpoint | What it does |
| --- | --- |
| `GET /execution/mode` | the configured mode and what it permits |
| `GET /execution/limits` | the hard limits and the gate list |
| `POST /execution/demo/propose` | size, gate and record one proposal |
| `GET /execution/proposals` | proposals, and which await approval |
| `POST /execution/proposals/{id}/approve` | human approval, then submission |
| `POST /execution/proposals/{id}/reject` | decline a proposal |
| `GET /execution/daily-risk` | the trading day and its budget |
| `GET /execution/positions` | open DEMO positions with MAE/MFE |
| `GET /execution/journal` | the DEMO trade journal |
| `GET /execution/comparison` | paper vs DEMO |
| `GET /execution/performance` | DEMO performance |
| `GET /execution/emergency` | emergency events |
| `GET /dashboard/demo-execution` | the operator panel |

There is deliberately no endpoint that changes the mode, opens a flag or arms
execution. Arming is a configuration change, so API access alone cannot move the
system out of OBSERVATION.

`POST /execution/demo/propose` takes a stop, not a lot size. Section 8 forbids an
arbitrary volume, so the size is derived and a caller cannot supply one.

## See also

- [demo execution safety](demo_execution_safety.md)
- [demo risk limits](demo_risk_limits.md)
- [demo reconciliation](demo_reconciliation.md)
- [demo trade journal](demo_trade_journal.md)
- [demo operations](demo_operations.md)
- [Phase 11 execution guard](execution_guard.md)
- [kill switch](kill_switch.md)
