import ast
import re

from google import genai
from google.genai import types
from google.genai.errors import ClientError as GenaiClientError

from .base import BaseAgentProvider, AgentResponse, ProviderQuotaExceeded

_QUOTA_STATUSES = frozenset({"RESOURCE_EXHAUSTED", "RATE_LIMIT_EXCEEDED"})


def _extract_text(response) -> str:
    """Extract plain text from a Gemini response object."""
    try:
        text = getattr(response, "text", None)
        if text:
            return text
    except Exception:
        pass
    try:
        dump = response.model_dump() if hasattr(response, "model_dump") else {}
        return "".join(
            part["text"]
            for candidate in (dump.get("candidates") or [])
            for part in ((candidate.get("content") or {}).get("parts") or [])
            if part.get("text") and not part.get("thought")
        )
    except Exception:
        return ""


def _finish_reason(response) -> str:
    try:
        dump = response.model_dump() if hasattr(response, "model_dump") else {}
        candidates = dump.get("candidates") or []
        return str((candidates[0].get("finish_reason") or "") if candidates else "").upper()
    except Exception:
        return ""


def _parse_quota_error(e: GenaiClientError) -> tuple[str, float | None, object]:
    """Parse a quota/rate-limit error into (human_message, retry_after_seconds, details)."""
    raw = str(e)
    resp_json = None
    try:
        resp_json = ast.literal_eval(raw[raw.index("{"):])
    except Exception:
        pass

    human_msg = raw
    retry_after: float | None = None
    quota_details = None

    if isinstance(resp_json, dict):
        err = resp_json.get("error") or {}
        human_msg = str(err.get("message") or raw)
        for detail in err.get("details") or []:
            dtype = str(detail.get("@type") or "")
            if dtype.endswith("RetryInfo"):
                try:
                    retry_after = float(str(detail.get("retryDelay") or "").rstrip("s"))
                except ValueError:
                    pass
            elif dtype.endswith("QuotaFailure"):
                quota_details = detail.get("violations") or detail

    if retry_after is None:
        m = re.search(r"retry[Dd]elay[^\d]*(\d+(?:\.\d+)?)s", raw) or \
            re.search(r"retry in (\d+(?:\.\d+)?)s", raw, re.IGNORECASE)
        if m:
            try:
                retry_after = float(m.group(1))
            except ValueError:
                pass

    return human_msg, retry_after, quota_details


class GeminiProvider(BaseAgentProvider):
    """
    Google Gemini provider.

    Usage:
        provider = GeminiProvider(api_key="YOUR_KEY", model="gemini-2.0-flash")
        response = provider.chat(
            messages=[{"role": "user", "content": "Hello!"}],
            system_prompt="You are a helpful assistant.",
        )
        print(response.content)
    """

    PROVIDER_NAME = "gemini"
    DEFAULT_MODEL = "gemini-2.0-flash"

    _DEFAULT_MAX_OUTPUT_TOKENS = 16384
    _MAX_CONTINUATIONS = 4
    _CONTINUATION_PROMPT = "Continue exactly from where you left off, without repeating anything already written."

    # Models that support thinking configuration
    _THINKING_MODELS = ("gemini-2.5",)

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(api_key, model, **kwargs)
        self._client = genai.Client(api_key=api_key)
        self._model_name = model if model.startswith("models/") else f"models/{model}"

    def chat(self, messages: list[dict], system_prompt: str = "", **kwargs) -> AgentResponse:
        """
        Send messages to Gemini and return an AgentResponse.
        Automatically continues the conversation if the model hits the output token limit.
        """
        contents = self._build_contents(messages)
        max_tokens = kwargs.get("max_tokens") or self._DEFAULT_MAX_OUTPUT_TOKENS
        temperature = kwargs.get("temperature", 0.7)

        response = self._generate(contents, max_tokens, temperature, system_prompt)
        text = _extract_text(response)
        input_tokens, output_tokens = self._usage(response)

        # If the response was cut off, keep asking the model to continue
        for _ in range(self._MAX_CONTINUATIONS):
            if "MAX_TOKENS" not in _finish_reason(response):
                break
            contents = contents + [
                types.Content(role="model", parts=[types.Part(text=text)]),
                types.Content(role="user",  parts=[types.Part(text=self._CONTINUATION_PROMPT)]),
            ]
            try:
                response = self._generate(contents, self._DEFAULT_MAX_OUTPUT_TOKENS, temperature, system_prompt)
            except Exception:
                break
            cont_text = _extract_text(response)
            i, o = self._usage(response)
            input_tokens += i
            output_tokens += o
            if cont_text:
                text += cont_text

        return AgentResponse(
            content=text,
            provider=self.PROVIDER_NAME,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw=self._dump(response),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate(self, contents, max_tokens: int, temperature: float, system_prompt: str):
        thinking_config = None
        if any(t in self.model for t in self._THINKING_MODELS):
            try:
                thinking_config = types.ThinkingConfig(thinking_budget=0)
            except Exception:
                pass

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_prompt or None,
            thinking_config=thinking_config,
        )
        try:
            return self._client.models.generate_content(
                model=self._model_name,
                contents=contents,
                config=config,
            )
        except GenaiClientError as e:
            if self._is_quota_error(e):
                human_msg, retry_after, details = _parse_quota_error(e)
                raise ProviderQuotaExceeded(
                    self.PROVIDER_NAME,
                    message=human_msg,
                    retry_after=retry_after,
                    details=details,
                ) from e

            # If the exact model name wasn't found, try a fallback
            if "NOT_FOUND" in str(e):
                fallback = self._find_fallback_model()
                if fallback:
                    return self._client.models.generate_content(
                        model=fallback, contents=contents, config=config
                    )
            raise

    def _is_quota_error(self, e: GenaiClientError) -> bool:
        raw = str(e)
        try:
            resp_json = ast.literal_eval(raw[raw.index("{"):])
            status = str((resp_json.get("error") or {}).get("status") or "").upper()
            if status in _QUOTA_STATUSES:
                return True
        except Exception:
            pass
        return "RESOURCE_EXHAUSTED" in raw.upper()

    def _find_fallback_model(self) -> str | None:
        available = [m.name for m in self._client.models.list()]
        short = self.model.split("/")[-1]
        return (
            next((m for m in available if short in m), None)
            or next((m for m in available if "gemini-flash" in m), None)
        )

    @staticmethod
    def _build_contents(messages: list[dict]) -> list[types.Content]:
        return [
            types.Content(
                role="model" if msg["role"] == "assistant" else "user",
                parts=[types.Part(text=msg["content"])],
            )
            for msg in messages
        ]

    @staticmethod
    def _usage(response) -> tuple[int, int]:
        usage = getattr(response, "usage_metadata", None)
        return (
            getattr(usage, "prompt_token_count", 0) or 0,
            getattr(usage, "candidates_token_count", 0) or 0,
        )

    @staticmethod
    def _dump(response) -> dict:
        try:
            return response.model_dump() if hasattr(response, "model_dump") else {}
        except Exception:
            return {}
