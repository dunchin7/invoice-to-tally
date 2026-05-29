# Product Strategy — Invoice-to-Tally

## One-line positioning

> *"Forward the bills. We post them to Tally, validate every GSTIN, and tell you which ones will cost you ITC — before the deadline."*

---

## The problem we actually solve

Every CA accounting tool assumes structured input already exists. ClearTax wants a clean Excel.
TallyPrime wants you to have keyed the voucher. GSTR-2B reconciliation assumes the books are
already populated.

But a CA's actual day starts with a WhatsApp group full of blurry bill photos, a client who sends
40 PDFs the night before the 11th, and a junior accountant burning 6 hours keying them into Tally.
That labor — unstructured documents → clean, posted, reconciled entries — is the gap nobody
automated, because it's hard, ugly, and not glamorous.

That is the gap this product closes.

---

## Target segment (Phase 1)

**Mid-size CA firms: 10–50 staff, 100–500 client GSTINs**

Why this segment first:
- Each firm represents ₹40–60k/month ARR (200 client-GSTINs × ₹250/GSTIN). 10 firms = ₹60L ARR.
- Firms this size already run a junior → senior → partner workflow that maps onto our
  maker-checker approval flow — we fit how they already work.
- Partners are the buyer; they respond to risk-avoidance, not just time-savings.
- Indian CA networks are tight — one partner recommendation spreads to 5 peers.

---

## The deliverable that earns the subscription

A per-client monthly artifact, delivered on the 18th of each month:

```
Client: Sharma Traders — April 2026
──────────────────────────────────────────────────────
142 bills processed automatically.   138 posted to Tally.
4 need your attention:
  ⚠  2 GSTINs are CANCELLED  →  ₹47,200 ITC at risk — do not claim
  ⚠  1 amount mismatch  →  CGST differs ₹200 vs GSTR-2B
  ⚠  1 blurry total  →  AI confidence 54% — please verify
──────────────────────────────────────────────────────
₹2,80,000 ITC matched and safe.
```

This report is the product. Every technical decision should serve it.

---

## The metric that matters

**Auto-post rate** — what % of invoices a CA accepts without touching.

Target: ≥ 80% across design partners' real bill sets.
Below 70%: you are creating more work than you save. Stop building features, fix extraction.

---

## What we build for

Every feature earns its place by answering: *"Does this help a mid-size CA partner recommend us to a peer?"*

Features are ranked by two outcomes:
- **Time saved** — measurable in junior staff hours
- **Risk avoided** — measurable in ITC rupees protected or penalties prevented

If a feature doesn't map to one of those, it waits.

---

## 90-day roadmap

### Gate: Prove it survives reality (Weeks 1–2)

Before any new code, this must be true:

- [ ] Pipeline tested on **50 real, messy invoices** (not synthetic PDFs)
- [ ] Field-level accuracy measured: GSTIN, invoice number, date, total, tax split must be ≥ 90%
- [ ] **One live Tally instance** — 10 vouchers posted, ledgers verified correct
- [ ] 3 mid-size firms lined up for **paid** pilots (₹15–25k for 1 month, 10 clients)

**If accuracy < 90%: fix extraction before shipping anything else.**

---

### Phase 1 — Trust features (Weeks 3–6)

The features that make a partner say "I'd trust this with a client":

1. **Per-field confidence scores** — CA sees which fields to verify, not every field
2. **GSTIN status validation** — live API check: active / cancelled / non-existent. Blocks posting if cancelled.
3. **Multi-rate + cess line-item XML** — each line item posts at its own GST rate and cess. Wrong ledgers on day one = dead in a WhatsApp group.
4. **Maker-checker roles** — junior / senior / partner permissions matching existing firm workflow
5. **Data handling story** — bring-your-own-Azure-key option, tenant isolation, one-page data note

---

### Phase 2 — WhatsApp ingestion (Weeks 7–10)

The acquisition wedge. A CA forwards a number to their clients — no software, no training,
no behavior change. Garbage in = garbage out, so Phase 1 must be solid first.

Scope:
- WhatsApp Business API receiving invoices
- Attachment download → existing pipeline
- Reply to sender with summary ("✅ 3 invoices received — 1 flagged for review")

---

### Phase 3 — Monthly report + multi-client dashboard (Weeks 11–13)

Wrap it in the artifact above. One screen: all clients, who's clean, who's at risk, what's
due when, rupees of ITC protected. This is the renewal driver — the thing a CA screenshots
and sends to *their* client to justify *their own* fee.

---

## What we are not building (yet)

These are real CA pain points and real future modules. They wait until Phase 1 is paying:

- TDS tracking and Form 26Q
- E-invoice IRN validation (NIC portal cross-check)
- Bank statement reconciliation (3-way match)
- GSTR-1 preparation from sales invoices
- Reverse charge (RCM) determination
- IMS accept/reject API (GSTN portal write access)

Every one of these will be asked for in sales calls. The answer is: *"We're focused on getting
purchase ingestion and ITC protection right before expanding. What we have already protects your
clients' ITC automatically — that's what we want to be excellent at."*

---

## Moat

Reconciliation logic is copyable in a weekend. The defensibility compounds in:

1. **Accuracy on real Indian bills** — every invoice processed tunes extraction. Incumbents assume clean input; we handle the mess. The evaluation corpus (`datasets/`) grows with every design partner.
2. **WhatsApp relationship** — once 30 clients forward bills to our number, displacing us means re-training 30 clients.
3. **Trust through transparency** — confidence scores and "here's what I wasn't sure of" honesty is what gets a partner to hand us their license risk. Incumbents over-promise full automation. Our 80/20 framing is more credible.

---

## Positioning vs. incumbents

| | ClearTax | TallyPrime | Us |
|---|---|---|---|
| Input required | Clean Excel / GSTN export | Manually keyed voucher | WhatsApp / PDF / any format |
| Handles scanned bills | No | No | Yes |
| GSTIN status check | No | No | Yes |
| ITC at-risk alert | Partial | No | Yes, per invoice |
| Maker-checker workflow | Basic | No | Yes |
| Tally integration | Export only | Native | Direct POST |

**Pitch:** "Works *alongside* your existing Tally. We are the ingestion and ITC-guard layer
you're missing — not a rip-and-replace."

---

## Pricing

- **Annual contract** — predictable line item for firm budgets
- **Platform fee** (₹10–15k/month per firm) + **per-client-GSTIN** (₹200–300/GSTIN/month)
- Firm with 200 client-GSTINs: ₹40–60k/month = ₹5–7L/year
- Against 2–3 junior staff hours displaced: ₹18–36L/year of capacity freed

Do not discount the platform fee. It filters tire-kickers.

---

## Sales motion

Not a SaaS PLG motion — a sales-led pilot motion:

1. **Identify** 3–5 firms via ICAI study circles, CA WhatsApp groups, referrals
2. **Sell a paid pilot** (not free): 1 month, 10 client-GSTINs, ₹15–25k
3. **Deliver the monthly report** at end of pilot — walk into the partner's office with it
4. **Convert to annual** contract on the spot
5. **Get a reference call** commitment as part of the contract

10 annual contracts from this motion = ₹60L ARR, bootstrapped.
