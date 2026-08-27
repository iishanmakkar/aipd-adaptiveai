from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
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
        raise RuntimeError("Database not available (demo mode)")
    async with async_session_maker() as session:
        yield session


async def init_db() -> None:
    if not _db_available or engine is None:
        raise RuntimeError("Database not available (demo mode)")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def is_db_available() -> bool:
    return _db_available