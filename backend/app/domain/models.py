"""Declarative table definitions.

This module contains schema only: no engine, no session, no queries. Importing it
performs no I/O, which preserves the domain layer's property of being exercisable
without infrastructure.

Two deliberate choices worth stating:

Enumerated values are stored as plain strings rather than database enum types.
Adding a member to the domain vocabulary therefore never requires a migration, and
validation stays at the Pydantic boundary where it belongs.

Timestamps use a UTC-normalising type decorator. SQLite does not persist offsets,
so a naive read-back would silently break SLA arithmetic. The decorator guarantees
that every datetime leaving the database is timezone-aware in UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.enums import Status, SubStatus


def utcnow() -> datetime:
    """The single time authority for persistence. Always aware, always UTC."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Round-trips datetimes as aware UTC regardless of backend storage fidelity."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base with deterministic constraint names."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Asset(Base):
    """A physical location. The permanent unit of record.

    The evidentiary standard is fixed here at intake time, before the repairing
    party is known, so it cannot be weakened later by the party being audited.

    last_event_seq and chain_head_hash are a cache of the chain tip. They make
    appending constant-time; verify_chain recomputes from the events themselves and
    does not trust these values.
    """

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(32), default="road_segment")
    ward: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=50.0)

    defect_claim: Mapped[str] = mapped_column(Text, default="")
    evidence_standard: Mapped[list[str]] = mapped_column(JSON, default=list)
    min_repair_minutes: Mapped[int] = mapped_column(Integer, default=120)

    last_event_seq: Mapped[int] = mapped_column(Integer, default=0)
    chain_head_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    complaints: Mapped[list[Complaint]] = relationship(
        back_populates="asset", lazy="raise", passive_deletes=True
    )
    events: Mapped[list[Event]] = relationship(
        back_populates="asset", lazy="raise", passive_deletes=True
    )


class Complaint(Base):
    """A single report against an asset. Temporary; the asset is not."""

    __tablename__ = "complaints"
    __table_args__ = (
        Index("ix_complaints_asset_status", "asset_id", "status"),
        Index("ix_complaints_ward_created", "ward", "created_at"),
        Index("ix_complaints_queue", "status", "priority_score"),
        Index("ix_complaints_sla", "sla_deadline"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), index=True)
    reporter_id: Mapped[str] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    ward: Mapped[str] = mapped_column(String(32))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)

    status: Mapped[str] = mapped_column(String(16), default=Status.REPORTED.value)
    sub_status: Mapped[str] = mapped_column(String(32), default=SubStatus.TRIAGED.value)

    assessed_urgency: Mapped[str] = mapped_column(String(4), default="P3")
    urgency: Mapped[str] = mapped_column(String(4), default="P3")
    impact_score: Mapped[int] = mapped_column(Integer, default=0)
    history_risk: Mapped[float] = mapped_column(Float, default=0.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)

    department: Mapped[str] = mapped_column(String(48))
    assignee_department: Mapped[str | None] = mapped_column(String(48), default=None)
    assigned_officer_id: Mapped[str | None] = mapped_column(String(64), default=None)

    triage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    min_repair_minutes: Mapped[int] = mapped_column(Integer, default=120)

    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    sla_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    asset: Mapped[Asset] = relationship(back_populates="complaints", lazy="raise")
    attempts: Mapped[list[ClosureAttempt]] = relationship(
        back_populates="complaint", lazy="raise", passive_deletes=True
    )


