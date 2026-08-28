# OrchestrAI

Agentic AI for autonomous business-workflow execution — HackHorizon 2026, Problem Statement 2.

Natural language → plan → tool execution → validation → human approval → report.

The language model never does arithmetic. It parses the request, drafts the plan, and writes prose. Budget checks, totals, scoring, and ranking are deterministic Python, so a live demo cannot silently invent a supplier.

## Quick start

```powershell
cd $env:USERPROFILE\Projects\hackhorizon-agentic
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python start.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The vendor mock listens on port 8001. If 8001 is already taken, the app still runs and falls back to the bundled catalog.

`start.py` boots two processes:

| Process | Port | Role |
|---|---|---|
| Mock vendor API | 8001 | Real HTTP supplier quotes with latency and failure injection |
| OrchestrAI | 8000 | Planner-executor, trace, UI |

No Gemini key is required. Without a key the heuristic parser + template planner still complete both judging use cases. With a key, parse/plan/report copy gets richer and is cached in SQLite so a later offline run still works.

Do **not** enable billing on the Google Cloud project that holds the Gemini key — that silently deletes the free tier.

## Demo (3 minutes)

1. Click **Primary · 50 laptops / PKR 10M**. Hit **Execute workflow**.
2. Point at the plan DAG — it appears *before* any tool runs.
3. Watch the live trace: HTTP quotes → weighted rank → validation → PO PDF → approval inbox.
4. Call out MegaOffice, rejected for busting PKR 10,000,000.
5. Open the generated PDF. Click **Approve spend**. Status flips.
6. Optionally tick **Force vendor timeout** and rerun — the executor retries, then continues.
7. Click **Secondary · vendor renewal / $20k**. Same six-step pipeline, different catalog. No new code.

## What was built (MVP mapped to the brief)

| Brief § | Implementation |
|---|---|
| 4.1 Intent & decomposition | `app/parser.py` + `app/domain_ext.py` — extended heuristic for 4 domains |
| 4.2 Orchestration | `app/executor.py` — sequential + conditional, step states, retries |
| 4.3 Tool layer | HTTP vendor API, PDF generator, approval queue — all logged |
| 4.4 Decision logic | Disclosed weights: price 50 / delivery 30 / warranty 20 |
| 4.5 Validation | Budget, quantity, consistency, required fields; self-correct or escalate |
| 4.6 Human gate | Approval inbox; agent cannot approve its own spend |
| 4.7 Reporting | Plain-language stakeholder report |
| 4.8 Observability | SQLite audit log + SSE live trace |
| Use case 2 | Software vendor renewal under $20,000 — same agent, new catalog data |
| Use case 3 | Travel expense reimbursement — `app/tools/reimbursement.py`, `mock_api/data/expense_policy.json` |
| Use case 4 | Employee onboarding — `app/tools/onboarding.py` (accounts + equipment PDF) |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for frozen JSON contracts.

```
Chat UI  →  parser  →  planner  →  executor
                                   ├─ fetch_suppliers  (HTTP :8001, local fallback)
                                   ├─ rank_suppliers   (deterministic)
                                   ├─ validate_selection
                                   ├─ generate_purchase_order (fpdf2)
                                   ├─ submit_for_approval
                                   └─ compile_report
                         SQLite audit log  →  SSE trace panel
```

## Tests (Validation & Reliability evidence)

```powershell
.\.venv\Scripts\python -m pytest -q
```

Covers: primary parse, secondary parse, over-budget rejection, validation self-correct signal, end-to-end PO + approval gate, second use case on the same pipeline, tool retry.

## Project layout

```
app/            planner-executor, tools, LLM provider chain
mock_api/       standalone vendor HTTP API
static/         single-page ops console
tests/          scenario suite
generated/      PO PDFs written at runtime
PITCH.md        Round 2 value / market narrative
DEMO.md         spoken demo script
```

## Notes for judges

- Mocked vendor data is labeled as simulated (latency is real HTTP).
- API keys, if used, live in `.env` only — never in client code.
- Adding a fourth supplier source is a new JSON file under `mock_api/data/` plus one catalog key. The agent core does not change.
- **Domain generalization**: the same executor core handles 4 distinct business domains (procurement, vendor comparison, expense reimbursement, employee onboarding) via additive `app/domain_ext.py` — no changes to protected files.

## Deployment

See [DEPLOY.md](DEPLOY.md) for deployment instructions.
