from validation.pipeline import run_normalization_pipeline, to_mutable_invoice


def validate_invoice(data: dict, allow_critical_override: bool = False) -> dict:
    """Backward-compatible wrapper returning normalized invoice data."""
    result = run_normalization_pipeline(data, allow_critical_override=allow_critical_override)
    return to_mutable_invoice(result.normalized)
