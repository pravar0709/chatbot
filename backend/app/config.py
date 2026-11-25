"""Application configuration loaded from environment variables."""

import os
from typing import List


class Settings:
    """Reads all config from env vars at import time."""

    LLM_API_KEYS: List[str] = []
    LLM_MODEL: str = "gemini/gemini-3.5-flash"
    DATABASE_URL: str = "sqlite:////data/app.db"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]
    ENABLE_FAILURE_SIMULATION: bool = False
    DEFAULT_SYSTEM_PROMPT: str = "You are a helpful assistant."
    LLM_TIMEOUT: int = 30
    PORT: int = 8000

    def __init__(self) -> None:
        raw_keys = os.getenv("LLM_API_KEYS", "")
        self.LLM_API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

        self.LLM_MODEL = os.getenv("LLM_MODEL", self.LLM_MODEL)
        self.DATABASE_URL = os.getenv("DATABASE_URL", self.DATABASE_URL)

        raw_origins = os.getenv("ALLOWED_ORIGINS", "")
        if raw_origins.strip():
            self.ALLOWED_ORIGINS = [o.strip() for o in raw_origins.split(",") if o.strip()]

        self.ENABLE_FAILURE_SIMULATION = os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true"
        self.DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", self.DEFAULT_SYSTEM_PROMPT)
        self.LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", str(self.LLM_TIMEOUT)))
        self.PORT = int(os.getenv("PORT", str(self.PORT)))

    @property
    def db_path(self) -> str:
        """Extract the file path from a sqlite:/// DATABASE_URL."""
        url = self.DATABASE_URL
        if url.startswith("sqlite:////"):
            return url[len("sqlite:///"):]          # keep leading /
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]
        return url

    @property
    def key_ids(self) -> dict:
        """Return {index: key_id_string} mapping, 1-based."""
        return {i: f"key_{i + 1}" for i in range(len(self.LLM_API_KEYS))}


settings = Settings()
