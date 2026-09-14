from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from contextlib import asynccontextmanager
import json
import logging
import time
from config import settings
from schemas import AgentRespondRequest, AgentRespondResponse
from rag.vector_store import VectorStore
from rag.seed_data import initialize_knowledge_base
from rag.retriever import Retriever
from llm.client import LLMClient
from agents.registry import AgentRegistry, agent_registry

logger = logging.getLogger("adaptiveai.agents")

# uvicorn's root logger defaults to WARNING; these JSON lines must reach stdout
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    vector_store = VectorStore()
    initialize_knowledge_base(vector_store)
    
    retriever = Retriever()
    llm_client = LLMClient()
    
    global agent_registry
    agent_registry = AgentRegistry(retriever, llm_client)
    
    print(f"Agent service started on port {settings.PORT}")
    print(f"Available agents: {agent_registry.get_all_names()}")
    print(f"Knowledge base documents: {vector_store.count()}")
    
    yield
    
    # Shutdown
    print("Agent service shutting down...")


app = FastAPI(
    title="AdaptiveAI Task Agents + RAG",
    description="Task-specific agents with retrieval-augmented generation for accessibility assistance",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "agents", "port": settings.PORT}


@app.post("/agent/respond", response_model=AgentRespondResponse)
async def agent_respond(request: Request):
    started = time.time()
    body = await request.json()
    try:
        validated = AgentRespondRequest(**body)
    except ValidationError as e:
        # Preserve FastAPI's 422 for a malformed body now that the handler
        # parses manually (to read X-Request-ID); without this it would 500.
        return JSONResponse(status_code=422, content={"detail": json.loads(e.json())})
    agent = agent_registry.get(validated.agent)
    if not agent:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent: {validated.agent}. Available: {agent_registry.get_all_names()}"
        )

    try:
        result = await agent.handle(validated.query, validated.entity, validated.extra_context)
    except Exception as e:
        logger.error(json.dumps({
            "event": "agent_error",
            "request_id": request.headers.get("X-Request-ID"),
            "session_id": validated.session_id,
            "agent": validated.agent,
            "error": str(e)[:200],
            "latency_ms": round((time.time() - started) * 1000, 1),
        }))
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    logger.info(json.dumps({
        "event": "agent_respond",
        "request_id": request.headers.get("X-Request-ID"),
        "session_id": validated.session_id,
        "agent": validated.agent,
        "sources": len(result["sources_used"]),
        "latency_ms": round((time.time() - started) * 1000, 1),
    }))
    return AgentRespondResponse(**result)


@app.get("/agents")
async def list_agents():
    return {"agents": agent_registry.get_all_names()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)