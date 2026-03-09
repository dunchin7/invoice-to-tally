# Phase 1 & Phase 2 Review: OCR-based Invoice Extractor Engine

## Scope reviewed

This review covers the OCR + extraction + normalization + reconciliation + posting stack implemented across:

- Ingestion/OCR (`ingestion/`, `ocr/`)
- LLM extraction (`llm/`)
- Validation and pre-import reconciliation (`validation/`)
- Tally XML and client integration (`tally/`)
- Workflow orchestration (`service/orchestrator.py`)
- CLI entrypoint (`main.py`)

## High-level assessment

The architecture is clean and modular, and unit tests for core post-OCR flows pass. The largest risk areas are:

1. **Entrypoint correctness and usability** (was broken before this review, now fixed in `main.py`).
2. **Confidence signal quality** in LLM extraction.
3. **Operational hardening gaps** for orchestration (state durability / partial failure semantics / upload mode).

## Module-by-module review

### 1) Ingestion + OCR

**What looks good**
- Input-aware routing for PDF/image/doc/docx with clear operator messages.
- OCR runtime validation is explicit and user-friendly for missing binaries.
- PDF text layer fallback to OCR is implemented correctly.

**Issues / risks**
- No explicit OCR timeout or page limits can cause long-running jobs on large/scanned PDFs.
- OCR language and image preprocessing are not configurable; quality may degrade for noisy invoices.

**Recommended tasks**
- Add configurable OCR timeout and max-pages guardrails.
- Add optional preprocessing pipeline (deskew, binarization, contrast) and per-tenant OCR language hints.

### 2) LLM extractor

**What looks good**
- Retry + repair pass strategy is solid.
- Diagnostics payload is practical for observability.

**Issues / risks**
- `_compute_confidence` counts only non-empty strings for many fields. Numeric fields (subtotal/tax/total) can be present but not counted, creating artificially low confidence.
- Confidence is completeness-only and does not include consistency checks (e.g., totals).

**Recommended tasks**
- Fix confidence field presence checks to handle numeric values and nested objects robustly.
- Add secondary confidence dimensions: schema-valid, accounting-consistent, extraction-repair-used.

### 3) Validation pipeline

**What looks good**
- Strong normalization and cross-field consistency checks.
- Clear critical-failure override mechanism.

**Issues / risks**
- Schema + accounting failures are raised as `ValueError`, but no structured error type exists for downstream classification.

**Recommended tasks**
- Introduce typed validation exceptions with machine-readable codes.
- Emit per-field confidence scores to support better manual review triage.

### 4) Pre-import reconciliation

**What looks good**
- Rule lookup precedence (SQLite → tenant JSON → global JSON) is sensible.
- Rich issue payload (suggestions, remediation, fallback action) is useful.

**Issues / risks**
- Suggestion ranking is token-overlap only and can be weak for OCR-noisy variants.
- Auto-create path returns "created" resolution but does not persist suggested rule automatically.

**Recommended tasks**
- Upgrade matcher with edit-distance / token-sort / alias weighting.
- Add optional "learn rule on approval" persistence flow.

### 5) Tally XML and HTTP client

**What looks good**
- Voucher mapping is well split from XML serialization.
- Balance validation and round-off thresholds are strong safeguards.
- Client retry/backoff and response parsing are implemented.

**Issues / risks**
- No circuit-breaker / request id correlation in client logs for high-volume use.

**Recommended tasks**
- Add request-id propagation and structured logs for each upload attempt.
- Add integration test fixture with representative Tally error responses.

### 6) Orchestrator

**What looks good**
- State machine and artifact persistence are clear and auditable.
- Manual-review routing and idempotency keying are practical.

**Issues / risks**
- Posting step currently simulates success after XML generation instead of using `TallyClient` in the orchestrated flow.
- Idempotency store writes are not lock-protected for concurrent workers.

**Recommended tasks**
- Integrate real upload mode in orchestrator with dry-run option and response persistence.
- Add file-locking or transactional store for idempotency in concurrent environments.

### 7) CLI entrypoint (`main.py`)

**What was fixed in this review**
- `main.py` had merge-corrupted code with duplicate `main()` definitions and an unclosed function call, causing a syntax error.
- Replaced with a single orchestration-focused CLI path that parses args, runs orchestrator, and prints structured JSON result.

## Priority task list

### P0 (must fix before broad rollout)
1. Keep `main.py` healthy with CI compile checks (`python -m py_compile main.py`).
2. Correct LLM confidence scoring to count numeric/non-string fields.
3. Wire real Tally upload option into orchestrator posting stage.

### P1 (next sprint)
1. Add OCR guardrails (timeout/page limits) and preprocessing toggles.
2. Improve reconciliation suggestion ranking.
3. Add concurrency-safe idempotency store writes.

### P2 (hardening)
1. Add richer typed error taxonomy across ingestion/extraction/validation/reconciliation/posting.
2. Add end-to-end smoke test over sample invoice with mocked provider + mocked Tally endpoint.
3. Add metrics hooks for stage latency and review-rate KPIs.

## Validation commands run during review

- `PYTHONPATH=. pytest -q` → passed.
- `python -m py_compile main.py` → passed after entrypoint fix.