class ClosureAttempt(Base):
    """One departmental claim that the defect has been eliminated.

    Every attempt is retained, including rejected ones. An attempt is never
    overwritten by a retry; the retry is a new row, which is what makes a pattern
    of failed closures visible on the asset.
    """

    __tablename__ = "closure_attempts"
    __table_args__ = (
        UniqueConstraint("complaint_id", "attempt_number", name="uq_attempt_number"),
        Index("ix_attempts_asset_submitted", "asset_id", "submitted_at"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(
        ForeignKey("complaints.id", ondelete="RESTRICT"), index=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)

    officer_id: Mapped[str] = mapped_column(String(64), index=True)
    remarks: Mapped[str] = mapped_column(Text)
    work_order_reference: Mapped[str | None] = mapped_column(String(64), default=None)
    work_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    audited_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    chain_sufficient: Mapped[bool | None] = mapped_column(Boolean, default=None)
    reuse_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    model_used: Mapped[str | None] = mapped_column(String(64), default=None)

    forensic_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    deficiencies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    complaint: Mapped[Complaint] = relationship(back_populates="attempts", lazy="raise")
    evidence: Mapped[list[EvidenceFile]] = relationship(
        back_populates="attempt", lazy="raise", passive_deletes=True
    )


class EvidenceFile(Base):
    """A stored file plus the deterministic measurements taken from it.

    The original bytes are never re-encoded. Only a derived preview is compressed,
    because re-encoding an original destroys the EXIF the temporal and geospatial
    links depend on, which would produce false deficiencies on honest uploads.
    """

    __tablename__ = "evidence_files"
    __table_args__ = (
        Index("ix_evidence_asset", "asset_id"),
        Index("ix_evidence_phash", "phash"),
        Index("ix_evidence_content_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    complaint_id: Mapped[str | None] = mapped_column(
        ForeignKey("complaints.id", ondelete="RESTRICT"), default=None
    )
    attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("closure_attempts.id", ondelete="RESTRICT"), index=True, default=None
    )

    kind: Mapped[str] = mapped_column(String(16), default="other")
    storage_key: Mapped[str] = mapped_column(String(200))
    thumbnail_key: Mapped[str | None] = mapped_column(String(200), default=None)
    content_hash: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    phash: Mapped[str | None] = mapped_column(String(16), default=None)
    dhash: Mapped[str | None] = mapped_column(String(16), default=None)

    exif: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    gps_lat: Mapped[float | None] = mapped_column(Float, default=None)
    gps_lng: Mapped[float | None] = mapped_column(Float, default=None)
    camera_make: Mapped[str | None] = mapped_column(String(64), default=None)
    camera_model: Mapped[str | None] = mapped_column(String(64), default=None)
    software_tag: Mapped[str | None] = mapped_column(String(120), default=None)
    c2pa_status: Mapped[str] = mapped_column(String(24), default="absent")

    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    attempt: Mapped[ClosureAttempt | None] = relationship(back_populates="evidence", lazy="raise")


class Decision(Base):
    """A citizen or reviewer decision on an attempt.

    For reviewers, reason carries the mandatory justification. It is required at
    the API boundary and permanently recorded here and on the passport.
    """

    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_attempt", "attempt_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("closure_attempts.id", ondelete="RESTRICT"))
    complaint_id: Mapped[str] = mapped_column(
        ForeignKey("complaints.id", ondelete="RESTRICT"), index=True
    )

    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text, default=None)

    chain_sufficient_at_decision: Mapped[bool | None] = mapped_column(Boolean, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Event(Base):
    """One append-only entry in an asset's hash-chained passport.

    No code path in this application updates or deletes an events row. The chain
    detects out-of-band modification. Note the honest limit: an attacker with write
    access who rewrites every subsequent hash and the asset tip would produce a
    self-consistent chain. Anchoring the tip externally, for example publishing a
    daily head hash, is the roadmap mitigation and is not implemented here.
    """

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("asset_id", "seq", name="uq_events_asset_seq"),)

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    seq: Mapped[int] = mapped_column(Integer)

    event_type: Mapped[str] = mapped_column(String(48))
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(String(64), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))

    asset: Mapped[Asset] = relationship(back_populates="events", lazy="raise")


class Notification(Base):
    """Transactional outbox and inbox in one table.

    The row is written in the same transaction as the state change it describes, so
    a status can never change without a corresponding notification existing. The
    dispatcher then moves delivery_status forward independently.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient", "recipient_id", "read_at"),
        Index("ix_notifications_outbox", "delivery_status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    recipient_id: Mapped[str] = mapped_column(String(64))
    recipient_type: Mapped[str] = mapped_column(String(16))

    complaint_id: Mapped[str | None] = mapped_column(String(16), default=None)
    asset_id: Mapped[str | None] = mapped_column(String(16), default=None)
    event_type: Mapped[str] = mapped_column(String(48))

    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    delivery_status: Mapped[str] = mapped_column(String(16), default="pending")
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class IdSequence(Base):
    """Durable counters for human-readable identifiers.

    Survives restarts, so identifiers never collide with persisted rows. A rolled
    back transaction may leave a gap; identifiers are opaque labels, not counts.
    """

    __tablename__ = "id_sequences"

    name: Mapped[str] = mapped_column(String(8), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
