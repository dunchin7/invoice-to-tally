from validation.pipeline import run_normalization_pipeline


def validate_invoice(data: dict, allow_critical_override: bool = False) -> dict:
    """Backward-compatible wrapper returning normalized invoice data."""
    result = run_normalization_pipeline(data, allow_critical_override=allow_critical_override)
    return result.normalized
