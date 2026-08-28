"""The observation driver: scheduling, execution, recovery, shutdown, health (sections 1, 2)."""
from datetime import datetime, timedelta, timezone

import pytest

from observation.driver import (
    ALLOWED_INTERVALS,
    DEFAULT_INTERVAL,
    DriverConfig,
    DriverState,
    ObservationDriver,
    TickOutcome,
    candle_timestamp,
)
from observation.lifecycle import ObservationStatus
from tests.phase14_helpers import NOW, FakeCycle, FakeResult, RecordingAlerts


def driver(**kwargs):
    kwargs.setdefault("cycle", FakeCycle(timestamp=NOW))
    kwargs.setdefault("config", DriverConfig(interval_seconds=300, symbols=("EURUSD",)))
    kwargs.setdefault("clock", lambda: NOW)
    kwargs.setdefault("sleeper", lambda seconds: None)
    return ObservationDriver(**kwargs)


# --------------------------------------------------------------- 2. scheduler
def test_the_default_interval_is_five_minutes():
    assert DEFAULT_INTERVAL == 300
    assert DriverConfig().interval_seconds == 300


def test_every_documented_interval_is_supported():
    assert ALLOWED_INTERVALS == (60, 300, 900, 1800, 3600)


def test_the_interval_comes_from_configuration_not_a_literal():
    config = DriverConfig.from_settings()
    assert config.interval_seconds in ALLOWED_INTERVALS


def test_an_unlisted_interval_is_refused(monkeypatch):
    import observation.driver as module

    monkeypatch.setattr(module, "load_yaml",
                        lambda: {"phase_14": {"interval_seconds": 137}})
    with pytest.raises(ValueError, match="interval_seconds"):
        DriverConfig.from_settings()


@pytest.mark.parametrize("interval,expected_minute", [(60, 34), (300, 30), (900, 30),
                                                      (1800, 30), (3600, 0)])
def test_the_candle_timestamp_floors_onto_the_interval_grid(interval, expected_minute):
    moment = datetime(2026, 8, 28, 9, 34, 51, tzinfo=timezone.utc)
    candle = candle_timestamp(moment, interval)
    assert candle.minute == expected_minute
    assert candle.second == 0
    assert candle <= moment


def test_the_candle_timestamp_is_normalised_to_utc():
    naive_equivalent = datetime(2026, 8, 28, 9, 34, tzinfo=timezone(timedelta(hours=7)))
    assert candle_timestamp(naive_equivalent, 3600).tzinfo == timezone.utc


# -------------------------------------------------------- 1. cycle execution
def test_a_tick_runs_every_configured_symbol():
    cycle = FakeCycle(timestamp=NOW)
    instance = driver(cycle=cycle,
                      config=DriverConfig(interval_seconds=300,
                                          symbols=("EURUSD", "GBPUSD")))
    tick = instance.run_once(now=NOW)
    assert cycle.calls == ["EURUSD", "GBPUSD"]
    assert len(tick.executed) == 2


def test_a_tick_records_the_candle_it_belongs_to():
    tick = driver().run_once(now=NOW + timedelta(seconds=137))
    assert tick.candle == candle_timestamp(NOW + timedelta(seconds=137), 300)


def test_an_executed_cycle_produces_an_observing_record():
    tick = driver().run_once(now=NOW)
    observation = tick.executed[0].observation
    assert observation.status is ObservationStatus.OBSERVING
    assert observation.entry_price == pytest.approx(1.1000)
    assert observation.nn_confidence == pytest.approx(0.80)


def test_a_halted_cycle_is_recorded_as_data_invalid():
    instance = driver(cycle=FakeCycle(timestamp=NOW, halted=True))
    tick = instance.run_once(now=NOW)
    report = tick.cycles[0]
    assert report.outcome is TickOutcome.HALTED
    assert report.observation.status is ObservationStatus.DATA_INVALID


# ----------------------------------------------------------- error recovery
def test_a_raising_cycle_does_not_kill_the_driver():
    instance = driver(cycle=FakeCycle(error=RuntimeError("mt5 exploded")))
    tick = instance.run_once(now=NOW)
    assert tick.failures and "mt5 exploded" in tick.failures[0].reasons[0]
    assert instance.stats.consecutive_errors == 1


def test_one_failing_symbol_does_not_stop_the_others():
    class Selective(FakeCycle):
        def run(self, symbol):
            if symbol == "EURUSD":
                raise RuntimeError("boom")
            return FakeResult(cycle_id="x", symbol=symbol, timestamp=NOW)

    instance = driver(cycle=Selective(timestamp=NOW),
                      config=DriverConfig(interval_seconds=300,
                                          symbols=("EURUSD", "GBPUSD")))
    tick = instance.run_once(now=NOW)
    assert len(tick.failures) == 1
    assert len(tick.executed) == 1


