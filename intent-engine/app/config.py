from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "intent-engine/.env", "./intent-engine/.env", "app/.env"), env_file_encoding="utf-8", extra="ignore")

    # NVIDIA NIM / LLM
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_api_key: str = ""
    nim_model: str = "meta/llama-3.2-11b-vision-instruct"

    # Service
    port: int = 8001
    host: str = "0.0.0.0"
    debug: bool = True

    # Context memory
    max_history_turns: int = 5


settings = Settings()
