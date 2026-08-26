"""Symbols are discovered from the terminal, never hardcoded."""
import ast
import pathlib

import pytest

from execution.mt5.symbols import (
    SYMBOL_MAPPING_AMBIGUOUS, SYMBOL_NOT_FOUND, AmbiguousSymbolError,
    SymbolResolutionError, SymbolResolver, canonical_name,
)
from tests.phase10_helpers import connected_client, module

CANONICAL = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")


@pytest.mark.parametrize(("broker", "canonical"), [
    ("EURUSD", "EURUSD"), ("EURUSDm", "EURUSD"), ("EURUSDc", "EURUSD"),
    ("EURUSD.a", "EURUSD"), ("EURUSD_i", "EURUSD"), ("mEURUSD", "EURUSD"),
    ("XAUUSDm", "XAUUSD"),
])
def test_broker_suffixes_and_prefixes_resolve(broker, canonical):
    resolver = SymbolResolver([broker], CANONICAL)
    info = resolver.resolve(canonical)
    assert info.name == broker and info.canonical == canonical


def test_the_resolver_refuses_to_choose_between_two_variants():
    resolver = SymbolResolver(["EURUSDm", "EURUSDc"], CANONICAL)
    with pytest.raises(AmbiguousSymbolError) as error:
        resolver.resolve("EURUSD")
    assert error.value.code == SYMBOL_MAPPING_AMBIGUOUS
    assert error.value.candidates == ("EURUSDc", "EURUSDm")


def test_an_exact_match_wins_over_a_decorated_one():
    """EURUSD alongside EURUSDm is not ambiguous: the exact name is unambiguous."""
    resolver = SymbolResolver(["EURUSD", "EURUSDm"], CANONICAL)
    assert resolver.resolve("EURUSD").name == "EURUSD"


def test_an_unknown_symbol_reports_not_found():
    resolver = SymbolResolver(["GBPUSDm"], CANONICAL)
    with pytest.raises(SymbolResolutionError) as error:
        resolver.resolve("EURUSD")
    assert error.value.code == SYMBOL_NOT_FOUND


def test_try_resolve_reports_instead_of_raising():
    resolver = SymbolResolver(["EURUSDm", "EURUSDc"], CANONICAL)
    info, code, candidates = resolver.try_resolve("EURUSD")
    assert info is None and code == SYMBOL_MAPPING_AMBIGUOUS and candidates


def test_reverse_mapping_returns_the_alm_canonical_name():
    resolver = SymbolResolver(["EURUSDm", "XAUUSDm"], CANONICAL)
    assert resolver.canonical_for("EURUSDm") == "EURUSD"
    assert resolver.canonical_for("XAUUSDm") == "XAUUSD"


def test_an_unrelated_broker_symbol_is_left_normalized():
    resolver = SymbolResolver(["BTCUSDm"], CANONICAL)
    assert resolver.canonical_for("BTCUSDm") == "BTCUSDM"


def test_a_long_affix_is_not_treated_as_the_same_symbol():
    resolver = SymbolResolver(["EURUSDEXTRA"], CANONICAL)
    with pytest.raises(SymbolResolutionError):
        resolver.resolve("EURUSD")


def test_the_client_discovers_symbols_from_the_terminal():
    client = connected_client(symbols=("EURUSDm", "GBPUSDm", "XAUUSDm"))
    assert client.get_symbols().ok
    assert client.resolver.names() == ("EURUSDm", "GBPUSDm", "XAUUSDm")
    assert client.resolve_symbol("EURUSD").data.name == "EURUSDm"


def test_the_client_reports_ambiguity_rather_than_guessing():
    client = connected_client(symbols=("EURUSDm", "EURUSDc"))
    result = client.resolve_symbol("EURUSD")
    assert not result.ok and result.code == SYMBOL_MAPPING_AMBIGUOUS
    assert set(result.reasons) == {"EURUSDc", "EURUSDm"}


def test_no_broker_symbol_is_hardcoded_in_the_mt5_package():
    """Canonical names may appear in config; decorated broker names may not appear in code."""
    offenders = []
    for path in pathlib.Path("execution/mt5").glob("*.py"):
        if path.name == "mock.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip()
                if len(text) > 6 and text[:6] in CANONICAL and text != text[:6]:
                    offenders.append(f"{path.name}:{text}")
    assert offenders == [], offenders


@pytest.mark.parametrize(("raw", "expected"), [
    ("eurusd", "EURUSD"), (" EUR/USD ", "EURUSD"), ("EUR-USD", "EURUSD"), (None, ""),
])
def test_canonical_name_normalization(raw, expected):
    assert canonical_name(raw) == expected
