import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.agent.service import AgentError, AgentService, ProviderError
from app.core.config import Settings


def part(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
        content=content, tool_calls=tool_calls))])


def tool_part(index, ident, name, args):
    return SimpleNamespace(index=index, id=ident, function=SimpleNamespace(name=name, arguments=args))


class Stream:
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    def __aiter__(self):
        async def iterator():
            for p in self.parts:
                yield p
        return iterator()

    async def close(self):
        self.closed = True


class FakeCompletions:
    def __init__(self, batches):
        self.batches = batches
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return Stream(self.batches.pop(0))


class FakeClient:
    def __init__(self, batches):
        self.chat = SimpleNamespace(completions=FakeCompletions(batches))

    async def close(self):
        pass


async def collect(service):
    return [evt async for evt in service.events("سلام")]


def test_one_request_for_normal_chat(monkeypatch):
    monkeypatch.setenv("KILO_API_KEY", "placeholder")
    client = FakeClient([[part("سلام "), part("دوست عزیز")]])
    agent = AgentService(Settings.from_env(), client_factory=lambda **k: client)
    result = asyncio.run(collect(agent))
    assert "".join(x["text"] for x in result if x["type"] == "delta") == "سلام دوست عزیز"
    assert result[-1]["type"] == "done"
    assert len(client.chat.completions.calls) == 1
    assert client.chat.completions.calls[0]["stream"] is True


def test_streaming_tool_round_and_allowlisted_result(monkeypatch):
    monkeypatch.setenv("KILO_API_KEY", "placeholder")
    client = FakeClient([
        [part(tool_calls=[tool_part(0, "call_1", "generate_caption", '{"product":"سایت"}')])],
        [part("کپشن آماده است")],
    ])
    agent = AgentService(Settings.from_env(), client_factory=lambda **k: client)
    result = asyncio.run(collect(agent))
    assert len(client.chat.completions.calls) == 2
    second = client.chat.completions.calls[1]["messages"]
    assert second[-1]["role"] == "tool"
    assert "سایت" in second[-1]["content"]
    assert result[-1]["type"] == "done"


def test_fallback_before_text(monkeypatch):
    monkeypatch.setenv("AI_FALLBACK_PROVIDER", "openrouter")
    monkeypatch.setenv("KILO_API_KEY", "placeholder")
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder")
    agent = AgentService(Settings.from_env())

    async def fake(provider, messages):
        if provider.name == "kilo":
            raise ProviderError("PROVIDER_RATE_LIMITED", 429, True)
        yield {"type": "delta", "text": "پاسخ دوم"}
        yield {"type": "done", "provider": provider.name, "model": provider.model}

    agent._run_provider = fake
    result = asyncio.run(collect(agent))
    assert result[0]["text"] == "پاسخ دوم"
    assert result[-1]["provider"] == "openrouter"


def test_no_fallback_after_partial_output(monkeypatch):
    monkeypatch.setenv("AI_FALLBACK_PROVIDER", "openrouter")
    monkeypatch.setenv("KILO_API_KEY", "placeholder")
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder")
    agent = AgentService(Settings.from_env())
    visited = []

    async def fake(provider, messages):
        visited.append(provider.name)
        yield {"type": "delta", "text": "ناقص"}
        raise ProviderError("PROVIDER_UNAVAILABLE", 503, True)

    agent._run_provider = fake

    async def run():
        with pytest.raises(AgentError) as e:
            return [x async for x in agent.events("سلام")]
        assert e.value.code == "PROVIDER_UNAVAILABLE"

    asyncio.run(run())
    assert visited == ["kilo"]


def test_no_configured_provider(monkeypatch):
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.setenv("AI_FALLBACK_PROVIDER", "none")
    agent = AgentService(Settings.from_env())

    async def run():
        with pytest.raises(AgentError) as e:
            return [x async for x in agent.events("سلام")]
        assert e.value.code == "AI_NOT_CONFIGURED"

    asyncio.run(run())


def test_empty_stream_is_error(monkeypatch):
    monkeypatch.setenv("KILO_API_KEY", "placeholder")
    client = FakeClient([[]])
    service = AgentService(Settings.from_env(), client_factory=lambda **kw: client)
    async def run():
        with pytest.raises(AgentError) as error:
            return [x async for x in service.events("سلام")]
        assert error.value.code == "EMPTY_PROVIDER_RESPONSE"
    asyncio.run(run())
