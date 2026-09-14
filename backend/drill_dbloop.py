"""Drill 2: restart Postgres mid-load on DB-backed endpoints.

Uses POST /api/session and GET /api/history (pure DB, sub-second) instead of
/api/query, so the restart window is measured without burning NIM quota.
The script itself triggers `docker compose restart postgres` partway through.
"""
import secrets
import subprocess
import threading
import time

import httpx

B = "http://localhost:8000"
email = f"drill2b{int(time.time())}@example.com"
tok = httpx.post(f"{B}/auth/register",
                 json={"email": email, "password": secrets.token_urlsafe(12)},
                 timeout=30).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}


def restart_later():
    time.sleep(12)
    print(">>> STOPPING postgres while requests are in flight", flush=True)
    subprocess.run(["docker", "compose", "stop", "postgres"], capture_output=True, timeout=120)
    time.sleep(6)
    print(">>> starting postgres again", flush=True)
    subprocess.run(["docker", "compose", "start", "postgres"], capture_output=True, timeout=120)


threading.Thread(target=restart_later, daemon=True).start()

results = []
for i in range(60):
    t0 = time.time()
    try:
        r = httpx.post(f"{B}/api/session", headers=H, timeout=30)
        sid = r.json().get("session_id") if r.status_code == 201 else None
        h = httpx.get(f"{B}/api/history/{sid}", headers=H, timeout=30) if sid else None
        results.append((i, round(time.time() - t0, 2), r.status_code,
                        h.status_code if h else "-"))
    except Exception as e:
        results.append((i, round(time.time() - t0, 2), -1, type(e).__name__))
    time.sleep(0.7)

fails = [r for r in results if r[2] != 201]
oks_after = [r for r in results if r[0] > 20 and r[2] == 201]
print(f"iterations: {len(results)} | non-201: {len(fails)} | 201s after restart: {len(oks_after)}")
for r in fails[:8]:
    print("  fail:", r)
print("last 4:", results[-4:])
