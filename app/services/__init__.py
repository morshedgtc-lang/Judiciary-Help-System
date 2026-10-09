"""Service layer: judiciary e-services scraping and parsing.

``scraper_service`` performs (rate-limited) HTTP requests; ``parser_service``
turns the raw HTML/JSON into typed structures. Keep them composed at the router
layer, e.g.::

    from app.services import parser_service, scraper_service

    with scraper_service.JudiciaryScraper() as scraper:
        page = parser_service.parse_cause_list(scraper.fetch_cause_list(court_id))
"""

from app.services import parser_service, scraper_service

__all__ = ["parser_service", "scraper_service"]
