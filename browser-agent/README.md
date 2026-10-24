# AdaptiveAI Browser Agent (Module 5)

Real Playwright Chromium service (port 8003). It opens real pages, reads the
live DOM, fills and clicks on them — and is the part of the system that reasons
about **safety** for blind users, because a click it cannot undo is not
something the user can see coming.

Nothing here is simulated: every result carries a status read from the live
page, and a failure names its cause instead of guessing.

## Safety model (the part to read first)

| Gate | Where | What it guarantees |
|---|---|---|
| SSRF allowlist | `tools/url_guard.py` + the per-request route interceptor in `tools/driver.py` | Public http(s) only. Every subresource is re-validated as it is fetched (redirects and DNS flips included); loopback/link-local/metadata are refused. The interceptor runs DNS lookups in a worker thread and caches the verdict per host, so one hostile page cannot stall the event loop. |
| Sensitive-page confirmation | `is_sensitive_url()` in `services/sessions.py` | Hosts **and paths** that look like login/payment/checkout need an explicit `confirmed` flag — `anystore.example/checkout` trips it, not just `login.example.com`. |
| CAPTCHA / challenge refusal | `detect_captcha()` in `services/sessions.py`, checked before every act in `main.py` | A page actively resisting automation is refused, never evaded. |
| robots.txt | `services/sessions.py` (`RobotsCache`) | Every act consults robots.txt; the fetch is SSRF-guarded like browser traffic, and fetched prefixes are not echoed back to the caller. Unfetchable robots.txt means "refuse to act". |
| Submit-class clicks | `services/sessions.py` + `main.py` | "Pay now"/"Delete"-class controls are held as proposals until the user confirms; single-use ids prevent replay. |
| Budgets | `SessionManager` | Navigation/submit budgets per hour, session cap, idle sweep. `SESSION_TTL_SECONDS` is honoured (it used to be unreachable). |

**The legacy `/agent/browse`, `/browse` and `/fill` routes.** `/browse` and
`/fill` act on a page they open themselves; `/agent/browse` only **reads** —
`click_element`, `fill_field`, `fill_form` and `navigate_to_url` are refused
there with a reason. That route has none of the gates above, so executing them
would have been a confirmation-free path around the session API; the refusal is
pinned by a test.

## Endpoints (19 paths, verified from `app.openapi()` 2026-10-24)

| Method | Path | Role |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/sessions` | List live sessions |
| POST | `/session/open` | Open (or reuse) one persistent Chromium page per chat session |
| POST | `/session/{id}/navigate` | Navigate, respecting the sensitive-page gate |
| POST | `/session/{id}/inspect` | Read-only DOM summary |
| POST | `/session/{id}/snapshot` | Accessibility-shaped node list |
| POST | `/session/{id}/text` | Visible text |
| POST | `/session/{id}/act` | Fill/click/select behind the gates (may answer `needs_confirmation`) |
| POST | `/session/{id}/confirm` | Execute a held proposal once |
| GET | `/session/{id}/status` | Session state, budgets, url |
| POST | `/session/{id}/close` | Tear down the page |
| POST | `/session/{id}/monitor/start` · `/stop` · `/status` · `/narrations` · `/interrupt` | Round 9 change narration: local polls, gated NIM calls |
| POST | `/browse` | Open a URL and return title/status/nodes/screenshot size |
| POST | `/fill` | Fill supplied fields with same-page readbacks |
| POST | `/agent/browse` | Read-only exploratory pass (commit intents refused) |

## Running

```bash
docker compose up -d browser-agent        # from the repo root
# or, locally:
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --port 8003
```

Configuration lives in `.env` (`NIM_API_KEY` for vision narration, model and
base URL). In the production overlay the service is internal-only.

## Tests

```bash
python -m pytest        # 63 tests as of 2026-10-24
```

Covered offline with fakes: URL/SSRF guards, session lifecycle and budgets,
monitor gating (quiet window, rate ceiling, consent), the commit-intent
refusal, driver guards, and the page-change filter (which uses `ratio()`, not
the upper-bound `quick_ratio()` that silently dropped a `$45 -> $54` change).

## What it does not do

- No CAPTCHA solving, no credential storage, no payment automation (design
  spec §3). A wall stays a wall.
- No cookies from the user's browser: this service has its own fresh profile,
  so it cannot act on an authenticated site. That is exactly why the MV3
  extension (`extension/`) operates the user's own logged-in browser instead.
- No desktop capture; monitoring covers the session's own page only
  (`docs/round9-monitoring.md` explains the scope decision).
