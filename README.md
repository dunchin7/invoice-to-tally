# Invoice to Tally – OCR + LLM Pipeline

A demo-grade proof-of-work system that converts invoice PDFs/images into **structured JSON** and **Tally-compatible XML** using OCR and Gemini LLM.

---

## 🚀 What This Project Does

This tool takes an invoice (PDF or image), extracts text using OCR, uses a Large Language Model (Gemini) to extract structured fields, normalizes and validates the output against a strict JSON schema, and finally generates a Tally-importable XML voucher.

**Pipeline:**

```
Invoice (PDF/Image)
   → OCR (Tesseract + Poppler)
   → Gemini LLM (field extraction)
   → Normalizer (cleans LLM output)
   → JSON Schema Validation
   → Structured JSON
   → Tally XML
```

---

## 📁 Project Structure

```
invoice-to-tally/
│
├── main.py                 # CLI entrypoint
├── settings.py             # Centralized env/config settings
├── requirements.txt        # Python dependencies
├── .env                    # Gemini API key (not committed)
├── .gitignore
│
├── ocr/
│   └── ocr_engine.py       # OCR logic (Tesseract + Poppler)
│
├── llm/
│   └── extractor.py        # Gemini LLM integration
│
├── schema/
│   └── invoice_schema.py   # JSON schema for validation
│
├── validation/
│   ├── __init__.py
│   └── normalizer.py       # Output normalization + schema validation
│
├── tally/
│   ├── __init__.py
│   └── xml_generator.py    # Tally XML generator
│
├── samples/
│   └── sample_invoice.pdf  # Demo invoice
│
├── outputs/                # Generated JSON + XML (gitignored)
│   ├── invoice_structured.json
│   └── tally_invoice.xml
```

---

### Pre-import reconciliation with Tally master data

Before XML generation, the CLI can now reconcile extracted entities against Tally master data:

* Fetches **party/ledger/stock-item** masters from Tally HTTP API and caches them locally (`outputs/tally_master_cache.json`).
* Resolves extracted buyer/line-item names using:
  1) tenant/global mapping rules (`validation/config/mapping_rules.json`),
  2) exact master-name match,
  3) alias match.
* Applies configurable fallback policies per entity (`auto_create`, `reject`, `manual_review`).
* Emits actionable reconciliation issues with field names and top suggestions in `outputs/preimport_report.json`.
* Supports tenant-specific rules from JSON and optional SQLite (`--mapping-rules-db`).

Useful flags:

```bash
python main.py --input samples/sample_invoice.pdf \
  --tenant-id default \
  --party-fallback manual_review \
  --stock-fallback reject \
  --ledger-fallback reject \
  --mapping-rules-file validation/config/mapping_rules.json
```

## ⚙️ Prerequisites

### 1) Python

* Python 3.10+ (tested with Python 3.12)

### 2) Tesseract OCR

Download and install:

```
https://github.com/UB-Mannheim/tesseract/wiki
```

Default install path used in code:

```
C:\Program Files\Tesseract-OCR\tesseract.exe
```

### 3) Poppler (for PDF support)

Download Poppler for Windows:

```
https://github.com/oschwartz10612/poppler-windows/releases
```

Extract to:

```
C:\poppler-25.12.0\Library\bin
```

> ⚠️ The Poppler path is hard-wired in `ocr/ocr_engine.py` for reliability.
### 2) OCR binaries

You need:

* **Tesseract OCR** (`tesseract` executable)
* **Poppler** (`pdftoppm` executable, used for PDF conversion)

Install references:

* Tesseract: <https://github.com/UB-Mannheim/tesseract/wiki>
* Poppler Windows builds: <https://github.com/oschwartz10612/poppler-windows/releases>

### 3) Configure OCR paths (optional but recommended)

The app reads OCR executable settings from environment variables:

* `TESSERACT_CMD` → full path to `tesseract` executable
* `POPPLER_PATH` → folder containing Poppler binaries (the folder that includes `pdftoppm`)

If unset, the app uses system defaults (`PATH`).

#### Linux / macOS examples

```bash
# Use system binaries from PATH (no extra config)
python main.py --input samples/sample_invoice.pdf

# Or explicitly set custom locations
export TESSERACT_CMD=/usr/local/bin/tesseract
export POPPLER_PATH=/usr/local/opt/poppler/bin
python main.py --input samples/sample_invoice.pdf
```

#### Windows (PowerShell) examples

```powershell
# Use explicit install locations
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$env:POPPLER_PATH = "C:\poppler-25.12.0\Library\bin"
python main.py --input samples/sample_invoice.pdf
```

