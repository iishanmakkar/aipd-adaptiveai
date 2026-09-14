from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
import logging
import os
import time
from collections import deque

from jose import JWTError, jwt

from app.config import settings
from app.database import init_db
from app.api.routes_auth import router as auth_router
from app.api.routes_session import router as session_router
from app.api.routes_query import router as query_router
from app.api.routes_transcribe import router as transcribe_router
from app.api.routes_vlm import router as vlm_router
from app.api.routes_preferences import router as preferences_router

logger = logging.getLogger("adaptiveai.access")

# Emit the structured access log on stdout: uvicorn's root logger defaults to
# WARNING, which silently swallowed every info line.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# Production guard: a deployment that declares itself production must never
# boot with DEBUG=True (it would auto-login every visitor as the demo user and
# open CORS to *). Set ADAPTIVEAI_PRODUCTION=1 in real deployments.
if os.getenv("ADAPTIVEAI_PRODUCTION", "").strip() in ("1", "true", "True") and settings.debug:
    raise RuntimeError(
        "Refusing to start: ADAPTIVEAI_PRODUCTION is set but DEBUG=True in backend/.env. "
        "DEBUG=True auto-logs every visitor in as the demo user and allows CORS from any origin."
    )


# ---- lightweight in-process metrics (visible at GET /api/metrics) ----
_METRICS = {
    "total_requests": 0,
    "total_2xx": 0,
    "total_4xx": 0,
    "total_5xx": 0,
    "started_at": time.time(),
}
_LATENCIES: deque[float] = deque(maxlen=1000)


def _record_metrics(status_code: int, latency_ms: float) -> None:
    _METRICS["total_requests"] += 1
    if status_code < 400:
        _METRICS["total_2xx"] += 1
    elif status_code < 500:
        _METRICS["total_4xx"] += 1
    else:
        _METRICS["total_5xx"] += 1
    _LATENCIES.append(latency_ms)


def _percentile(p: float) -> float | None:
    if not _LATENCIES:
        return None
    ordered = sorted(_LATENCIES)
    idx = min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))
    return round(ordered[idx], 1)


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


def _rate_limit_key(request: Request) -> str:
    """Per-user buckets when a valid bearer token is present, per-IP otherwise.

    Keying on IP alone is wrong behind Docker/reverse-proxy NAT: every browser
    appears to come from one source address, so a single abusive client could
    exhaust the shared 200/min bucket and lock out everyone else. Decoding the
    JWT (no DB hit) gives each authenticated user their own bucket.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = jwt.decode(auth[7:].strip(), settings.jwt_secret,
                                 algorithms=[settings.jwt_algorithm])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except JWTError:
            pass  # bad/expired token: fall through to IP bucket
    return f"ip:{request.client.host if request.client else 'unknown'}"


@app.middleware("http")
async def add_middleware_process_time(request: Request, call_next):
    start_time = time.time()
    # Generate request ID
    request_id = request.headers.get("X-Request-ID") or f"{id(request)}-{int(start_time)}"
    request.state.request_id = request_id

    # Rate limiting - real 429 (fixed bug: was Response with dict -> 500)
    client_ip = request.client.host if request.client else "unknown"
    rate_key = _rate_limit_key(request)

    # Second layer for the unauthenticated auth endpoints: they are IP-keyed
    # (no token yet), so behind NAT one abuser could exhaust the shared bucket
    # and lock everyone out of logging in - and mint unlimited fresh user
    # buckets via /auth/register to farm the per-user limit. Account
    # creation/login is a rare action for real users, so it gets a tight,
    # separate per-IP budget that does not touch normal traffic.
    if request.url.path in ("/auth/register", "/auth/login"):
        auth_key = f"auth:{request.url.path}:{client_ip}"
        if not check_rate_limit(auth_key, max_requests=10, window_sec=60):
            _record_metrics(429, (time.time() - start_time) * 1000)
            return JSONResponse(
                content={"error": "Too many authentication attempts; try again later."},
                status_code=429,
                headers={"X-Rate-Limit-Remaining": "0", "Retry-After": "60"},
            )

    if not check_rate_limit(rate_key, max_requests=200, window_sec=60):
        _record_metrics(429, (time.time() - start_time) * 1000)
        return JSONResponse(
            content={"error": "Rate limit exceeded"},
            status_code=429,
            headers={"X-Rate-Limit-Remaining": "0", "Retry-After": "60"}
        )

    response = await call_next(request)
    latency_ms = round((time.time() - start_time) * 1000, 1)
    response.headers["X-Process-Time"] = str(latency_ms / 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Rate-Limit-Remaining"] = str(
        max(0, 200 - len(_rate_limit_store.get(rate_key, [])))
    )

    # Structured access log: one JSON line per request, correlated on request_id
    # across backend -> intent-engine -> agents (each service logs the same id).
    _record_metrics(response.status_code, latency_ms)
    logger.info(json.dumps({
        "event": "request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "latency_ms": latency_ms,
        "client": client_ip,
    }))

    return response


@app.get("/api/metrics")
async def metrics():
    """In-process request metrics for ops visibility. Counts reset on restart."""
    return {
        **_METRICS,
        "uptime_seconds": round(time.time() - _METRICS["started_at"], 1),
        "latency_ms": {
            "p50": _percentile(50),
            "p95": _percentile(95),
            "p99": _percentile(99),
        },
    }


# Include routers
app.include_router(auth_router)
app.include_router(session_router)
app.include_router(query_router)
app.include_router(transcribe_router)
app.include_router(vlm_router)
app.include_router(preferences_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "adaptiveai-backend"}