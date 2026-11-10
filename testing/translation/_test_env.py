"""Environment helper for translation unit and integration tests.

Provides a clean fallback shim when running in air-gapped environments where
`openai` or `langchain_openai` are not installed, while deferring to the real
packages whenever present in the environment.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, cast

import httpx


def ensure_test_dependencies() -> None:
    """Install lightweight HTTP transport shims only if openai/langchain_openai are absent."""
    try:
        import openai  # noqa: F401
    except ImportError:
        _install_openai_shim()

    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        _install_langchain_openai_shim()


def _install_openai_shim() -> None:
    mod = types.ModuleType("openai")

    class APIError(Exception):
        def __init__(
            self, message: str = "", request: Any = None, body: Any = None
        ) -> None:
            super().__init__(message)
            self.message = message
            self.request = request
            self.body = body

    class OpenAIError(APIError):
        pass

    class APIConnectionError(APIError):
        def __init__(
            self, *, message: str = "Connection error.", request: Any = None
        ) -> None:
            super().__init__(message, request=request, body=None)

    class APITimeoutError(APIConnectionError):
        def __init__(self, request: Any = None) -> None:
            super().__init__(message="Request timed out.", request=request)

    class APIStatusError(APIError):
        def __init__(
            self, message: str, *, response: Any = None, body: Any = None
        ) -> None:
            super().__init__(
                message, request=getattr(response, "request", None), body=body
            )
            self.response = response
            self.status_code = getattr(response, "status_code", 500)

    class RateLimitError(APIStatusError):
        pass

    class APIResponseValidationError(APIError):
        def __init__(
            self,
            response: Any = None,
            body: Any = None,
            *,
            message: str = "Invalid response",
        ) -> None:
            super().__init__(
                message, request=getattr(response, "request", None), body=body
            )
            self.response = response

    mod.APIError = APIError  # type: ignore[attr-defined]
    mod.OpenAIError = OpenAIError  # type: ignore[attr-defined]
    mod.APIConnectionError = APIConnectionError  # type: ignore[attr-defined]
    mod.APITimeoutError = APITimeoutError  # type: ignore[attr-defined]
    mod.APIStatusError = APIStatusError  # type: ignore[attr-defined]
    mod.RateLimitError = RateLimitError  # type: ignore[attr-defined]
    mod.APIResponseValidationError = APIResponseValidationError  # type: ignore[attr-defined]
    sys.modules["openai"] = mod


@dataclass
class _Chunk:
    content: Any = ""
    response_metadata: dict[str, Any] = field(default_factory=dict)
    usage_metadata: dict[str, int] | None = None

    @property
    def text(self) -> str:
        return self.content if isinstance(self.content, str) else ""


def _install_langchain_openai_shim() -> None:
    import openai

    pkg = types.ModuleType("langchain_openai")

    class ChatOpenAI:
        def __init__(
            self,
            *,
            base_url: str = "",
            api_key: str = "unused",
            model: str = "mock",
            temperature: float = 0.2,
            streaming: bool = True,
            stream_usage: bool = True,
            max_retries: int = 0,
            http_client: httpx.Client | None = None,
            timeout: Any = None,
            model_kwargs: dict[str, Any] | None = None,
            max_tokens: int | None = None,
            **kwargs: Any,
        ) -> None:
            del kwargs
            self.base_url = base_url.rstrip("/")
            self.api_key = api_key
            self.model = model
            self.temperature = temperature
            self.streaming = streaming
            self.stream_usage = stream_usage
            self.max_retries = max_retries
            self.http_client = http_client
            self.timeout = timeout
            self.model_kwargs = model_kwargs or {}
            self.max_tokens = max_tokens

        def _build_body(
            self, messages: list[dict[str, str]], stream: bool
        ) -> dict[str, Any]:
            norm_msgs = []
            for m in messages:
                if isinstance(m, tuple):
                    norm_msgs.append({"role": m[0], "content": m[1]})
                else:
                    norm_msgs.append(m)
            body: dict[str, Any] = {
                "model": self.model,
                "messages": norm_msgs,
                "temperature": self.temperature,
                "stream": stream,
            }
            if self.model_kwargs:
                body.update(self.model_kwargs)
            if stream and self.stream_usage:
                body["stream_options"] = {"include_usage": True}
            if self.max_tokens is not None:
                body["max_tokens"] = self.max_tokens
            return body

        def _headers(self) -> dict[str, str]:
            h = {"Content-Type": "application/json"}
            if self.api_key and self.api_key != "unused":
                h["Authorization"] = f"Bearer {self.api_key}"
            return h

        def invoke(self, messages: list[dict[str, str]]) -> _Chunk:
            url = f"{self.base_url}/chat/completions"
            body = self._build_body(messages, stream=False)
            client = self.http_client or httpx.Client(timeout=self.timeout)
            request = httpx.Request("POST", url)
            try:
                resp = client.post(
                    url, json=body, headers=self._headers(), timeout=self.timeout
                )
            except httpx.TimeoutException as exc:
                raise openai.APITimeoutError(request=cast("Any", request)) from exc
            except httpx.HTTPError as exc:
                raise openai.APIConnectionError(
                    message=str(exc), request=cast("Any", request)
                ) from exc
            if resp.status_code >= 400:
                raise openai.APIStatusError(
                    f"Error code: {resp.status_code}",
                    response=cast("Any", resp),
                    body=resp.text,
                )
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            content = msg.get("content", "")
            finish_reason = choice.get("finish_reason")
            usage_raw = data.get("usage") or {}
            usage_meta = (
                {
                    "input_tokens": usage_raw.get("prompt_tokens", 0),
                    "output_tokens": usage_raw.get("completion_tokens", 0),
                    "total_tokens": usage_raw.get("total_tokens", 0),
                }
                if usage_raw
                else None
            )
            return _Chunk(
                content=content,
                response_metadata={
                    "finish_reason": finish_reason,
                    "token_usage": usage_raw,
                },
                usage_metadata=usage_meta,
            )

        def stream(self, messages: list[dict[str, str]]) -> Iterator[_Chunk]:
            # Support both SSE streaming servers and single-JSON mock servers
            chunk = self.invoke(messages)
            yield chunk

    pkg.ChatOpenAI = ChatOpenAI  # type: ignore[attr-defined]
    sys.modules["langchain_openai"] = pkg


def install_translation_env(base_url: str) -> dict[str, str | None]:
    """Set ZIVON_BASE_URL / ZIVON_MODEL / ZIVON_API_KEY for test runs."""
    ensure_test_dependencies()
    keys = (
        "ZIVON_BASE_URL",
        "ZIVON_MODEL",
        "ZIVON_API_KEY",
        "ZIVON_LLM_MANAGER_URL",
    )
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["ZIVON_BASE_URL"] = base_url
    os.environ["ZIVON_MODEL"] = "mock-evon-v3.3"
    os.environ["ZIVON_API_KEY"] = "test-key"
    os.environ.pop("ZIVON_LLM_MANAGER_URL", None)
    return saved


def restore_translation_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
