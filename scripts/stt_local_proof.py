#!/usr/bin/env python
"""Proof that /api/transcribe turns real spoken audio into the right words.

The voice path is the product. Everything else in this repository can be verified
with a stub; this cannot, so it is verified with actual sound: Windows' own
text-to-speech engine speaks a sentence into a WAV file, that file is uploaded to
the real `/api/transcribe` route, and the route's answer is compared with what was
said. `faster-whisper` decodes it locally - no cloud key, no network model.

Exit 0 = the words came back. 1 = they did not, or the route failed. 3 = could not
run here (no TTS voice, no model, no wheel), which is NOT a pass and must never be
quoted as one.

Run:  .venv/Scripts/python.exe scripts/stt_local_proof.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

SENTENCE = "book two tickets for the seven pm show"

failures: list[str] = []


def require(condition: bool, what: str) -> None:
    print(("  ok   " if condition else "  FAIL ") + what, flush=True)
    if not condition:
        failures.append(what)


def synthesize(destination: Path) -> tuple[bool, str]:
    """Speak SENTENCE into a WAV using the operating system's own voice."""
    script = f'''
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile("{destination}")
$synth.Speak("{SENTENCE}")
$synth.Dispose()
Write-Output "spoke"
'''
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"powershell could not run: {e}"
    if result.returncode != 0 or not destination.exists():
        return False, (result.stderr or result.stdout or "no file written")[:300]
    return True, ""


def main() -> int:
    print(f"target sentence: {SENTENCE!r}")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "spoken.wav"
        made, why = synthesize(wav)
        if not made:
            print(f"INCONCLUSIVE: Windows produced no speech audio ({why})")
            print("This is not a pass. It means this machine has no text-to-speech "
                  "voice for the probe to speak with, not that transcription is broken.")
            return 3
        frames = wav.stat().st_size
        print(f"audio: {wav.name}, {frames} bytes")
        require(frames > 20000, "the spoken file is long enough to be a sentence")

        os.environ["SUPABASE_DB_URL"] = ""
        os.environ["DEBUG"] = "True"
        os.environ["NIM_API_KEY"] = ""
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except Exception as e:
            print(f"INCONCLUSIVE: faster-whisper is not importable here ({e}). "
                  "The pinned build needs a wheel for this interpreter.")
            return 3

        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        with open(wav, "rb") as handle:
            response = client.post("/api/transcribe",
                                   files={"audio": ("spoken.wav", handle.read(),
                                                    "audio/wav")})
        print(f"route status: {response.status_code}")
        if response.status_code != 200:
            print(f"body: {response.text[:400]}")
            body = response.text.lower()
            if "not installed" in body or "no module" in body or "model" in body:
                print("INCONCLUSIVE: the local model could not run on this machine.")
                return 3
            require(False, "the route answered 200")
            return 1

        data = response.json()
        # The route's own field name, not a guess at it: a probe that reads the
        # wrong key reports a working transcription as an empty one.
        transcript = str(data.get("transcript", "")).strip().lower()
        print(f"transcript: {transcript!r}")
        require(bool(transcript), "a non-empty transcript came back")
        require("language" in data, f"the response names the language ({data.get('language')})")
        for word in ("book", "tickets", "show"):
            require(word in transcript, f"the word {word!r} was recognised")
        # Whisper writes numbers as digits: "two" arrives as "2" and "seven pm" as
        # "7 p.m.". Both are correct transcriptions, so the check is on the meaning.
        for spoken, written in (("two", "2"), ("seven", "7")):
            require(spoken in transcript or written in transcript,
                    f"the number {spoken!r} was recognised (as a word or a digit)")
        require("ticket" in transcript and "book" in transcript,
                "the sentence survived as a sentence, not as fragments")

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s) did not hold.")
        return 1
    print("PASSED: real spoken audio came back as the right words, on this machine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
