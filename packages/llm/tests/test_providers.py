from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from trace_llm.providers import (
    AnthropicAdapter,
    LLMError,
    LLMMessage,
    LLMRequest,
    LLMValidationError,
    LoggingHook,
    MockProvider,
    ModelCapabilities,
    ModelCapabilityRegistry,
    OpenAIAdapter,
    PIIRedactor,
    PromptTemplateLoader,
    ToolSpec,
)


class DemoSchema(BaseModel):
    status: str


class CaptureHook(LoggingHook):
    def __init__(self) -> None:
        self.requests: list[Mapping[str, Any]] = []
        self.responses: list[Mapping[str, Any]] = []
        self.errors: list[tuple[Exception, Mapping[str, Any]]] = []

    def on_request(self, provider: str, payload: Mapping[str, Any]) -> None:
        self.requests.append(payload)

    def on_response(self, provider: str, payload: Mapping[str, Any]) -> None:
        self.responses.append(payload)

    def on_error(self, provider: str, error: Exception, payload: Mapping[str, Any]) -> None:
        self.errors.append((error, payload))


def _registry(provider: str, model: str, *, tools: bool = True, structured: bool = True, stream: bool = True) -> ModelCapabilityRegistry:
    registry = ModelCapabilityRegistry()
    registry.register(
        provider,
        model,
        ModelCapabilities(
            supports_tools=tools,
            supports_structured_output=structured,
            max_context=16_000,
            streaming_supported=stream,
        ),
    )
    return registry


def test_mock_provider() -> None:
    provider = MockProvider()
    request = LLMRequest(model="mock", messages=(LLMMessage(role="user", content="hello"),))
    assert provider.generate(request).text.startswith("mock-response")


def test_openai_structured_with_retry_repair() -> None:
    calls = {"n": 0}

    def transport(_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            content = "not-json"
        else:
            content = '{"status": "ok"}'
        return {
            "choices": [
                {
                    "message": {"content": content, "tool_calls": []},
                    "finish_reason": "stop",
                }
            ]
        }

    adapter = OpenAIAdapter(transport=transport, capability_registry=_registry("openai", "model-a"))
    request = LLMRequest(model="model-a", messages=(LLMMessage(role="user", content="reply json"),))

    result = adapter.generate_structured(request, DemoSchema, max_retries=2)

    assert result.status == "ok"
    assert calls["n"] == 2


def test_anthropic_tool_calling() -> None:
    def transport(_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "content": [
                {"type": "tool_use", "name": "lookup", "input": {"query": "voltage"}},
            ],
            "stop_reason": "tool_use",
        }

    adapter = AnthropicAdapter(transport=transport, capability_registry=_registry("anthropic", "model-b"))
    request = LLMRequest(
        model="model-b",
        messages=(LLMMessage(role="user", content="use tool"),),
        tools=(ToolSpec(name="lookup", description="lookup", input_schema={"type": "object"}),),
    )

    tool_calls = adapter.call_tools(request)

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "lookup"
    assert tool_calls[0].arguments == {"query": "voltage"}


def test_openai_streaming_text() -> None:
    def transport(_payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        return [
            {"choices": [{"delta": {"content": "hello "}}]},
            {"choices": [{"delta": {"content": "world"}}]},
        ]

    adapter = OpenAIAdapter(transport=transport, capability_registry=_registry("openai", "model-s"))
    request = LLMRequest(model="model-s", messages=(LLMMessage(role="user", content="stream"),), stream=True)

    collected = "".join(adapter.stream_text(request))

    assert collected == "hello world"


def test_prompt_template_loader(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Hello {name}", encoding="utf-8")

    loader = PromptTemplateLoader(tmp_path)

    assert loader.load("prompt.txt", name="Ada") == "Hello Ada"


def test_logging_hook_uses_pii_redaction() -> None:
    hook = CaptureHook()

    def transport(_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"choices": [{"message": {"content": "ok", "tool_calls": []}, "finish_reason": "stop"}]}

    adapter = OpenAIAdapter(
        transport=transport,
        capability_registry=_registry("openai", "model-log"),
        hook=hook,
        redactor=PIIRedactor(),
    )
    request = LLMRequest(
        model="model-log",
        messages=(LLMMessage(role="user", content="email me at user@example.com"),),
    )

    adapter.generate(request)

    assert hook.requests
    logged_messages = hook.requests[0]["messages"]
    assert "[REDACTED_EMAIL]" in logged_messages[0]["content"]


def test_capability_enforcement_raises() -> None:
    def transport(_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"choices": [{"message": {"content": "ok", "tool_calls": []}, "finish_reason": "stop"}]}

    adapter = OpenAIAdapter(
        transport=transport,
        capability_registry=_registry("openai", "model-no-tools", tools=False),
    )
    request = LLMRequest(
        model="model-no-tools",
        messages=(LLMMessage(role="user", content="tool"),),
        tools=(ToolSpec(name="x", description="x", input_schema={}),),
    )

    try:
        adapter.call_tools(request)
    except LLMError:
        pass
    else:
        raise AssertionError("Expected LLMError")


def test_structured_failure_exhausts_retries() -> None:
    def transport(_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"choices": [{"message": {"content": "always bad", "tool_calls": []}, "finish_reason": "stop"}]}

    adapter = OpenAIAdapter(transport=transport, capability_registry=_registry("openai", "model-f"))
    request = LLMRequest(model="model-f", messages=(LLMMessage(role="user", content="json"),))

    try:
        adapter.generate_structured(request, DemoSchema, max_retries=1)
    except LLMValidationError:
        pass
    else:
        raise AssertionError("Expected LLMValidationError")
