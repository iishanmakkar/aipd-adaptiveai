import os
from typing import List, Dict, Any
from config import settings


class LLMClient:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self._client = None
        self._init_client()

    def _init_client(self):
        # REAL MODE: requires valid NIM API key - no demo fallbacks
        if self.provider == "nim":
            api_key = settings.NIM_API_KEY or settings.LLM_API_KEY or os.getenv("NIM_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("NIM_API_KEY not set - set it in agents/.env for real mode")
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=settings.NIM_BASE_URL)
        elif self.provider == "openai":
            api_key = settings.LLM_API_KEY or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set - set LLM_API_KEY in agents/.env for real mode")
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)
        elif self.provider == "anthropic":
            api_key = settings.LLM_API_KEY or os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            from anthropic import Anthropic
            self._client = Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def chat(self, messages: List[Dict[str, str]]) -> str:
        # REAL MODE: direct LLM call, no mock fallback - errors propagate for visibility
        if self.provider in ("openai", "nim"):
            return self._chat_openai(messages)
        elif self.provider == "anthropic":
            return self._chat_anthropic(messages)
        raise ValueError(f"Unknown provider: {self.provider}")

    def _chat_openai(self, messages: List[Dict[str, str]]) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content.strip()

    def _chat_anthropic(self, messages: List[Dict[str, str]]) -> str:
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_messages = [m for m in messages if m["role"] != "system"]
        response = self._client.messages.create(
            model=self.model,
            system=system_msg,
            messages=user_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.content[0].text.strip()