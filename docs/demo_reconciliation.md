# DEMO Reconciliation (Phase 16)

After every execution the internal state is compared with what MT5 reports. The
comparison is read-only: a mismatch is recorded and alerted, **never repaired**.

## What is compared

`Reconciler.reconcile(request, result, position)` checks:

| Check | Compares |
| --- | --- |
| `ticket` | a broker ticket exists |
| `volume` | filled volume vs requested volume |
| `price` | filled price vs requested price |
| `position` | the position exists at the broker |
| `position_volume` | position volume vs filled volume |
| `position_ticket` | position ticket vs result ticket |
| `pnl` | profit is readable |
| `sl` / `tp` | the stops the broker set vs the ones requested |

Tolerances live in `config/settings.yaml` under `phase_11.reconciliation`
(`volume_tolerance`, `price_tolerance`).

## The four verdicts

| Status | Meaning |
| --- | --- |
| `MATCHED` | every check passed |
| `MISMATCHED` | at least one check failed |
| `POSITION_MISSING` | the broker filled but reports no position |
| `NOT_APPLICABLE` | the order was blocked, rejected or failed |

## A mismatch is a safe shutdown

Section 15 says a mismatch raises `RECONCILIATION_FAILURE` and alerts. Section 17
adds that it is one of the automatic shutdown conditions, and Phase 16 wires the
two together: on `MISMATCHED` or `POSITION_MISSING` the service engages the
kill switch, so no further order can be submitted while internal state and broker
state disagree.

That is the conservative direction. A system that cannot confirm what it owns
should not be deciding what to buy next.

The shutdown blocks new orders and nothing else. Open positions are untouched —
see [demo execution safety](demo_execution_safety.md) for why.

## What is recorded

Three rows per execution, all persisted before the next stage begins:

- `execution_results` — the broker's answer (section 13);
- `reconciliation_records` — the comparison, its checks and its differences;
- `execution_audit_logs` — one row per stage, including `RECONCILIATION`;
- `demo_emergency_events` — when a mismatch triggered a shutdown.

`demo_trade_journal` carries the same fill alongside the market, feature, model,
strategy and risk context it came from.

## Nothing is corrected

There is no code path in reconciliation that sends an order. A mismatch does not
produce a corrective trade, a partial close, a re-send or an adjustment. The
tests assert that exactly one order reached the broker even when the fill did not
match the request.

## Alerts

| Alert | When |
| --- | --- |
| `RECONCILIATION_FAILURE` | any mismatch or missing position |
| `EMERGENCY_SHUTDOWN` | the mismatch engaged the kill switch |
| `KILL_SWITCH_TRIGGERED` | the switch changed state |

## Reading it back

```
GET /execution/orders          the results
GET /execution/audit           the per-stage audit trail
GET /execution/emergency       emergency events (positions_closed is always false)
GET /dashboard/demo-execution  the operator panel, including the last reconciliation
```
