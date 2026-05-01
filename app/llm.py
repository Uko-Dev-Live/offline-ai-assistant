"""Async client for the Ollama runtime — runs entirely on localhost."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

import httpx

from .config import settings


logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns an error."""


async def health_check() -> dict:
    """Return Ollama status and the list of locally installed models."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            r.raise_for_status()
            data = r.json()
        models = [m["name"] for m in data.get("models", [])]
        return {
            "ok": True,
            "configured_model": settings.model,
            "model_installed": settings.model in models,
            "available_models": models,
        }
    except Exception as exc:  # noqa: BLE001 — surfaced to user
        logger.warning("Ollama health check failed: %s", exc)
        return {"ok": False, "error": str(exc), "configured_model": settings.model}


def _base_payload(messages: list[dict], stream: bool) -> dict:
    return {
        "model": settings.model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": settings.temperature,
            "num_ctx": settings.num_ctx,
        },
    }


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Yield response text chunks from Ollama as they arrive."""
    payload = _base_payload(messages, stream=True)
    timeout = httpx.Timeout(settings.request_timeout, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{settings.ollama_url}/api/chat", json=payload
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", errors="replace")
                    raise OllamaError(f"Ollama error {r.status_code}: {body[:300]}")

                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = chunk.get("message") or {}
                    text = msg.get("content")
                    if text:
                        yield text
                    if chunk.get("done"):
                        return
    except httpx.ConnectError as exc:
        raise OllamaError(
            f"Cannot reach Ollama at {settings.ollama_url}. "
            "Is the `ollama` service running?"
        ) from exc
    except httpx.ReadTimeout as exc:
        raise OllamaError("Ollama request timed out.") from exc


async def stream_chat_with_metrics(messages: list[dict]) -> dict:
    """Stream a chat call and return wall-clock + Ollama-reported metrics.

    Used by the benchmark module. Captures:
      - ttft_s          : seconds until the first non-empty content chunk
      - total_s         : seconds from request start to `done: true`
      - eval_count      : tokens generated (from Ollama)
      - eval_duration_s : time the model spent generating (from Ollama)
      - prompt_eval_*   : same, for the prompt-encoding phase
      - load_duration_s : time spent loading the model into memory
      - text            : the full concatenated response
    """
    payload = _base_payload(messages, stream=True)
    timeout = httpx.Timeout(settings.request_timeout, connect=10.0)

    start = time.perf_counter()
    ttft: float | None = None
    final: dict[str, Any] = {}
    text_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{settings.ollama_url}/api/chat", json=payload
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", errors="replace")
                    raise OllamaError(f"Ollama error {r.status_code}: {body[:300]}")

                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = chunk.get("message") or {}
                    content = msg.get("content")
                    if content:
                        if ttft is None:
                            ttft = time.perf_counter() - start
                        text_parts.append(content)
                    if chunk.get("done"):
                        final = chunk
                        break
    except httpx.ConnectError as exc:
        raise OllamaError(f"Cannot reach Ollama at {settings.ollama_url}.") from exc

    total = time.perf_counter() - start
    if ttft is None:
        ttft = total

    return {
        "text": "".join(text_parts),
        "ttft_s": ttft,
        "total_s": total,
        "eval_count": int(final.get("eval_count", 0) or 0),
        "eval_duration_s": (final.get("eval_duration", 0) or 0) / 1e9,
        "prompt_eval_count": int(final.get("prompt_eval_count", 0) or 0),
        "prompt_eval_duration_s": (final.get("prompt_eval_duration", 0) or 0) / 1e9,
        "load_duration_s": (final.get("load_duration", 0) or 0) / 1e9,
    }


async def complete_chat(
    messages: list[dict],
    response_format: dict | str | None = None,
) -> tuple[str, dict]:
    """Non-streaming chat completion. Returns (text, metadata).

    `response_format` is forwarded to Ollama's `format` parameter:
      - a JSON Schema dict to constrain output to that schema (recommended)
      - the string "json" for free-form JSON output
      - None for plain text
    """
    payload = _base_payload(messages, stream=False)
    if response_format is not None:
        payload["format"] = response_format

    timeout = httpx.Timeout(settings.request_timeout, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{settings.ollama_url}/api/chat", json=payload)
            if r.status_code != 200:
                raise OllamaError(f"Ollama error {r.status_code}: {r.text[:300]}")
            data = r.json()
    except httpx.ConnectError as exc:
        raise OllamaError(f"Cannot reach Ollama at {settings.ollama_url}.") from exc
    except httpx.ReadTimeout as exc:
        raise OllamaError("Ollama request timed out.") from exc

    text = (data.get("message") or {}).get("content", "")
    meta = {
        "total_duration_s": (data.get("total_duration", 0) or 0) / 1e9,
        "eval_count": int(data.get("eval_count", 0) or 0),
        "eval_duration_s": (data.get("eval_duration", 0) or 0) / 1e9,
        "prompt_eval_count": int(data.get("prompt_eval_count", 0) or 0),
    }
    return text, meta
