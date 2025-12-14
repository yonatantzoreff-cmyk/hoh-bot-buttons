"""SQLAlchemy ORM models for core messaging tables."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Message(Base):
    __tablename__ = "messages"

    message_id = Column(BigInteger, primary_key=True)
    org_id = Column(BigInteger, nullable=False)
    conversation_id = Column(BigInteger, ForeignKey("conversations(conversation_id)"), nullable=False)
    event_id = Column(BigInteger, ForeignKey("events(event_id)"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("contacts(contact_id)"), nullable=False)
    direction = Column(String, nullable=False)
    template_id = Column(BigInteger, ForeignKey("message_templates(template_id)"))
    body = Column(Text, nullable=False)
    raw_payload = Column(JSONB)
    whatsapp_msg_sid = Column(String)
    sent_at = Column(DateTime(timezone=True))
    received_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class MessageDeliveryLog(Base):
    __tablename__ = "message_delivery_log"

    delivery_id = Column(BigInteger, primary_key=True)
    org_id = Column(BigInteger, ForeignKey("orgs(org_id)"), nullable=False)
    message_id = Column(BigInteger, ForeignKey("messages(message_id)"), nullable=False)
    status = Column(String, nullable=False)
    error_code = Column(String)
    error_message = Column(Text)
    provider = Column(String, nullable=False, default="twilio")
    provider_payload = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
