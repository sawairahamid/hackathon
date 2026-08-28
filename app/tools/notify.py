"""Slack incoming-webhook notification. Graceful no-op if SLACK_WEBHOOK_URL is unset."""

from __future__ import annotations

import logging
import os

from app.models import ToolResult
from app.tools import tool

log = logging.getLogger(__name__)


@tool(
    name="send_notification",
    description="Post a notification to the configured Slack webhook. If SLACK_WEBHOOK_URL is not set, logs the message and returns ok=True (demo-safe no-op).",
)
def send_notification(
    message: str = "",
    workflow_id: str | None = None,
    artifact_url: str | None = None,
    channel: str | None = None,
) -> ToolResult:
    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        log.info("[notify] SLACK_WEBHOOK_URL not set — notification skipped: %s", message)
        return ToolResult(
            ok=True,
            tool="send_notification",
            data={"sent": False, "reason": "SLACK_WEBHOOK_URL not configured", "message": message},
            source="local",
        )

    body: dict = {
        "text": message,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*OrchestrAI Notification*\n{message}"},
            }
        ],
    }
    if artifact_url:
        body["blocks"].append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{artifact_url}|View artifact>"},
        })
    if workflow_id:
        body["blocks"].append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Workflow: `{workflow_id}`"}],
        })

    try:
        import httpx
        resp = httpx.post(webhook, json=body, timeout=5.0)
        ok = resp.status_code == 200
        return ToolResult(
            ok=ok,
            tool="send_notification",
            data={"sent": ok, "http_status": resp.status_code, "message": message},
            error=None if ok else f"Slack returned HTTP {resp.status_code}: {resp.text[:200]}",
            source="live",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("[notify] Slack post failed: %s", exc)
        return ToolResult(
            ok=False,
            tool="send_notification",
            data={"sent": False, "message": message},
            error=str(exc),
            source="live",
        )
