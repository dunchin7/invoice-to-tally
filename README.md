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

---

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
