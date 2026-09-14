from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import logging
import time
import json

from app.config import settings
from app.schemas import ClassifyRequest, ClassifyResponse
from app.classifier import (
    llm_classify,
    keyword_classify,
    get_session_history,
    add_to_history,
    clear_session,
    clear_all_sessions,
)

logger = logging.getLogger("adaptiveai.intent")

# uvicorn's root logger defaults to WARNING; structured lines must reach stdout
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# Rate limiting store
_rate_limit_store: dict = {}


def check_rate_limit(client_ip: str, max_requests: int = 60, window_sec: int = 60) -> bool:
    """Simple rate limiting check for classify endpoint."""
    now = time.time()
    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = []
    
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
    _rate_limit_store.clear()
    clear_all_sessions()
    yield
    clear_all_sessions()


app = FastAPI(
    title="AdaptiveAI Intent & Context Engine",
    description="Classifies user intent and selects appropriate agent for accessibility assistance",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
)

# Security: TrustedHost
if not settings.debug:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["your-domain.com", "api.your-domain.com"]
    )

# CORS - allow all origins in integrated mode for inter-service communication
allow_origins = ["*"] if settings.debug else ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self' http: https: data:;"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    # Rate limit info
    client_ip = request.client.host if request.client else "unknown"
    if client_ip in _rate_limit_store:
        response.headers["X-Rate-Limit-Remaining"] = str(
            max(0, 60 - len(_rate_limit_store[client_ip]))
        )
    
    return response


@app.post("/intent/classify", response_model=ClassifyResponse)
async def classify_intent(http_request: Request, request: ClassifyRequest):
    """
    Classify user input into intent and select target agent.
    
    Uses LLM with conversation history for context-aware classification.
    Falls back to keyword-based classifier if LLM fails.
    Enforces rate limiting and request validation.
    """
    http_request.state.started_at = time.time()
    # `request` is the validated body model; headers/client live on the ASGI Request.
    client_ip = (
        http_request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (http_request.client.host if http_request.client else "unknown")
    )
    
    # Rate limiting
    if not check_rate_limit(client_ip, max_requests=60, window_sec=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Validate input text length
    if len(request.input_text) > 2000:
        raise HTTPException(status_code=400, detail="Input text too long (max 2000 chars)")
    
    if len(request.screen_context or "") > 5000:
        raise HTTPException(status_code=400, detail="Screen context too long (max 5000 chars)")
    
    # Include history from session memory
    session_history = get_session_history(request.session_id)
    request.history = session_history + request.history
    
    # Classify with fallback
    try:
        result = await llm_classify(request)
    except Exception as e:
        logger.warning(f"LLM classification failed, using fallback: {str(e)[:100]}")
        intent, agent, entity, confidence, reasoning = keyword_classify(
            request.input_text, request.screen_context or "")
        result = ClassifyResponse(
            intent=intent,
            target_agent=agent,
            extracted_entity=entity,
            reasoning=f"LLM failed: {str(e)[:80]}, using keyword fallback: {reasoning}",
            confidence=confidence,
        )
    
    # Update session memory
    add_to_history(request.session_id, request.input_text, result)

    started = getattr(http_request.state, "started_at", None)
    latency_ms = round((time.time() - started) * 1000, 1) if started else None
    logger.info(json.dumps({
        "event": "classify",
        "request_id": http_request.headers.get("X-Request-ID"),
        "session_id": request.session_id,
        "intent": result.intent,
        "target_agent": result.target_agent,
        "confidence": result.confidence,
        "latency_ms": latency_ms,
    }))

    return result


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "intent-engine"}


@app.get("/intent/session/{session_id}/history")
async def get_history(session_id: str):
    """Get conversation history for a session."""
    return {"session_id": session_id, "history": get_session_history(session_id)}


@app.delete("/intent/session/{session_id}")
async def clear_session_endpoint(session_id: str):
    """Clear conversation history for a session."""
    clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)