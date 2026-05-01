"""FastAPI application — wires routes, static files, logging."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import benchmark, database, llm, structured
from .config import settings
from .models import (
    BenchmarkRequest,
    ChatRequest,
    ConversationCreate,
    ConversationRename,
    StructuredRequest,
)


# ----- Logging -----

def _setup_logging() -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_h = RotatingFileHandler(
        settings.log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    stream_h = logging.StreamHandler()
    stream_h.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [file_h, stream_h]


_setup_logging()
log = logging.getLogger("app")


# ----- App lifecycle -----

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    database.init_db()
    log.info("Database ready at %s", settings.db_path)
    health = await llm.health_check()
    if health.get("ok"):
        log.info(
            "Ollama OK. Configured model=%s installed=%s",
            settings.model, health.get("model_installed"),
        )
        if not health.get("model_installed"):
            log.warning(
                "Model '%s' is not installed. Run: ollama pull %s",
                settings.model, settings.model,
            )
    else:
        log.warning("Ollama unreachable at startup: %s", health.get("error"))
    yield
    log.info("Shutting down.")


app = FastAPI(title="Offline AI Assistant", version="1.1.0", lifespan=lifespan)

# Local-only by default; widen if you serve the UI from another origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- Health & conversations -----

@app.get("/api/health")
async def health() -> dict:
    return await llm.health_check()


@app.get("/api/conversations")
async def conversations_list() -> list[dict]:
    return database.list_conversations()


@app.post("/api/conversations", status_code=201)
async def conversations_create(payload: ConversationCreate) -> dict:
    conv_id = database.create_conversation(payload.title)
    return {"id": conv_id, "title": payload.title}


@app.delete("/api/conversations/{conv_id}")
async def conversations_delete(conv_id: int) -> dict:
    if not database.delete_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.patch("/api/conversations/{conv_id}")
async def conversations_rename(conv_id: int, payload: ConversationRename) -> dict:
    if not database.rename_conversation(conv_id, payload.title):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.get("/api/conversations/{conv_id}/messages")
async def conversations_messages(conv_id: int) -> list[dict]:
    return database.get_messages(conv_id)


# ----- Streaming chat -----

@app.post("/api/chat")
async def chat(payload: ChatRequest):
    """Stream the assistant's response as plain text chunks (UTF-8)."""
    conv_id = payload.conversation_id
    if conv_id is None:
        title = payload.message.strip().splitlines()[0][:60] or "New chat"
        conv_id = database.create_conversation(title)

    database.add_message(conv_id, "user", payload.message)

    history = database.get_messages(conv_id, limit=settings.max_history_messages)
    messages = [{"role": "system", "content": settings.system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]

    async def generator():
        # Send the conversation id as a sentinel first line so the UI can pick it up.
        yield f"\x00CONV:{conv_id}\x00"
        collected: list[str] = []
        try:
            async for chunk in llm.stream_chat(messages):
                collected.append(chunk)
                yield chunk
        except llm.OllamaError as exc:
            err = f"\n\n[error] {exc}"
            collected.append(err)
            yield err
        finally:
            full = "".join(collected).strip()
            if full:
                database.add_message(conv_id, "assistant", full)

    return StreamingResponse(generator(), media_type="text/plain; charset=utf-8")


# ----- Structured (schema-validated) -----

@app.post("/api/structured")
async def structured_endpoint(payload: StructuredRequest) -> dict:
    """Return a Pydantic-validated JSON object. Retries once on invalid output."""
    return await structured.get_structured(payload.prompt)


# ----- Benchmark -----

@app.post("/api/benchmark")
async def benchmark_endpoint(payload: BenchmarkRequest) -> dict:
    """Run a small in-process benchmark. Useful for ad-hoc measurements from the UI.

    For serious measurement use the CLI: `python -m scripts.benchmark`.
    """
    if payload.warmup:
        try:
            await benchmark.run_single("Say hi.")
        except llm.OllamaError as exc:
            raise HTTPException(503, f"LLM unavailable during warmup: {exc}") from exc

    results = []
    for _ in range(payload.runs):
        try:
            results.append(await benchmark.run_single(payload.prompt))
        except llm.OllamaError as exc:
            raise HTTPException(503, f"LLM error during benchmark: {exc}") from exc

    return {
        "results": benchmark.to_dicts(results),
        "aggregate": benchmark.aggregate(results),
    }


# ----- Static UI -----

app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(settings.static_dir / "index.html")
