"""Immutable received sync bodies with bounded retention."""

from datetime import datetime

from sqlalchemy import DateTime, Index, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import BaseDbModel


class ReceivedCapture(BaseDbModel):
    object_key: Mapped[str] = mapped_column(Text, primary_key=True)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_receivedcapture_expires_at", "expires_at"),)

    def __repr__(self) -> str:
        return f"<ReceivedCapture(object_key={self.object_key!r})>"
