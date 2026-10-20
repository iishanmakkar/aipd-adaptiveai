from fastapi import APIRouter, UploadFile, File, HTTPException
import tempfile
import threading
import os
import logging

router = APIRouter(prefix="/api", tags=["transcribe"])
logger = logging.getLogger(__name__)

# Lazy-load whisper model
_whisper_model = None
_whisper_load_lock = threading.Lock()


def get_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    # Double-checked: two concurrent first requests must not each construct
    # a ~1GB model (the loser was orphaned). The lock only serializes the
    # one-time load; the signature stays sync for existing callers.
    with _whisper_load_lock:
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
        # Save temp file. The suffix comes from the client's filename, so pin it
        # to known audio extensions instead of trusting it.
        ALLOWED_SUFFIXES = (".webm", ".wav", ".mp3", ".m4a", ".ogg", ".flac")
        suffix = os.path.splitext(audio.filename or "")[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            suffix = ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            # vad_filter strips silence/noise before decoding: without it,
            # Whisper hallucinates words (observed: pure silence -> "you")
            # and the endpoint returned a fake transcript with 200.
            # transcribe() is CPU-bound sync (up to tens of seconds) — run it
            # in a worker thread or it freezes the WHOLE event loop (health
            # checks, chat and monitor polls all stall during a transcription).
            def _transcribe_sync():
                segments, info = model.transcribe(
                    tmp_path, beam_size=5,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                    condition_on_previous_text=False,
                )
                kept = [
                    s for s in segments
                    if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0
                ]
                text = " ".join(s.text.strip() for s in kept)
                return text, info

            import anyio
            try:
                text, info = await anyio.to_thread.run_sync(_transcribe_sync)
            except HTTPException:
                raise
            except Exception as e:
                # Truncated/corrupt media makes ffmpeg/whisper raise: that is
                # a bad upload (422), never a server failure (500).
                logger.warning(f"audio decode failed: {type(e).__name__}: {str(e)[:150]}")
                raise HTTPException(
                    status_code=422,
                    detail="Could not decode audio - it may be corrupt or an unsupported format")
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
    # The endpoint follows the KEY, not the URL substring: an operator that
    # sets only OPENAI_API_KEY while nim_base_url keeps its default would
    # otherwise POST the OpenAI key to NVIDIA with model whisper-1 (401/404
    # from NIM, and the "fixed" fallback never actually happens).
    if settings.nim_api_key:
        api_key, base_url = settings.nim_api_key, settings.nim_base_url
    else:
        api_key, base_url = os.getenv("OPENAI_API_KEY"), "https://api.openai.com/v1"
    if api_key:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp2:
                tmp2.write(data)
                tmp2_path = tmp2.name
            try:
                with open(tmp2_path, "rb") as f:
                    resp = await client.audio.transcriptions.create(model="whisper-1", file=f)
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
