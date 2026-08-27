from fastapi import APIRouter, UploadFile, File, HTTPException
import tempfile
import os
import logging

router = APIRouter(prefix="/api", tags=["transcribe"])
logger = logging.getLogger(__name__)

# Lazy-load whisper model
_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
        # Use base model for CPU, float32 for accuracy; tiny would be faster
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("faster-whisper model loaded")
        return _whisper_model
    except ImportError:
        logger.warning("faster-whisper not installed - install with pip install faster-whisper")
        return None
    except Exception as e:
        logger.warning(f"Failed to load whisper model: {e}")
        return None

@router.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    REAL transcribe using faster-whisper if available, else OpenAI Whisper API.
    No fake data - returns 503 if no STT backend configured.
    """
    data = await audio.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio file too large (max 10MB)")

    # Try faster-whisper first (local, no API key needed)
    model = get_whisper_model()
    if model is not None:
        # Save temp file
        suffix = ".webm"
        if audio.filename:
            suffix = os.path.splitext(audio.filename)[1] or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            segments, info = model.transcribe(tmp_path, beam_size=5)
            text = " ".join([s.text.strip() for s in segments])
            if not text.strip():
                raise HTTPException(status_code=422, detail="No speech detected in audio")
            return {"transcript": text.strip(), "language": info.language, "duration": info.duration}
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # Fallback: Try OpenAI Whisper API via NIM/OpenAI if key is configured
    from app.config import settings
    api_key = settings.nim_api_key or os.getenv("OPENAI_API_KEY")
    if api_key and api_key != "demo-key":
        try:
            from openai import OpenAI
            # Use OpenAI's whisper via NIM base if NIM supports audio, else default openai
            client = OpenAI(api_key=api_key, base_url=settings.nim_base_url if "nvidia" in settings.nim_base_url else "https://api.openai.com/v1")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp2:
                tmp2.write(data)
                tmp2_path = tmp2.name
            try:
                with open(tmp2_path, "rb") as f:
                    resp = client.audio.transcriptions.create(model="whisper-1", file=f)
                return {"transcript": resp.text}
            finally:
                try:
                    os.unlink(tmp2_path)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"OpenAI transcribe failed: {e}")
            raise HTTPException(status_code=502, detail=f"STT service error: {str(e)[:200]}")

    # No STT backend available - REAL error, no fake
    raise HTTPException(
        status_code=503,
        detail="STT not configured: install faster-whisper (pip install faster-whisper) or set NIM_API_KEY/OPENAI_API_KEY for cloud STT"
    )