#### Docker-friendly example

```dockerfile
ENV TESSERACT_CMD=/usr/bin/tesseract
ENV POPPLER_PATH=/usr/bin
```

> Runtime validation is input-aware: image OCR requires **Tesseract**; PDF OCR requires **Tesseract + Poppler**. Errors clearly list what is missing.

### 4) Configure Tally upload options (optional)

Set these environment variables to enable direct upload to a running Tally instance:

* `TALLY_HOST` (default: `localhost`)
* `TALLY_PORT` (default: `9000`)
* `TALLY_COMPANY` (optional company context for imports)
* `TALLY_VOUCHER_TYPE` (default: `Sales`)
* `TALLY_VOUCHER_ACTION` (default: `Create`)
* `TALLY_TIMEOUT_SECONDS` (default: `15`)
* `TALLY_MAX_RETRIES` (default: `3`)
* `TALLY_RETRY_BACKOFF_SECONDS` (default: `1`)

Use CLI flags to control upload behavior:

```bash
python main.py --input samples/sample_invoice.pdf --upload-to-tally
python main.py --input samples/sample_invoice.pdf --upload-to-tally --dry-run
```


### Why OCR binaries are required (and accuracy impact)

This project uses Python wrappers (`pytesseract`, `pdf2image`) around native OCR tools:

* `pytesseract` **does not include OCR itself**; it calls the external `tesseract` binary.
* `pdf2image` converts PDFs via Poppler tools (notably `pdftoppm`) before OCR.

For best extraction quality, use current stable Tesseract/Poppler builds and clear PDF/image inputs (higher DPI, non-blurry scans).

### Can we include OCR binaries in this repo?

Short answer: **not recommended**.

* Binary artifacts are large and will bloat git history.
* Cross-platform binaries differ (Linux/macOS/Windows), so one repo copy will not fit all environments.
* Packaging and redistribution/licensing obligations are easier to manage via OS packages or Docker base images.
* Security and patching are better handled by package managers or maintained container images.

Recommended approach:

* Install OCR binaries at deploy/runtime layer (host VM, CI image, or Docker image).
* Pass locations with `TESSERACT_CMD` / `POPPLER_PATH` when paths are non-standard.

---


## 🧭 Orchestration Layer

The project now includes a service orchestrator (`service/orchestrator.py`) that tracks each invoice as a job through:

- `ingested`
- `extracted`
- `validated`
- `review_required`
- `posted`
- `failed`

For every job, the orchestrator persists artifacts under `outputs/orchestration/<job_id>/`:

- `raw_ocr_text.txt`
- `extracted_invoice.json`
- `normalized_invoice.json`
- `validation_report.json`
- `tally_invoice.xml` (when posted)
- `upload_response.json`
- `job_record.json` (state + audit trail)

It also writes:

- `outputs/orchestration/manual_review_queue.jsonl` for low-confidence or validation-failed invoices.
- `outputs/orchestration/idempotency_store.json` to prevent duplicate Tally posting for the same invoice.

Idempotency persistence is guarded by a file lock (`idempotency_store.lock`) so duplicate submissions for the same idempotency key are resolved atomically. The first winner records the successful upload response, and later duplicates are marked as `duplicate` with the original response nested under `response` for replay retrieval and traceability.

## 🔑 Gemini API Key Setup

