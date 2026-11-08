"""Compatibility helper for scripts: no import-time network calls or paid model defaults."""
from openai import AsyncOpenAI
from app.core.config import get_settings


def get_llm_client():
    providers = get_settings().candidates()
    if not providers:
        raise RuntimeError("No AI provider configured")
    provider = providers[0]
    return AsyncOpenAI(base_url=provider.base_url, api_key=provider.api_key, max_retries=0), provider.model
