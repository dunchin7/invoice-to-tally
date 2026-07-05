# Notice Response Agent — Build Spec

*The hero agent. Drafts replies to GST/IT notices grounded in the client's own reconciled ledger,
with verified citations. Builds directly on the ITC Guardian reconciliation engine.*

---

## Why this agent, and why it's defensible

Notice-reply drafting is a 4-hours-to-30-minutes task, high-stakes ("a single wrong reply →
penalty, interest, prosecution"), and the hottest paid AI category for Indian CAs.

**The serious competitor is Taxmann.AI + EY India's "Draft Bot"** (July 2025): upload a notice → it
validates procedural elements → drafts a reply with provisions and case references, grounded in
India's largest legal corpus with hyperlinked citations. VIDUR, GST Notice AI, TaxNoticeAI do
similar, lighter. **Every one of them drafts from a generic notice + a law library. None can see
the client's actual books.**

Our differentiation is structural, not "better law knowledge" — we will never out-corpus Taxmann,
and we should not try. The **ITC Guardian** has already reconciled *this client's* books against
GSTR-2B. When a **DRC-01C** (ITC-mismatch auto-notice) or **ASMT-10** (scrutiny) arrives, we draft
the reply *from that reconciliation* — real figures, real supplier-level detail — which no
law-library tool can do. On top of that we add a citation-verification loop that guarantees no
fabricated case law (the anti-*Buckeye-Trust* guarantee).

**Why we can ground the law accurately despite the ~73% LLM ceiling:** the Taxmann–IIT Kharagpur
benchmark showed even top LLMs cap at ~73% on *general* Indian tax law. We sidestep that by keeping
the law surface **narrow and stable** — the DRC-01C/ITC domain touches only Rule 88D, Sec 16(2)(c),
Rule 37A, and a handful of circulars. A small, curated, verifiable set is maintainable to near-100%
accuracy; a general corpus is not. Narrow scope isn't a limitation here — it's the accuracy
strategy.

---

## Scope (v1)

**In scope — the ITC-mismatch loop:**
- **DRC-01C** (Rule 88D: 3B ITC > 2B beyond tolerance, 7-day clock) — the natural extension of ITC Guardian
- **ASMT-10** (GST scrutiny of returns)

**Out of scope for v1** (later versions): SCN/DRC-01, income-tax 143(3)/148, registration notices.
Start narrow — the DRC-01C loop is where we already hold the grounding data.

**The agent NEVER submits.** It drafts to a review queue. Filing is always a human action.

---

## Inputs

1. **The notice document** (PDF upload or WhatsApp forward). Extract:
   - GSTIN, legal name, tax period
   - Notice type & reference number (DRC-01C / ASMT-10)
   - The specific discrepancy: claimed 3B ITC, available 2B ITC, the delta, section/rule cited
   - Response deadline (compute days remaining, flag if < 3)

2. **The client's reconciled ledger** — pulled directly from the ITC Guardian
   `ReconciliationReport` for that GSTIN + period. This is the moat: we already have
   matched / value-mismatch / books-only / gstr2b-only classification per invoice.

3. **The client's filed returns** for the period (GSTR-1, GSTR-3B, GSTR-2B) — for cross-referencing
   what was actually claimed vs available.

4. **Grounding corpus** (law) — current GST Act sections, CBIC circulars & notifications, and a
   case-law index, each entry carrying a stable citation ID and source URL.

---

## Pipeline

```
Notice PDF ──► extract(notice) ──► {gstin, period, type, discrepancy, deadline}
                                          │
                                          ▼
              load ITC Guardian ReconciliationReport(gstin, period)
                                          │
                                          ▼
              classify the discrepancy against OUR reconciliation:
                • books_only invoices → supplier hasn't filed → ITC legitimately
                  deferrable / reversible with explanation
                • value_mismatch → explain the specific per-invoice delta
                • timing (2B lag) → invoice appears in next period's 2B
                • genuine excess → flag for CA, do NOT auto-justify
                                          │
                                          ▼
              retrieve grounding law for the applicable rule (e.g. Rule 37A,
              Sec 16(2)(c), Circular refs) with citation IDs
                                          │
                                          ▼
              draft reply (LLM) — MUST cite only retrieved citation IDs
                                          │
                                          ▼
              ┌─────────────────────────────────────────────┐
              │  CITATION-VERIFICATION LOOP (anti-Buckeye)   │
              │  every citation in the draft is checked      │
              │  against the grounding index. Unverifiable   │
              │  citations are STRIPPED and the draft is      │
              │  regenerated. Nothing unverifiable is emitted.│
              └─────────────────────────────────────────────┘
                                          │
                                          ▼
              draft → maker-checker review queue (never auto-filed)
```

---

## The citation-verification loop (the core trust feature)

This is what defeats *Buckeye Trust* and beats VIDUR's unproven claims. Non-negotiable design:

1. The LLM is instructed it may cite **only** from the retrieved grounding set, and must tag each
   citation with its `citation_id`.
2. After generation, **every** `citation_id` and quoted section text in the draft is validated
   against the grounding index:
   - `citation_id` must exist in the retrieved set.
   - Quoted statutory text must match the source within a similarity threshold.
3. Any citation that fails → **stripped**, and the claim it supported is either regenerated from a
   verified source or flagged `[CITATION UNVERIFIED — CA to confirm]`.
4. **The agent never emits a citation it did not verify against a real source.** A draft with a
   fabricated citation is a product-integrity failure, not a minor bug.
5. Every citation in the final draft links to its source (section/paragraph) for one-click CA
   verification.

**Guarantee we can sell:** *"Every legal reference in a draft is traceable to a real, current
source — or it isn't in the draft."*

---

## Output

A structured draft reply containing:
- Header: notice ref, GSTIN, period, deadline
- Point-by-point response to the discrepancy, **quoting the client's own reconciled figures**
  (e.g. "Of the ₹X ITC excess alleged, ₹Y pertains to N invoices where the supplier had not filed
  GSTR-1 as of the 2B cut-off — reconciliation attached")
- Verified citations inline, each linked to source
- An attachable reconciliation annexure (from ITC Guardian, already CSV/JSON)
- A confidence/completeness note for the CA: what's solid, what needs the CA's judgment

---

## Maker-checker flow

Maps to the mid-size-firm workflow and ICAI IT-control expectations:

| Role | Can | Cannot |
|---|---|---|
| **Junior** | See queue, fix flagged items, edit draft | Approve / send |
| **Senior** | Review, approve draft for partner sign-off | Final filing |
| **Partner** | Sign off, mark ready to file | — |

Nothing leaves the system without human sign-off. Filing to the portal remains a manual CA action
(v1 produces the draft + annexure; it does not submit).

---

## Security boundary

- Runs inside the same India-resident, DPDPA-aligned boundary as the rest of the pipeline.
- **Bring-your-own-Azure-key** supported — notice + ledger data never leaves the firm's tenant.
- **Immutable audit log**: every draft records which client data was accessed, which grounding
  sources were retrieved, every citation emitted and its verification result, and who reviewed/
  signed. This log is both a compliance artifact and a defense if a reply is ever questioned.
- No client data used for training. Contractual no-retention.

---

## What we reuse vs build

**Reuse (already built):**
- `reconciliation/` engine → the `ReconciliationReport` is the grounding data
- `llm/providers/` abstraction → BYO-Azure-key, provider selection
- OCR / document ingestion → for reading the notice PDF
- Idempotency + output-dir patterns

**Build new:**
- Notice parser (extract discrepancy + deadline from DRC-01C / ASMT-10)
- Grounding corpus + retrieval index (GST Act, circulars, case law) with citation IDs
- The citation-verification loop
- Draft generator with the citation contract
- Maker-checker review queue + roles
- Audit log

---

## v1 definition of done

- [ ] Parses a real DRC-01C and extracts GSTIN, period, ITC delta, deadline
- [ ] Pulls the matching ITC Guardian reconciliation for that GSTIN + period
- [ ] Classifies the discrepancy against our reconciliation (books_only / value_mismatch / timing / genuine)
- [ ] Generates a draft that quotes the client's real figures
- [ ] **Zero unverified citations reach the output** (citation-verification loop enforced + tested)
- [ ] Draft lands in a maker-checker queue; nothing auto-files
- [ ] Full audit log of data accessed, sources cited, verification results, reviewers
- [ ] Runs under BYO-Azure-key with no data leaving the firm's tenant
