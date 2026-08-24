from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import COTReport


class COTRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, values: dict[str, Any]) -> tuple[COTReport, bool]:
        query = select(COTReport).where(
            COTReport.report_date == values["report_date"],
            COTReport.market == values["market"],
            COTReport.contract == values["contract"],
            COTReport.source == values["source"],
        )
        existing = self.session.scalar(query)
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            self.session.commit()
            self.session.refresh(existing)
            return existing, False
        report = COTReport(**values)
        self.session.add(report)
        try:
            self.session.commit()
            self.session.refresh(report)
            return report, True
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(query)
            if existing is None:
                raise
            return existing, False

    def upsert_many(self, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        inserted = updated = 0
        for row in rows:
            _, created = self.upsert(row)
            inserted += int(created)
            updated += int(not created)
        return inserted, updated

    def list(self, *, market: str | None = None, offset: int = 0, limit: int = 100) -> list[COTReport]:
        query = select(COTReport)
        if market:
            query = query.where(COTReport.market.ilike(f"%{market}%"))
        query = query.order_by(COTReport.report_date.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(query))

