from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, is_db_available
from app.models.user import User

# bcrypt directly rather than passlib: passlib 1.7.4 (unmaintained since 2020)
# raises against bcrypt >= 4.1, which is what a fresh install resolves to, and
# that made every register/login 500. Stored hashes are standard $2b$ bcrypt, so
# this stays compatible with anything already in the database.
_BCRYPT_MAX_BYTES = 72


def _password_bytes(password: str) -> bytes:
    # bcrypt silently ignores anything past 72 bytes; truncate explicitly so the
    # limit is visible instead of depending on library behaviour.
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(plain_password), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed/truncated hash in the DB must read as "not authenticated".
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    try:
        user_uuid = UUID(user_id)
    except (ValueError, TypeError):
        # Valid signature but a garbage subject (e.g. "admin"): no row can
        # match, and letting UUID() raise would 500 instead of 401.
        raise credentials_exception
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def get_current_user_optional(
    token: str = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db)
):
    """No token + DEBUG: persistent demo user (the UI has no login flow, so this
    is the only way the interface works in dev). Forged/expired/unknown-subject
    tokens ALWAYS 401, even in DEBUG. Production sets ADAPTIVEAI_PRODUCTION=1,
    which refuses DEBUG boots entirely (see app.main)."""
    if not token:
        if not settings.debug:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not is_db_available():
            return DemoUser()
        # Try to get or create persistent demo user for real DB mode (no fake random id each request)
        try:
            result = await db.execute(select(User).where(User.email == "demo@adaptiveai.io"))
            demo_user = result.scalar_one_or_none()
            if demo_user:
                return demo_user
            # Create persistent demo user
            demo_user = User(email="demo@adaptiveai.io", hashed_password=get_password_hash("demo123"))
            db.add(demo_user)
            await db.flush()
            # Ensure preference row exists
            from app.models.preference import Preference
            pref = Preference(user_id=demo_user.id)
            db.add(pref)
            await db.commit()
            await db.refresh(demo_user)
            return demo_user
        except Exception as e:
            # If DB error, fallback to ephemeral DemoUser (e.g., DB not migrated yet)
            import logging
            logging.getLogger(__name__).warning(f"Demo user creation failed ({e}), using ephemeral")
            try:
                await db.rollback()
            except Exception:
                pass
            return DemoUser()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        # A forged/expired/malformed token is never accepted, not even in
        # DEBUG: the UI sends no tokens at all (demo path below), so no
        # legitimate flow depends on this fallback.
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        user_uuid = UUID(user_id)
    except (ValueError, TypeError):
        # Valid signature but a non-UUID subject: unknown by definition, and
        # UUID() raising here would 500 instead of 401.
        raise HTTPException(status_code=401, detail="Invalid token")

    # No-DB demo mode accepts ONLY the no-token path above (the UI sends no
    # tokens at all). A presented token with a valid signature must 401 here:
    # minting a demo identity for an attacker-chosen subject would let anyone
    # impersonate any id.
    if not is_db_available():
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        # Unknown subject: 401 in every mode. Minting a demo identity for an
        # attacker-chosen UUID would let anyone impersonate any id.
        raise HTTPException(status_code=401, detail="User not found")
    return user


# Demo mode: mock user for testing without database
class DemoUser:
    def __init__(self):
        self.id = uuid4()
        self.email = "demo@example.com"


async def get_demo_user() -> DemoUser:
    """Return a mock user for demo mode (no DB required)."""
    return DemoUser()