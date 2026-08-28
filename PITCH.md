# OrchestrAI — Round 2 pitch (≈4 minutes)

Round 2 is 40% value proposition, 40% market viability, 20% delivery. Say this, then sit down.

## 1. The problem (30s)

Enterprises do not have a chatbot problem. They have a *hand-off* problem. A purchase request today is a chat message, a spreadsheet of vendor quotes, a Word PO, and an email to a manager — four tools, one tired human stitching them together. Every delayed approval is cash sitting still; every unlogged decision is an audit finding.

## 2. What we built (45s)

OrchestrAI is an agent that *acts*. You type:

> Create a purchase request for 50 laptops under PKR 10 million, compare three suppliers, identify the best option, prepare the purchase order, and send it for approval.

It plans the work in the open, calls tools, checks its own math, and stops at a human gate. It will not spend a rupee without a person. That is the product, not a disclaimer.

## 3. Why this is not “just GPT” (45s)

The model never picks the supplier and never adds the totals. Ranking is a disclosed 50 / 30 / 20 weighted score. Validation re-checks budget, quantity, and consistency *after* the choice. If a quote busts the ceiling, it is flagged in the trace — you just watched MegaOffice get rejected. If a vendor API times out, the agent retries, then falls back. That is the difference between a demo and a system a procurement lead could defend to internal audit.

## 4. Who pays, and why now (60s)

Buyer: Head of Procurement / COO in mid-market firms (200–5,000 employees) that already run email + Excel + a half-used ERP.

Pain they already budget for: cycle time on POs, maverick spend, and audit preparation.

Wedge: start with the highest-volume, lowest-ambiguity workflow — catalog procurement under a stated ceiling — then clone the same planner-executor onto vendor renewals, reimbursements, and onboarding. You saw the second use case run on the same six steps with only new catalog data. That is the scalability story.

Pakistan / GCC specific: PKR-native documents, bilingual later, on-prem or VPC because spend data does not belong in a consumer chatbot. Competitors are generic copilots (they talk) or heavy BPMS suites (they take 9 months). We ship the loop: plan, act, check, ask a human.

## 5. Traction path (30s)

- Week 0: this prototype, two workflows, full audit log.
- 90 days: plug into one real vendor list + one real approver inbox (email) at a design-partner firm.
- 12 months: workflow library sold as seats to procurement ops, not as “an LLM app.”

## 6. The ask (15s)

We are not asking you to believe a slide about agents. We are asking you to type a sentence and watch a purchase order appear, with every decision explainable. That is OrchestrAI.

## Objection handling

| Pushback | Answer |
|---|---|
| “LLMs hallucinate prices.” | Prices never come from the LLM. They come from the vendor API / catalog. The model writes the plan and the report. |
| “This is mocked data.” | On purpose, and labeled. Live vendor APIs are a connector, not a rewrite — the tool registry is pluggable. |
| “People already have SAP.” | SAP issues the PO *after* someone decided. We automate the decision packet that currently lives in email. |
| “What if the model plans the wrong steps?” | Plans are validated against the registered tool list; a template plan is the cold-start fallback. The DAG is shown before execution. |
