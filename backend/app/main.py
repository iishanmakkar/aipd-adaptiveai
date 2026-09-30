from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
import logging
import os
import time
from collections import OrderedDict, deque

from jose import JWTError, jwt

from app.config import settings
from app.database import init_db
from app.api.routes_auth import router as auth_router
from app.api.routes_session import router as session_router
from app.api.routes_query import router as query_router
from app.api.routes_transcribe import router as transcribe_router
from app.api.routes_vlm import router as vlm_router
from app.api.routes_preferences import router as preferences_router
from app.api.routes_behavior import router as behavior_router
from app.api.routes_formfill import router as formfill_router
from app.api.routes_pagecontext import router as pagecontext_router
from app.api.routes_monitor import router as monitor_router
from app.api.routes_share import router as share_router
from app.api.routes_alt import router as alt_router

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

# Fail closed on a placeholder JWT secret in production: the shipped default is
# public, so any production boot without a real JWT_SECRET could forge tokens.
_JWT_PLACEHOLDER = "dev-secret-change-in-production-min-32-chars-long"
if (
    os.getenv("ADAPTIVEAI_PRODUCTION", "").strip() in ("1", "true", "True")
    and settings.jwt_secret.strip() in ("", _JWT_PLACEHOLDER)
):
    raise RuntimeError(
        "Refusing to start: ADAPTIVEAI_PRODUCTION is set but JWT_SECRET is the "
        "shipped default. Set a random 32+ char JWT_SECRET in backend/.env."
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


# Rate limiting - bounded in-memory store (evict oldest-idle past the cap:
# the key falls back to client IP, so unbounded growth is a memory-exhaustion
# vector - same shape as intent-engine).
_rate_limit_store: "OrderedDict[str, list[float]]" = OrderedDict()
_RATE_LIMIT_MAX_KEYS = 5000


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
    if not _rate_limit_store[client_ip]:
        _rate_limit_store.pop(client_ip, None)
        _rate_limit_store[client_ip] = []

    if len(_rate_limit_store[client_ip]) >= max_requests:
        return False

    _rate_limit_store[client_ip].append(now)
    _rate_limit_store.move_to_end(client_ip)
    while len(_rate_limit_store) > _RATE_LIMIT_MAX_KEYS:
        _rate_limit_store.popitem(last=False)
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


def _parse_allowed_hosts(raw: str) -> list[str]:
    """Split ALLOWED_HOSTS on commas, dropping blanks (env-driven TrustedHost)."""
    return [h.strip() for h in raw.split(",") if h.strip()]


# Security: TrustedHost middleware - enforced from ALLOWED_HOSTS in production.
# The old hardcoded placeholder domain is gone: an env you forget is now a
# loud warning, not a silent misconfiguration.
if not settings.debug:
    _allowed = _parse_allowed_hosts(settings.allowed_hosts)
    if _allowed:
        from fastapi.middleware.trustedhost import TrustedHostMiddleware
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed)
    else:
        logger.warning("ALLOWED_HOSTS is empty with DEBUG=False - TrustedHost skipped; set ALLOWED_HOSTS in production")


# CORS - explicit origins in every mode (browsers reject wildcard +
# credentials). Debug list covers local dev + the in-compose frontend
# hostname proof traffic arrives as; production is locked to FRONTEND_URL.
if settings.debug:
    allow_origins = [
        "http://localhost:3000", "http://localhost:5173",
        "http://127.0.0.1:3000", "http://127.0.0.1:5173",
        "http://frontend:5173",
    ]
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
    # The same treatment covers the Chromium-driving endpoints: each call
    # boots headless Chromium (+ a VLM call), so callers get their own small
    # budget instead of the shared 200/min bucket. Authenticated callers keep
    # their per-user split here too (same NAT reason as the global bucket);
    # anonymous callers fall back to per-IP.
    _HEAVY_BUDGETS = {"/api/form-fill": 10, "/api/page-context": 30}
    check_global = True
    # Normalize trailing slashes before budget lookup: "/api/form-fill/"
    # otherwise bypassed the heavy budget entirely (exact-match miss).
    path = request.url.path.rstrip("/") or "/"
    if path in ("/auth/register", "/auth/login"):
        auth_key = f"auth:{path}:{client_ip}"
        if not check_rate_limit(auth_key, max_requests=10, window_sec=60):
            _record_metrics(429, (time.time() - start_time) * 1000)
            return JSONResponse(
                content={"error": "Too many authentication attempts; try again later."},
                status_code=429,
                headers={"X-Rate-Limit-Remaining": "0", "Retry-After": "60"},
            )
        remaining_key, remaining_max = auth_key, 10
        check_global = False
    elif path in _HEAVY_BUDGETS:
        heavy_max = _HEAVY_BUDGETS[path]
        heavy_key = f"heavy:{path}:{rate_key}"
        if not check_rate_limit(heavy_key, max_requests=heavy_max, window_sec=60):
            _record_metrics(429, (time.time() - start_time) * 1000)
            return JSONResponse(
                content={"error": "Too many automated-browsing requests; try again later."},
                status_code=429,
                headers={"X-Rate-Limit-Remaining": "0", "Retry-After": "60"},
            )
        remaining_key, remaining_max = heavy_key, heavy_max
        check_global = False
    else:
        remaining_key, remaining_max = rate_key, 200

    if check_global and not check_rate_limit(rate_key, max_requests=200, window_sec=60):
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
        max(0, remaining_max - len(_rate_limit_store.get(remaining_key, [])))
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
app.include_router(behavior_router)
app.include_router(formfill_router)
app.include_router(pagecontext_router)
app.include_router(monitor_router)
app.include_router(share_router)
app.include_router(alt_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "adaptiveai-backend"}