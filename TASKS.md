# Project Tracker — Judiciary Help System Bangladesh

Task tracking for this repo. GitHub issues/Projects can be linked here as the
canonical external tracker; this file is the in-repo mirror.

- External tracker: _TBD (link GitHub Project once created)_
- Repo: https://github.com/morshedgtc-lang/Judiciary-Help-System

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

## Phase 0 — Setup & tooling
- [x] Repo scaffold, git remote, initial commit
- [x] Virtualenv `.venv` + `requirements.txt` installed
- [x] Lint (ruff) verified — pytest pending test files
- [x] `deploy/` folder created

## Phase 1 — Core data layer
- [x] `database.py`/`models.py`: SQLite caching model (`CaseQueryCache`)
- [x] `schemas.py`: case-lookup request/response models

## Phase 2 — Services
- [x] `services/parser_service.py`: case-number regex engine (CR/GR/Civil/Criminal + year)
- [x] `services/scraper_service.py`: curl_cffi + httpx fallback, sessions, Cloudflare handling
- [x] `services/explainer_service.py`: plain Bangla/English explanations
- [x] Privacy guardrails: PII redaction/sanitization (`services/privacy_service.py`)
- [x] Case-lookup orchestration service (scrape -> parse -> cache -> explain)

## Phase 3 — Web app
- [x] `main.py`: routes, CORS, lifespan, template/static mounting
- [x] `routers/case_lookup.py`: POST + GET `/api/v1/cases/lookup`
- [x] `templates/index.html`: Tailwind responsive bilingual UI
- [x] `static/app.js`: lookup form + result rendering

## Phase 4 — Docs, tests, deploy
- [x] `README.md`: setup, architecture, legal disclaimers, configuration
- [x] Tests (parser, scraper fallback, PII redaction, cache, lookup orchestration)
- [x] Deploy artifacts in `deploy/` (Dockerfile, Procfile, notes) + `.dockerignore`

## Phase 5 — Live validation & resilience
- [x] Live end-to-end lookup vs the real portal (Chandpur, CJM court id 930,
      case `সি. আর. মামলা - ৬৩১/২০২৫` → found, status, next hearing)
- [x] Case-number search formats (only bare `serial/year`, Latin + Bengali digits)
- [x] Detail-page parsing: hearing-history table + identity row, `caseno` required
- [x] Cause-list marquee/table disambiguation (`_data_table`)
- [x] Unicode folding for precomposed/composed Bengali (NFKC) + dict-shaped districts
- [x] Raw-HTTP response cache (`app/services/http_cache.py`): tiered memory-LRU +
      `http_response_cache` table; route-aware TTLs (30d masters / 30min today's
      cause list / 24h caseinfo); stale fallback on outage
- [x] Cache unit tests (`tests/test_http_cache.py`) + live cache verification

## Backlog
- Introduce Alembic migrations before any schema changes in production
  (`http_response_cache` table is auto-created via `init_db` today).
- Scheduled cleanup of expired `http_response_cache` rows (max-age sweep).
