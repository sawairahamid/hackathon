# OrchestrAI — Deployment Guide

## Architecture overview

`start.py` boots two processes in one shell:

| Process | Port | Role |
|---|---|---|
| Mock vendor API | 8001 | Simulated HTTP supplier quotes |
| OrchestrAI main | 8000 | Parser → planner → executor, trace UI |

The Docker image runs `start.py` so both services share one container.

---

## Option A — Docker (local or any VPS)

```bash
docker build -t orchestrai .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e GROQ_API_KEY=your_key \
  -e SLACK_WEBHOOK_URL=https://hooks.slack.com/... \
  orchestrai
```

Open http://localhost:8000.

To persist the SQLite database across container restarts:

```bash
docker run -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e GEMINI_API_KEY=your_key \
  orchestrai
```

---

## Option B — Render.com (free tier)

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New → Blueprint**.
3. Connect your repo — Render reads `render.yaml` automatically.
4. Set the secret env vars in the Render dashboard:
   - `GEMINI_API_KEY` (optional — falls back to Groq then templates)
   - `GROQ_API_KEY` (optional)
   - `SLACK_WEBHOOK_URL` (optional)
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
| `HOST` | No | `127.0.0.1` | Use `0.0.0.0` in Docker |
| `PORT` | No | `8000` | |
| `DATABASE_PATH` | No | `data/orchestrai.db` | Relative to repo root |
| `SLACK_WEBHOOK_URL` | No | — | Slack -> Apps -> Incoming Webhooks. No-op if unset. |

---

## Notes

- **LLM keys are optional.** Without any key, the heuristic parser + template planner + deterministic scorer still complete all four reference use cases. Demo works offline.
- **Mock API is bundled.** No external vendor API dependency.
- **Generated PDFs** land in `generated/`. On ephemeral hosts, PDFs are lost on restart. Mount the `generated/` directory to a volume if you need persistence.
- **SQLite WAL mode** is enabled. Safe for concurrent readers; not safe for multi-process writes.
