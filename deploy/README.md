# Deployment

This folder holds deployment artifacts. The application is a standard ASGI app
(`app.main:app`) and honours the `PORT` environment variable.

## Environment

Set these in your platform (never commit real secrets):

- `SECRET_KEY` — a long random string.
- `DATABASE_URL` — e.g. `postgresql+psycopg2://user:pass@host:5432/dbname`.
  Defaults to a local SQLite file, which is fine for a single-instance demo but
  **not** for multi-replica production.
- `CORS_ORIGINS` — comma-separated origins that may call the API.
- Optional scraper tuning: `JUDICIARY_MIN_INTERVAL`, `JUDICIARY_TIMEOUT`,
  `JUDICIARY_TRANSPORT`, `JUDICIARY_CACHE_TTL_MINUTES`, `JUDICIARY_HTTP_CACHE_ENABLED`.

Schema is created automatically on startup (dev convenience). For production,
introduce Alembic migrations before changing models.

## Option A — Docker

From the repository root:

```bash
docker build -f deploy/Dockerfile -t judiciary-help .
docker run -p 8000:8000 --env-file .env judiciary-help
```

## Option B — Railway (or any nixpacks/Procfile host)

1. Create a project and connect this repository.
2. Set the **Dockerfile path** to `deploy/Dockerfile` (root directory: repo
   root), or rely on `deploy/Procfile` if using the Procfile builder.
3. Add the environment variables above.
4. Deploy. The service listens on `$PORT`.

## Notes

- `curl_cffi` provides browser TLS impersonation and is installed from a wheel;
  the app falls back to `httpx` if it is unavailable.
- The scraper is deliberately rate-limited (`JUDICIARY_MIN_INTERVAL`) and
  cached (`JUDICIARY_CACHE_TTL_MINUTES`). Keep these values conservative to
  avoid being blocked by, and to be respectful of, the government portal.
