"""Schema-validated LLM responses with a single retry on failure.

Why two layers of safety?

1. We pass a JSON Schema to Ollama's `format` parameter. This constrains the
   model's *generation* (modern Ollama versions enforce the schema during
   sampling). For most prompts on most models this alone produces valid output.

2. We then validate the result with Pydantic. This catches cases where:
     - the running Ollama version is older and ignores the schema,
     - the model produces JSON that satisfies the schema syntactically but
       violates a Pydantic field constraint we added (e.g. confidence > 1.0),
     - the model emits trailing prose, code fences, or other noise.

If validation fails, we send one more attempt with the validation error fed
back to the model. If that also fails, we return a structured failure object
instead of crashing — calling code can decide what to do with it.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from . import llm
from .config import settings


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The schema we ask the model to fill in. Tweak fields freely — the rest of
# the module is generic and will follow whatever you put here.
# ---------------------------------------------------------------------------

class AssistantResponse(BaseModel):
    """Structured response the model must produce."""

    answer: str = Field(
        ...,
        min_length=1,
        description="The direct answer to the user's question.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Self-rated confidence in the answer, between 0.0 and 1.0.",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="One or two sentences explaining how the answer was reached.",
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Up to three useful follow-up questions for the user.",
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Short topic tags for this question (e.g. ['python','asyncio']).",
    )


class StructuredFailure(BaseModel):
    """Returned when both attempts fail validation."""

    success: bool = False
    error: str
    last_raw_output: str
    last_validation_error: str
    attempts: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(s: str) -> str:
    """Some models wrap JSON in ```json ... ```. Strip those before parsing."""
    return _CODE_FENCE.sub("", s).strip()


def _build_messages(prompt: str, prior_error: str | None = None) -> list[dict]:
    schema = AssistantResponse.model_json_schema()
    sys = (
        f"{settings.system_prompt}\n\n"
        "You MUST respond with a single JSON object that strictly matches this schema:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Rules:\n"
        " - Output ONLY the JSON object. No prose, no markdown fences, no comments.\n"
        " - All required fields must be present.\n"
        " - `confidence` must be a number between 0.0 and 1.0."
    )
    messages: list[dict] = [
        {"role": "system", "content": sys},
        {"role": "user", "content": prompt},
    ]
    if prior_error:
        messages.append({
            "role": "user",
            "content": (
                "Your previous reply failed schema validation with this error:\n"
                f"{prior_error}\n\n"
                "Return a corrected JSON object now. Output ONLY the JSON object."
            ),
        })
    return messages


def _validate(raw: str) -> tuple[AssistantResponse | None, str | None]:
    """Try to parse + validate. Returns (model, None) on success, (None, error) on failure."""
    try:
        cleaned = _strip_fences(raw)
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"Output is not valid JSON: {exc}. First 200 chars: {raw[:200]!r}"
    if not isinstance(data, dict):
        return None, f"Output JSON is not an object (got {type(data).__name__})."
    try:
        return AssistantResponse(**data), None
    except ValidationError as exc:
        # Compact, single-line error description for re-prompting.
        errs = exc.errors(include_url=False)
        summary = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errs
        )
        return None, f"Pydantic validation failed: {summary}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 2  # original try + one retry


async def get_structured(prompt: str) -> dict:
    """Ask the model for a schema-compliant response.

    Returns a dict with three keys:

        success      : bool
        data         : the validated AssistantResponse, or a StructuredFailure
        debug        : per-attempt diagnostics for observability

    Behaviour:
      1. First attempt with schema-constrained generation.
      2. On validation failure, retry exactly once, feeding the error back.
      3. If both fail, return success=False with the last raw output preserved.
    """
    schema = AssistantResponse.model_json_schema()
    attempts: list[dict[str, Any]] = []

    last_error: str | None = None
    last_raw: str = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        messages = _build_messages(
            prompt, prior_error=last_error if attempt > 1 else None
        )
        record: dict[str, Any] = {"attempt": attempt}

        try:
            raw, meta = await llm.complete_chat(messages, response_format=schema)
            record["meta"] = meta
        except llm.OllamaError as exc:
            last_error = f"LLM error: {exc}"
            record["error"] = last_error
            attempts.append(record)
            log.warning("Structured attempt %d: LLM error: %s", attempt, exc)
            continue

        last_raw = raw
        validated, err = _validate(raw)
        if validated is not None:
            record["ok"] = True
            attempts.append(record)
            return {
                "success": True,
                "data": validated.model_dump(),
                "debug": {"attempts": attempts},
            }

        last_error = err or "unknown validation error"
        record["error"] = last_error
        record["raw_preview"] = raw[:300]
        attempts.append(record)
        log.warning("Structured attempt %d failed: %s", attempt, last_error)

    failure = StructuredFailure(
        error=f"Model failed to produce valid structured output after {MAX_ATTEMPTS} attempts.",
        last_raw_output=last_raw,
        last_validation_error=last_error or "unknown",
        attempts=MAX_ATTEMPTS,
    )
    return {
        "success": False,
        "data": failure.model_dump(),
        "debug": {"attempts": attempts},
    }
