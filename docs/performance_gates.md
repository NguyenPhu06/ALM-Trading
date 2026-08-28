# Performance Gates & Automation Eligibility (Phase 17)

A performance gate is a claim about evidence, not a switch.

The decisive property, from section 17 and enforced in code: **a failed gate must
not enable higher-risk execution.** The objects in `validation/gates.py` can only
report — they hold no settings object, define no `enable`, `arm` or `apply`
method, and `enables_execution` is a property that returns a constant False.

## The eight gates (section 17)

`config/settings.yaml` → `phase_17.gates`:

| Gate | Default | Direction |
| --- | --- | --- |
| `minimum_samples` | 100 | at least |
| `maximum_drawdown` | 0.05 | at most |
| `minimum_expectancy` | 0.0 | at least |
| `minimum_profit_factor` | 1.10 | at least |
| `maximum_rejection_rate` | 0.10 | at most |
| `maximum_reconciliation_failure_rate` | 0.0 | at most |
| `maximum_high_confidence_failure_rate` | 0.30 | at most |
| `minimum_calibration_quality` | 0.80 | at least |

Three verdicts per gate: `PASS`, `FAIL`, `UNKNOWN`.

**An unmeasured gate is UNKNOWN, which is not a pass.** Fail-closed: not
measuring something is not evidence that it is fine, and a report with any
unknown gate does not pass overall.

Every failing gate is reported at once, not just the first.

## DEMO automation eligibility (section 18)

`DEMO_AUTOMATION_ELIGIBLE` is **computed**. Ten checks:

```
champion_strategy · sufficient_observations · stable_model · acceptable_drawdown
execution_quality · no_reconciliation_failures · no_critical_data_issues
kill_switch_released · risk_gates_pass · circuit_breaker_closed
```

Plus the performance gate report: a failed gate adds `performance_gates` to the
missing list.

Fail-closed on every axis. A check whose input is `None` lands in `unknown`, and
unknown is not eligible.

### Eligibility enables nothing

This is the part that matters:

- `AutomationEligibility.enabled` is a constant **False**.
- `as_dict()["automatically_enabled"]` is a constant **False**.
- The evaluator has no method that writes a setting.
- Being eligible leaves `DEMO_EXECUTION_MODE` exactly where it was.

Arming `DEMO_AUTOMATED` still requires, separately and deliberately:

1. `DEMO_EXECUTION_MODE=DEMO_AUTOMATED`
2. `DEMO_AUTOMATED_EXECUTION_ENABLED=true`
3. `DEMO_TRADING_ENABLED=true`, `MT5_EXECUTION_ENABLED=true`
4. `EXECUTION_KILL_SWITCH=false`
5. a verified DEMO account, and every gate passing per order

`DEMO_AUTOMATION_APPROVED` records that a named human accepted the eligibility
finding. It is **not** sufficient on its own — a configuration that approves
automation for `DEMO_AUTOMATED` without the Phase 16 opt-in is refused at startup
rather than silently treated as armed.

## Why gates and eligibility are separate

A gate says "the evidence clears this bar". Eligibility says "every precondition
for automation currently holds". Neither says "turn it on", and the only thing
that does is a human editing configuration and restarting the process.

## Endpoints

```
GET /validation/gates?window=30d   the eight gates against a chosen window
GET /validation/eligibility        the ten checks, plus what is still required
```

Both are GET. There is no endpoint anywhere that changes the mode, opens a flag
or enables automation — `tests/test_phase9_safety_invariants.py` asserts it by
enumerating every writable route.

## See also

- [execution quality](execution_quality.md)
- [circuit breaker](circuit_breaker.md)
- [demo validation](demo_validation.md)
