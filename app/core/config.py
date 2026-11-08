"""Environment-only configuration; never embed API keys in source control."""
import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

SUPPORTED_PROVIDERS = {"kilo", "groq", "openrouter", "ollama", "custom"}
DEFAULT_URLS = {
    "kilo": "https://ai-gateway.kilo.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}
DEFAULT_MODELS = {
    "kilo": "kilo-auto/free",
    "groq": "openai/gpt-oss-20b",
    "openrouter": "openrouter/free",
    "ollama": "qwen2.5:1.5b",
    "custom": "",
}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    base_url: str
    api_key: str


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    environment: str
    primary_provider: str
    fallback_provider: str
    service_token: str
    allow_anonymous_dev: bool
    allow_paid_openrouter: bool
    request_timeout_seconds: int
    max_output_tokens: int
    max_tool_rounds: int
    max_history_messages: int
    max_history_chars: int
    max_concurrent_requests: int

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            environment=os.getenv("AI_ENVIRONMENT", "development").strip().lower(),
            primary_provider=os.getenv("AI_PRIMARY_PROVIDER", "kilo").strip().lower(),
            fallback_provider=os.getenv("AI_FALLBACK_PROVIDER", "none").strip().lower(),
            service_token=os.getenv("AI_SERVICE_TOKEN", ""),
            allow_anonymous_dev=_flag("AI_ALLOW_ANONYMOUS_DEV"),
            allow_paid_openrouter=_flag("AI_ALLOW_PAID_OPENROUTER"),
            request_timeout_seconds=_integer("AI_REQUEST_TIMEOUT_SECONDS", 35, 5, 120),
            max_output_tokens=_integer("AI_MAX_OUTPUT_TOKENS", 500, 64, 4096),
            max_tool_rounds=_integer("AI_MAX_TOOL_ROUNDS", 2, 0, 5),
            max_history_messages=_integer("AI_MAX_HISTORY_MESSAGES", 16, 0, 60),
            max_history_chars=_integer("AI_MAX_HISTORY_CHARS", 16000, 1000, 80000),
            max_concurrent_requests=_integer("AI_MAX_CONCURRENT_REQUESTS", 16, 1, 200),
        )
        if settings.environment not in {"development", "test", "production"}:
            raise ValueError("AI_ENVIRONMENT must be development, test or production")
        if settings.primary_provider not in SUPPORTED_PROVIDERS:
            raise ValueError("Invalid AI_PRIMARY_PROVIDER")
        if settings.fallback_provider not in SUPPORTED_PROVIDERS | {"none"}:
            raise ValueError("Invalid AI_FALLBACK_PROVIDER")
        if settings.environment == "production" and settings.allow_anonymous_dev:
            raise ValueError("Anonymous API cannot be enabled in production")
        return settings

    def candidates(self) -> list[ProviderConfig]:
        names = list(dict.fromkeys([self.primary_provider, self.fallback_provider]))
        configured = []
        for name in names:
            if name == "none":
                continue
            prefix = name.upper()
            model = os.getenv(f"{prefix}_MODEL", DEFAULT_MODELS[name]).strip()
            base_url = os.getenv(f"{prefix}_BASE_URL", DEFAULT_URLS.get(name, "")).strip().rstrip("/")
            api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
            if name == "ollama":
                api_key = api_key or "ollama"
            if not model or not base_url or not api_key:
                continue
            parsed = urlsplit(base_url)
            if not parsed.hostname or parsed.scheme not in {"http", "https"}:
                raise ValueError(f"Invalid {prefix}_BASE_URL")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and not _flag("AI_ALLOW_PRIVATE_HTTP"):
                raise ValueError(f"Insecure {prefix}_BASE_URL: use HTTPS or explicitly enable private-network HTTP")
            if name == "kilo" and model != "kilo-auto/free" and not model.endswith(":free"):
                raise ValueError("Only kilo-auto/free or :free models are allowed")
            if name == "openrouter" and not self.allow_paid_openrouter:
                if model != "openrouter/free" and not model.endswith(":free"):
                    raise ValueError("Only openrouter/free or :free models are allowed by default")
            configured.append(ProviderConfig(name, model, base_url, api_key))
        return configured


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
