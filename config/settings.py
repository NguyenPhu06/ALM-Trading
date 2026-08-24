from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
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
    log_level: str = "INFO"

    @model_validator(mode="after")
    def enforce_phase_safety(self) -> "Settings":
        if self.live_trading_enabled:
            raise ValueError("LIVE_TRADING_ENABLED must be false during Phase 1A/1B")
        return self

    @property
    def yaml(self) -> dict[str, Any]:
        return load_yaml()


@lru_cache
def get_settings() -> Settings:
    return Settings()
