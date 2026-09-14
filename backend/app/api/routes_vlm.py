from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
import json
import os
from app.config import settings

router = APIRouter(tags=["vlm"])

# A malicious client skips every frontend check, so upload limits are enforced
# here: base64 inflates payloads ~4/3, so ~11MB of image arrives as ~15MB JSON.
MAX_VLM_PAYLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_IMAGE_PREFIXES = ("data:image/jpeg", "data:image/png", "data:image/webp", "data:image/gif")


@router.post("/v1/chat/completions")
@router.post("/v1/chat/completions/")
async def vlm_proxy(request: Request):
    """
    REAL VLM proxy: forwards vision requests to NVIDIA NIM (meta/llama-3.2-11b-vision-instruct)
    Frontend sends OpenAI-compatible payload with base64 image; we forward to NIM and return response.
    No mock data.
    """
    declared_len = request.headers.get("content-length")
    if declared_len and declared_len.isdigit() and int(declared_len) > MAX_VLM_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large: screenshots are capped at 15MB including base64 encoding")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if len(json.dumps(body)) > MAX_VLM_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large: screenshots are capped at 15MB including base64 encoding")

    images = []
    for message in (body.get("messages") or [] if isinstance(body, dict) else []):
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for part in message["content"]:
            if isinstance(part, dict) and part.get("type") == "image_url":
                images.append((part.get("image_url") or {}).get("url", ""))
    if len(images) > 4:
        raise HTTPException(status_code=413, detail="Too many images in one request (max 4)")
    for url in images:
        if url and not url.startswith(ALLOWED_IMAGE_PREFIXES + ("https://", "http://")):
            raise HTTPException(status_code=415, detail="Unsupported image format: use JPEG, PNG, WebP or GIF")

    # Get API key from frontend header or backend config
    auth = request.headers.get("authorization", "")
    api_key = None
    if auth.lower().startswith("bearer "):
        api_key = auth[7:].strip()
    if not api_key:
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
