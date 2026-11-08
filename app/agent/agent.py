"""Backward-compatible agent entrypoint. New clients should use /api/v2 endpoints."""
from app.agent.service import AgentService
from app.core.config import get_settings


async def run_agent_stream(user_input: str, chat_history: list | None = None):
    async for event in AgentService(get_settings()).events(user_input, chat_history):
        if event["type"] == "delta":
            yield event["text"]
