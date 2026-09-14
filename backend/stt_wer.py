"""Human-speech WER harness for AdaptiveAI STT.

Point it at a folder of real recorded clips. For each `NAME.wav` it reads the
transcribed text from the running backend and compares it to `NAME.txt` (the
ground-truth words actually spoken), printing per-clip word-error-rate.

    python stt_wer.py path/to/clips --base http://localhost:8000

Requires the stack up (real faster-whisper in the backend container). Ground
truth files are plain text, one utterance per file, punctuation optional (it is
stripped before comparison).
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

import httpx


def normalise(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips_dir")
    ap.add_argument("--base", default="http://localhost:8000")
    args = ap.parse_args()

    clips = sorted(Path(args.clips_dir).glob("*.wav"))
    if not clips:
        print(f"no .wav files in {args.clips_dir}", file=sys.stderr)
        return 1

    total_err = 0
    total_words = 0
    with httpx.Client(timeout=180.0) as client:
        for wav in clips:
            truth_file = wav.with_suffix(".txt")
            if not truth_file.exists():
                print(f"{wav.name}: SKIP (no {truth_file.name} ground truth)")
                continue
            ref = normalise(truth_file.read_text(encoding="utf-8"))
            with wav.open("rb") as f:
                r = client.post(f"{args.base}/api/transcribe",
                                files={"audio": (wav.name, f, "audio/wav")})
            if r.status_code != 200:
                print(f"{wav.name}: HTTP {r.status_code} -> {r.text[:80]}")
                continue
            hyp = normalise(r.json().get("transcript", ""))
            wrong = len(ref) - sum(b.size for b in
                                   difflib.SequenceMatcher(a=ref, b=hyp).get_matching_blocks())
            wer = wrong / max(len(ref), 1)
            total_err += wrong
            total_words += len(ref)
            print(f"{wav.name}: WER {wer*100:5.1f}%  ({wrong}/{len(ref)} words)  "
                  f"heard: {' '.join(hyp)[:60]}")

    if total_words:
        print(f"\nOVERALL WER: {total_err/total_words*100:.1f}%  "
              f"({total_err}/{total_words} words across {len(clips)} clips)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
