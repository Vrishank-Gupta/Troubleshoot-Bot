"""FastAPI application entry point."""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, analytics, chat, escalations, sops
from app.config import get_settings

# Register all ORM models so Base.metadata is populated before create_all
import app.models.db_models  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


def _init_db():
    from app.database import Base, engine
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    from app.services.cache_service import _init_redis
    _init_redis(settings.redis_url)
    yield


app = FastAPI(
    title="SOP Troubleshooting Chatbot",
    description="Customer-facing troubleshooting chatbot driven by structured SOP flows.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def total_latency_middleware(request: Request, call_next):
    """Records total request time for /chat/* endpoints."""
    from app.middleware import latency as lat
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    if request.url.path.startswith("/chat"):
        lat.record(lat.STAGE_TOTAL, ms)
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again."},
    )


# Register routers
app.include_router(chat.router)
app.include_router(sops.router)
app.include_router(escalations.router)
app.include_router(analytics.router)
app.include_router(admin.router)


@app.get("/", tags=["health"])
def root():
    return {"message": "SOP Chatbot API is running.", "environment": settings.environment}


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "environment": settings.environment}
