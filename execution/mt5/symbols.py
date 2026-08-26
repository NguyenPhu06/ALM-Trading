"""Symbol discovery.

Broker symbol names are discovered from the terminal, never hardcoded. Exness and
other brokers decorate the canonical name with a suffix or prefix (EURUSDm,
EURUSDc, EURUSD.a, mEURUSD). When more than one broker symbol maps to the same
canonical name the resolver refuses to guess.

Three distinct names are kept apart deliberately:

* `name`       — the broker's own symbol, e.g. `EURUSDm`. Used when calling MT5.
* `normalized` — that name with separators stripped, e.g. `EURUSDM`. Matching only.
* `canonical`  — the ALM name, e.g. `EURUSD`. Everything downstream uses this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence

SYMBOL_MAPPING_AMBIGUOUS = "SYMBOL_MAPPING_AMBIGUOUS"
SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"

_CLEAN = re.compile(r"[^A-Z0-9]")


class SymbolResolutionError(LookupError):
    code = SYMBOL_NOT_FOUND

    def __init__(self, message: str, *, code: str | None = None, candidates: Sequence[str] = ()):
        super().__init__(message)
        if code:
            self.code = code
        self.candidates = tuple(candidates)


class AmbiguousSymbolError(SymbolResolutionError):
    code = SYMBOL_MAPPING_AMBIGUOUS


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    name: str
    normalized: str
    canonical: str | None = None
    description: str | None = None
    digits: int | None = None
    point: float | None = None
    spread: int | None = None
    trade_mode: Any = None
    visible: bool = True
    path: str | None = None


def canonical_name(raw: Any) -> str:
    """Strip separators and upper-case. Does not remove broker affixes."""
    return _CLEAN.sub("", str(raw or "").strip().upper())


class SymbolResolver:
    """Maps an ALM canonical name (EURUSD) onto the broker's symbol (EURUSDm).

    A broker name matches when its normalized form equals the canonical name, or
    when the canonical name is a prefix/suffix of it within `MAX_AFFIX` characters.
    """

    MAX_AFFIX = 4

    def __init__(self, symbols: Iterable[Any], canonical_symbols: Sequence[str] | None = None):
        self.symbols: tuple[SymbolInfo, ...] = tuple(self._coerce(item) for item in symbols)
        self._by_name = {info.name.upper(): info for info in self.symbols}
        self.canonical_symbols = tuple(canonical_name(item) for item in (canonical_symbols or ()))

    @staticmethod
    def _coerce(item: Any) -> SymbolInfo:
        if isinstance(item, SymbolInfo):
            return item
        if isinstance(item, str):
            return SymbolInfo(item, canonical_name(item))
        read = item.get if isinstance(item, dict) else (lambda n, d=None: getattr(item, n, d))
        name = str(read("name") or "")
        return SymbolInfo(
            name, canonical_name(name), description=read("description"), digits=read("digits"),
            point=read("point"), spread=read("spread"), trade_mode=read("trade_mode"),
            visible=bool(read("visible", True)), path=read("path"),
        )

    def _matches(self, info: SymbolInfo, target: str) -> bool:
        normalized = info.normalized
        if normalized == target:
            return True
        extra = len(normalized) - len(target)
        if 0 < extra <= self.MAX_AFFIX and (normalized.startswith(target) or normalized.endswith(target)):
            return True
        return False

    def candidates(self, symbol: str) -> tuple[SymbolInfo, ...]:
        target = canonical_name(symbol)
        if not target:
            return ()
        return tuple(info for info in self.symbols if self._matches(info, target))

    def resolve(self, symbol: str) -> SymbolInfo:
        """Return the single broker symbol, stamped with the requested canonical name.

        An exact match wins outright, so EURUSD alongside EURUSDm is not ambiguous.
        Two decorated variants with no exact match are ambiguous and the caller
        must choose — the resolver never picks for you.
        """
        target = canonical_name(symbol)
        matches = self.candidates(target)
        if not matches:
            raise SymbolResolutionError(f"no broker symbol matches {symbol}", code=SYMBOL_NOT_FOUND)
        exact = [info for info in matches if info.normalized == target]
        chosen = exact[0] if len(exact) == 1 else matches[0] if len(matches) == 1 else None
        if chosen is None:
            names = sorted(info.name for info in matches)
            raise AmbiguousSymbolError(
                f"{symbol} maps to multiple broker symbols: {', '.join(names)}",
                code=SYMBOL_MAPPING_AMBIGUOUS, candidates=names,
            )
        return replace(chosen, canonical=target)

    def try_resolve(self, symbol: str) -> tuple[SymbolInfo | None, str | None, tuple[str, ...]]:
        """Non-raising variant: (info, error_code, candidate_names)."""
        try:
            return self.resolve(symbol), None, ()
        except SymbolResolutionError as error:
            return None, error.code, error.candidates

    def canonical_for(self, broker_symbol: str) -> str:
        """Reverse mapping: EURUSDm -> EURUSD when a canonical list is configured."""
        normalized = canonical_name(broker_symbol)
        best: str | None = None
        for candidate in self.canonical_symbols:
            if normalized == candidate:
                return candidate
            extra = len(normalized) - len(candidate)
            if 0 < extra <= self.MAX_AFFIX and (
                normalized.startswith(candidate) or normalized.endswith(candidate)
            ) and (best is None or len(candidate) > len(best)):
                best = candidate
        return best or normalized

    def names(self) -> tuple[str, ...]:
        return tuple(info.name for info in self.symbols)
