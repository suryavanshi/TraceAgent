from __future__ import annotations

from pydantic import BaseModel

from trace_llm import (
    LLMMessage,
    LLMRequest,
    ModelCapabilities,
    ModelCapabilityRegistry,
    OpenAIAdapter,
    PromptTemplateLoader,
)


class DesignDecision(BaseModel):
    summary: str
    risk: str


registry = ModelCapabilityRegistry()
registry.register(
    "openai",
    "openai-model",
    ModelCapabilities(
        supports_tools=True,
        supports_structured_output=True,
        max_context=128_000,
        streaming_supported=True,
    ),
)


def fake_transport(payload: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": '{"summary":"Add pull-up resistor", "risk":"low"}',
                    "tool_calls": [],
                },
                "finish_reason": "stop",
            }
        ]
    }


loader = PromptTemplateLoader("packages/llm/examples/prompts")
prompt = loader.load("design_review.txt", design_input="MCU reset line")
adapter = OpenAIAdapter(transport=fake_transport, capability_registry=registry)
request = LLMRequest(model="openai-model", messages=(LLMMessage(role="user", content=prompt),))
structured = adapter.generate_structured(request, DesignDecision)
print(structured.model_dump())
