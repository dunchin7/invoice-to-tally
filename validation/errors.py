from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class ValidationFlowError(Exception):
    """Base class for structured validation failures."""

    message: str
    code: str
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.context:
            payload["context"] = self.context
        return payload


class SchemaValidationError(ValidationFlowError):
    def __init__(self, message: str, context: dict[str, Any] | None = None):
        super().__init__(message=message, code="SCHEMA_VALIDATION_ERROR", context=context or {})


class AccountingValidationError(ValidationFlowError):
    def __init__(self, message: str, context: dict[str, Any] | None = None):
        super().__init__(message=message, code="ACCOUNTING_VALIDATION_ERROR", context=context or {})


class FieldNormalizationError(ValidationFlowError):
    def __init__(self, message: str, context: dict[str, Any] | None = None):
        super().__init__(message=message, code="FIELD_NORMALIZATION_ERROR", context=context or {})
