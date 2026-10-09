"""SQLAlchemy 2.0 ORM models for the Judiciary Help System.

Mirrors the API contract in :mod:`app.schemas`. The Python enums are imported
from ``app.schemas`` and reused as the single source of truth; they are stored
in the database as their lowercase values (``native_enum=False`` keeps the
schema portable across SQLite and PostgreSQL).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.schemas import CaseStatus, CaseType, TicketPriority, TicketStatus, UserRole


def _enum(enum_cls: type) -> SAEnum:
    """Store the enum's ``.value`` (e.g. ``"citizen"``) in a portable VARCHAR."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole), default=UserRole.CITIZEN)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    requested_tickets: Mapped[list[HelpTicket]] = relationship(
        back_populates="requester",
        foreign_keys="HelpTicket.requester_id",
    )
    assigned_tickets: Mapped[list[HelpTicket]] = relationship(
        back_populates="assigned_to",
        foreign_keys="HelpTicket.assigned_to_id",
    )
    comments: Mapped[list[TicketComment]] = relationship(back_populates="author")


# ---------------------------------------------------------------------------
# Cases & hearings
# ---------------------------------------------------------------------------


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    case_type: Mapped[CaseType] = mapped_column(_enum(CaseType), index=True)
    court: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[CaseStatus] = mapped_column(
        _enum(CaseStatus), default=CaseStatus.FILED, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    filing_date: Mapped[date | None] = mapped_column(Date)
    next_hearing_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    hearings: Mapped[list[Hearing]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="Hearing.hearing_date",
    )
    tickets: Mapped[list[HelpTicket]] = relationship(back_populates="case")


class Hearing(Base):
    __tablename__ = "hearings"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    hearing_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    judge: Mapped[str | None] = mapped_column(String(120))
    courtroom: Mapped[str | None] = mapped_column(String(120))
    purpose: Mapped[str | None] = mapped_column(String(255))
    outcome: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    case: Mapped[Case] = relationship(back_populates="hearings")


# ---------------------------------------------------------------------------
# Help-desk categories, tickets & comments
# ---------------------------------------------------------------------------


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tickets: Mapped[list[HelpTicket]] = relationship(back_populates="category")


class HelpTicket(Base):
    __tablename__ = "help_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(
        _enum(TicketStatus), default=TicketStatus.OPEN, index=True
    )
    priority: Mapped[TicketPriority] = mapped_column(
        _enum(TicketPriority), default=TicketPriority.NORMAL, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    case_id: Mapped[int | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"), index=True
    )
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    category: Mapped[Category | None] = relationship(back_populates="tickets")
    case: Mapped[Case | None] = relationship(back_populates="tickets")
    requester: Mapped[User] = relationship(
        back_populates="requested_tickets", foreign_keys=[requester_id]
    )
    assigned_to: Mapped[User | None] = relationship(
        back_populates="assigned_tickets", foreign_keys=[assigned_to_id]
    )
    comments: Mapped[list[TicketComment]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketComment.created_at",
    )


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("help_tickets.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    ticket: Mapped[HelpTicket] = relationship(back_populates="comments")
    author: Mapped[User] = relationship(back_populates="comments")


# ---------------------------------------------------------------------------
# Case-lookup cache
# ---------------------------------------------------------------------------

class HttpResponseCache(Base):
    """Raw HTTP response cache (tier-2, SQLite/Postgres) for portal requests.

    Backs :class:`app.services.http_cache.HttpCache` so repeated lookups for the
    same district/court/cause-list/case pages are served locally instead of
    hammering the government servers — over months of use the same static assets
    (geo tree, court lists, office units) are fetched only once. Only successful
    ``GET`` responses are stored; the per-route TTL keeps genuinely changing
    data (today's cause list) reasonably fresh.
    """

    __tablename__ = "http_response_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(512))
    params_json: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column()
    content_type: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    @property
    def is_fresh(self) -> bool:
        if self.expires_at is None:
            return True
        return self.expires_at > datetime.utcnow()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<HttpResponseCache {self.key!r} status={self.status_code}>"


class CaseQueryCache(Base):
    """Cached result of a citizen case-number lookup.

    Repeat lookups are served from here so we never spam the government servers
    (avoiding rate limits / IP blocks), and so results remain available when the
    upstream portal is down. ``query_key`` is the normalized case number plus an
    optional court scope.
    """

    __tablename__ = "case_query_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    case_number: Mapped[str] = mapped_column(String(64), index=True)
    normalized_number: Mapped[str] = mapped_column(String(64), index=True)
    court_id: Mapped[int | None] = mapped_column(index=True)
    # found | not_found | error
    status: Mapped[str] = mapped_column(String(16), default="found", index=True)
    # live | fallback
    source: Mapped[str] = mapped_column(String(16), default="live")
    http_status: Mapped[int | None] = mapped_column()
    payload: Mapped[str | None] = mapped_column(Text)  # serialized response JSON
    hit_count: Mapped[int] = mapped_column(default=0)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    @property
    def is_fresh(self) -> bool:
        """Whether this entry may still be served without re-fetching."""
        if self.status == "error":
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > datetime.utcnow()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CaseQueryCache {self.query_key!r} status={self.status} "
            f"hits={self.hit_count}>"
        )
