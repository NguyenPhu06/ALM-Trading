# Shadow Trading (Phase 17)

SHADOW runs the DEMO pipeline exactly and stops one step short of the wire.

Same market data. Same features. Same NN inference. Same strategy decision. Same
risk evaluation. Same execution proposal. **No broker order.**

## Not a second pipeline

The spec is explicit: *"Do not maintain separate trading logic."* This is
enforced structurally rather than promised.

A shadow record is minted inside `ControlledDemoTradingService.propose()`, from
the `GateChainDecision` the DEMO path just produced:

```python
shadow_signal = self.shadow.record(request, decision, context)
```

`ShadowRecorder.record()` takes the request and the decision — not a symbol and a
price — so there is no way to mint a shadow record without the artefacts DEMO
used. The recorder holds no client, no guard, no connection and no gate chain;
`tests/test_shadow_demo_parity.py` parses the module to prove it.

Because the record is a *view* of the decision rather than a recomputation, the
two cannot drift apart.

## What parity actually means

The twelve gates split in two, and the split is named in
[gates.py](../execution/demo/gates.py):

| Group | Gates | SHADOW vs DEMO |
| --- | --- | --- |
| `DECISION_GATES` | account, data quality, spread, risk, drawdown, exposure, DCA, strategy, model, session | **must agree** |
| `TRANSMISSION_GATES` | ExecutionGuard, KillSwitch | differ by design |

Decision gates answer *"is this a trade worth taking"*. Transmission gates answer
*"may this reach a broker"* — and that difference **is** the mode.

So a shadow signal carries two verdicts:

- `approved` — would this order have been sent? In SHADOW, always false.
- `decision_approved` — would the trade have been *taken*, had execution been
  armed? This is the figure shadow trading exists to produce.

`ExecutionGuard` sits on the transmission side because its refusals are dominated
by the configuration flags; the order-validity checks it also performs are
covered on the decision side by SpreadGate, RiskGate, SessionGate and
DemoAccountValidator.

## Every DEMO candidate has a shadow record

Section 3, by construction. The record is minted on the shared proposal path, so
a DEMO candidate without a shadow record is not a thing that can happen — whether
the order was approved, blocked, awaiting approval, or transmitted.

The blocked ones matter most. They are exactly the population the gates removed,
and whether removing them helped is a question the performance gates can only
answer if the rows exist.

`shadow_signal_id = sha256("shadow|" + request_id)[:32]`, so the pairing is a
function rather than bookkeeping: a shadow signal can always be found from a DEMO
trade and vice versa, even if one of the two rows is missing.

## What a shadow record holds

Section 3, field for field: `shadow_signal_id`, `demo_execution_request_id`,
`symbol`, `timestamp`, `side`, `entry`, `stop_loss`, `take_profit`, `strategy`,
`model`, `confidence`, `risk_snapshot_id`, `session`, `regime`, `feature_version`,
`model_version` — plus the gate verdicts, why it was not executed, and
`orders_sent`, which is a constant 0 in the dataclass, in the database column and
in the API payload.

## Shadow outcomes

When a signal reaches its exit condition (section 4):

```
expected_entry · expected_exit · expected_pnl · MFE · MAE · duration
spread · slippage_estimate · net_expected_pnl
```

`net_expected_pnl` is the headline. An expected move smaller than the spread and
the estimated slippage is not an expected profit, and reporting the gross number
instead would be the most flattering possible lie.

MFE and MAE come from the price path between entry and exit. Without a path they
are bounded by the exit itself rather than invented, which understates the
excursions — the safe direction to be wrong in.

A signal that never reaches an exit is **abandoned**, never assumed flat.

## Modes

| Mode | Sends orders | Records shadow |
| --- | --- | --- |
| `OBSERVATION` (default) | no | yes |
| `SHADOW` | no | yes |
| `PAPER` | no | yes |
| `DEMO_MANUAL_APPROVAL` | yes, after a human | yes |
| `DEMO_AUTOMATED` | yes | yes |
| `LIVE_DISABLED` | no | yes |

Shadow recording is on by default (`SHADOW_MODE_ENABLED=true`) because it cannot
send anything. Turning the *mode* to SHADOW does not open any broker flag — it
needs none of them, because it reaches no broker.

## Endpoints

```
GET /validation/shadow            shadow signals (orders_sent is 0 on every row)
GET /validation/shadow/outcomes   resolved outcomes, net of modelled cost
GET /validation/signal-quality    counts and performance
```

## See also

- [shadow vs demo](shadow_vs_demo.md)
- [demo validation](demo_validation.md)
- [controlled demo trading](controlled_demo_trading.md)
