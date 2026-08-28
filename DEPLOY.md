# OrchestrAI — Deployment Guide

## Architecture overview

`start.py` boots two processes in one shell:

| Process | Port | Role |
|---|---|---|
| Mock vendor API | 8001 | Simulated HTTP supplier quotes |
| OrchestrAI main | 8000 | Parser → planner → executor, trace UI |

---

## Option A — Local / VPS (Python)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python start.py
```

Open http://localhost:8000.

---

## Option B — Render.com (free tier)

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New → Blueprint**.
3. Connect your repo — Render reads `render.yaml` automatically.
4. Set the secret env vars in the Render dashboard:
   - `GEMINI_API_KEY` (optional — falls back to Groq then templates)
   - `GROQ_API_KEY` (optional)
5. Click **Deploy**.

> [!WARNING]
> **SQLite on Render free tier**: The filesystem is ephemeral.
> Each deploy wipes `data/orchestrai.db`.
> To keep history across deploys, add a **Render Disk** mounted at `/app/data`
> (min 1 GB, ~$0.25/GB/month) and set `DATABASE_PATH=/app/data/orchestrai.db`.

---

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GEMINI_API_KEY` | No | — | Free tier at aistudio.google.com. Do NOT enable billing. |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | |
| `GROQ_API_KEY` | No | — | Free at console.groq.com |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | |
| `SUPPLIER_API_URL` | No | `http://127.0.0.1:8001` | Points to the mock vendor API |
| `HOST` | No | `127.0.0.1` | |
| `PORT` | No | `8000` | |
| `DATABASE_PATH` | No | `data/orchestrai.db` | Relative to repo root |

---

## Notes

- **LLM keys are optional.** Without any key, the heuristic parser + template planner + deterministic scorer still complete all four reference use cases. Demo works offline.
- **Mock API is bundled.** No external vendor API dependency.
- **Generated PDFs** land in `generated/`. On ephemeral hosts, PDFs are lost on restart. Mount the `generated/` directory to a volume if you need persistence.
- **SQLite WAL mode** is enabled. Safe for concurrent readers; not safe for multi-process writes.
