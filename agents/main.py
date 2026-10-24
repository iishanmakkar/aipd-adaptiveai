from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from contextlib import asynccontextmanager
import asyncio
import json
import logging
import time
from config import settings
from schemas import AgentRespondRequest, AgentRespondResponse, OrchestrateRequest
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
    # lifespan rebinding only touches this module's name: publish the instance
    # on the registry module too, so `from agents.registry import
    # agent_registry` never sees the initial None at request time.
    import agents.registry as _registry_module
    _registry_module.agent_registry = agent_registry
    # ...and on the package attribute: `from agents import agent_registry`
    # (advertised in agents/__init__.py's __all__) otherwise stays bound to
    # the import-time None forever - the same latent None the registry-module
    # rebinding above exists to fix.
    import agents as _agents_package
    _agents_package.agent_registry = agent_registry
    
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
    # Explicit origins, no credentials: service-to-service needs no cookies,
    # and browsers reject wildcard + credentials. Covers local dev, docs, and
    # the in-compose frontend hostname.
    allow_origins=[
        "http://localhost:3000", "http://localhost:5173",
        "http://127.0.0.1:3000", "http://127.0.0.1:5173",
        "http://frontend:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "agents", "port": settings.PORT}


@app.post("/agent/respond", response_model=AgentRespondResponse)
async def agent_respond(request: Request):
    started = time.time()
    try:
        body = await request.json()
    except Exception:
        # Manual parsing (to read X-Request-ID) skips FastAPI's automatic
        # 422 for malformed JSON; without this it would 500.
        return JSONResponse(status_code=422, content={"detail": "Invalid JSON body"})
    try:
        # model_validate, not **body: a valid-JSON non-object body (a list,
        # a string, null - one buggy client line) raised TypeError on **body,
        # and TypeError is not ValidationError, so it surfaced as a 500.
        validated = AgentRespondRequest.model_validate(body)
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
    except (ValueError, KeyError) as e:
        # Caller error (bad entity/query for the agent): 422, not 500 - a 500
        # would read as an outage and retry forever.
        raise HTTPException(status_code=422, detail=str(e)[:200])
    except Exception as e:
        logger.error(json.dumps({
            "event": "agent_error",
            "request_id": request.headers.get("X-Request-ID"),
            "session_id": validated.session_id,
            "agent": validated.agent,
            "error": str(e)[:200],
            "latency_ms": round((time.time() - started) * 1000, 1),
        }))
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)[:300]}")

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


class OrchestrateResponse(AgentRespondResponse):
    agent: str = ""
    plan: list[str] = []  # type: ignore[assignment]


@app.post("/agent/orchestrate", response_model=OrchestrateResponse)
async def agent_orchestrate(request: Request):
    """Natural-language goal -> plan + specialist execution (Phase 2.1)."""
    from agents.orchestrator import llm_route, keyword_route

    started = time.time()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"detail": "Invalid JSON body"})
    try:
        validated = OrchestrateRequest.model_validate(body)
    except ValidationError as e:
        return JSONResponse(status_code=422, content={"detail": json.loads(e.json())})
    # LLM routing with keyword fallback lives inside llm_route. The sync LLM
    # call must not run on the event loop (it stalls every concurrent
    # request for the whole model round-trip).
    general = agent_registry.get("general_agent")
    if general is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialized")
    llm_client = general.llm
    agent_name, via = await asyncio.to_thread(llm_route, validated.goal, llm_client)
    agent = agent_registry.get(agent_name)
    if not agent:
        agent_name, via = keyword_route(validated.goal), "keyword"
        agent = agent_registry.get(agent_name)
    plan = [f"route ({via}) -> {agent_name}", "execute specialist", "return grounded answer"]
    try:
        result = await agent.handle(validated.goal, validated.entity, validated.extra_context)  # type: ignore[union-attr]
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e)[:200])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)[:300]}")
    logger.info(json.dumps({
        "event": "agent_orchestrate",
        "request_id": request.headers.get("X-Request-ID"),
        "session_id": validated.session_id,
        "agent": agent_name,
        "latency_ms": round((time.time() - started) * 1000, 1),
    }))
    return {**result, "agent": agent_name, "plan": plan}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)