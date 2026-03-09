# AGENTS.md

## Project map
- `ingestion/`: Input intake helpers for files and metadata before OCR begins.
- `ocr/`: OCR extraction logic (PDF/image → raw text) and OCR-related configuration hooks.
- `llm/`: LLM-facing extraction/parsing components that transform OCR text into structured invoice fields.
- `validation/`: Normalization, schema checks, reconciliation rules, confidence scoring, and validation reporting.
- `tally/`: Tally-specific XML generation, transport clients, and upload contract handling.
- `service/`: Orchestration/state-machine workflows, idempotency controls, artifact writes, and job lifecycle management.
- `tests/`: Unit/integration coverage for orchestrator, validation, Tally conversion/upload behavior, and regression cases.

## Runbook commands
Execute in this order before opening or updating a PR:
1. **Compile/syntax sanity**
   - `python -m compileall ingestion ocr llm validation tally service tests`
2. **Unit/integration tests**
   - `python -m pytest tests -q`
3. **(Optional) Full pipeline smoke run**
   - `python main.py --input samples/sample_invoice.pdf --dry-run`

If any step fails, stop and fix forward before proceeding.

## Change rules
- Keep modules decoupled: avoid cross-layer shortcuts (e.g., `ocr/` calling `tally/` directly).
- Preserve structured error contracts: do not replace typed/structured errors with raw strings or ambiguous generic failures.
- Add or adjust tests for every behavioral change, including negative/error-path coverage when relevant.

## Orchestrator safety
- Enforce idempotency for posting steps: repeated processing of the same logical invoice must not create duplicate Tally submissions.
- Respect `--dry-run` semantics: generate and persist artifacts/reports without performing live Tally upload side effects.
- In live mode, persist upload request/response and job-state artifacts needed for traceability and replay diagnostics.

## Validation & confidence policy
- Confidence must be deterministic and explainable from component-level signals (OCR quality, extraction certainty, validation outcomes).
- When extending confidence logic, update thresholds/rules and tests together so review-required routing remains predictable.
- Maintain a stable error-code taxonomy for validation/reconciliation failures; new failure classes require new explicit codes, not overloaded existing codes.

## PR checklist
- Tests run locally and results recorded in PR description.
- Backward-compatibility impact documented (schemas, flags, artifact formats, and API contracts).
- Security/sanitization checks completed for logs/artifacts (no secrets, sensitive payload minimization, safe redaction where required).

## Do-not-do list
- Do not hardcode secrets, credentials, tenant identifiers, or environment-specific endpoints.
- Do not silently swallow exceptions; always propagate or map to structured errors with context.
- Do not break output schemas/contracts without documenting migration notes and compatibility implications.
