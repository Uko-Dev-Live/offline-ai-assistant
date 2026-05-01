// Offline AI Assistant — frontend logic. Vanilla JS, no build step.
(() => {
  const $  = (id) => document.getElementById(id);
  const $$ = (sel) => document.querySelectorAll(sel);

  // ---------- Common helpers ----------
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  // Minimal markdown: code fences + inline code + bold/italic.
  const renderMd = (text) => {
    let out = escapeHtml(text);
    out = out.replace(/```([\s\S]*?)```/g, (_, body) => `<pre><code>${body}</code></pre>`);
    out = out.replace(/`([^`\n]+)`/g, (_, body) => `<code>${body}</code>`);
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return out;
  };

  // ---------- Mode tabs ----------
  $$(".mode").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode;
      $$(".mode").forEach((b) => b.classList.toggle("active", b === btn));
      $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${mode}`));
    });
  });

  // ============================================================
  //                       CHAT MODE
  // ============================================================
  const chatEls = {
    messages: $("messages"),
    input: $("input"),
    composer: $("composer"),
    send: $("send"),
    newChat: $("new-chat"),
    convList: $("conversations"),
  };
  let chat = { activeId: null, streaming: false };

  const scrollDown = () => { chatEls.messages.scrollTop = chatEls.messages.scrollHeight; };

  const setBusy = (busy) => {
    chat.streaming = busy;
    chatEls.send.disabled = busy;
    chatEls.input.disabled = busy;
  };

  async function loadConversations() {
    const r = await fetch("/api/conversations");
    const list = await r.json();
    chatEls.convList.innerHTML = "";
    for (const c of list) {
      const item = document.createElement("div");
      item.className = "conv-item" + (c.id === chat.activeId ? " active" : "");
      item.dataset.id = c.id;
      item.innerHTML = `
        <span class="conv-title">${escapeHtml(c.title)}</span>
        <button class="conv-del" title="Delete">✕</button>
      `;
      item.addEventListener("click", (e) => {
        if (e.target.classList.contains("conv-del")) return;
        openConversation(c.id);
      });
      item.querySelector(".conv-del").addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete "${c.title}"?`)) return;
        await fetch(`/api/conversations/${c.id}`, { method: "DELETE" });
        if (chat.activeId === c.id) {
          chat.activeId = null;
          renderEmpty();
        }
        loadConversations();
      });
      chatEls.convList.appendChild(item);
    }
  }

  async function openConversation(id) {
    chat.activeId = id;
    const r = await fetch(`/api/conversations/${id}/messages`);
    const messages = await r.json();
    chatEls.messages.innerHTML = "";
    if (!messages.length) {
      renderEmpty();
    } else {
      for (const m of messages) appendMessage(m.role, m.content);
    }
    loadConversations();
    scrollDown();
  }

  function newChat() {
    chat.activeId = null;
    renderEmpty();
    loadConversations();
    chatEls.input.focus();
  }

  function renderEmpty() {
    chatEls.messages.innerHTML = `
      <div class="empty">
        <h2>Ready when you are.</h2>
        <p>This assistant runs entirely on your machine. No data leaves this computer.</p>
      </div>
    `;
  }

  function appendMessage(role, content) {
    const empty = chatEls.messages.querySelector(".empty");
    if (empty) empty.remove();
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;
    wrap.innerHTML = `
      <div class="label">${role === "user" ? "you" : "ai"}</div>
      <div class="body">${renderMd(content)}</div>
    `;
    chatEls.messages.appendChild(wrap);
    return wrap.querySelector(".body");
  }

  async function sendMessage(text) {
    if (!text.trim() || chat.streaming) return;
    appendMessage("user", text);
    const aiBody = appendMessage("assistant", "");
    aiBody.innerHTML = '<span class="cursor"></span>';
    scrollDown();
    setBusy(true);

    let raw = "";
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: chat.activeId }),
      });
      if (!r.body) throw new Error("Streaming not supported by browser.");

      const reader = r.body.getReader();
      const dec = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        let chunk = dec.decode(value, { stream: true });
        const m = chunk.match(/\x00CONV:(\d+)\x00/);
        if (m) {
          chat.activeId = parseInt(m[1], 10);
          chunk = chunk.replace(m[0], "");
        }
        raw += chunk;
        aiBody.innerHTML = renderMd(raw) + '<span class="cursor"></span>';
        scrollDown();
      }
      aiBody.innerHTML = renderMd(raw);
    } catch (err) {
      aiBody.innerHTML = renderMd(raw + `\n\n[error] ${err.message}`);
    } finally {
      setBusy(false);
      loadConversations();
      chatEls.input.focus();
    }
  }

  chatEls.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatEls.input.value;
    chatEls.input.value = "";
    autoresize();
    sendMessage(text);
  });
  chatEls.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatEls.composer.requestSubmit();
    }
  });
  function autoresize() {
    chatEls.input.style.height = "auto";
    chatEls.input.style.height = Math.min(chatEls.input.scrollHeight, 220) + "px";
  }
  chatEls.input.addEventListener("input", autoresize);
  chatEls.newChat.addEventListener("click", newChat);

  // ============================================================
  //                    STRUCTURED MODE
  // ============================================================
  const sEls = {
    form: $("structured-form"),
    prompt: $("structured-prompt"),
    btn: $("structured-go"),
    out: $("structured-output"),
  };

  function renderStructured(payload) {
    sEls.out.innerHTML = "";

    const { success, data, debug } = payload;
    const card = document.createElement("article");
    card.className = "s-card " + (success ? "ok" : "fail");

    if (success) {
      const conf = Math.round((data.confidence || 0) * 100);
      const tags = (data.tags || [])
        .map((t) => `<span class="s-tag">${escapeHtml(t)}</span>`).join("");
      const followups = (data.follow_up_questions || [])
        .map((q) => `<li>${escapeHtml(q)}</li>`).join("");

      card.innerHTML = `
        <p class="s-answer">${escapeHtml(data.answer)}</p>

        <div class="s-row">
          <strong>confidence</strong>
          <div class="s-bar"><span style="width:${conf}%"></span></div>
          <code>${conf}%</code>
        </div>

        <p class="s-reasoning">${escapeHtml(data.reasoning)}</p>

        ${tags ? `<div class="s-tags">${tags}</div>` : ""}
        ${followups ? `<ul class="s-followups">${followups}</ul>` : ""}

        <details class="s-debug">
          <summary>raw payload (${debug.attempts.length} attempt${debug.attempts.length === 1 ? "" : "s"})</summary>${escapeHtml(JSON.stringify(payload, null, 2))}</details>
      `;

      // Click a follow-up to feed it back as the next prompt.
      card.querySelectorAll(".s-followups li").forEach((li) => {
        li.addEventListener("click", () => {
          sEls.prompt.value = li.textContent;
          sEls.prompt.focus();
        });
      });
    } else {
      const f = data;
      card.innerHTML = `
        <p class="s-answer" style="color:var(--danger)">Validation failed</p>
        <p class="s-fail-msg">${escapeHtml(f.error)}</p>
        <p class="s-row"><strong>last error</strong> <code>${escapeHtml(f.last_validation_error)}</code></p>
        <details class="s-debug">
          <summary>raw model output</summary>${escapeHtml(f.last_raw_output || "(empty)")}</details>
        <details class="s-debug">
          <summary>full debug</summary>${escapeHtml(JSON.stringify(payload, null, 2))}</details>
      `;
    }
    sEls.out.appendChild(card);
  }

  sEls.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = sEls.prompt.value.trim();
    if (!prompt) return;

    sEls.btn.disabled = true;
    sEls.out.innerHTML = `<p class="b-running">Generating structured response (will retry once on failure)…</p>`;

    try {
      const r = await fetch("/api/structured", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await r.json();
      renderStructured(data);
    } catch (err) {
      sEls.out.innerHTML = `<p class="s-fail-msg">${escapeHtml(err.message)}</p>`;
    } finally {
      sEls.btn.disabled = false;
    }
  });

  // ============================================================
  //                    BENCHMARK MODE
  // ============================================================
  const bEls = {
    form: $("bench-form"),
    prompt: $("bench-prompt"),
    runs: $("bench-runs"),
    warmup: $("bench-warmup"),
    btn: $("bench-go"),
    out: $("bench-output"),
  };

  function statCard(title, value, unit, sub) {
    return `
      <div class="b-stat">
        <h3>${title}</h3>
        <div><span class="big">${value}</span><span class="unit">${unit}</span></div>
        <div class="sub">${sub}</div>
      </div>
    `;
  }

  function renderBench(payload) {
    const { results, aggregate: agg } = payload;

    const summary = `
      <div class="bench-summary">
        ${statCard("TTFT", agg.ttft_ms.median, "ms",
                   `min ${agg.ttft_ms.min} · p95 ${agg.ttft_ms.p95}`)}
        ${statCard("Tokens / sec", agg.tokens_per_second.median, "tok/s",
                   `min ${agg.tokens_per_second.min} · max ${agg.tokens_per_second.max} (model-reported)`)}
        ${statCard("Total latency", agg.total_latency_ms.median, "ms",
                   `min ${agg.total_latency_ms.min} · p95 ${agg.total_latency_ms.p95}`)}
        ${statCard("Tokens / sec (wall)", agg.wall_tokens_per_second.median, "tok/s",
                   `as perceived after first token`)}
      </div>
    `;

    const rows = results.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${r.ttft_ms}</td>
        <td>${r.total_latency_ms}</td>
        <td>${r.tokens_generated}</td>
        <td>${r.tokens_per_second}</td>
        <td>${r.wall_tokens_per_second}</td>
      </tr>
    `).join("");

    const table = `
      <table class="b-table">
        <thead>
          <tr>
            <th>#</th><th>TTFT (ms)</th><th>Total (ms)</th>
            <th>Tokens</th><th>tok/s</th><th>wall tok/s</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;

    bEls.out.innerHTML = summary + table;
  }

  bEls.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = bEls.prompt.value.trim();
    const runs = parseInt(bEls.runs.value, 10) || 3;
    const warmup = bEls.warmup.checked;
    if (!prompt) return;

    bEls.btn.disabled = true;
    bEls.out.innerHTML = `<p class="b-running">Running ${runs} measured run${runs === 1 ? "" : "s"}${warmup ? " (with warmup)" : ""}… please wait</p>`;

    try {
      const r = await fetch("/api/benchmark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, runs, warmup }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      const data = await r.json();
      renderBench(data);
    } catch (err) {
      bEls.out.innerHTML = `<p class="s-fail-msg">${escapeHtml(err.message)}</p>`;
    } finally {
      bEls.btn.disabled = false;
    }
  });

  // ============================================================
  //                       HEALTH
  // ============================================================
  async function refreshHealth() {
    try {
      const r = await fetch("/api/health");
      const data = await r.json();
      const dot = $("status-dot");
      if (!data.ok) {
        dot.className = "dot err";
        dot.title = "Ollama unreachable";
        $("meta-model").textContent = data.configured_model || "—";
        return;
      }
      $("meta-model").textContent = data.configured_model;
      if (data.model_installed) {
        dot.className = "dot ok";
        dot.title = "Ready";
      } else {
        dot.className = "dot warn";
        dot.title = `Model not installed: run  ollama pull ${data.configured_model}`;
      }
    } catch {
      const dot = $("status-dot");
      dot.className = "dot err";
      dot.title = "Backend unreachable";
    }
  }

  // ---------- Boot ----------
  $("meta-host").textContent = location.host || "localhost";
  refreshHealth();
  setInterval(refreshHealth, 15000);
  loadConversations();
})();