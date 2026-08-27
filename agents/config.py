import os
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "agents/.env", "./agents/.env", "app/.env"), env_file_encoding="utf-8", extra="ignore")

    LLM_PROVIDER: Literal["openai", "anthropic", "nim"] = "nim"
    LLM_MODEL: str = "meta/llama-3.2-11b-vision-instruct"
    LLM_API_KEY: str = ""
    NIM_API_KEY: str = ""
    NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 500

    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    COLLECTION_NAME: str = "adaptiveai_knowledge"
    TOP_K: int = 3

    HOST: str = "0.0.0.0"
    PORT: int = 8002


settings = Settings()
