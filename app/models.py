"""SQLAlchemy ORM models for core tables used by webhook flows."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Message(Base):
    __tablename__ = "messages"

    message_id = Column(BigInteger, primary_key=True)
    org_id = Column(BigInteger, nullable=False)
    whatsapp_msg_sid = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class MessageDeliveryLog(Base):
    __tablename__ = "message_delivery_log"

    delivery_id = Column(BigInteger, primary_key=True)
    org_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False)
    status = Column(Text, nullable=False)
    error_code: Optional[str] = Column(Text)
    error_message: Optional[str] = Column(Text)
    provider = Column(Text, nullable=False, default="twilio")
    provider_payload = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
