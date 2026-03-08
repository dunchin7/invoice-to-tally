from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Provider interface for invoice extraction orchestration."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @abstractmethod
    def extract_structured_invoice(self, raw_text: str) -> str:
        """Return model response text that should contain invoice JSON."""

    @abstractmethod
    def repair_json(self, raw_text: str, broken_json: str, parse_error: str) -> str:
        """Return model response text containing repaired JSON only."""
