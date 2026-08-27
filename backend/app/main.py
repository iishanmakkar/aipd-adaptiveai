from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import time

from app.config import settings
from app.database import init_db
from app.api.routes_auth import router as auth_router
from app.api.routes_session import router as session_router
from app.api.routes_query import router as query_router
from app.api.routes_transcribe import router as transcribe_router
from app.api.routes_vlm import router as vlm_router

logger = logging.getLogger(__name__)


# Rate limiting - simple in-memory store
_rate_limit_store: dict = {}


def check_rate_limit(client_ip: str, max_requests: int = 100, window_sec: int = 60) -> bool:
    """Simple rate limiting check."""
    now = time.time()
    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = []
    
    # Remove timestamps outside the window
    _rate_limit_store[client_ip] = [
        ts for ts in _rate_limit_store[client_ip] 
        if now - ts < window_sec
    ]
    
    if len(_rate_limit_store[client_ip]) >= max_requests:
        return False
    
    _rate_limit_store[client_ip].append(now)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - try to init DB but don't crash if unavailable (demo mode)
    try:
        await init_db()
        logger.info("Database connected successfully")
    except Exception as e:
        logger.warning(f"Database connection failed (demo mode): {e}")
    yield
    # Shutdown - cleanup rate limit store
    _rate_limit_store.clear()


app = FastAPI(
    title="AdaptiveAI Backend",
    description="Backend API for AdaptiveAI - Context-Aware AI for Independent Digital Accessibility",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)


# Security: TrustedHost middleware - only allow specific hosts in production
if not settings.debug:
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["your-domain.com", "api.your-domain.com"]
    )


# CORS - restrict in production
if settings.debug:
    allow_origins = ["*"]
else:
    allow_origins = [settings.frontend_url]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Rate-Limit-Remaining"],
)


@app.middleware("http")
async def add_middleware_process_time(request: Request, call_next):
    start_time = time.time()
    # Generate request ID
    request_id = f"{id(request)}-{int(start_time)}"
    request.state.request_id = request_id
    
    # Rate limiting - real 429 (fixed bug: was Response with dict -> 500)
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip, max_requests=200, window_sec=60):
        return JSONResponse(
            content={"error": "Rate limit exceeded"},
            status_code=429,
            headers={"X-Rate-Limit-Remaining": "0", "Retry-After": "60"}
        )
    
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Rate-Limit-Remaining"] = str(
        max(0, 200 - len(_rate_limit_store.get(client_ip, [])))
    )
    
    return response


# Include routers
app.include_router(auth_router)
app.include_router(session_router)
app.include_router(query_router)
app.include_router(transcribe_router)
app.include_router(vlm_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "adaptiveai-backend"}