"""Idempotency (section 12).

One signal produces one order. The request id is derived from the decision
(signal, symbol, side, intent, strategy, trading day) rather than generated, so
a repeat submission is *recognisable* rather than merely improbable.

The registry checks two places: an in-process set, which catches a duplicate
inside one run, and the persisted execution requests, which catches a duplicate
across restarts. A store that cannot be read is treated as "cannot confirm this
is new", and the submission is refused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DUPLICATE_EXECUTION_REQUEST = "DUPLICATE_EXECUTION_REQUEST"
IDEMPOTENCY_STORE_UNAVAILABLE = "IDEMPOTENCY_STORE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class IdempotencyVerdict:
    request_id: str
    duplicate: bool
    reasons: tuple[str, ...] = ()
    first_seen: datetime | None = None

    @property
    def allowed(self) -> bool:
        return not self.duplicate and not self.reasons

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "duplicate": self.duplicate,
                "allowed": self.allowed, "reasons": list(self.reasons),
                "first_seen": self.first_seen}


class IdempotencyRegistry:
    """Fail-closed duplicate detection over an optional persistent store."""

    def __init__(self, repository: Any = None):
        self.repository = repository
        self._seen: dict[str, datetime] = {}

    def _stored(self, request_id: str) -> tuple[bool, datetime | None, str | None]:
        if self.repository is None:
            return False, None, None
        lookup = getattr(self.repository, "execution_exists", None)
        if lookup is None:
            return False, None, IDEMPOTENCY_STORE_UNAVAILABLE
        try:
            row = lookup(request_id)
        except Exception:
            logger.exception("idempotency lookup failed for %s", request_id)
            return False, None, IDEMPOTENCY_STORE_UNAVAILABLE
        if not row:
            return False, None, None
        stamp = getattr(row, "timestamp", None) if not isinstance(row, bool) else None
        return True, stamp, None

    def check(self, request_id: str) -> IdempotencyVerdict:
        key = str(request_id)
        if key in self._seen:
            return IdempotencyVerdict(key, True, (DUPLICATE_EXECUTION_REQUEST,), self._seen[key])
        stored, stamp, error = self._stored(key)
        if error:
            return IdempotencyVerdict(key, False, (error,))
        if stored:
            return IdempotencyVerdict(key, True, (DUPLICATE_EXECUTION_REQUEST,), stamp)
        return IdempotencyVerdict(key, False)

    def register(self, request_id: str, *, moment: datetime | None = None) -> IdempotencyVerdict:
        """Claim the id. A second claim for the same id reports the duplicate."""
        key = str(request_id)
        verdict = self.check(key)
        if verdict.allowed:
            self._seen[key] = moment or datetime.now(timezone.utc)
        return verdict

    def forget(self, request_id: str) -> None:
        """Only for a request that never reached the broker (a cancelled proposal)."""
        self._seen.pop(str(request_id), None)

    @property
    def known(self) -> tuple[str, ...]:
        return tuple(self._seen)
