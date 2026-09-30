from pydantic import BaseModel, EmailStr, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _non_blank_password(cls, value: str) -> str:
        # An empty/whitespace password would bcrypt-hash to a real credential.
        if not value or not value.strip():
            raise ValueError("password must not be blank")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _non_blank_password(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("password must not be blank")
        return value


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: str | None = None