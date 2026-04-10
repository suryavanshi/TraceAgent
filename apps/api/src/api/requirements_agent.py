from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from design_ir.models import CircuitSpec
from trace_llm.providers import LLMMessage, LLMProvider, LLMRequest, PromptTemplateLoader

MISSING_VOLTAGE_QUESTION = "What are the required input and output voltage rails (including tolerances)?"
MISSING_CURRENT_LIMIT_QUESTION = "What are the expected current limits for each rail and high-current interface?"
MISSING_INTERFACE_QUESTION = "Which exact external interfaces/protocols are required (UART/SPI/I2C/CAN/USB/GPIO)?"
MISSING_DIMENSION_QUESTION = "What are the board dimensions, height limits, and connector placement constraints?"


class RequirementsChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1)


class RequirementsDerivationOutput(BaseModel):
    proposed_circuit_spec: CircuitSpec
    summary: str = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)
    ambiguity_notes: list[str] = Field(default_factory=list)


class RequirementsAgentResult(BaseModel):
    proposed_circuit_spec: CircuitSpec
    summary: str
    open_questions: list[str] = Field(default_factory=list)


class RuleBasedRequirementsProvider(LLMProvider):
    """Local provider used for tests/dev when no external model wiring exists."""

    def generate(self, request: LLMRequest):  # pragma: no cover - not used by this agent
        raise NotImplementedError

    def generate_structured(self, request: LLMRequest, schema: type[BaseModel], max_retries: int = 2):
        user_text = "\n".join(message.content for message in request.messages if message.role == "user")
        prompt_text = user_text.lower()

        board_type = "sensor-node"
        if "tracker" in prompt_text:
            board_type = "asset-tracker"
        elif "stm32" in prompt_text:
            board_type = "controller"

        interfaces: list[dict[str, str]] = []
        if "i2c" in prompt_text:
            interfaces.append({"name": "I2C", "description": "I2C sensor and peripheral bus"})
        if "usb-c" in prompt_text or "usb c" in prompt_text:
            interfaces.append({"name": "USB-C", "description": "USB Type-C connector for power and optional data"})
        if "can" in prompt_text:
            interfaces.append({"name": "CAN", "description": "CAN interface with transceiver"})
        if "ble" in prompt_text:
            interfaces.append({"name": "BLE", "description": "Bluetooth Low Energy radio link"})

        rails: list[dict[str, str]] = []
        if "lipo" in prompt_text:
            rails.append({"name": "Battery rail", "description": "Single-cell LiPo battery input"})
        if "12v" in prompt_text and "5v" in prompt_text:
            rails.append({"name": "12V input", "description": "Primary external supply"})
            rails.append({"name": "5V rail", "description": "Regulated 5V output rail"})
        if "usb-c" in prompt_text or "usb c" in prompt_text:
            rails.append({"name": "VBUS", "description": "USB-C provided power rail"})

        blocks = []
        if "esp32" in prompt_text:
            blocks.append({"name": "ESP32 MCU", "description": "Main MCU with wireless connectivity"})
        if "stm32" in prompt_text:
            blocks.append({"name": "STM32 MCU", "description": "Main MCU and control logic"})
        if "sensor" in prompt_text:
            blocks.append({"name": "Sensor subsystem", "description": "Environmental sensing block"})
        if "tracker" in prompt_text:
            blocks.append({"name": "Tracking subsystem", "description": "BLE advertising and position/asset tracking"})

        mechanical_constraints = []
        if "30x30" in prompt_text:
            mechanical_constraints.append("Maximum board outline 30mm x 30mm")
        elif "small" in prompt_text:
            mechanical_constraints.append("Compact board required; exact dimensions not provided")

        payload: dict[str, Any] = {
            "proposed_circuit_spec": {
                "schema_version": "1.0.0",
                "product_name": "Derived CircuitSpec",
                "summary": "Derived requirements from user request.",
                "target_board_type": board_type,
                "functional_blocks": blocks,
                "interfaces": interfaces,
                "power_rails": rails,
                "environmental_constraints": [],
                "mechanical_constraints": mechanical_constraints,
                "cost_constraints": [],
                "manufacturing_constraints": [],
                "preferred_parts": [],
                "banned_parts": [],
                "open_questions": [],
            },
            "summary": "Extracted high-level PCB requirements from the conversation.",
            "open_questions": [],
            "ambiguity_notes": [],
        }
        return schema.model_validate(payload)

    def call_tools(self, request: LLMRequest):  # pragma: no cover - not used by this agent
        return ()

    def stream_text(self, request: LLMRequest):  # pragma: no cover - not used by this agent
        yield ""


