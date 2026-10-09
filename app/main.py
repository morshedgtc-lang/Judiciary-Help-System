"""FastAPI entrypoint for the Judiciary Help System.

Run locally with::

    uvicorn app.main:app --reload

Interactive docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.database import init_db
from app.routers import case_lookup

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Create tables on startup (dev convenience; production uses Alembic).
    init_db()
    yield


app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(case_lookup.router, prefix=settings.api_v1_prefix)


@app.get("/", response_class=HTMLResponse, tags=["web"])
def index(request: Request) -> HTMLResponse:
    """Serve the citizen-facing lookup page."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "project_name": settings.project_name,
            "version": settings.version,
            "api_prefix": settings.api_v1_prefix,
        },
    )


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
