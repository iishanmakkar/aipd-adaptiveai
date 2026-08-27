from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import logging
import time
import json

from app.config import settings
from app.schemas import ClassifyRequest, ClassifyResponse
from app.classifier import llm_classify, keyword_classify, get_session_history, add_to_history, clear_session

logger = logging.getLogger(__name__)

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
    yield


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
async def classify_intent(request: ClassifyRequest):
    """
    Classify user input into intent and select target agent.
    
    Uses LLM with conversation history for context-aware classification.
    Falls back to keyword-based classifier if LLM fails.
    Enforces rate limiting and request validation.
    """
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0] or request.client.host
    
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
        result = keyword_classify(request.input_text, request.screen_context or "")
        result.reasoning = f"LLM failed: {str(e)[:80]}, using keyword fallback"
    
    # Update session memory
    add_to_history(request.session_id, request.input_text, result)
    
    logger.info(
        f"Session {request.session_id}: '{request.input_text[:60]}...' -> "
        f"{result.intent} ({result.target_agent})"
    )
    
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