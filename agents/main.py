from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings
from schemas import AgentRespondRequest, AgentRespondResponse
from rag.vector_store import VectorStore
from rag.seed_data import initialize_knowledge_base
from rag.retriever import Retriever
from llm.client import LLMClient
from agents.registry import AgentRegistry, agent_registry


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
async def agent_respond(request: AgentRespondRequest):
    agent = agent_registry.get(request.agent)
    if not agent:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent: {request.agent}. Available: {agent_registry.get_all_names()}"
        )
    
    try:
        result = await agent.handle(request.query, request.entity, request.extra_context)
        return AgentRespondResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.get("/agents")
async def list_agents():
    return {"agents": agent_registry.get_all_names()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)