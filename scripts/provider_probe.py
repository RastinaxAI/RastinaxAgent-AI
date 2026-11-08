"""Run on target server with environment keys; never print secrets."""
import asyncio
import sys
from openai import AsyncOpenAI
from app.core.config import get_settings


async def main():
    providers = get_settings().candidates()
    if not providers:
        print("NOT_READY: no provider configured")
        return 2
    for provider in providers:
        print(f"Checking {provider.name} / {provider.model} ...", flush=True)
        client = AsyncOpenAI(base_url=provider.base_url, api_key=provider.api_key,
                             timeout=15.0, max_retries=0)
        try:
            response = await client.chat.completions.create(
                model=provider.model, messages=[{"role": "user", "content": "در یک جمله فارسی سلام کن."}],
                max_tokens=80,
            )
            print(f"OK: {provider.name} / model={response.model}")
        except Exception as exc:
            print(f"FAILED: {provider.name} / error_type={type(exc).__name__}")
            return 1
        finally:
            await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
