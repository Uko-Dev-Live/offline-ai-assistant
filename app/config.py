"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val is not None and val.strip() else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # --- Server ---
    host: str = _env("APP_HOST", "127.0.0.1")
    port: int = _env_int("APP_PORT", 8000)

    # --- Ollama (the local LLM runtime) ---
    ollama_url: str = _env("OLLAMA_URL", "http://127.0.0.1:11434")
    model: str = _env("MODEL_NAME", "llama3.2:3b")
    temperature: float = _env_float("MODEL_TEMPERATURE", 0.7)
    num_ctx: int = _env_int("MODEL_NUM_CTX", 4096)
    request_timeout: int = _env_int("REQUEST_TIMEOUT", 120)

    # --- Persona / system prompt ---
    system_prompt: str = _env(
        "SYSTEM_PROMPT",
        "You are a helpful, concise offline AI assistant. "
        "Answer clearly and directly. If you do not know something, say so.",
    )

    # --- Storage / paths ---
    db_path: Path = BASE_DIR / "data" / "conversations.db"
    log_path: Path = BASE_DIR / "logs" / "app.log"
    static_dir: Path = BASE_DIR / "static"

    # --- History limits ---
    max_history_messages: int = _env_int("MAX_HISTORY_MESSAGES", 20)


settings = Settings()
