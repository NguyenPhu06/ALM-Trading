from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[1]


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
    demo_execution_max_volume: float = 0.10
    demo_execution_symbols: str = ""
    execution_audit_enabled: bool = True

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
    def demo_execution_symbol_allowlist(self) -> tuple[str, ...]:
        return tuple(item.strip().upper() for item in self.demo_execution_symbols.split(",") if item.strip())

    @property
    def environment(self) -> str:
        return self.trading_environment.strip().upper()

    def mt5_credentials_present(self) -> bool:
        """True when a login/password/server triple is configured, without exposing it."""
        return bool(self.mt5_login and self.mt5_password and self.mt5_server)

    @property
    def yaml(self) -> dict[str, Any]:
        return load_yaml()


@lru_cache
def get_settings() -> Settings:
    return Settings()
