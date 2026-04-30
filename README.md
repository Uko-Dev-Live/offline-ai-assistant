# Offline AI Assistant

A complete, production-ready AI assistant that runs **entirely on your Ubuntu machine**. No API keys. No cloud calls. Once installed, you can pull the network cable and it still works.

This guide is written for absolute beginners. If you can open a terminal, you can finish it.

**This version adds two production features on top of the basic chat:**

- **Benchmarking** — measure tokens/sec, time-to-first-token (TTFT), and total latency, with results saved to disk for later comparison.
- **Schema-validated outputs** — force the model to return structured JSON, validated by Pydantic, with an automatic retry on failure and a graceful fallback if the retry also fails.

---

## Table of contents

1. [What you're building](#1-what-youre-building)
2. [Architecture](#2-architecture)
3. [Project file structure](#3-project-file-structure)
4. [Prerequisites](#4-prerequisites)
5. [Step-by-step install](#5-step-by-step-install)
6. [Running it (development)](#6-running-it-development)
7. [Production deployment with systemd](#7-production-deployment-with-systemd)
8. [Benchmarking the model](#8-benchmarking-the-model)
9. [Structured outputs (JSON schema + Pydantic + retry)](#9-structured-outputs-json-schema--pydantic--retry)
10. [Customisation](#10-customisation)
11. [Troubleshooting](#11-troubleshooting)
12. [Going further](#12-going-further)

---

## 1. What you're building

A self-hosted assistant with **three modes**, all running locally:

| Mode           | What it does                                                        |
|----------------|---------------------------------------------------------------------|
| **Chat**       | Streaming conversation, persistent history in SQLite                |
| **Structured** | Sends your prompt, returns a JSON object validated against a Pydantic schema, retries once on failure |
| **Benchmark**  | Measures TTFT, tokens/sec and total latency in your browser, plus a CLI tool for proper measurement |

You open it at `http://127.0.0.1:8000` and switch between the three modes from the sidebar.

---

## 2. Architecture

```
┌────────────────┐   HTTP      ┌─────────────────────────┐   HTTP   ┌──────────────┐
│  Browser (UI)  │ ──────────▶ │  FastAPI app            │ ───────▶ │   Ollama     │
│  3 modes       │             │  /api/chat              │          │ (LLM runtime)│
└────────────────┘             │  /api/structured        │          └──────┬───────┘
                               │  /api/benchmark         │                 │
                               │                         │                 ▼
                               │  • Pydantic validation  │          ┌──────────────┐
                               │  • SQLite history       │          │  Local model │
                               │  • Logging (rotating)   │          │ e.g. llama3.2│
                               └─────────────────────────┘          └──────────────┘
```

- **Ollama** is the runtime that downloads and serves open-source language models on `localhost:11434`.
- **FastAPI** is the Python web framework. It serves the UI, talks to Ollama, stores chat history, validates structured outputs, and runs benchmarks.
- **SQLite** is a single-file database — no server to install.
- **The browser UI** is plain HTML / CSS / JavaScript. No build step. No frameworks.

---

## 3. Project file structure

```
offline-ai-assistant/
│
├── README.md                       ← this guide
├── requirements.txt                ← Python dependencies
├── .env.example                    ← template for your config
├── .gitignore
│
├── app/                            ← Python backend
│   ├── __init__.py
│   ├── config.py                   ← reads env vars, holds settings
│   ├── database.py                 ← SQLite helpers (conversations, messages)
│   ├── llm.py                      ← async client for Ollama
│   │                                  • stream_chat(): streaming generator
│   │                                  • stream_chat_with_metrics(): + timing
│   │                                  • complete_chat(): non-streaming, supports JSON schema
│   ├── benchmark.py                ← TTFT / tokens-per-sec / latency measurements
│   ├── structured.py               ← Pydantic schema + retry-once-then-fail-gracefully
│   ├── models.py                   ← request schemas (Pydantic)
│   └── main.py                     ← FastAPI app + routes
│
├── static/                         ← the web UI
│   ├── index.html                  ← three-mode tab UI
│   ├── style.css                   ← refined dark terminal theme
│   └── app.js                      ← chat + structured + benchmark logic
│
├── scripts/
│   ├── install.sh                  ← installs Ollama, model, Python deps
│   ├── start.sh                    ← launches the dev server
│   └── benchmark.py                ← CLI benchmark with CSV/JSON output
│
├── systemd/
│   └── ai-assistant.service        ← production service unit
│
├── data/                           ← created at runtime
│   └── conversations.db            ← SQLite database (auto-generated)
│
├── benchmarks/                     ← created when you run benchmarks
│   ├── benchmark-<timestamp>.json
│   └── benchmark-<timestamp>.csv
│
└── logs/                           ← created at runtime
    └── app.log                     ← rotating log file (auto-generated)
```

---

## 4. Prerequisites

- **Ubuntu 20.04 or newer** (also works on Debian, Pop!_OS, Mint, WSL2)
- **At least 8 GB RAM** (16 GB is comfortable for a 3B-parameter model)
- **~10 GB free disk space** (the model itself is 2–3 GB)
- A user with `sudo` access
- A working internet connection — *only for the install step.* Afterwards, everything works offline.

You do **not** need a GPU. Everything works on CPU. A GPU just makes it faster.

---

## 5. Step-by-step install

Two paths. **Automatic** runs one script. **Manual** teaches you what each piece does.

### Option A — automatic

```bash
cd offline-ai-assistant
chmod +x scripts/install.sh scripts/start.sh
./scripts/install.sh
```

Skip to [Section 6](#6-running-it-development).

### Option B — manual (recommended for learning)

#### 5.1 Install system packages
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
```

#### 5.2 Install Ollama
Ollama is the engine that runs the model. Single binary plus a background service.
```bash
curl -fsSL https://ollama.com/install.sh | sh
systemctl status ollama          # should be 'active (running)' — press q to exit
```

#### 5.3 Download a small language model
```bash
ollama pull llama3.2:3b
```

| Model           | Size    | Notes                                  |
|-----------------|---------|----------------------------------------|
| `llama3.2:1b`   | ~1.3 GB | Tiny & quick, lower quality            |
| `llama3.2:3b`   | ~2.0 GB | **Recommended starting point**         |
| `phi3:mini`     | ~2.3 GB | Strong reasoning for the size          |
| `qwen2.5:3b`    | ~2.0 GB | Good multilingual + good JSON          |
| `gemma2:2b`     | ~1.6 GB | Polite tone                            |

Quick smoke test:
```bash
ollama run llama3.2:3b "In one sentence, what is Ubuntu?"
```

#### 5.4 Set up the Python environment
```bash
cd offline-ai-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

When the venv is active your prompt starts with `(.venv)`. To leave: `deactivate`.

#### 5.5 Create your config
```bash
cp .env.example .env
```
Defaults work; useful knobs are `MODEL_NAME`, `MODEL_TEMPERATURE`, `SYSTEM_PROMPT`.

---

## 6. Running it (development)

```bash
./scripts/start.sh
```

Open **http://127.0.0.1:8000**. You'll see three tabs in the sidebar: **chat**, **structured**, **benchmark**.

The dot at the top-left:
- 🟢 green — Ollama up and the configured model is installed
- 🟡 amber — Ollama up but model not pulled yet (`ollama pull <name>`)
- 🔴 red   — backend can't reach Ollama

To stop: `Ctrl-C`.

---

## 7. Production deployment with systemd

`systemd` is Ubuntu's service manager. We register the assistant so it starts on boot, restarts on crash, and runs in the background.

#### 7.1 Find your project path and username
```bash
pwd            # e.g. /home/alice/offline-ai-assistant
whoami         # e.g. alice
```

#### 7.2 Customise the service file
Open `systemd/ai-assistant.service` and replace the placeholders, or use this one-liner:
```bash
sed -i "s|YOUR_USER|$(whoami)|g; s|PROJECT_DIR|$(pwd)|g" systemd/ai-assistant.service
```

#### 7.3 Install and enable
```bash
sudo cp systemd/ai-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-assistant
systemctl status ai-assistant
journalctl -u ai-assistant -f       # live logs, Ctrl-C to exit
```

To stop: `sudo systemctl stop ai-assistant`. To disable auto-start: `sudo systemctl disable ai-assistant`.

#### 7.4 (Optional) expose to your local network
Edit `/etc/systemd/system/ai-assistant.service` and change `--host 127.0.0.1` to `--host 0.0.0.0`, then `sudo systemctl daemon-reload && sudo systemctl restart ai-assistant`. Don't expose it to the public internet without authentication.

---

## 8. Benchmarking the model

When you switch models, change context size, or move to different hardware, you'll want to know how it actually performs. The project ships with two ways to measure that.

### 8.1 What we measure

| Metric                    | Definition                                                                   | What it tells you |
|---------------------------|------------------------------------------------------------------------------|-------------------|
| **TTFT** (time to first token) | Wall-clock seconds from sending the request to the first content chunk arriving | How responsive the assistant feels. Includes prompt processing and, on a cold start, model load time. |
| **Tokens / second**       | `eval_count` ÷ `eval_duration` — the model's reported generation rate         | The "pure" generation speed of the model on your hardware. Not affected by network or prompt length. |
| **Wall tokens / second**  | `eval_count` ÷ (total\_wall\_clock − TTFT)                                   | How fast tokens stream once they start. Closer to what a user perceives. |
| **Total latency**         | Wall-clock seconds from request to last token                                 | The experience of asking and waiting for a complete answer. |

You'll usually see `tokens / second` slightly higher than `wall tokens / second` — the wall-clock figure includes scheduling and HTTP overhead.

### 8.2 Run a benchmark from the UI

Click the **benchmark** tab. Set a prompt, number of runs, leave warmup checked, click **run →**. You'll get four big stat cards (TTFT, tok/s, total latency, wall tok/s) and a per-run table.

The UI is convenient for ad-hoc checks but it's running inside the same process serving the HTTP request, so you may see slightly inflated wall times. **For accurate, reportable numbers, use the CLI.**

### 8.3 Run a benchmark from the CLI

```bash
source .venv/bin/activate
python -m scripts.benchmark
```

Output:

```
Model: llama3.2:3b
Ollama: http://127.0.0.1:11434

  warmup 1/1 ... ok (38.4 tok/s, load=2.81s)

Running 5 measured run(s):

  #   TTFT (ms)   Total (ms)   Tokens     tok/s   wall tok/s
  ----------------------------------------------------------------
  1       142.3       2841.6       96      38.7         35.6
  2       128.7       2716.4       91      39.1         35.0
  3       155.1       3011.2      102      38.4         35.6
  4       139.5       2780.0       94      38.9         35.5
  5       133.8       2702.3       89      38.6         34.5

Aggregate over 5 run(s):
  TTFT (ms)            : median=   139.5  p95=   155.1
  Total latency (ms)   : median=  2780.0  p95=  3011.2
  Tokens / sec (model) : median=    38.7  min=    38.4
  Tokens / sec (wall)  : median=    35.5  min=    34.5

Saved: benchmarks/benchmark-20251201-103445.json
       benchmarks/benchmark-20251201-103445.csv
```

Each run is also written to `benchmarks/` as JSON (full detail) and CSV (easy to plot in a spreadsheet).

### 8.4 Useful flags

```bash
python -m scripts.benchmark --runs 10                  # more runs = better stats
python -m scripts.benchmark --warmup 2                 # use 2 warmup runs
python -m scripts.benchmark --warmup 0                 # measure cold-start cost
python -m scripts.benchmark --prompt "Write a haiku."  # repeat one prompt
python -m scripts.benchmark --no-save                  # don't write files
```

### 8.5 Methodology — getting fair numbers

Three things will burn you if you don't watch for them:

1. **Cold start**. The first request after Ollama starts (or after the model has been evicted from RAM) pays a one-off "load" cost. On a laptop this can be 2–5 seconds. The benchmark warmup run absorbs that cost — don't skip it unless you specifically *want* to measure cold start.
2. **CPU contention**. A YouTube tab, a compile, a backup running — all of these cut tokens/sec by 30–80%. Close everything. If you must, run with `nice -n -10` and keep the system idle.
3. **Variance is real**. Don't compare single numbers. Run at least 5 measurements and look at the **median** and **p95**. Mean is fine, but median is more robust against the occasional outlier.

### 8.6 Comparing models

To compare two models on the same hardware, the simplest workflow is:

```bash
# Try llama3.2:3b
ollama pull llama3.2:3b
echo "MODEL_NAME=llama3.2:3b" > .env
python -m scripts.benchmark --runs 10

# Then phi3:mini
ollama pull phi3:mini
sed -i 's|llama3.2:3b|phi3:mini|' .env
python -m scripts.benchmark --runs 10

# Compare the two CSV files in your favourite spreadsheet.
```

The JSON files include the model name and config snapshot, so you can keep them around as a benchmark archive.

### 8.7 What's "good"?

Rough orders of magnitude on a modern laptop CPU (no GPU):

| Model size | Typical tokens/sec on CPU |
|------------|---------------------------|
| 1B         | 30–60                     |
| 3B         | 12–30                     |
| 7B         | 3–10                      |

With a recent NVIDIA GPU, multiply by 5–20×. If your numbers are an order of magnitude lower than this, you're either out of RAM (model is being swapped) or sharing a machine that's busy doing other work.

---

## 9. Structured outputs (JSON schema + Pydantic + retry)

Free-form chat is fine for humans, but if you want to **build on top** of the model — drive a UI, populate a database, kick off a workflow — you need structure. This project ships with an opinionated way to do that.

### 9.1 The flow

```
                    ┌────────────────────────────────────────────────┐
   User prompt ──▶  │  POST /api/structured                           │
                    │                                                 │
                    │  Attempt 1                                      │
                    │   1. Build prompt  =  system_prompt             │
                    │                       + JSON schema             │
                    │                       + user prompt             │
                    │   2. Call Ollama with `format: <schema>`        │
                    │      (constrains generation to the schema)      │
                    │   3. Parse JSON                                 │
                    │   4. Validate with Pydantic                     │
                    │      ──▶ success: return validated dict         │
                    │      ──▶ failure: capture error, go to attempt 2│
                    │                                                 │
                    │  Attempt 2 (only if attempt 1 failed)            │
                    │   1. Re-build prompt with the validation error  │
                    │      appended ("your previous reply failed…")   │
                    │   2..4 same as above                             │
                    │      ──▶ success: return validated dict         │
                    │      ──▶ failure: return StructuredFailure      │
                    │                  (success=false, raw output     │
                    │                   preserved for debugging)      │
                    └────────────────────────────────────────────────┘
```

Two layers of safety:

1. **Schema-constrained generation.** We pass the JSON Schema to Ollama's `format` parameter. Modern Ollama versions enforce this during sampling, so the model literally cannot emit invalid syntax for the schema.
2. **Pydantic validation.** Even with constrained generation we re-validate. This catches older Ollama versions that ignore the schema, and constraints Pydantic understands but JSON Schema doesn't (e.g. cross-field rules), and keeps your code defensible against future changes.

### 9.2 The schema

It's defined once in `app/structured.py`:

```python
class AssistantResponse(BaseModel):
    answer: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    follow_up_questions: list[str] = Field(default_factory=list, max_length=3)
    tags: list[str] = Field(default_factory=list, max_length=8)
```

Modify it freely — the rest of the module is generic. Add a `sources: list[str]` field, a `category: Literal["fact","opinion","instruction"]`, whatever you need. The retry logic will pick up the new schema automatically.

### 9.3 Try it

**From the UI** — click the **structured** tab, type *"What's the difference between TCP and UDP?"*, hit run. You'll get an answer card with a confidence bar, italicised reasoning, clickable follow-up questions, and topic tags.

**From the command line:**

```bash
curl -s http://127.0.0.1:8000/api/structured \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Is Python a compiled or interpreted language?"}' | jq .
```

Example response on success:

```json
{
  "success": true,
  "data": {
    "answer": "Python is technically both: source code is compiled to bytecode and then executed by an interpreter (the CPython VM). In everyday usage it is described as 'interpreted'.",
    "confidence": 0.92,
    "reasoning": "CPython compiles .py files to .pyc bytecode at import time, which a stack-based VM then executes; this matches the standard definition of an interpreted language with a JIT-less bytecode VM.",
    "follow_up_questions": [
      "How does PyPy's JIT change this?",
      "What is the .pyc file format?"
    ],
    "tags": ["python", "compilers", "interpreters"]
  },
  "debug": {
    "attempts": [{"attempt": 1, "ok": true, "meta": {...}}]
  }
}
```

Example response on graceful failure (both attempts invalid):

```json
{
  "success": false,
  "data": {
    "success": false,
    "error": "Model failed to produce valid structured output after 2 attempts.",
    "last_raw_output": "Sure! Here is your answer: Python is interpreted...",
    "last_validation_error": "Output is not valid JSON: Expecting value: line 1 column 1 (char 0).",
    "attempts": 2
  },
  "debug": {
    "attempts": [
      {"attempt": 1, "error": "...", "raw_preview": "..."},
      {"attempt": 2, "error": "...", "raw_preview": "..."}
    ]
  }
}
```

Your application code can branch on `success` and behave accordingly — fall back to free-form chat, log the failure, ask the user to rephrase, etc.

### 9.4 Why this beats prompt engineering alone

You can technically get JSON out of any model by writing *"please respond with JSON"* and crossing your fingers. In practice that approach fails 5–20% of the time on small models — trailing prose, markdown fences, missing fields, hallucinated keys. The combination of schema-constrained generation + strict Pydantic + automatic retry catches almost all of those failures, and the ones it can't catch are returned to your code as a clean error rather than as a JSON parse exception in production.

---

## 10. Customisation

### Change the model
```bash
ollama pull qwen2.5:3b
```
Edit `.env`: `MODEL_NAME=qwen2.5:3b`. Restart.

### Change the persona
Edit `SYSTEM_PROMPT` in `.env`.

### Tune response style
- `MODEL_TEMPERATURE=0.2` — focused, factual
- `MODEL_TEMPERATURE=0.9` — playful, varied
- `MODEL_NUM_CTX=8192` — longer memory of the conversation (uses more RAM)

### Change the structured schema
Edit `AssistantResponse` in `app/structured.py`. Restart.

### Change the look
`static/style.css` defines a small set of CSS variables at the top — tweak those to retheme the entire UI.

---

## 11. Troubleshooting

**The status dot is red.** Ollama isn't running. `sudo systemctl start ollama`.

**The status dot is amber.** Model not pulled. `ollama pull <model_name>`.

**Replies are very slow.** CPU-only with limited RAM. Try `llama3.2:1b` or `gemma2:2b`. If you have an NVIDIA GPU, install CUDA drivers and Ollama will use it automatically.

**`Address already in use` on port 8000.** Change `APP_PORT` in `.env` or stop the conflicting app.

**`pip install` fails with "externally-managed-environment".** You forgot to activate the venv. `source .venv/bin/activate`.

**Structured endpoint always fails.** Your model is probably too small or too old to handle JSON well. Try `qwen2.5:3b` (excellent at JSON) or `phi3:mini`. Also check the `last_raw_output` field in the response — it shows what the model actually said.

**Benchmarks show wildly different results between runs.** Almost always CPU contention. Close other apps, retry. Also check that `load_duration_s` is `0.0` after warmup — if it's nonzero, the model is being repeatedly evicted from memory (you may be low on RAM).

**I want to wipe all conversations.** `rm data/conversations.db` and restart.

---

## 12. Going further

- **Markdown rendering**: swap the tiny formatter in `static/app.js` for [marked.js](https://marked.js.org/).
- **File upload + RAG**: chunk documents, embed with `nomic-embed-text` (also via Ollama), store vectors in SQLite using `sqlite-vec`, retrieve top-k before the LLM call.
- **Voice in/out**: `whisper.cpp` for STT and `piper` for TTS, both fully offline.
- **Tool use**: implement function calling — give the model a calculator, file reader, or shell-runner. `qwen2.5` does this well.
- **Authentication**: `fastapi-users` before exposing beyond localhost.
- **Eval harness**: extend `scripts/benchmark.py` to also score answer quality with a separate "judge" model, and track it across model swaps.

---

## License

This scaffold is provided as-is. The model weights you download via Ollama are governed by their respective licenses — read them.