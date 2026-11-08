"""Provider-independent asynchronous streaming and bounded agent tool orchestration."""
import logging
from typing import Any, AsyncIterator, Callable

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import call_tool, tools_schema
from app.core.config import ProviderConfig, Settings, get_settings

logger = logging.getLogger(__name__)


class AgentError(Exception):
    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code = code
        self.status = status


class ProviderError(AgentError):
    def __init__(self, code: str, status: int = 503, retryable: bool = False):
        super().__init__(code, status)
        self.retryable = retryable


def prepare_messages(user_input: str, chat_history: list[dict] | None, settings: Settings) -> list[dict]:
    if not isinstance(user_input, str) or not user_input.strip() or len(user_input) > 3000:
        raise AgentError("INVALID_INPUT", 422)
    history = chat_history or []
    if not isinstance(history, list) or len(history) > settings.max_history_messages:
        raise AgentError("INVALID_HISTORY", 422)
    total_chars = 0
    safe_history = []
    for item in history:
        # Never trust client-supplied system/developer/tool roles or tool calls.
        if not isinstance(item, dict) or set(item.keys()) != {"role", "content"}:
            raise AgentError("INVALID_HISTORY", 422)
        if item["role"] not in {"user", "assistant"}:
            raise AgentError("INVALID_HISTORY", 422)
        content = item["content"]
        if not isinstance(content, str) or len(content) > 4000:
            raise AgentError("INVALID_HISTORY", 422)
        total_chars += len(content)
        safe_history.append({"role": item["role"], "content": content})
    if total_chars > settings.max_history_chars:
        raise AgentError("INVALID_HISTORY", 422)
    return [{"role": "system", "content": SYSTEM_PROMPT}, *safe_history,
            {"role": "user", "content": user_input.strip()}]


def _provider_error(exc: Exception) -> ProviderError:
    if isinstance(exc, RateLimitError) or (isinstance(exc, APIStatusError) and exc.status_code == 429):
        return ProviderError("PROVIDER_RATE_LIMITED", 429, True)
    if isinstance(exc, APIStatusError):
        if exc.status_code in (401, 403):
            return ProviderError("PROVIDER_AUTH_FAILED", 503, False)
        if exc.status_code == 402:
            return ProviderError("PROVIDER_BILLING_REQUIRED", 503, False)
        return ProviderError("PROVIDER_UNAVAILABLE", 503, exc.status_code >= 500)
    if isinstance(exc, (APIConnectionError, APITimeoutError, TimeoutError)):
        return ProviderError("PROVIDER_UNAVAILABLE", 503, True)
    return ProviderError("PROVIDER_UNAVAILABLE", 503, False)


class AgentService:
    def __init__(self, settings: Settings | None = None,
                 client_factory: Callable[..., Any] = AsyncOpenAI):
        self.settings = settings or get_settings()
        self.client_factory = client_factory

    async def _run_provider(self, provider: ProviderConfig, messages: list[dict]) -> AsyncIterator[dict]:
        client = self.client_factory(
            base_url=provider.base_url, api_key=provider.api_key,
            timeout=self.settings.request_timeout_seconds, max_retries=0,
        )
        try:
            conversation = list(messages)
            for round_no in range(self.settings.max_tool_rounds + 1):
                allow_tools = round_no < self.settings.max_tool_rounds
                kwargs: dict[str, Any] = {
                    "model": provider.model, "messages": conversation,
                    "stream": True, "max_tokens": self.settings.max_output_tokens,
                }
                if allow_tools:
                    kwargs["tools"] = tools_schema
                stream = await client.chat.completions.create(**kwargs)
                calls: dict[int, dict] = {}
                text_fragments = []
                try:
                    async for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if getattr(delta, "content", None):
                            text_fragments.append(delta.content)
                            yield {"type": "delta", "text": delta.content}
                        for item in (getattr(delta, "tool_calls", None) or []):
                            ix = item.index
                            value = calls.setdefault(ix, {"id": "", "name": "", "arguments": ""})
                            if getattr(item, "id", None):
                                value["id"] = item.id
                            function = getattr(item, "function", None)
                            if function:
                                if getattr(function, "name", None):
                                    value["name"] += function.name
                                if getattr(function, "arguments", None):
                                    value["arguments"] += function.arguments
                finally:
                    close = getattr(stream, "close", None)
                    if close is not None:
                        await close()
                if not calls:
                    if not text_fragments:
                        raise ProviderError("EMPTY_PROVIDER_RESPONSE", 503, True)
                    yield {"type": "done", "provider": provider.name, "model": provider.model}
                    return
                if not allow_tools:
                    raise ProviderError("TOOL_ROUND_LIMIT", 503, False)
                safe_calls = []
                for ix in sorted(calls):
                    call = calls[ix]
                    if not call["id"] or not call["name"]:
                        raise ProviderError("PROVIDER_INVALID_RESPONSE", 503, False)
                    safe_calls.append({
                        "id": call["id"], "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    })
                conversation.append({"role": "assistant", "content": "".join(text_fragments) or None,
                                     "tool_calls": safe_calls})
                for call in safe_calls:
                    conversation.append({
                        "role": "tool", "tool_call_id": call["id"],
                        "content": call_tool(call["function"]["name"], call["function"]["arguments"]),
                    })
            raise ProviderError("TOOL_ROUND_LIMIT", 503, False)
        except ProviderError:
            raise
        except (APIConnectionError, APITimeoutError, APIStatusError, TimeoutError) as exc:
            logger.warning("AI provider request failed: provider=%s error_type=%s", provider.name, type(exc).__name__)
            raise _provider_error(exc) from exc
        except Exception as exc:
            logger.exception("Unexpected AI provider failure: provider=%s", provider.name)
            raise ProviderError("PROVIDER_UNAVAILABLE", 503, False) from exc
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                await close()

    async def events(self, user_input: str, chat_history: list[dict] | None = None) -> AsyncIterator[dict]:
        messages = prepare_messages(user_input, chat_history, self.settings)
        providers = self.settings.candidates()
        if not providers:
            raise AgentError("AI_NOT_CONFIGURED", 503)
        for index, provider in enumerate(providers):
            exposed_text = False
            try:
                async for event in self._run_provider(provider, messages):
                    if event["type"] == "delta":
                        exposed_text = True
                    yield event
                return
            except ProviderError as exc:
                # Switching models after any visible text corrupts a response.
                # Failover only for retryable errors before the first delta.
                if exposed_text or not exc.retryable or index == len(providers) - 1:
                    raise AgentError(exc.code, exc.status) from exc
                logger.warning("AI fallback: from=%s to=%s", provider.name, providers[index + 1].name)
        raise AgentError("PROVIDER_UNAVAILABLE", 503)
