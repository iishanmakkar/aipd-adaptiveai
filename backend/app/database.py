from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from fastapi import HTTPException
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Global flag to track DB availability
_db_available = False

if not settings.supabase_db_url or settings.supabase_db_url.strip() == "":
    logger.warning("No SUPABASE_DB_URL configured - running in demo mode without DB")
    engine = None
    async_session_maker = None
    _db_available = False
else:
    try:
        engine = create_async_engine(settings.supabase_db_url, echo=False, pool_pre_ping=True)
        async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        _db_available = True
    except Exception as e:
        logger.warning(f"Failed to create database engine: {e}")
        engine = None
        async_session_maker = None


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    if not _db_available or async_session_maker is None:
        # Raised as a dependency, so this must be an HTTPException: a bare
        # RuntimeError would surface as 500 instead of the documented 503.
        raise HTTPException(
            status_code=503,
            detail="Database not available - configure SUPABASE_DB_URL or run `docker compose up postgres`",
        )
    try:
        async with async_session_maker() as session:
            yield session
    except HTTPException:
        raise
    except Exception as e:
        # A DB that dies mid-flight raises HERE, at pool checkout inside the
        # dependency - before any route's own try/except can run. Without this
        # wrapper, a postgres restart produced 500s (seen in the Round-4
        # shutdown drill) instead of the documented 503.
        raise HTTPException(
            status_code=503,
            detail=f"Database connection failed: {str(e)[:200]}",
        )


async def init_db() -> None:
    if not _db_available or engine is None:
        raise RuntimeError("Database not available (demo mode)")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def is_db_available() -> bool:
    return _db_available