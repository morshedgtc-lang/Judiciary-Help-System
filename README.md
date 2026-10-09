# Judiciary Help System — Bangladesh

A citizen-facing web service that turns a raw **case number** (e.g.
`সি.আর. ৮৪৪/২০২৩`, `জি.আর. ১৩৭/২০২৬`, `844/2023`) into a clear, bilingual
(বাংলা / English) summary of a case: its type, court, status, next hearing date,
latest order, and the concrete next steps a person should take.

It is an **independent helper**, not a government site. It reads the public
Bangladesh judiciary cause-list/search portal, parses the results, masks all
personal data, and explains them in plain language — politely caching everything
so the government servers are never hammered.

## Features

- **Case-number understanding** — recognises Civil/Criminal, `CR`, `GR`, and
  more, in both Bengali and English numerals, with a two-digit-year heuristic
  (`G.R. 77/99` → 1999).
- **Plain-language explanation** — status detection, relative next-hearing
  dates ("আর ৫ দিন বাকি"), and tailored next steps, in Bangla or English.
- **Privacy by default** — phone numbers, NIDs, e-mail, addresses and bank
  accounts are masked (including Bengali-numeral forms) before anything is
  stored, explained or shown. Only aggregate counts are kept.
- **Respectful scraping** — browser TLS impersonation via `curl_cffi` with an
  `httpx` fallback, rate limiting, retries with backoff, and automatic
  Cloudflare/block detection with transport failover.
- **Resilient caching** — successful lookups are cached (SQLite by default); if
  the upstream portal is blocked or down, the last good result is served.

## Architecture

```
app/
  main.py                      FastAPI app: routes, CORS, templates, static
  core/config.py               Settings (env / .env via pydantic-settings)
  database.py                  SQLAlchemy engine, session, Base, init_db
  models.py                    ORM models (incl. CaseQueryCache)
  schemas.py                   Pydantic request/response contract
  routers/case_lookup.py       POST/GET /api/v1/cases/lookup
  services/
    scraper_service.py         HTTP transport (curl_cffi + httpx), throttling
    parser_service.py          HTML/JSON parsing + case-number regex engine
    privacy_service.py         PII redaction
    explainer_service.py       Bilingual plain-language summaries
    case_lookup_service.py     Orchestration: scrape → parse → cache → explain
  templates/index.html         Citizen UI (Tailwind)
  static/app.js                Lookup form + result rendering
tests/                         pytest suite (offline, httpx mock transport)
deploy/                        Dockerfile, Procfile, deployment notes
```

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit values
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 for the UI, or http://127.0.0.1:8000/docs for the
interactive API.

### API

```bash
# Look up a case
curl -X POST http://127.0.0.1:8000/api/v1/cases/lookup \
  -H "Content-Type: application/json" \
  -d '{"case_number": "সি.আর. ৮৪৪/২০২৩", "court_id": 900, "language": "bn"}'

# Or with query parameters
curl "http://127.0.0.1:8000/api/v1/cases/lookup?case_number=GR-137/2026&language=en"
```

## Configuration

Environment variables (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./judiciary_help.db` | SQLAlchemy database |
| `SECRET_KEY` | `change-me-in-production` | App secret (set in production) |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `JUDICIARY_BASE_URL` | `https://causelist.judiciary.gov.bd` | Source portal |
| `JUDICIARY_MIN_INTERVAL` | `1.0` | Minimum seconds between requests |
| `JUDICIARY_TIMEOUT` | `20.0` | Request timeout (seconds) |
| `JUDICIARY_TRANSPORT` | `auto` | `auto` \| `curl_cffi` \| `httpx` |
| `JUDICIARY_DEFAULT_DISTRICT` | `Chandpur` | Default district |
| `JUDICIARY_DEFAULT_COURT` | `চীফ জুডিসিয়াল` | Default court name |
| `JUDICIARY_CACHE_TTL_MINUTES` | `360` | Cache freshness window (lookup results) |
| `JUDICIARY_HTTP_CACHE_ENABLED` | `true` | Raw portal-response cache on/off |
| `JUDICIARY_HTTP_CACHE_CAPACITY` | `256` | Max in-memory cache entries |

The raw-response cache (`app/services/http_cache.py`) reroutes *all* portal page
requests: geo/court/office-unit master data is cached for **30 days**, past
cause lists for 30 days, today's cause list for **30 minutes**, and `caseinfo`
pages for 24 hours (route-aware TTLs in `ttl_for`). It is tiered — a bounded
in-memory LRU backed by the persistent `http_response_cache` table — so repeat
lookups over months of use never re-hit the portal, and during a portal outage
the last known response is served as a stale fallback.

## Tests

```bash
python -m pytest          # offline tests, no network required
ruff check app tests
```

## Deployment

See [`deploy/`](deploy/README.md). A `Dockerfile` and `Procfile` are provided;
the app honours the `PORT` environment variable and creates its schema on
startup.

## Legal & privacy

- This project is **not affiliated with or endorsed by** the Government of
  Bangladesh. It summarises publicly available judicial information.
- Always treat the **official court/portal record as authoritative**; this tool
  is a convenience layer and may lag or mis-read the source.
- Personal data is masked automatically. Do not rely on this service to obtain
  or share anyone's private information.
- Please scrape responsibly (the defaults already rate-limit and cache).
