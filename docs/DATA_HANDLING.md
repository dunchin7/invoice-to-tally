# Data Handling — What Happens to Your Clients' Invoices

*For CA firm partners evaluating a pilot. One page.*

---

## The short version

Your clients' invoice data is processed, posted to your Tally, and then retained only as long
as you need the reconciliation history. We do not train models on it. We do not share it.
You can bring your own Azure key so it never leaves your cloud.

---

## Data flow

```
Client sends PDF/image
       ↓
OCR (runs locally on your server or our hosted instance)
       ↓
Azure OpenAI GPT-4o  ←── structured extraction only, no storage at Azure
       ↓
Normalized JSON  ←── stored in your output directory
       ↓
Tally XML  →  Tally HTTP port (your LAN, never leaves your network)
       ↓
Reconciliation report  →  your output directory
```

---

## What is sent to Azure OpenAI

Only the **extracted text** from the invoice — not the original PDF or image.

The text is sent as a one-shot chat completion. Azure OpenAI processes it and returns JSON.
Azure OpenAI does not log or store chat content for model training by default (per Microsoft's
data privacy terms for Azure services). Your Azure subscription's data residency controls apply.

If you use your own Azure OpenAI resource (see "Bring your own key" below), the data never
leaves your Azure tenant at all.

---

## What we store

| Data | Where | How long |
|------|-------|----------|
| Extracted invoice JSON | Your server / your directory | Until you delete it |
| Reconciliation reports (JSON, CSV, text) | Your server / your directory | Until you delete it |
| Idempotency index (invoice hash → posted status) | Your server | Until you delete it |
| Raw PDFs / images | Your server (input directory) | You control |

We do not operate a central database that holds client invoice data. Output files are local
to where the pipeline runs.

---

## Bring your own Azure key (recommended for data-sensitive firms)

If you want zero invoice data to pass through a third-party service, configure the pipeline
with your firm's Azure OpenAI deployment:

```env
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=https://yourfirm.openai.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
```

In this mode, data goes: your server → your Azure tenant → your Tally. We never see it.

---

## Client isolation

Each client's output is written to a separate job directory, scoped by tenant ID. There is no
cross-client data leakage in the output files. If you run the tool centrally for multiple
clients, we recommend one output root per client:

```
outputs/
  sharma-traders/
  gupta-enterprises/
  delhi-exports/
```

---

## Tally communication

XML is posted via HTTP to Tally's local port (default 9000). This is a LAN-only call —
Tally must be running on the same network. No invoice data transits the internet during
the Tally posting step.

---

## What we do NOT do

- We do not store invoice data centrally or in a cloud database
- We do not use your clients' invoices to train or fine-tune any model
- We do not share data with third parties other than Azure OpenAI (for extraction) and
  your Tally instance (for posting)
- We do not have access to your Tally installation or your Tally company files

---

## Questions partners ask

**"What if Azure OpenAI leaks our data?"**
Azure OpenAI's enterprise terms explicitly exclude customer data from model training. Your data
is processed in-memory per request. For zero-trust, use your own Azure key — then even we
cannot see what's processed.

**"Can you sign an NDA / data processing agreement?"**
Yes. Contact us before the pilot starts.

**"What happens to data if we stop using the product?"**
All data lives on your server in files you control. Deleting the output directory deletes all
extracted data. There is nothing to "request deletion" from our side because we don't hold it.

**"Is it DPDPA compliant?"** *(Digital Personal Data Protection Act 2023)*
Invoice data is financial/business data, not personal data in most cases. To the extent it
contains personal data (individual proprietors, sole traders), your firm is the data fiduciary
and you control retention. We are a data processor operating under your instructions.

---

*Last updated: May 2026*
