# Real-Speech STT Test — Runbook (A2)

**Status: still open.** Round 4 measured WER on *synthesized* speech (Windows
SAPI voices): 0% on short clips, 2.8% on a 36-word sentence, silence/noise
correctly rejected. Synthesized speech is clean and evenly paced — real human
speech (accents, disfluencies, background noise, fast/mumbled) will score
**worse**, and that number has not been measured because this environment has no
human voice to record. Verified 2026-09-19: audio devices exist (Intel SST
Digital Microphones, OK) but no capture tooling (no ffmpeg, no sounddevice) —
so even room-tone capture isn't possible from here. A phone recording works.

## Five-minute version (minimum viable: 3 clips on any phone)

Record with any voice-memo app, transfer the files to one folder, add a matching
`.txt` per clip with the words actually spoken:

1. `clean.wav` — "What is the permanent address field asking for?" (normal pace,
   quiet room) + `clean.txt` with that sentence.
2. `noisy.wav` — same sentence with TV/fan on + `noisy.txt` (same text).
3. `fast.wav` — "and what about this one" (fast, mumbled) + `fast.txt`.

Then (stack up):

```bash
docker compose up -d
cd backend
python stt_wer.py ../path/to/your/clips   # needs httpx (in requirements-dev.txt)
```

Expected honest outcome: `clean` near 0%, `noisy`/`fast` worse — report all
three numbers, don't average them away. The full 10-clip matrix below is the
thorough version; the 3-clip version above closes the gap enough to replace
"unmeasured" with a real number.

## Full matrix (when you have 20 minutes + multiple speakers)

Record each as `NAME.wav` (16-bit PCM WAV, 16 kHz mono is ideal but any format
Whisper accepts works) into one folder, with a matching `NAME.txt` containing the
words actually spoken (punctuation optional — it is stripped). Cover:

1. `form-normal.wav` — a form question at normal pace.
2. `followup.wav` — a context follow-up ("and what about this one").
3. `fast-mumbled.wav` — deliberately fast / unclear.
4. `fan-noise.wav` — spoken over a fan / air-con.
5. `traffic-noise.wav` — outdoors or near a road.
6. `crosstalk.wav` — another person talking in the background.
7. `accent-<name>.wav` — a non-native-accented speaker (team member).
8. `long-pause.wav` — a sentence with mid-sentence pauses.
9. `quiet.wav` — spoken far from the mic.
10. `silence.wav` — 3s of room tone only (expect `422 No speech detected`).

## Run it

Stack must be up (real faster-whisper in the backend container):

```bash
docker compose up -d
cd backend
python stt_wer.py ../path/to/your/clips
```

It prints per-clip WER and an overall number, e.g.

```
form-normal.wav: WER 0.0% (0/7 words)  heard: what does the permanent address field mean
fast-mumbled.wav: WER 18.2% (4/22 words)  heard: ...
OVERALL WER: 9.4% (12/128 words across 10 clips)
```

Validated on the synthesized clips: `stt_wer.py` reports 0% / 2.8% / overall
2.3% and skips clips with no `.txt` — so the tool works; only the human audio
is missing.

## Report honestly

Fill this in with the real numbers and paste into README §11 (move the item from
"not verified" to "proven" once done):

| clip | category | WER | notes |
|---|---|---|---|
| form-normal | clean | ___% | |
| fast-mumbled | disfluent | ___% | |
| fan-noise | noise | ___% | |
| traffic-noise | noise | ___% | |
| crosstalk | competing voice | ___% | |
| accent-* | accented | ___% | |
| long-pause | pauses | ___% | |
| quiet | low SNR | ___% | |
| silence | (expect 422) | n/a | |

If noisy/accented WER is high, that is a real limitation to state plainly with
the number — do not average it away. Possible mitigations to note if needed:
switch Whisper to the `small`/`medium` model (accuracy vs latency), add client
side noise suppression, or gate on `no_speech_prob` (already done).