def test_a_failure_emits_an_alert():
    alerts = RecordingAlerts()
    driver(cycle=FakeCycle(error=RuntimeError("boom")), alerts=alerts).run_once(now=NOW)
    assert "observation_cycle_failed" in alerts.names()


def test_a_success_clears_the_consecutive_error_counter():
    cycle = FakeCycle(error=RuntimeError("boom"))
    instance = driver(cycle=cycle)
    instance.run_once(now=NOW)
    cycle.error = None
    instance.run_once(now=NOW + timedelta(minutes=5))
    assert instance.stats.consecutive_errors == 0


def test_the_loop_stops_after_too_many_consecutive_errors():
    instance = driver(cycle=FakeCycle(error=RuntimeError("boom")),
                      config=DriverConfig(interval_seconds=60, symbols=("EURUSD",),
                                          max_consecutive_errors=3))
    ticks = instance.run_forever(max_ticks=10)
    assert len(ticks) == 3
    assert instance.state is DriverState.FAILED


# -------------------------------------------------------- graceful shutdown
def test_stop_during_a_cycle_still_finishes_that_tick():
    """Graceful means the in-flight tick completes; the next one never starts."""
    instance = driver()
    original = instance.cycle.run

    def run(symbol):
        instance.stop(reason="TEST")
        return original(symbol)

    instance.cycle.run = run
    result = instance.run_forever(max_ticks=10)
    assert len(result) == 1
    assert result[0].executed, "the in-flight cycle still produced its observation"
    assert instance.stopping


def test_stop_during_the_sleep_prevents_the_next_tick():
    instance = driver()

    def sleeper(seconds):
        instance.stop(reason="TEST")

    instance._sleep = sleeper
    assert len(instance.run_forever(max_ticks=10)) == 1


def test_stopping_emits_the_driver_stopped_alert():
    alerts = RecordingAlerts()
    instance = driver(alerts=alerts)
    instance.stop(reason="MAINTENANCE")
    assert "observation_driver_stopped" in alerts.names()


def test_max_ticks_bounds_the_loop():
    instance = driver()
    assert len(instance.run_forever(max_ticks=3)) == 3
    assert instance.state is DriverState.STOPPED


# --------------------------------------------------------- health reporting
def test_health_is_healthy_after_a_successful_tick(memory_repository):
    # Alerting must be wired too: an unwatched driver reports monitoring UNKNOWN.
    instance = driver(repository=memory_repository, alerts=RecordingAlerts())
    instance.run_once(now=NOW)
    assert str(instance.health(NOW).state) == "HEALTHY"


def test_health_degrades_after_a_failure(memory_repository):
    instance = driver(cycle=FakeCycle(error=RuntimeError("boom")),
                      repository=memory_repository, alerts=RecordingAlerts())
    instance.run_once(now=NOW)
    health = instance.health(NOW)
    # The NN is UNKNOWN rather than DEGRADED here on purpose: the failing cycle
    # never reached it, and UNKNOWN outranks DEGRADED in this codebase.
    assert str(health.components["market_data"].state) == "DEGRADED"
    assert str(health.components["nn"].state) == "UNKNOWN"
    assert str(health.state) != "HEALTHY"


def test_an_unwatched_driver_reports_monitoring_as_unknown(memory_repository):
    instance = driver(repository=memory_repository)
    instance.run_once(now=NOW)
    assert str(instance.health(NOW).components["monitoring"].state) == "UNKNOWN"


def test_a_cycle_without_a_model_reports_the_nn_as_degraded(memory_repository):
    """A missing model is a known state; UNKNOWN is reserved for "never ran"."""
    result = FakeResult(cycle_id="c", symbol="EURUSD", timestamp=NOW,
                        snapshot=None, regime=None)
    instance = driver(cycle=FakeCycle(results=[result]), repository=memory_repository,
                      alerts=RecordingAlerts())
    assert str(instance.health(NOW).components["nn"].state) == "UNKNOWN"
    instance.run_once(now=NOW)
    assert str(instance.health(NOW).components["nn"].state) == "DEGRADED"


def test_a_long_silence_is_reported_as_stale():
    instance = driver()
    instance.run_once(now=NOW)
    assert instance._is_stale(NOW + timedelta(hours=2))


def test_the_status_payload_reports_the_schedule_and_zero_orders():
    instance = driver()
    instance.run_once(now=NOW)
    status = instance.status(NOW)
    assert status["cycles_per_minute"] == pytest.approx(0.2)
    assert status["orders_sent"] == 0
    assert status["observation_mode"] is True
    assert status["config"]["interval_seconds"] == 300


def test_the_driver_state_moves_from_stopped_to_running():
    instance = driver()
    assert instance.state is DriverState.STOPPED
    instance.start()
    assert instance.state is DriverState.RUNNING
