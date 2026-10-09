"""Service layer: judiciary e-services scraping, parsing and explanation.

``scraper_service`` performs (rate-limited) HTTP requests; ``parser_service``
turns the raw HTML/JSON into typed structures; ``privacy_service`` masks PII;
``explainer_service`` renders bilingual plain-language summaries. Keep them
composed at the router layer, e.g.::

    from app.services import parser_service, scraper_service, explainer_service

    with scraper_service.JudiciaryScraper() as scraper:
        detail = parser_service.parse_case_detail(
            scraper.fetch_case_detail(court_id=1, case_type=2, case_id="abc")
        )
"""

from app.services import (
    case_lookup_service,
    explainer_service,
    parser_service,
    privacy_service,
    scraper_service,
)

__all__ = [
    "case_lookup_service",
    "explainer_service",
    "parser_service",
    "privacy_service",
    "scraper_service",
]
