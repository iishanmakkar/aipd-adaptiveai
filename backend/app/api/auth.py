from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, is_db_available
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


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

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def get_current_user_optional(
    token: str = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db)
):
    """REAL MODE: if no token, in DEBUG use persistent demo user (real DB row); else require auth."""
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
            result = await db.execute(select(User).where(User.email == "demo@adaptiveai.local"))
            demo_user = result.scalar_one_or_none()
            if demo_user:
                return demo_user
            # Create persistent demo user
            demo_user = User(email="demo@adaptiveai.local", hashed_password=get_password_hash("demo123"))
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
        if settings.debug:
            return DemoUser()
        raise HTTPException(status_code=401, detail="Invalid token")

    # If DB not available, return demo user with id from token
    if not is_db_available():
        demo = DemoUser()
        try:
            demo.id = UUID(user_id)
        except Exception:
            pass
        return demo

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        if settings.debug:
            demo = DemoUser()
            try:
                demo.id = UUID(user_id)
            except Exception:
                pass
            return demo
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