# Demo script — rehearse twice, including once with Wi‑Fi off

Total: 3–4 minutes. Do not narrate code. Narrate the loop: plan → act → check → ask a human.

## Setup (before judges walk up)

- `python start.py` already running.
- Browser on http://127.0.0.1:8000, chaos checkboxes **unchecked**.
- Phone hotspot on standby.
- One teammate on the keyboard, one speaking.

## Beat sheet

1. **Hook (15s).** “This is not a chatbot. It is an agent that turns a sentence into a purchase order and then *stops* for a human.”
2. **Paste the official prompt (5s).** Click the Primary preset so it is word-for-word from the brief.
3. **Plan before execution (20s).** Hit Execute. Point at the DAG: “This appeared before any tool ran. If it were a script, there would be nothing to show here.”
4. **Trace (40s).** Call out the HTTP vendor call, then the 50/30/20 score, then validation PASS. Name MegaOffice and the PKR 10 million ceiling.
5. **Artifact (20s).** Open the PDF. Confirm quantity 50 and the selected supplier match the trace.
6. **Human gate (20s).** “The agent is not allowed to approve its own spend.” Click Approve. Status flips.
7. **Report (15s).** Scroll the stakeholder summary. “This is what a non-technical manager would receive.”
8. **Chaos (25s).** Tick Force vendor timeout, rerun. “First call fails, executor retries, workflow still completes.”
9. **Generalizability (25s).** Secondary preset. “Same six tools, software catalog, $20k ceiling. NexSuite is rejected over budget. No new agent code.”

## If the network dies

Keep going. The vendor API is local. The LLM falls back to the heuristic parser and template plan. Say that out loud — it is a feature: “Resilience is a scored requirement. We built for the room’s Wi‑Fi, not a lab.”

## If a judge types their own prompt

Safe patterns: “buy N {laptops/software} under {amount}”. If they invent a domain we did not catalog, the planner still runs and the vendor API maps unknown items to the laptop catalog — say so, do not bluff that it is a live ERP.
