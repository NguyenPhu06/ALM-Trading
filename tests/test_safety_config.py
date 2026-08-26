from __future__ import annotations

import yaml
import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from config.settings import ROOT, Settings
from database.base import Base
import database.models  # noqa: F401


def test_live_trading_cannot_be_enabled():
    with pytest.raises(ValidationError, match="must be false"):
        Settings(
            database_url="sqlite://", tradingview_webhook_secret="a-secure-test-secret-of-24-chars",
            live_trading_enabled=True,
        )


def test_compose_has_timescale_volume_and_healthchecks():
    """Sanctioned Phase 9 architecture is exactly db + api + observation-only frontend."""
    with (ROOT / "docker-compose.yml").open(encoding="utf-8") as handle:
        compose = yaml.safe_load(handle)
    assert set(compose["services"]) == {"db", "api", "frontend"}
    assert compose["services"]["db"]["image"].startswith("timescale/timescaledb:")
    for service in ("db", "api", "frontend"):
        assert "healthcheck" in compose["services"][service]
    assert "postgres_data" in compose["volumes"]


def test_compose_api_pins_live_and_demo_trading_off():
    with (ROOT / "docker-compose.yml").open(encoding="utf-8") as handle:
        compose = yaml.safe_load(handle)
    environment = compose["services"]["api"]["environment"]
    assert str(environment["LIVE_TRADING_ENABLED"]).lower() == "false"
    assert str(environment["DEMO_TRADING_ENABLED"]).lower() == "false"


def test_compose_frontend_is_observation_only():
    """The dashboard container serves static assets; it holds no broker or DB credential."""
    with (ROOT / "docker-compose.yml").open(encoding="utf-8") as handle:
        compose = yaml.safe_load(handle)
    frontend = compose["services"]["frontend"]
    assert "environment" not in frontend
    assert frontend["depends_on"]["api"]["condition"] == "service_healthy"


def test_all_models_compile_for_postgresql():
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        assert str(table.select().compile(dialect=dialect))

