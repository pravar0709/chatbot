"""FastAPI application entry point."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.db import init_db
from app.routes import router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up – initializing database")
    await init_db()
    logger.info(
        "Keys configured: %d | Model: %s | Failure sim: %s",
        len(settings.LLM_API_KEYS),
        settings.LLM_MODEL,
        settings.ENABLE_FAILURE_SIMULATION,
    )
    yield
    logger.info("Shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Lyftr Chatbot API", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Routes
app.include_router(router)


# ── Global exception handlers ────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Return 422 with detail field, never a stack trace."""
    errors = exc.errors()
    # Build a readable summary
    details = []
    for e in errors:
        loc = " -> ".join(str(l) for l in e.get("loc", []))
        msg = e.get("msg", "")
        details.append(f"{loc}: {msg}")
    return JSONResponse(
        status_code=422,
        content={"detail": details},
    )


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    """Catch-all: never leak stack traces."""
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error"},
    )