class RequirementsAgent:
    def __init__(self, provider: LLMProvider, model: str = "requirements-v1") -> None:
        self._provider = provider
        self._model = model
        self._prompt_loader = PromptTemplateLoader(Path(__file__).parent / "prompts")

    def derive(self, chat_history: list[RequirementsChatMessage], latest_user_request: str) -> RequirementsAgentResult:
        rendered_prompt = self._prompt_loader.load(
            "requirements_extraction.txt",
            chat_history=json.dumps([message.model_dump() for message in chat_history], indent=2),
            latest_user_request=latest_user_request,
        )
        request = LLMRequest(
            model=self._model,
            messages=(
                LLMMessage(role="system", content="You are a requirements extraction agent for PCB projects."),
                LLMMessage(role="user", content=rendered_prompt),
            ),
            temperature=0,
        )

        structured = self._provider.generate_structured(request, RequirementsDerivationOutput)
        sanitized = self._apply_quality_rules(
            structured=structured,
            source_text="\n".join([message.content for message in chat_history] + [latest_user_request]),
        )

        return RequirementsAgentResult(
            proposed_circuit_spec=sanitized.proposed_circuit_spec,
            summary=sanitized.summary,
            open_questions=sanitized.open_questions,
        )

    def _apply_quality_rules(
        self,
        structured: RequirementsDerivationOutput,
        source_text: str,
    ) -> RequirementsDerivationOutput:
        questions = list(dict.fromkeys(structured.open_questions + structured.proposed_circuit_spec.open_questions))
        ambiguities = list(structured.ambiguity_notes)
        source_lc = source_text.lower()

        if not structured.proposed_circuit_spec.power_rails:
            questions.append(MISSING_VOLTAGE_QUESTION)
        if not any(token in source_lc for token in ("ma", "amp", "current", "a ")):
            questions.append(MISSING_CURRENT_LIMIT_QUESTION)
        if not structured.proposed_circuit_spec.interfaces:
            questions.append(MISSING_INTERFACE_QUESTION)
        if not self._has_explicit_dimensions(structured.proposed_circuit_spec, source_lc):
            questions.append(MISSING_DIMENSION_QUESTION)

        for invented in self._find_unjustified_numeric_claims(structured.proposed_circuit_spec, source_lc):
            ambiguities.append(f"Potentially invented exact value: {invented}")
            questions.append(f"Please confirm whether '{invented}' is a real requirement or only a placeholder.")

        if self._looks_ambiguous(source_lc):
            ambiguities.append("The request contains qualitative terms that need quantification.")

        structured.proposed_circuit_spec.open_questions = list(dict.fromkeys(questions))
        structured.open_questions = list(dict.fromkeys(questions))
        structured.ambiguity_notes = list(dict.fromkeys(ambiguities))
        return structured

    @staticmethod
    def _has_explicit_dimensions(spec: CircuitSpec, source_lc: str) -> bool:
        combined = " ".join(spec.mechanical_constraints).lower() + " " + source_lc
        return bool(re.search(r"\b\d+(?:\.\d+)?\s?(?:x|×)\s?\d+(?:\.\d+)?\s?mm\b", combined))

    @staticmethod
    def _find_unjustified_numeric_claims(spec: CircuitSpec, source_lc: str) -> list[str]:
        extracted = []
        searchable_values = [
            spec.summary,
            *[entry.name for entry in spec.power_rails],
            *[entry.description or "" for entry in spec.power_rails],
            *spec.mechanical_constraints,
            *spec.preferred_parts,
        ]
        for value in searchable_values:
            for token in re.findall(r"\b\d+(?:\.\d+)?\s?(?:v|a|ma|mm|mil|ohm|k|uf|nf)\b", value.lower()):
                if token not in source_lc:
                    extracted.append(token)
        return sorted(set(extracted))

    @staticmethod
    def _looks_ambiguous(source_lc: str) -> bool:
        ambiguous_terms = ("small", "cheap", "low power", "fast", "robust", "compact")
        return any(term in source_lc for term in ambiguous_terms)
