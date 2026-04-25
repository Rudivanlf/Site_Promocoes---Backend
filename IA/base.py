from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentResponse:
    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Optional[dict] = field(default=None, repr=False)


class BaseAgentProvider(ABC):
    PROVIDER_NAME: str = ""
    DEFAULT_MODEL: str = ""

    def __init__(self, api_key: str, model: str = "", **kwargs):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL

    @abstractmethod
    def chat(self, messages: list[dict], system_prompt: str = "", **kwargs) -> AgentResponse:
        """
        Send a list of messages to the provider and return an AgentResponse.

        messages format:
            [
                {"role": "user",      "content": "Hello!"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user",      "content": "How are you?"},
            ]
        """
        ...


class ProviderQuotaExceeded(Exception):
    """Raised when a provider returns a rate-limit / quota-exhausted error."""

    def __init__(
        self,
        provider: str,
        message: str = "",
        retry_after: float | None = None,
        details: object | None = None,
    ):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.retry_after = retry_after
        self.details = details
