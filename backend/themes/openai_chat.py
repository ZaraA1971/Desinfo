"""OpenAI chat helper for theme classification."""
from __future__ import annotations

from typing import Any

import httpx

from backend.config import Settings, get_settings


def build_chat_payload(
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float = 0.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if not model.startswith("gpt-5"):
        payload["temperature"] = temperature
    if max_tokens > 0:
        if model.startswith("gpt-5"):
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
    return payload


def _retry_payload(payload: dict[str, Any], error_text: str) -> dict[str, Any] | None:
    err = error_text.lower()
    retry = dict(payload)
    changed = False
    if "max_completion_tokens" in err and "max_completion_tokens" in retry:
        retry["max_tokens"] = retry.pop("max_completion_tokens")
        changed = True
    if "max_tokens" in err and "max_tokens" in retry and "max_completion_tokens" not in retry:
        retry["max_completion_tokens"] = retry.pop("max_tokens")
        changed = True
    if "temperature" in err and "temperature" in retry:
        retry.pop("temperature", None)
        changed = True
    return retry if changed else None


def post_chat_completion(
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float = 0.0,
    settings: Settings | None = None,
    timeout: float | None = None,
) -> str:
    cfg = settings or get_settings()
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    model = cfg.openai_model
    payload = build_chat_payload(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    headers = {
        "Authorization": f"Bearer {cfg.openai_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{cfg.openai_base_url.rstrip('/')}/chat/completions"
    req_timeout = timeout if timeout is not None else cfg.openai_timeout_seconds

    with httpx.Client(timeout=req_timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            retry = _retry_payload(payload, resp.text)
            if retry is not None:
                resp = client.post(url, json=retry, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return str(content or "").strip()
