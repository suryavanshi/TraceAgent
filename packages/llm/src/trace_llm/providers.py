from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError


class LLMError(RuntimeError):
    """Base error for provider failures."""


class LLMTransientError(LLMError):
    """Retryable provider failure."""


class LLMValidationError(LLMError):
    """Structured output parsing/validation failure."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMRequest:
    model: str
    messages: tuple[LLMMessage, ...]
    tools: tuple[ToolSpec, ...] = ()
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    finish_reason: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCapabilities:
    supports_tools: bool
    supports_structured_output: bool
    max_context: int
    streaming_supported: bool


class ModelCapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[tuple[str, str], ModelCapabilities] = {}

    def register(self, provider: str, model: str, capabilities: ModelCapabilities) -> None:
        self._capabilities[(provider, model)] = capabilities

    def get(self, provider: str, model: str) -> ModelCapabilities:
        key = (provider, model)
        if key not in self._capabilities:
            raise LLMError(f"Missing capabilities for provider={provider}, model={model}")
        return self._capabilities[key]


class LoggingHook(Protocol):
    def on_request(self, provider: str, payload: Mapping[str, Any]) -> None: ...

    def on_response(self, provider: str, payload: Mapping[str, Any]) -> None: ...

    def on_error(self, provider: str, error: Exception, payload: Mapping[str, Any]) -> None: ...


class PIIRedactor:
    _PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
        (re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"), "[REDACTED_PHONE]"),
        (re.compile(r"sk-[A-Za-z0-9]{10,}"), "[REDACTED_API_KEY]"),
    )

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            redacted = value
            for pattern, replacement in self._PATTERNS:
                redacted = pattern.sub(replacement, redacted)
            return redacted
        if isinstance(value, Mapping):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self.redact(v) for v in value)
        return value


class PromptTemplateLoader:
    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir)

    def load(self, relative_path: str, **values: Any) -> str:
        path = (self._root / relative_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        template = path.read_text(encoding="utf-8")
        return template.format(**values)


TStructured = TypeVar("TStructured", bound=BaseModel)


class StructuredOutputHelper(Generic[TStructured]):
    def __init__(self, schema: type[TStructured]) -> None:
        self._schema = schema

    def parse(self, text: str) -> TStructured:
        candidate = text.strip()
        if not candidate:
            raise LLMValidationError("Empty structured output")
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMValidationError("Structured output is not valid JSON") from exc

        try:
            return self._schema.model_validate(parsed)
        except ValidationError as exc:
            raise LLMValidationError("Structured output schema validation failed") from exc

    def repair_instruction(self, error: Exception) -> str:
        return (
            "The prior response did not satisfy the required JSON schema. "
            f"Return JSON only and fix this issue: {error}"
        )


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def generate_structured(
        self,
        request: LLMRequest,
        schema: type[TStructured],
        max_retries: int = 2,
    ) -> TStructured:
        raise NotImplementedError

    @abstractmethod
    def call_tools(self, request: LLMRequest) -> tuple[ToolCall, ...]:
        raise NotImplementedError

    @abstractmethod
    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        raise NotImplementedError


class MockProvider(LLMProvider):
    def generate(self, request: LLMRequest) -> LLMResponse:
        prompt = request.messages[-1].content if request.messages else ""
        return LLMResponse(text=f"mock-response:{prompt[:32]}", model=request.model)

    def generate_structured(
        self,
        request: LLMRequest,
        schema: type[TStructured],
        max_retries: int = 2,
    ) -> TStructured:
        response = self.generate(request)
        helper = StructuredOutputHelper(schema)
        return helper.parse(response.text)

    def call_tools(self, request: LLMRequest) -> tuple[ToolCall, ...]:
        return ()

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        yield self.generate(request).text


Transport = Callable[[Mapping[str, Any]], Mapping[str, Any] | Iterable[Mapping[str, Any]]]


class BaseHTTPAdapter(LLMProvider):
    provider_name = "base"

    def __init__(
        self,
        transport: Transport,
        capability_registry: ModelCapabilityRegistry,
        hook: LoggingHook | None = None,
        redactor: PIIRedactor | None = None,
    ) -> None:
        self._transport = transport
        self._capability_registry = capability_registry
        self._hook = hook
        self._redactor = redactor or PIIRedactor()

    def generate(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request)
        self._emit_request(payload)
        try:
            raw = self._transport(payload)
            if not isinstance(raw, Mapping):
                raise LLMError("Expected non-stream response mapping")
            response = self._parse_response(request.model, raw)
        except Exception as exc:
            self._emit_error(exc, payload)
            raise
        self._emit_response(response.raw)
        return response

    def generate_structured(
        self,
        request: LLMRequest,
        schema: type[TStructured],
        max_retries: int = 2,
    ) -> TStructured:
        capabilities = self._capability_registry.get(self.provider_name, request.model)
        if not capabilities.supports_structured_output:
            raise LLMError(f"Model {request.model} does not support structured output")

        helper = StructuredOutputHelper(schema)
        current_request = request
        for _attempt in range(max_retries + 1):
            response = self.generate(current_request)
            try:
                return helper.parse(response.text)
            except LLMValidationError as exc:
                repaired_messages = list(current_request.messages)
                repaired_messages.append(LLMMessage(role="system", content=helper.repair_instruction(exc)))
                current_request = LLMRequest(
                    model=current_request.model,
                    messages=tuple(repaired_messages),
                    tools=current_request.tools,
                    temperature=current_request.temperature,
                    max_tokens=current_request.max_tokens,
                    stream=current_request.stream,
                    metadata=current_request.metadata,
                )
        raise LLMValidationError("Failed to produce schema-valid output after retries")

    def call_tools(self, request: LLMRequest) -> tuple[ToolCall, ...]:
        capabilities = self._capability_registry.get(self.provider_name, request.model)
        if not capabilities.supports_tools:
            raise LLMError(f"Model {request.model} does not support tool calling")
        response = self.generate(request)
        return response.tool_calls

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        capabilities = self._capability_registry.get(self.provider_name, request.model)
        if not capabilities.streaming_supported:
            raise LLMError(f"Model {request.model} does not support streaming")
        payload = self._build_payload(LLMRequest(**{**request.__dict__, "stream": True}))
        self._emit_request(payload)
        try:
            chunks = self._transport(payload)
            if isinstance(chunks, Mapping):
                raise LLMError("Expected iterable chunks for stream response")
            for chunk in chunks:
                text = self._parse_stream_chunk(chunk)
                if text:
                    yield text
        except Exception as exc:
            self._emit_error(exc, payload)
            raise

    @abstractmethod
    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _parse_response(self, model: str, payload: Mapping[str, Any]) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def _parse_stream_chunk(self, chunk: Mapping[str, Any]) -> str:
        raise NotImplementedError

    def _emit_request(self, payload: Mapping[str, Any]) -> None:
        if self._hook:
            self._hook.on_request(self.provider_name, self._redactor.redact(dict(payload)))

    def _emit_response(self, payload: Mapping[str, Any]) -> None:
        if self._hook:
            self._hook.on_response(self.provider_name, self._redactor.redact(dict(payload)))

    def _emit_error(self, error: Exception, payload: Mapping[str, Any]) -> None:
        if self._hook:
            self._hook.on_error(self.provider_name, error, self._redactor.redact(dict(payload)))


class OpenAIAdapter(BaseHTTPAdapter):
    provider_name = "openai"

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [message.__dict__ for message in request.messages],
            "stream": request.stream,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    def _parse_response(self, model: str, payload: Mapping[str, Any]) -> LLMResponse:
        choices = payload.get("choices") or []
        if not choices:
            raise LLMError("OpenAI response missing choices")
        first = choices[0]
        message = first.get("message") or {}
        text = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = tuple(
            ToolCall(name=tool["function"]["name"], arguments=json.loads(tool["function"]["arguments"]))
            for tool in raw_tool_calls
        )
        return LLMResponse(
            text=text,
            model=model,
            finish_reason=first.get("finish_reason"),
            tool_calls=tool_calls,
            raw=payload,
        )

    def _parse_stream_chunk(self, chunk: Mapping[str, Any]) -> str:
        choices = chunk.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        return str(delta.get("content") or "")


class AnthropicAdapter(BaseHTTPAdapter):
    provider_name = "anthropic"

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [message.__dict__ for message in request.messages],
            "stream": request.stream,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in request.tools
            ]
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    def _parse_response(self, model: str, payload: Mapping[str, Any]) -> LLMResponse:
        content = payload.get("content") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in content:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
            if block_type == "tool_use":
                tool_calls.append(
                    ToolCall(name=str(block.get("name")), arguments=dict(block.get("input") or {}))
                )
        return LLMResponse(
            text="".join(text_parts),
            model=model,
            finish_reason=str(payload.get("stop_reason") or ""),
            tool_calls=tuple(tool_calls),
            raw=payload,
        )

    def _parse_stream_chunk(self, chunk: Mapping[str, Any]) -> str:
        if chunk.get("type") == "content_block_delta":
            delta = chunk.get("delta") or {}
            if delta.get("type") == "text_delta":
                return str(delta.get("text") or "")
        return ""
