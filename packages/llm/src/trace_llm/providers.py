from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str) -> str:
        raise NotImplementedError


class MockProvider(LLMProvider):
    def complete(self, prompt: str) -> str:
        return f"mock-response:{prompt[:32]}"
