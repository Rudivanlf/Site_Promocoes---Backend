import time
import threading

from django.conf import settings
from jinja2 import Environment, StrictUndefined
from typing import Any

from .base import BaseAgentProvider, AgentResponse, ProviderQuotaExceeded
from .gemini_provider import GeminiProvider


# ---------------------------------------------------------------------------
# Provider registry — add new providers here
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, type[BaseAgentProvider]] = {
    "gemini": GeminiProvider,
}


# ---------------------------------------------------------------------------
# Per-provider cooldown (in-process, resets on restart)
# ---------------------------------------------------------------------------

_cooldown_lock = threading.Lock()
_provider_cooldown: dict[str, float] = {}


def _set_cooldown(provider_name: str, retry_after: float | None) -> None:
    wait = max(float(retry_after or 0), 10.0)
    with _cooldown_lock:
        _provider_cooldown[provider_name] = time.time() + wait


def _check_cooldown(provider_name: str) -> float | None:
    """Return remaining cooldown seconds, or None if the provider is available."""
    with _cooldown_lock:
        available_at = _provider_cooldown.get(provider_name)
    if available_at is None:
        return None
    remaining = available_at - time.time()
    return remaining if remaining > 0 else None


# ---------------------------------------------------------------------------
# Jinja2 prompt rendering
# ---------------------------------------------------------------------------

def render_prompt(template_str: str, context: dict[str, Any]) -> str:
    """
    Render a Jinja2 template string with the given context.

    Example:
        render_prompt("Hello, {{ name }}!", {"name": "World"})
        # -> "Hello, World!"
    """
    env = Environment(undefined=StrictUndefined, autoescape=False)
    return env.from_string(template_str).render(**(context or {}))


# ---------------------------------------------------------------------------
# AgentService
# ---------------------------------------------------------------------------

class AgentService:
    """
    Thin wrapper around provider classes.

    Typical usage:
        response = AgentService.chat(
            provider_name="gemini",
            messages=[{"role": "user", "content": "Hello!"}],
            system_prompt="You are a helpful assistant.",
        )
        print(response.content)

    Provider credentials are read from settings.AGENT_PROVIDERS:
        AGENT_PROVIDERS = {
            "gemini": {
                "api_key": "YOUR_KEY",
                "model": "gemini-1.5-flash",   # optional
            }
        }
    """

    @staticmethod
    def get_provider(provider_name: str, api_key: str = "", model: str = "") -> BaseAgentProvider:
        """Instantiate and return a provider by name."""
        provider_name = provider_name.lower()
        if provider_name not in PROVIDERS:
            raise ValueError(
                f"Provider '{provider_name}' not supported. "
                f"Available: {', '.join(PROVIDERS)}"
            )

        cfg: dict = getattr(settings, "AGENT_PROVIDERS", {}).get(provider_name, {})
        resolved_key = api_key or cfg.get("api_key", "")
        resolved_model = model or cfg.get("model", "")

        if not resolved_key:
            raise ValueError(
                f"No API key configured for provider '{provider_name}'. "
                "Pass api_key= or set it in settings.AGENT_PROVIDERS."
            )

        cls = PROVIDERS[provider_name]
        kwargs = {"model": resolved_model} if resolved_model else {}
        return cls(api_key=resolved_key, **kwargs)

    @staticmethod
    def chat(
        provider_name: str,
        messages: list[dict],
        system_prompt: str = "",
        api_key: str = "",
        model: str = "",
        **kwargs,
    ) -> AgentResponse:
        """
        Send messages to a provider and return an AgentResponse.

        Raises ProviderQuotaExceeded if the provider is rate-limited.
        """
        remaining = _check_cooldown(provider_name)
        if remaining is not None:
            raise ProviderQuotaExceeded(
                provider_name,
                message=f"Provider '{provider_name}' is cooling down. Retry in {int(remaining) + 1}s.",
                retry_after=remaining,
            )

        provider = AgentService.get_provider(provider_name, api_key, model)

        try:
            return provider.chat(messages, system_prompt=system_prompt, **kwargs)
        except ProviderQuotaExceeded as e:
            _set_cooldown(provider_name, getattr(e, "retry_after", None))
            raise
