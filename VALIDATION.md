# Validation & Reliability evidence

HackHorizon 2026 · Problem Statement 2 · OrchestrAI

This is the evidence pack for the 15% Validation & Reliability criterion. Every claim maps to an automated test in `tests/test_scenarios.py`. The suite needs no network and no API key.

```powershell
.\.venv\Scripts\python -m pytest -q
```

Latest run: **8 passed**.

## Acceptance mapping (brief section 9)

Input: *"Create a purchase request for 50 laptops under PKR 10 million, compare three suppliers, identify the best option, prepare the purchase order, and send it for approval."*

| Brief requirement | Test | Result |
|---|---|---|
| Parse item, qty 50, PKR 10,000,000, 3 suppliers | `test_parse_primary_use_case` | pass |
| Retrieve ≥3 quotes | `test_happy_path_primary_generates_po_and_approval_gate` | pass |
| Flag any quote over the ceiling | MegaOffice rejected in happy-path ranking; `test_rank_rejects_over_budget_and_picks_transparent_winner` | pass |
| Rank remaining on disclosed 50/30/20 weights | same | pass |
| Select top-ranked and state why | ByteHub selected; justification in ranking JSON | pass |
| Generate PO PDF with correct line items | PDF written under `generated/` and copied to `samples/` | pass |
| Submit to approval queue as pending | workflow status `pending_approval` | pass |
| Plain-language report | report persisted on the workflow row | pass |

## Failure and self-correct paths

| Scenario | Test | What a judge should see |
|---|---|---|
| Over-budget quotes produce no forged PO | `test_over_budget_chaos_escalates_instead_of_forging_a_po` | `selected is None`, rejected list populated |
| Validation catches a budget breach and suggests re-rank | `test_validation_catches_budget_breach_and_suggests_rerank` | `action == retry_rank` |
| Tool timeout then retry | `test_tool_timeout_retries_then_succeeds` | first invoke fails, second succeeds; executor retries |
| Second use case, same pipeline | `test_secondary_use_case_same_pipeline_no_new_code` | NexSuite rejected over $20k; CloudForge selected |

## Live chaos toggles (UI)

On the ops console, the Chaos panel forces the same paths without changing code:

- **Force vendor timeout** — first HTTP call 503s, executor retries
- **Force malformed payload** — first payload is unusable, client retries then falls back
- **Inflate all quotes over budget** — ranking returns no winner, workflow escalates instead of inventing a supplier
