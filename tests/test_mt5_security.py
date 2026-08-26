"""Credentials must not reach source, logs, the database or an API response."""
import logging
import pathlib
import re
import subprocess

import pytest
from pydantic import SecretStr

from config.settings import ROOT, Settings
from database.base import Base
from database.models import MT5AccountRecord, MT5AccountSnapshotRecord, MT5ConnectionEventRecord
from database.repositories.mt5 import scrub
from execution.mt5.connection import MT5Connection, mask_login
from execution.mt5.service import MT5ReadOnlyService
from tests.phase10_helpers import connected_client, module

SECRET = "super-secret-mt5-password"
BASE = dict(database_url="sqlite://", tradingview_webhook_secret="a-secure-test-secret-of-24-chars")
CREDENTIAL_TOKENS = ("password", "secret", "credential", "api_key", "token")


def settings_with_credentials(**overrides):
    return Settings(**BASE, mt5_login=987654321, mt5_password=SecretStr(SECRET),
                    mt5_server="Exness-MT5Trial8", **overrides)


# ------------------------------------------------------------------ in memory
def test_the_password_is_a_secret_and_never_reprs_in_the_clear():
    settings = settings_with_credentials()
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert SECRET not in repr(settings.mt5_password)
    assert settings.mt5_password.get_secret_value() == SECRET


def test_credentials_presence_is_reported_without_exposing_them():
    settings = settings_with_credentials()
    assert settings.mt5_credentials_present() is True
    assert SECRET not in str(settings.mt5_credentials_present())


# ---------------------------------------------------------------------- logs
def test_connecting_never_writes_the_password_to_the_log(caplog):
    settings = settings_with_credentials()
    fake = module()
    with caplog.at_level(logging.DEBUG):
        MT5Connection(settings, module=fake).connect()
    assert SECRET not in caplog.text
    assert "987654321" not in caplog.text
    # It must still have been handed to the terminal itself.
    assert fake.init_kwargs.get("password") == SECRET


def test_a_terminal_failure_does_not_leak_the_password(caplog):
    class Exploding:
        def initialize(self, **kwargs):
            raise RuntimeError("boom")

        def terminal_info(self):
            return None

    with caplog.at_level(logging.DEBUG):
        report = MT5Connection(settings_with_credentials(), module=Exploding()).connect()
    assert SECRET not in caplog.text
    assert report.code == "MT5_TERMINAL_NOT_AVAILABLE"


# ------------------------------------------------------------------ database
def test_no_mt5_table_has_a_credential_column():
    offenders = [(table.name, column.name)
                 for table in Base.metadata.sorted_tables if table.name.startswith("mt5_")
                 for column in table.columns
                 if any(token in column.name.lower() for token in CREDENTIAL_TOKENS)]
    assert offenders == [], offenders


def test_persisted_rows_contain_no_credential_and_only_a_masked_login(db_session):
    MT5ReadOnlyService(db_session, client=connected_client()).connect()
    for model in (MT5AccountRecord, MT5AccountSnapshotRecord, MT5ConnectionEventRecord):
        for row in db_session.query(model).all():
            text = str({c.name: getattr(row, c.name) for c in model.__table__.columns})
            assert SECRET not in text
            assert "987654321" not in text, model.__name__
            assert not any(token in text.lower() for token in ("password=", "secret="))


def test_scrub_removes_secret_keys_at_any_depth():
    payload = {"login": 1, "password": SECRET, "inner": {"api_key": "x", "token": "y", "bid": 1.1},
               "rows": [{"secret": "z", "ask": 1.2}]}
    cleaned = scrub(payload)
    assert cleaned == {"login": 1, "inner": {"bid": 1.1}, "rows": [{"ask": 1.2}]}
    assert SECRET not in str(cleaned)


# ----------------------------------------------------------------------- API
def credential_keys(payload):
    """Walk a JSON payload and collect any key that names a credential."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if any(token in str(key).lower() for token in CREDENTIAL_TOKENS):
                found.append(str(key))
            found.extend(credential_keys(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(credential_keys(item))
    return found


def test_no_mt5_endpoint_returns_a_credential(client, db_session):
    """Checks JSON keys and secret values, not substrings.

    A status code such as MT5_CREDENTIALS_MISSING legitimately contains the word
    'credential'; a key named `password` never would.
    """
    for path in ("/mt5/status", "/mt5/account", "/mt5/symbols", "/mt5/health",
                 "/mt5/positions", "/mt5/orders", "/mt5/data-quality", "/mt5/snapshots",
                 "/mt5/tick/EURUSD", "/mt5/candles/EURUSD/M15", "/dashboard/mt5"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert credential_keys(response.json()) == [], path
        assert SECRET not in response.text, path
        assert "987654321" not in response.text, path


def test_the_connect_endpoint_returns_only_a_masked_login(client):
    body = client.post("/mt5/connect").json()
    assert credential_keys(body) == []
    assert body["read_only"] is True and body["execution_enabled"] is False
    assert body.get("login") in (None, mask_login(None)) or body["login"].startswith("*")


# -------------------------------------------------------------------- source
def test_no_credential_literal_is_committed_in_source():
    pattern = re.compile(r"MT5_PASSWORD\s*=\s*['\"].+['\"]|mt5_password\s*=\s*['\"].+['\"]")
    offenders = []
    for path in list(ROOT.glob("execution/**/*.py")) + list(ROOT.glob("config/*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}")
    assert offenders == [], offenders


def test_env_example_ships_empty_credential_placeholders():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        assert f"{key}=\n" in text or text.rstrip().endswith(f"{key}="), key


def test_env_is_not_tracked_by_git():
    tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True)
    assert tracked.stdout.strip() == "", ".env must never be tracked"
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [line.strip() for line in ignore]
