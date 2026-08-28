from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[1]

# Phase 16 execution modes. Declared here rather than imported from the
# execution package so that Settings has no dependency on it;
# execution.demo.modes.ExecutionMode is checked against this tuple by a test.
EXECUTION_MODES = ("OBSERVATION", "SHADOW", "PAPER", "DEMO_MANUAL_APPROVAL",
                   "DEMO_AUTOMATED", "LIVE_DISABLED")
# The two modes that can reach a broker. Both need DEMO_TRADING_ENABLED.
BROKER_EXECUTION_MODES = ("DEMO_MANUAL_APPROVAL", "DEMO_AUTOMATED")


def load_yaml() -> dict[str, Any]:
    path = ROOT / "config" / "settings.yaml"
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "sqlite:///./alm_trading.db"
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None
    tradingview_webhook_secret: str = Field(min_length=24)
    live_trading_enabled: bool = False
    demo_trading_enabled: bool = False
    log_level: str = "INFO"
    market_data_provider: str = "historical"
    market_data_api_key: str | None = None
    market_data_base_url: str = "https://api.twelvedata.com"
    market_data_timeout: float = 30.0
    market_data_rate_limit: float = 8.0
    market_data_max_retries: int = 3
    market_data_backoff_seconds: float = 1.0

    # ------------------------------------------------------------ Phase 10 MT5
    # MT5 supplies market data. Phase 11 adds a gated DEMO execution path.
    trading_environment: str = "DEMO"
    read_only_mode: bool = True
    mt5_enabled: bool = False
    # Phase 11: read-only is no longer a startup invariant, it is one of three
    # independent execution gates. Data access never depends on it.
    mt5_read_only: bool = False
    mt5_execution_enabled: bool = False
    mt5_login: int | None = None
    mt5_password: SecretStr | None = None
    mt5_server: str | None = None
    mt5_terminal_path: str | None = None
    mt5_broker: str = "Exness"
    mt5_magic_number: int = 0
    mt5_timeout_ms: int = 30000
    mt5_bridge_url: str | None = None
    mt5_bridge_token: SecretStr | None = None

    # --------------------------------------------------- Phase 11 DEMO execution
    # Three independent gates, all closed by default. An order needs every one of
    # them opened deliberately, and ExecutionGuard re-checks all of them per order.
    execution_kill_switch: bool = True
    # Phase 12: observe the real market, calculate everything, send nothing.
    observation_mode: bool = True
    observation_symbols: str = "EURUSD"
    observation_interval_seconds: int = 60
    # Phase 13: learning is an explicit job, never something inference triggers.
    ai_training_enabled: bool = True
    ai_auto_promote: bool = False
    ai_online_learning_enabled: bool = False
    # Phase 14: a trigger may propose training; only a human may start it.
    ai_manual_training: bool = True
    ai_automatic_training: bool = False
    observation_driver_enabled: bool = False
    demo_execution_max_volume: float = 0.10
    demo_execution_symbols: str = ""
    execution_audit_enabled: bool = True

    # ------------------------------------- Phase 16 controlled DEMO trading
    # A REAL account may never execute. The flag exists so that the refusal is
    # explicit and testable rather than merely absent, and it is refused at
    # startup exactly like LIVE_TRADING_ENABLED.
    real_account_execution: bool = False
    # The single source of truth for what the system is allowed to do. There is
    # no implicit switching: whatever is configured here is the mode, and a
    # closed gate blocks the order rather than quietly changing the mode.
    demo_execution_mode: str = "OBSERVATION"
    # DEMO_AUTOMATED additionally requires this flag, so reaching automated
    # execution needs two deliberate settings rather than one.
    demo_automated_execution_enabled: bool = False
    # DCA is off until someone turns it on, and every DCA order still re-runs
    # the whole gate chain (see execution/demo/gates.py).
    demo_dca_enabled: bool = False
    # The trading-day boundary. Named explicitly so a daily limit can never be
    # ambiguous about which day it belongs to.
    demo_trading_timezone: str = "UTC"
    demo_trading_day_reset_hour: int = 0

    # ------------------------------ Phase 17 shadow trading and DEMO validation
    # Shadow recording is on by default because it cannot send anything: it
    # records what the SAME pipeline decided, so DEMO and SHADOW stay comparable
    # by construction rather than by convention.
    shadow_mode_enabled: bool = True
    # The circuit breaker is on by default. Turning it off does not enable
    # execution; it only removes an automatic reason to stop.
    circuit_breaker_enabled: bool = True
    # Section 18: eligibility is COMPUTED and advisory. This flag records that a
    # named human accepted it, and it is still not sufficient on its own —
    # DEMO_AUTOMATED also needs DEMO_AUTOMATED_EXECUTION_ENABLED.
    demo_automation_approved: bool = False

    @model_validator(mode="after")
    def enforce_phase_safety(self) -> "Settings":
        """Only LIVE remains a hard startup invariant.

        DEMO_TRADING_ENABLED and MT5_EXECUTION_ENABLED became settable in Phase 11
        so that a manual DEMO order can be tested at all. They stay false by
        default and ExecutionGuard refuses every order unless both are true, the
        kill switch is released, and the account is a verified DEMO account.
        """
        if self.live_trading_enabled:
            raise ValueError("LIVE_TRADING_ENABLED must be false during Phases 1-11")
        if self.trading_environment.strip().upper() != "DEMO":
            raise ValueError("TRADING_ENVIRONMENT must be DEMO during Phase 11")
        if not self.read_only_mode:
            raise ValueError("READ_ONLY_MODE must be true during Phase 11")
        if self.demo_trading_enabled and self.mt5_read_only:
            raise ValueError("MT5_READ_ONLY must be false to enable DEMO execution")
        # Phase 13 invariants: a model may never promote itself, and nothing may
        # fit a model inside the market loop.
        if self.ai_auto_promote:
            raise ValueError("AI_AUTO_PROMOTE must be false; promotion requires human approval")
        if self.ai_online_learning_enabled:
            raise ValueError("AI_ONLINE_LEARNING_ENABLED must be false during Phase 13")
        # Phase 14: the 24/7 driver must never be able to start a training run.
        if self.ai_automatic_training:
            raise ValueError("AI_AUTOMATIC_TRAINING must be false; training is a manual job")
        # Phase 16 invariants. LIVE stays impossible and a REAL account stays
        # unexecutable; the mode must be one of the five declared modes, and
        # DEMO_AUTOMATED needs its own separate opt-in.
        if self.real_account_execution:
            raise ValueError("REAL_ACCOUNT_EXECUTION must be false; only DEMO accounts may execute")
        mode = self.demo_execution_mode.strip().upper()
        if mode not in EXECUTION_MODES:
            raise ValueError(
                f"DEMO_EXECUTION_MODE must be one of {', '.join(sorted(EXECUTION_MODES))}")
        if mode == "DEMO_AUTOMATED" and not self.demo_automated_execution_enabled:
            raise ValueError(
                "DEMO_EXECUTION_MODE=DEMO_AUTOMATED requires "
                "DEMO_AUTOMATED_EXECUTION_ENABLED=true")
        if mode in BROKER_EXECUTION_MODES and not self.demo_trading_enabled:
            raise ValueError(
                f"DEMO_EXECUTION_MODE={mode} requires DEMO_TRADING_ENABLED=true")
        if not 0 <= self.demo_trading_day_reset_hour <= 23:
            raise ValueError("DEMO_TRADING_DAY_RESET_HOUR must be between 0 and 23")
        # Phase 17: approving automation is a statement about evidence, not a
        # switch. It never substitutes for the Phase 16 opt-in, so a configuration
        # that approves automation without arming it is refused rather than
        # silently treated as armed.
        if self.demo_automation_approved and mode == "DEMO_AUTOMATED" and not (
                self.demo_automated_execution_enabled):
            raise ValueError(
                "DEMO_AUTOMATION_APPROVED does not arm execution; "
                "DEMO_AUTOMATED_EXECUTION_ENABLED is still required")
        return self

    @property
    def execution_allowed_by_config(self) -> bool:
        """Configuration-level verdict only. The account and guard are checked separately."""
        return (
            self.environment == "DEMO"
            and not self.live_trading_enabled
            and self.demo_trading_enabled
            and self.mt5_execution_enabled
            and not self.mt5_read_only
            and not self.execution_kill_switch
        )

    @property
    def observation_symbol_list(self) -> tuple[str, ...]:
        return tuple(item.strip().upper() for item in self.observation_symbols.split(",") if item.strip())

    @property
    def demo_execution_symbol_allowlist(self) -> tuple[str, ...]:
        return tuple(item.strip().upper() for item in self.demo_execution_symbols.split(",") if item.strip())

    @property
    def environment(self) -> str:
        return self.trading_environment.strip().upper()

    @property
    def execution_mode(self) -> str:
        """The configured mode, normalised. OBSERVATION is the shipped default."""
        return self.demo_execution_mode.strip().upper()

    @property
    def broker_execution_configured(self) -> bool:
        """Configuration-level only: the mode asks for a broker.

        Whether an order actually reaches one is decided per order by the gate
        chain, which re-checks every flag, the account and the kill switch.
        """
        return self.execution_mode in BROKER_EXECUTION_MODES

    def mt5_credentials_present(self) -> bool:
        """True when a login/password/server triple is configured, without exposing it."""
        return bool(self.mt5_login and self.mt5_password and self.mt5_server)

    @property
    def yaml(self) -> dict[str, Any]:
        return load_yaml()


@lru_cache
def get_settings() -> Settings:
    return Settings()
