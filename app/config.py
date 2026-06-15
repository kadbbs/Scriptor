import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv(override=True)


class Settings(BaseModel):
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/novel_agent.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()
