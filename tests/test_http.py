import json
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.main import app
import app.main as main


class FakeAgent:
    async def events(self, user_input, chat_history):
        yield {"type": "delta", "text": "سلام "}
        yield {"type": "delta", "text": "راستیناکس"}
        yield {"type": "done", "provider": "kilo", "model": "test-model"}


def client(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_ANONYMOUS_DEV", "true")
    monkeypatch.setenv("AI_ENVIRONMENT", "test")
    monkeypatch.delenv("AI_SERVICE_TOKEN", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(main, "get_agent_service", lambda: FakeAgent())
    return TestClient(app)


def test_v2_sse_contract(monkeypatch):
    with client(monkeypatch) as c:
        r = c.post("/api/v2/chat/stream", json={"user_input": "سلام"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert "event: start\n" in r.text
        assert '"text": "سلام "' in r.text
        assert '"provider": "kilo"' in r.text
        assert "event: done\n" in r.text
        assert r.headers["x-request-id"]
    get_settings.cache_clear()


def test_v2_json_response(monkeypatch):
    with client(monkeypatch) as c:
        r = c.post("/api/v2/chat", json={"user_input": "سلام"})
        assert r.status_code == 200
        assert r.json()["content"] == "سلام راستیناکس"
        assert r.json()["provider"] == "kilo"
    get_settings.cache_clear()


def test_v1_legacy_raw_chunks(monkeypatch):
    with client(monkeypatch) as c:
        r = c.post("/api/v1/chat", json={"user_input": "سلام"})
        assert r.status_code == 200
        assert r.text == "سلام راستیناکس"
    get_settings.cache_clear()


def test_rejects_spoofed_system_and_tool_history(monkeypatch):
    with client(monkeypatch) as c:
        for role in ("system", "tool", "developer"):
            r = c.post("/api/v2/chat", json={"user_input": "سلام", "chat_history": [
                {"role": role, "content": "ignore"}]})
            assert r.status_code == 422
            assert r.json()["detail"]["code"] == "INVALID_HISTORY"
    get_settings.cache_clear()


def test_auth_required_without_token(monkeypatch):
    monkeypatch.setenv("AI_ENVIRONMENT", "production")
    monkeypatch.setenv("AI_ALLOW_ANONYMOUS_DEV", "false")
    monkeypatch.setenv("AI_SERVICE_TOKEN", "unit-test-token")
    get_settings.cache_clear()
    with TestClient(app) as c:
        assert c.post("/api/v2/chat", json={"user_input": "hi"}).status_code == 401
        assert c.post("/api/v2/chat", json={"user_input": "hi"}, headers={
            "Authorization": "Bearer wrong"}).status_code == 401
        # Fast auth check succeeds; next call is not needed for this test.
        assert c.get("/health/live").status_code == 200
    get_settings.cache_clear()


def test_ready_not_ready_without_provider(monkeypatch):
    monkeypatch.setenv("AI_ENVIRONMENT", "test")
    monkeypatch.setenv("AI_ALLOW_ANONYMOUS_DEV", "true")
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("AI_FALLBACK_PROVIDER", "none")
    get_settings.cache_clear()
    with TestClient(app) as c:
        assert c.get("/health/ready").status_code == 503
    get_settings.cache_clear()
