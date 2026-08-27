from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
import os
from app.config import settings

router = APIRouter(tags=["vlm"])

@router.post("/v1/chat/completions")
@router.post("/v1/chat/completions/")
async def vlm_proxy(request: Request):
    """
    REAL VLM proxy: forwards vision requests to NVIDIA NIM (meta/llama-3.2-11b-vision-instruct)
    Frontend sends OpenAI-compatible payload with base64 image; we forward to NIM and return response.
    No mock data.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Get API key from frontend header or backend config
    auth = request.headers.get("authorization", "")
    api_key = None
    if auth.lower().startswith("bearer "):
        api_key = auth[7:].strip()
    if not api_key or api_key == "demo-key":
        api_key = settings.nim_api_key or os.getenv("NIM_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="VLM not configured: set NIM_API_KEY in backend/.env or VITE_NIM_API_KEY in frontend/.env")

    # Forward to NVIDIA NIM
    nim_url = f"{settings.nim_base_url.rstrip('/')}/chat/completions"
    # Ensure vision model is used if not specified
    if "model" not in body or not body["model"]:
        body["model"] = "meta/llama-3.2-11b-vision-instruct"

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                nim_url,
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
            )
            # Return NIM response as-is (including errors)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text[:500])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"VLM proxy error: {str(e)[:300]}")

@router.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "meta/llama-3.2-11b-vision-instruct", "object": "model", "owned_by": "nvidia"},
            {"id": settings.nim_model, "object": "model", "owned_by": "nvidia"},
        ]
    }
