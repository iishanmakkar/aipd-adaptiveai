from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "backend/.env", "./backend/.env", "app/.env"), env_file_encoding="utf-8", extra="ignore")
    debug: bool = True

    # Database - optional for demo/integrated mode without external DB
    supabase_db_url: str = ""

    # JWT - default for demo mode
    jwt_secret: str = "dev-secret-change-in-production-min-32-chars-long"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # NVIDIA NIM
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_api_key: str = ""
    nim_model: str = "meta/llama-3.2-11b-vision-instruct"

    # External services (can be overridden for real services)
    intent_service_url: str = "http://localhost:8001"
    agent_service_url: str = "http://localhost:8002"

    # Frontend CORS
    frontend_url: str = "http://localhost:3000"

    # Policy engine
    clarifying_threshold: int = 3
    context_window_size: int = 5


settings = Settings()
