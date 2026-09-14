"""Concurrent load test for the AdaptiveAI pipeline.

Runs N concurrent workers against POST /api/query-demo (real intent -> agent ->
policy, no DB) for a fixed wall-clock window, and reports status-code mix and
latency percentiles. Results are printed as JSON; redirect to a file if you want
one (python loadtest.py 10 60 > out.json). Usage:

    python loadtest.py 10 60
"""
import asyncio
import json
import secrets
import statistics
import sys
import time

import httpx

BASE = "http://localhost:8000"
QUERIES = [
    "What does the Aadhaar number field mean?",
    "How do I fill the permanent address field?",
    "Summarize this PDF for me",
    "Where is the submit button on this page?",
    "What is photosynthesis?",
    "What can you help me with?",
    "Explain the water cycle in simple terms",
    "How do I read the terms and conditions?",
]


def _jitter() -> float:
    # secrets-based uniform: no predictable timing in the load pattern.
    return 0.2 + (secrets.randbelow(801) / 1000.0)


async def worker(client: httpx.AsyncClient, worker_id: int, deadline: float, results: list):
    i = 0
    while time.time() < deadline:
        q = QUERIES[(worker_id + i) % len(QUERIES)]
        t0 = time.time()
        try:
            r = await client.post(f"{BASE}/api/query-demo", json={
                "session_id": f"load-{worker_id}-{i}",
                "input_text": q, "input_source": "text", "screen_context": "",
            }, timeout=240.0)
            latency = time.time() - t0
            body = r.text[:120] if r.status_code != 200 else ""
            results.append({"status": r.status_code, "latency": latency, "err": body})
        except Exception as e:
            results.append({"status": -1, "latency": time.time() - t0,
                            "err": f"{type(e).__name__}: {str(e)[:80]}"})
        i += 1
        await asyncio.sleep(_jitter())


def summarize(results):
    ok = [r["latency"] for r in results if r["status"] == 200]
    codes = {}
    for r in results:
        codes[r["status"]] = codes.get(r["status"], 0) + 1
    out = {"n": len(results), "codes": codes}
    if ok:
        ordered = sorted(ok)
        out["p50"] = round(ordered[int(0.50 * (len(ordered) - 1))], 1)
        out["p95"] = round(ordered[int(0.95 * (len(ordered) - 1))], 1)
        out["p99"] = round(ordered[int(0.99 * (len(ordered) - 1))], 1)
        out["max"] = round(ordered[-1], 1)
        out["mean"] = round(statistics.mean(ok), 1)
    return out


async def run(concurrency: int, seconds: int):
    results: list = []
    deadline = time.time() + seconds
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[
            worker(client, w, deadline, results) for w in range(concurrency)
        ])
    summary = summarize(results)
    print(f"== concurrency={concurrency} window={seconds}s ==")
    print(json.dumps({"concurrency": concurrency, "seconds": seconds,
                      "summary": summary, "raw": results[-200:]}, indent=1))


def _bounded_int(value: str, lo: int, hi: int) -> int:
    n = int(value)
    if not lo <= n <= hi:
        raise SystemExit(f"value must be between {lo} and {hi}, got {value}")
    return n


if __name__ == "__main__":
    concurrency = _bounded_int(sys.argv[1], 1, 200) if len(sys.argv) > 1 else 10
    seconds = _bounded_int(sys.argv[2], 1, 600) if len(sys.argv) > 2 else 60
    asyncio.run(run(concurrency, seconds))
