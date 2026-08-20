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
    ai_monthly_budget_usd: float
    ai_input_price_per_million: float
    ai_cached_input_price_per_million: float
    ai_output_price_per_million: float


def get_settings() -> Settings:
    return Settings(
        database_path=Path(os.getenv("DATABASE_PATH", "data/travel_companion.db")),
        ai_provider=os.getenv("AI_PROVIDER", "local").lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        timezone=os.getenv("APP_TIMEZONE", "Europe/Zurich"),
        monitor_interval_seconds=max(60, int(os.getenv("MONITOR_INTERVAL_SECONDS", "3600"))),
        ai_monthly_budget_usd=max(0, float(os.getenv("AI_MONTHLY_BUDGET_USD", "4.50"))),
        ai_input_price_per_million=max(0, float(os.getenv("AI_INPUT_PRICE_PER_MILLION", "0.25"))),
        ai_cached_input_price_per_million=max(0, float(os.getenv("AI_CACHED_INPUT_PRICE_PER_MILLION", "0.025"))),
        ai_output_price_per_million=max(0, float(os.getenv("AI_OUTPUT_PRICE_PER_MILLION", "2.00"))),
    )
