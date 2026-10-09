"""Case-lookup API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import CaseLookupRequest, CaseLookupResponse, Language
from app.services import case_lookup_service

router = APIRouter(prefix="/cases", tags=["case-lookup"])


@router.post(
    "/lookup",
    response_model=CaseLookupResponse,
    summary="Look up a case by number",
)
def lookup_case(
    request: CaseLookupRequest,
    db: Session = Depends(get_db),
) -> CaseLookupResponse:
    """Fetch, parse, cache and explain a case for a citizen."""
    return case_lookup_service.lookup_case(db, request)


@router.get(
    "/lookup",
    response_model=CaseLookupResponse,
    summary="Look up a case by number (query-string form)",
)
def lookup_case_get(
    case_number: str = Query(min_length=1, max_length=64),
    court_id: int | None = Query(default=None),
    court: str | None = Query(default=None, max_length=200),
    language: Language = Query(default=Language.BN),
    force_refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> CaseLookupResponse:
    """Convenience GET wrapper around :func:`lookup_case`."""
    request = CaseLookupRequest(
        case_number=case_number,
        court_id=court_id,
        court=court,
        language=language,
        force_refresh=force_refresh,
    )
    return case_lookup_service.lookup_case(db, request)
