"""Pydantic v2 request/response schemas for the Judiciary Help System.

These models define the API contract and are intentionally decoupled from the
SQLAlchemy ORM models in ``app.models``; the ``from_attributes=True`` config
lets read schemas be built straight from ORM instances.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    CITIZEN = "citizen"
    STAFF = "staff"
    ADMIN = "admin"


class CaseType(str, Enum):
    CIVIL = "civil"
    CRIMINAL = "criminal"
    FAMILY = "family"
    LABOR = "labor"
    LAND = "land"
    WRIT = "writ"
    APPEAL = "appeal"


class CaseStatus(str, Enum):
    FILED = "filed"
    PENDING = "pending"
    IN_HEARING = "in_hearing"
    ADJOURNED = "adjourned"
    DISPOSED = "disposed"
    DISMISSED = "dismissed"


class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    AWAITING_INFO = "awaiting_info"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str | None = None
    role: UserRole | None = None
    exp: int | None = None


class Message(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)
    role: UserRole = UserRole.CITIZEN


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool = True
    created_at: datetime


# ---------------------------------------------------------------------------
# Hearings
# ---------------------------------------------------------------------------


class HearingBase(BaseModel):
    hearing_date: datetime
    judge: str | None = Field(default=None, max_length=120)
    courtroom: str | None = Field(default=None, max_length=120)
    purpose: str | None = Field(default=None, max_length=255)
    outcome: str | None = None


class HearingCreate(HearingBase):
    case_id: int


class HearingUpdate(BaseModel):
    hearing_date: datetime | None = None
    judge: str | None = Field(default=None, max_length=120)
    courtroom: str | None = Field(default=None, max_length=120)
    purpose: str | None = Field(default=None, max_length=255)
    outcome: str | None = None


class HearingRead(HearingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class CaseBase(BaseModel):
    case_number: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=2, max_length=255)
    case_type: CaseType
    court: str = Field(min_length=2, max_length=120)
    status: CaseStatus = CaseStatus.FILED
    description: str | None = None
    filing_date: date | None = None
    next_hearing_date: date | None = None


class CaseCreate(CaseBase):
    pass


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    case_type: CaseType | None = None
    court: str | None = Field(default=None, min_length=2, max_length=120)
    status: CaseStatus | None = None
    description: str | None = None
    filing_date: date | None = None
    next_hearing_date: date | None = None


class CaseRead(CaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    hearings: list[HearingRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Help-desk categories
# ---------------------------------------------------------------------------


class CategoryBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9-]+$")
    description: str | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool = True


# ---------------------------------------------------------------------------
# Help-desk ticket comments
# ---------------------------------------------------------------------------


class TicketCommentBase(BaseModel):
    body: str = Field(min_length=1)
    is_internal: bool = False  # internal notes are hidden from citizens


class TicketCommentCreate(TicketCommentBase):
    pass


class TicketCommentRead(TicketCommentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author_id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Help-desk tickets
# ---------------------------------------------------------------------------


class HelpTicketBase(BaseModel):
    subject: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10)
    priority: TicketPriority = TicketPriority.NORMAL
    category_id: int | None = None
    case_id: int | None = None


class HelpTicketCreate(HelpTicketBase):
    pass


class HelpTicketUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, min_length=10)
    priority: TicketPriority | None = None
    status: TicketStatus | None = None
    category_id: int | None = None
    assigned_to_id: int | None = None


class HelpTicketRead(HelpTicketBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: TicketStatus = TicketStatus.OPEN
    requester_id: int
    assigned_to_id: int | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    category: CategoryRead | None = None
    comments: list[TicketCommentRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


# ---------------------------------------------------------------------------
# Case lookup (citizen-facing case-number search)
# ---------------------------------------------------------------------------


class Language(str, Enum):
    EN = "en"
    BN = "bn"


class CaseKind(str, Enum):
    CIVIL = "civil"
    CRIMINAL = "criminal"
    CR = "cr"  # Criminal Revision / Rule
    GR = "gr"  # General Register (police-reported criminal case)
    UNKNOWN = "unknown"


class PartyRole(str, Enum):
    PLAINTIFF = "plaintiff"
    DEFENDANT = "defendant"
    PETITIONER = "petitioner"
    RESPONDENT = "respondent"
    ACCUSED = "accused"
    COMPLAINANT = "complainant"
    UNKNOWN = "unknown"


class RedactionType(str, Enum):
    PHONE = "phone"
    NID = "nid"
    EMAIL = "email"
    ADDRESS = "address"
    BANK_ACCOUNT = "bank_account"


class ParsedCaseNumber(BaseModel):
    """Structured form of a raw case number like ``সি.আর. ৮৪৪/২০২৩``."""

    raw: str
    normalized: str
    kind: CaseKind = CaseKind.UNKNOWN
    prefix: str | None = None
    serial: int | None = None
    year: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Party(BaseModel):
    name: str
    role: PartyRole = PartyRole.UNKNOWN
    redacted: bool = False


class PrivacyReport(BaseModel):
    """Summary of PII masking applied to a response (no original values stored)."""

    applied: bool = False
    total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


class CaseSummary(BaseModel):
    case_number: str
    normalized_number: str
    kind: CaseKind = CaseKind.UNKNOWN
    year: int | None = None
    court: str | None = None
    court_id: int | None = None
    subject: str | None = None
    parties: list[Party] = Field(default_factory=list)
    status: str | None = None
    next_hearing_date: date | None = None
    last_order_summary: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None


class CaseLookupRequest(BaseModel):
    case_number: str = Field(min_length=1, max_length=64)
    court_id: int | None = None
    court: str | None = Field(default=None, max_length=200)
    language: Language = Language.BN
    force_refresh: bool = False


class CaseLookupResponse(BaseModel):
    found: bool
    cached: bool = False
    # live | fallback | cache
    source: str = "live"
    language: Language = Language.BN
    parsed: ParsedCaseNumber | None = None
    summary: CaseSummary | None = None
    explanation: str | None = None
    next_steps: list[str] = Field(default_factory=list)
    privacy: PrivacyReport = Field(default_factory=PrivacyReport)
    message: str | None = None
    fetched_at: datetime | None = None
