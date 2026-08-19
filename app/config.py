from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    ai_provider: str
    openai_api_key: str | None
    openai_model: str
    timezone: str
    monitor_interval_seconds: int


def get_settings() -> Settings:
    return Settings(
        database_path=Path(os.getenv("DATABASE_PATH", "data/travel_companion.db")),
        ai_provider=os.getenv("AI_PROVIDER", "local").lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        timezone=os.getenv("APP_TIMEZONE", "Europe/Zurich"),
        monitor_interval_seconds=max(60, int(os.getenv("MONITOR_INTERVAL_SECONDS", "3600"))),
    )

