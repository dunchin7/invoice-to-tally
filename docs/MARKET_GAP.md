# Market Gap & Re-Locked Direction

*Supersedes the "product for mid-size CA firms" framing in STRATEGY.md and CONTEXT_AGENTS.md.
Those remain valid as the first connector + higher-value agents; this document reframes the whole
into the larger, more defensible opportunity the ground-reality research surfaced.*

---

## Re-locked problem statement

> Indian businesses run their operations on one set of systems (SAP / NetSuite / Dynamics /
> marketplaces / banks) and their statutory books + compliance on another (**Tally + the GST
> portal**). **Nothing connects the two.** Data crosses the boundary by manual Excel export and
> human re-keying — the "swivel-chair." Global integration tools ignore the Indian stack and cost
> 5–10× what this market will pay; custom software carries an unaffordable maintenance cliff. So the
> gap gets filled by **headcount, not software**.
>
> We build the **agentic integration layer for the Indian finance stack — Tally- and GST-aware glue
> that connects any operational system into Tally + the GST portal — delivered to CA firms as a
> productized, done-for-you, maintained service.**

---

## The three decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Who we sell to | **CA / accounting / virtual-CFO firms** (not direct-to-mid-market) |
| 2 | How we deliver | **Productized service** (done-for-you, retainer) — not self-serve software |
| 3 | Tally's no-API reality | **It's our moat** — conditional on the productized-service model |

### Why these three reinforce each other
- CA firms **live in Tally** and feel the integration pain across *many* clients at once — concentrated demand.
- A **productized service** matches how this market buys (relationship-led, "just make it work, and keep it working") and turns Tally's maintenance burden into **retainer revenue** instead of a margin-killer.
- Tally's **missing API** walls out the global players who would otherwise win; building the connector once and reusing it across clients is only economic *because* we productize.

---

## Where the gap is, exactly

**The operational-system → statutory-system → government-portal triangle:**
`ERP / marketplace / bank → Tally → GST portal`

This one boundary concentrates all four failure conditions:

1. **Weakest APIs in the stack.** Tally (~80% of Indian business accounting) has **no modern REST
   API** — ODBC read-only + deprecated, XML-over-HTTP needs a running instance and no concurrent
   writes, TDL developers scarce. The GST portal is an offline-Excel-utility workflow.
2. **Highest stakes.** Blocked ITC, 18% interest, DRC-01C notices, GSTR-3B hard-locking all live
   here. Errors are expensive and increasingly irreversible.
3. **Worst-fit tooling.** Global iPaaS = $50k–210k/yr + implementation and **zero Indian-stack
   connectors**; Zapier/Make cheap but self-serve, no Tally/GST connectors; RPA brittle and
   enterprise-priced; custom dev ₹10–50L + 15–25%/yr maintenance cliff.
4. **No affordable middle → filled by headcount.** The real competitor is **"hire a junior at
   ~₹2L/yr to re-key."** That ₹16k/month is the hard price ceiling.

**Quantified pain at this boundary:**
- GST reconciliation: **40–60 hrs/month** per finance team; a 30-client CA firm ≈ **5,040 hrs/yr ≈ 3 FTEs**.
- Multi-bank reconciliation: **3–7 staff-days/month** (10–15 at high volume).
- E-commerce settlement recon (Amazon/Flipkart): **10–15 hrs/week**, **2–3% silent revenue leakage**.
- Multi-entity consolidation: collapses into Excel + email past **3–4 entities**.
- Month-end close: **~10 days, ~5 people**, books ~15 days post-close.

---

## The offering

A **connector library + agentic orchestration**, sold as a **maintained service to CA firms**.

**Connectors (each: source system → Tally / GST, with correct GST logic):**
1. **Unstructured documents → Tally** — *this is what invoice-to-tally already does. Connector #1, and our proof the model works.*
2. Bank statement (multi-bank, PDF/CSV/MT940) → Tally reconciliation
3. Marketplace settlement (Amazon/Flipkart/Meesho) → books + GST
4. ERP export (SAP/NetSuite/Dynamics) → GST portal filing
5. GSTR-2B ↔ purchase register reconciliation *(already built)*
6. Multi-entity trial balances → consolidated MIS

**Agentic layer on top** (the durable moat if Tally ever ships an API): the ITC-Guardian and
Notice-Response agents from CONTEXT_AGENTS.md become *higher-value services layered on the
integration base* — grounded in the client data the connectors already move.

**Pricing:** hybrid — **low-lakh one-time setup + ₹5k–25k/month retainer per client-workflow**,
under the "hire a junior" ceiling. Build the connector once (30% custom margin), replicate across
clients (60–70% productized margin). The retainer *is* the answer to the maintenance cliff.

---

## Positioning & the honest competitive picture

**The lane is not empty.** **Suvit (now Vyapar TaxOne)** already does documents → Tally → GST recon
via WhatsApp, 10k firms, acquired Nov 2025. The document→Tally connector specifically is contested.

**Our differentiation:**
- **Breadth of connectors** beyond documents — ERP/bank/marketplace → Tally+GST is the part no one
  has productized as a service.
- **Service, not self-serve** — Suvit is a tool the firm must run; we deliver and maintain the
  outcome, which is what CA firms actually want to buy (and resell).
- **The agentic layer** (grounded, cited ITC/notice work) sits on top of the integration base —
  defensible even if the connector wall falls.

**What we must NOT do** (validated dead ends): a generic tax-research chatbot (ICAI CA GPT is free),
a standalone notice-reply tool with no client data (crowded), or generic self-serve iPaaS
(the market won't configure it themselves).

---

## The one paradox to manage

**The billing-model trap:** CA firms bill per return/hour, so automation can cannibalize their own
revenue. The resolution: **target the advisory/virtual-CFO-leaning firms** — the segment already
booming (₹25k–1.5L/mo retainers, 55% YoY growth) that *wants* to move up from compliance grunt-work
to advisory. For them, our service **frees capacity to sell advisory**, it doesn't cannibalize.
Compliance-only firms that bill by the hour are the wrong first customer.

---

## Risks (named honestly)

- **Tally integration is slow and finicky** — bounded/known, not open-ended; de-risked by starting
  from the connector we have.
- **Services don't scale like SaaS** — mitigated only by disciplined productization (build once,
  replicate); if we drift into bespoke-per-client, margins die.
- **Suvit/Vyapar is ahead on document→Tally** — we lead with breadth + service + agentic layer, not
  by re-fighting them on connector #1.
- **Tally could ship a real API** — lowers the connector wall; why the durable moat is the
  orchestration + service + relationship layer, not the pipe.

---

## What to validate next (not code)

1. **Talk to 5 advisory/VCFO-leaning CA firms** — confirm they'd buy a maintained connector service
   and resell it, and which connector (#2–#6) is their sharpest pain after documents.
2. **Confirm the Suvit/Vyapar boundary** — a deeper competitor scan of what they do and don't cover
   beyond document→Tally.
3. **Price test** — validate the setup + retainer bands against the "hire a junior" ceiling with
   real firms.
4. **Pick connector #2** from that evidence, and only then design/build.

Invoice-to-tally is connector #1 and the working proof. Everything above builds on it — no work is
thrown away, it's recontextualized as the first piece of a larger, more defensible layer.
