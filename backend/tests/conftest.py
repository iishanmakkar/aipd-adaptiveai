"""Pytest bootstrap for the backend suite.

Forces a deterministic, network-free configuration *before* any app module is
imported: `app.config.settings` is a module-level singleton and `app.database`
builds its engine at import time, so both must see an empty DB URL to make the
offline suite independent of whatever backend/.env happens to contain.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE_ROOT = os.path.dirname(_HERE)

if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

# Empty URL -> app.database stays in "demo mode" (engine = None), which is what
# the offline degrade tests assert. Point TEST_DATABASE_URL at a real Postgres
# to enable the `live` DB-backed tests; they stay deselected otherwise.
os.environ["SUPABASE_DB_URL"] = os.environ.get("TEST_DATABASE_URL", "")
os.environ["DEBUG"] = "True"
os.environ["NIM_API_KEY"] = ""

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    """The limiter bucket is process-global; without this, the 429 test would
    starve every later test in the session."""
    import app.main as service
    service._rate_limit_store.clear()
    yield
    service._rate_limit_store.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0]


class FakeSession:
    """Minimal AsyncSession stand-in that replays canned query results.

    The models use Postgres UUID/JSONB columns, so an in-memory SQLite session
    is not an option; route logic is exercised against this instead and real
    SQL is covered by the `live` tests running against Postgres in CI.
    """

    def __init__(self, results=None):
        self._results = list(results or [])
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, *args, **kwargs):
        return self._results.pop(0) if self._results else FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def flush(self):
        pass

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        pass
