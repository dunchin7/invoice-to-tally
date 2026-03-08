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

## ⚙️ Prerequisites

### 1) Python

* Python 3.10+ (tested with Python 3.12)

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

### 2) Tally XML

```
outputs/tally_invoice.xml
```

---

## 🧠 Architecture Notes

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
