from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from dotenv import load_dotenv

from app import trace

load_dotenv()

GEMINI_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
]


def _hash(provider: str, model: str, prompt: str) -> str:
    return hashlib.sha256(f"{provider}|{model}|{prompt}".encode("utf-8")).hexdigest()


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _try_gemini(prompt: str) -> tuple[str, str] | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    last_err: Exception | None = None
    client = genai.Client(api_key=key)
    for model in GEMINI_MODELS:
        cache_key = _hash("gemini", model, prompt)
        cached = trace.cache_get(cache_key)
        if cached:
            return cached, f"gemini:{model}:cache"
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            text = _strip_fence(getattr(resp, "text", None) or "")
            if not text:
                continue
            json.loads(text)
            trace.cache_put(cache_key, "gemini", model, text)
            return text, f"gemini:{model}"
        except Exception as exc:  # noqa: BLE001 — provider chain must never crash the agent
            last_err = exc
            continue
    if last_err:
        return None
    return None


def _try_groq(prompt: str) -> tuple[str, str] | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    cache_key = _hash("groq", model, prompt)
    cached = trace.cache_get(cache_key)
    if cached:
        return cached, f"groq:{model}:cache"
    try:
        import httpx

        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Reply with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        text = _strip_fence(resp.json()["choices"][0]["message"]["content"])
        json.loads(text)
        trace.cache_put(cache_key, "groq", model, text)
        return text, f"groq:{model}"
    except Exception:  # noqa: BLE001
        return None


def complete_json(prompt: str) -> tuple[dict[str, Any] | None, str]:
    """Return (parsed_json, provider_tag). json is None if every provider failed."""
    for fn in (_try_gemini, _try_groq):
        result = fn(prompt)
        if result:
            text, tag = result
            try:
                return json.loads(text), tag
            except json.JSONDecodeError:
                continue
    # Last-ditch: any cached response for a similar prompt is not attempted;
    # callers must use their deterministic fallback.
    return None, "fallback"


def provider_status() -> dict[str, Any]:
    return {
        "gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "groq": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "fallback_templates": True,
    }