1. Go to: [https://makersuite.google.com/app/apikey](https://makersuite.google.com/app/apikey)
2. Create a free Gemini API key
3. Create a `.env` file in the project root:

```
GEMINI_API_KEY=your_api_key_here
```

---

## 🧪 Setup Instructions

### 1) Clone the repo

```
git clone <your-repo-url>
cd invoice-to-tally
```

### 2) Create virtual environment

```
python -m venv venv
venv\Scripts\activate
```

### 3) Install dependencies

```
pip install -r requirements.txt
```

---

## ▶️ Running the Demo

```
python main.py --input samples/sample_invoice.pdf
```

### Expected Output

```
[*] Extracting text from invoice...
[*] Sending text to Gemini for field extraction...
[*] Validating extracted invoice...
[+] Structured invoice saved to: outputs/invoice_structured.json
[+] Tally XML saved to: outputs/tally_invoice.xml
```

---

## 📄 Output Files

### 1) Structured JSON

```
outputs/invoice_structured.json
```

Example:

```json
{
  "invoice_number": "INV-3337",
  "invoice_date": "January 25, 2016",
  "seller": "DEMO - Sliced Invoices | Suite 5A-1204 123 Somewhere Street Your City AZ 12345",
  "buyer": "Test Business | 123 Somewhere St Melbourne, VIC 3000",
  "line_items": [
    {
      "description": "Web Design - This is a sample description...",
      "quantity": 1.0,
      "unit_price": 85.0,
      "total_price": 85.0
    }
  ],
  "subtotal": 85.0,
  "tax": 8.5,
  "total": 93.5,
  "currency": "AUD"
}
```

---

### 2) Tally XML

```
outputs/tally_invoice.xml
```

Example:

```xml
<?xml version='1.0' encoding='utf-8'?>
<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE>
          <VOUCHER VCHTYPE="Sales" ACTION="Create">
            <DATE>January 25, 2016</DATE>
            <VOUCHERNUMBER>INV-3337</VOUCHERNUMBER>
            <PARTYLEDGERNAME>Test Business | 123 Somewhere St Melbourne, VIC 3000</PARTYLEDGERNAME>
            <NARRATION>Imported from Invoice AI</NARRATION>

            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Sales</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>85.0</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Tax</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>8.5</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>Test Business | 123 Somewhere St Melbourne, VIC 3000</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>93.5</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>
```

---

## 🧠 Architecture Notes

* **OCR Layer:** Tesseract + Poppler
* **OCR Layer:** Tesseract + Poppler (env-driven config)
* **LLM Layer:** Gemini via `google-genai`
* **Normalization:** Fixes inconsistent field names, numeric strings, nested objects
* **Validation:** JSON Schema ensures correctness
* **Output:** Deterministic XML for Tally

---

## ⚠️ Known Limitations

* Date format is not normalized to `YYYYMMDD`
* Tax is not split into CGST/SGST/IGST
* Buyer/seller ledgers must exist in Tally
* Works best with clean printed invoices

---

## 🔮 Future Enhancements

* Batch processing of invoice folders
* OpenAI / Azure fallback for LLM
* Automatic ledger creation
* GST ledger mapping
* Multi-line invoice support
* Configurable XML templates

---

## 👨‍💻 Demo Script (What to Say)

> We take a raw invoice PDF, extract text using OCR, pass it to Gemini for structured field extraction, normalize and validate the output against a strict schema, then generate a Tally-compatible XML voucher.

Then run:

```
python main.py --input samples/sample_invoice.pdf
```

---

## 📜 License

MIT License

---

## ✅ Status

This is a working proof-of-work prototype demonstrating:

* Invoice OCR
* LLM-powered field extraction
* Schema validation
* Accounting-system XML generation

**Ready for demo and iteration.**

---

## 📊 Evaluation Workflow (Field + Document Quality)

Use the benchmark dataset and evaluator to measure extraction quality over time.

### Benchmark folders

- `datasets/source_docs/`: source invoice files by vendor/template (scaffold kept via `.gitkeep`; avoid committing large binaries).
- `datasets/ground_truth/`: labeled JSON ground truth.
- `evaluation/run_eval.py`: evaluation runner.
- `evaluation/reports/`: generated CSV/JSON reports.

### Run evaluation

```bash
python evaluation/run_eval.py \
  --ground-truth-dir datasets/ground_truth \
  --predictions-dir outputs \
  --report-dir evaluation/reports
```

### Metrics included

- Field-level precision / recall / F1 for key fields (`invoice_number`, `invoice_date`, `seller`, `buyer`, `currency`, `subtotal`, `tax`, `total`).
- Line-item matching precision / recall / F1 based on description + quantity + unit price + total price.
- Document-level quality:
  - exact document match rate
  - critical-field pass rate

### Release readiness gates

By default the evaluator fails (`exit code 1`) when either gate fails:

- Any critical field (`invoice_number`, `invoice_date`, `total`) has F1 below `0.95`.
- Critical document pass rate is below `0.90`.

Override thresholds if required:

```bash
python evaluation/run_eval.py \
  --critical-f1-threshold 0.98 \
  --critical-doc-pass-threshold 0.95
```

### Report outputs for regression tracking

- `evaluation/reports/evaluation_summary.json`: full run summary + gate status.
- `evaluation/reports/evaluation_fields.csv`: tabular metrics for plotting/tracking.

### Adding new invoice templates/vendors to benchmark

1. Add the source invoice under `datasets/source_docs/`.
2. Create a matching labeled JSON in `datasets/ground_truth/` with the same file stem.
3. Generate or collect prediction JSON in your predictions folder with the same stem.
4. Run evaluator and inspect release gates + metrics trend in saved reports.
