# Circuit Breaker & Recovery (Phase 17)

The Phase 16 emergency controller engages the kill switch. The circuit breaker
adds the thing the kill switch alone cannot give: **a state that survives an
operator releasing the switch.**

Without it, recovery would be one button press. Section 23 asks for four specific
things first.

## The eleven triggers (section 22)

| Trigger | Fires when |
| --- | --- |
| `DAILY_LOSS_EXCEEDED` | daily drawdown ≥ `max_daily_loss` |
| `DRAWDOWN_EXCEEDED` | total drawdown ≥ `max_total_drawdown` |
| `RECONCILIATION_FAILURE` | any reconciliation failure |
| `REPEATED_EXECUTION_FAILURES` | ≥ `max_execution_failures` (default 3) |
| `STALE_MARKET_DATA` | data older than `data_stale_seconds` (default 180) |
| `MODEL_FAILURE` | the model failed |
| `RISK_ENGINE_FAILURE` | the risk engine failed |
| `UNEXPECTED_ACCOUNT` | account type is not DEMO or CONTEST |
| `UNEXPECTED_BROKER` | broker differs from the configured one |
| `UNEXPECTED_SYMBOL` | symbol outside the allowlist |
| `ABNORMAL_SPREAD` | spread > `max_spread × abnormal_spread_ratio` (default 2×) |

`None` means *not observed*, which is not the same as bad, and trips nothing.

**Wide is not abnormal.** A spread above `max_spread` is a gate refusal for that
order; a spread at twice the limit is a breaker trip for the session. They are
different mechanisms answering different questions.

`evaluate()` never trips. `check()` evaluates and trips if anything fired.

## Tripping

Opening the breaker:

- sets state to `OPEN` and records the triggers;
- engages the kill switch;
- writes a `circuit_breaker_events` row;
- raises `CIRCUIT_BREAKER_TRIPPED` at CRITICAL severity;
- **does not close any open position.**

`positions_closed` is a column that is always False, for the same reason as in
Phase 16: liquidating positions would be a second, larger and less reversible
decision taken by code that has just discovered it cannot trust its own inputs.

While open, `ControlledDemoTradingService._transmit` refuses before anything
reaches the wire — independently of the kill switch, which is the whole point.

## Recovery (section 23)

> "DEMO_AUTOMATED must NOT automatically restart."

Four items, none inferred:

```
health_check · risk_check · account_validation · human_approval
```

`human_approval` requires **both** a named approver and a stated reason. An
incomplete checklist raises `RecoveryRefused` naming exactly what is missing, and
the breaker stays open.

There is no timeout, no retry counter and no automatic reset anywhere in the
module, so `DEMO_AUTOMATED` cannot resume by waiting.

### Recovery does not release the kill switch

Two mechanisms, two deliberate actions. Closing the breaker removes the breaker's
block; the kill switch the trip engaged is still engaged, and releasing it is a
separate operator action with its own reason.

```bash
curl -X POST localhost:8000/validation/circuit-breaker/reset \
  -H 'content-type: application/json' -d '{
    "health_check": true, "risk_check": true, "account_validation": true,
    "approved_by": "your name", "reason": "verified healthy after recovery"
  }'
```

An incomplete checklist returns **409** with the missing items. The response
always carries `demo_automated_resumed: false`.

Then, separately:

```bash
curl -X POST localhost:8000/execution/kill-switch/release \
  -H 'content-type: application/json' -d '{"reason": "verified healthy after recovery"}'
```

## Anomalies are not the breaker (section 21)

Nine change detectors — signal frequency, spread, slippage, prediction
distribution, confidence distribution, PnL distribution, regime distribution,
execution latency, MT5 connectivity.

An anomaly says the system is behaving differently from its own recent baseline.
That is **a reason to look, not a verdict**, and it raises an alert without
tripping anything. Section 21 alerts; section 22 stops.

Everything is compared against a stated baseline. Without one there is no anomaly
— only a first observation, and the detector says `skipped` rather than treating
the first reading as normal or as alarming.

Signal rate is measured **per hour**, so a 24h window and a 7d window are
comparable without pretending they are the same size.

## Configuration

`config/settings.yaml` → `phase_17.circuit_breaker` and `phase_17.anomaly`.
`CIRCUIT_BREAKER_ENABLED=true` ships on. Turning it off does not enable
execution; it only removes an automatic reason to stop.

## Endpoints

```
GET  /validation/circuit-breaker         state, triggers, history, what recovery needs
POST /validation/circuit-breaker/reset   the four-item checklist
```

## See also

- [demo execution safety](demo_execution_safety.md) — the Phase 16 emergency path
- [kill switch](kill_switch.md)
- [performance gates](performance_gates.md)
