from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import create_access_token, get_password_hash, verify_password, get_current_user
from app.database import get_db, is_db_available
from app.models.user import User
from app.models.preference import Preference
from app.schemas.auth import UserRegister, UserLogin, Token

router = APIRouter(prefix="/auth", tags=["auth"])


async def require_db(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available in demo mode. Configure SUPABASE_DB_URL to enable.")
    return db


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister, db: AsyncSession = Depends(require_db)):
    # Check if user exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user
    hashed_password = get_password_hash(user_data.password)
    user = User(email=user_data.email, hashed_password=hashed_password)
    db.add(user)
    await db.flush()

    # Create default preferences
    pref = Preference(user_id=user.id)
    db.add(pref)

    await db.commit()

    # Create token
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login", response_model=Token)
async def login(user_data: UserLogin, db: AsyncSession = Depends(require_db)):
    result = await db.execute(select(User).where(User.email == user_data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"id": str(current_user.id), "email": current_user.email}