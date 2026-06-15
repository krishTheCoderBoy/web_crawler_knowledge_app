import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./App.css";

const API = "http://127.0.0.1:8000";

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

function parseSSEChunk(text) {
  const events = [];
  const blocks = text.split("\n\n");
  for (const block of blocks) {
    const lines = block.split("\n");
    let eventName = "message";
    let dataStr = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) eventName = line.slice(7).trim();
      else if (line.startsWith("data: ")) dataStr = line.slice(6).trim();
    }
    if (dataStr) {
      try {
        events.push({ event: eventName, data: JSON.parse(dataStr) });
      } catch {}
    }
  }
  return events;
}

async function streamPost(url, body, onEvent, signal) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || "Request failed");
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const evts = parseSSEChunk(part + "\n\n");
      for (const e of evts) onEvent(e);
    }
  }
  if (buffer.trim()) {
    for (const e of parseSSEChunk(buffer)) onEvent(e);
  }
}

// ---------------------------------------------------------------------------
// Tool call display labels
// ---------------------------------------------------------------------------

const TOOL_ICONS = {
  search_knowledge_base: "🔍",
  list_indexed_pages: "📋",
  get_page_summary: "📄",
  web_search_fallback: "🌐",
  extract_structured_data: "🗂️",
};

const TOOL_LABELS = {
  search_knowledge_base: (args) => `Searching KB: "${args.query}"`,
  list_indexed_pages: () => "Listing all indexed pages",
  get_page_summary: (args) => `Reading page: ${args.url}`,
  web_search_fallback: (args) => `Web search: "${args.query}"`,
  extract_structured_data: (args) => `Extracting structured data from ${args.url}`,
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };
  return (
    <button className="copy-btn" onClick={copy} title="Copy message">
      {copied ? "✓" : "⧉"}
    </button>
  );
}

function ToolStep({ step }) {
  const icon = TOOL_ICONS[step.name] || "⚙️";
  const label = TOOL_LABELS[step.name]
    ? TOOL_LABELS[step.name](step.args || {})
    : step.name;
  return (
    <div className={`tool-step ${step.status}`}>
      <span className="tool-icon">{icon}</span>
      <span className="tool-label">{label}</span>
      {step.status === "running" && <span className="tool-spinner" />}
      {step.status === "done" && step.summary && (
        <span className="tool-summary">{step.summary}</span>
      )}
    </div>
  );
}

function MessageBubble({ msg, activeSource, onSourceClick }) {
  if (msg.role === "user") {
    return (
      <div className="message user">
        <div className="message-text">{msg.text}</div>
        <CopyButton text={msg.text} />
      </div>
    );
  }

  if (msg.role === "system") {
    return (
      <div className="message system">
        <div className="message-text">{msg.text}</div>
      </div>
    );
  }

  return (
    <div className="message assistant">
      {msg.toolSteps && msg.toolSteps.length > 0 && (
        <div className="tool-steps">
          {msg.toolSteps.map((step, i) => (
            <ToolStep key={i} step={step} />
          ))}
        </div>
      )}
      <div className="message-text">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
      </div>
      {msg.model && (
        <div className="model-used">Answered with: {msg.model}</div>
      )}
      {msg.sources && msg.sources.length > 0 && (
        <div className="sources">
          <span className="sources-label">Retrieved Sources</span>
          <div className="source-chips">
            {msg.sources.map((src, i) => (
              <button
                key={`${src.url}-${i}`}
                className={`source-chip ${
                  activeSource?.url === src.url &&
                  activeSource?.chunk_index === src.chunk_index
                    ? "active"
                    : ""
                }`}
                onClick={() => onSourceClick(src)}
              >
                {src.title || `Source ${i + 1}`}
              </button>
            ))}
          </div>
        </div>
      )}
      <CopyButton text={msg.text} />
    </div>
  );
}

function CrawlProgressBar({ job }) {
  if (!job) return null;
  const { status, crawled, max, current_url, total_pages, error_count } = job;
  const pct = max > 0 ? Math.min(100, Math.round((crawled / max) * 100)) : 0;
  const isDone = status === "done";
  const isError = status === "error";

  return (
    <div className={`crawl-progress ${isDone ? "done" : ""} ${isError ? "error" : ""}`}>
      <div className="progress-header">
        <span className="progress-status">
          {isError ? "Crawl failed" : isDone ? `Done — ${total_pages} pages` : `Crawling…  ${crawled} pages`}
        </span>
        {error_count > 0 && (
          <span className="progress-errors">{error_count} errors</span>
        )}
        <span className="progress-pct">{pct}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {!isDone && !isError && current_url && (
        <div className="progress-url" title={current_url}>
          {current_url.length > 60 ? current_url.slice(0, 57) + "…" : current_url}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");
  const [kbName, setKbName] = useState("default");
  const [newKbName, setNewKbName] = useState("");
  const [kbList, setKbList] = useState([]);
  const [kbStatus, setKbStatus] = useState(null);
  const [availableModels, setAvailableModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [url, setUrl] = useState("");
  const [crawlJob, setCrawlJob] = useState(null);
  const [crawlResult, setCrawlResult] = useState(null);
  const [messages, setMessages] = useState([]);
  const [streamingMsg, setStreamingMsg] = useState(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [activeSource, setActiveSource] = useState(null);
  const [indexing, setIndexing] = useState(false);
  const [asking, setAsking] = useState(false);
  const [suggestedQuestions, setSuggestedQuestions] = useState([]);
  const [maxPages, setMaxPages] = useState(50);

  const chatEndRef = useRef(null);
  const abortRef = useRef(null);
  const crawlESRef = useRef(null);

  // Apply theme
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingMsg]);

  // Initial load
  useEffect(() => {
    fetchModels();
    fetchKbList();
  }, []);

  // Reload KB status when kb changes
  useEffect(() => {
    fetchKbStatus(kbName);
  }, [kbName]);

  const fetchModels = async () => {
    try {
      const res = await fetch(`${API}/models`);
      const data = await res.json();
      if (!res.ok) throw new Error("Unable to load models");
      setAvailableModels(data.available_models || []);
      setSelectedModel(data.selected_model || "");
    } catch {
      setError("Backend not reachable. Start the FastAPI server and try again.");
    }
  };

  const fetchKbList = async () => {
    try {
      const res = await fetch(`${API}/kb`);
      const data = await res.json();
      setKbList(Array.isArray(data) ? data : []);
    } catch {}
  };

  const fetchKbStatus = async (name) => {
    try {
      const res = await fetch(`${API}/kb/${encodeURIComponent(name)}/status`);
      const data = await res.json();
      setKbStatus(data);
    } catch {}
  };

  // ------------------------------------------------------------------
  // Crawling with SSE progress
  // ------------------------------------------------------------------

  const startCrawl = async () => {
    const trimmed = url.trim();
    if (!trimmed) { setError("Enter a website URL to crawl."); return; }
    setError("");
    setCrawlResult(null);
    setCrawlJob({ status: "starting", crawled: 0, max: maxPages, total_pages: 0 });

    // Close any existing EventSource
    if (crawlESRef.current) { crawlESRef.current.close(); }

    let jobId;
    try {
      const res = await fetch(`${API}/crawl/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmed, max_pages: maxPages }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to start crawl");
      jobId = data.job_id;
    } catch (err) {
      setError(err.message);
      setCrawlJob(null);
      return;
    }

    const es = new EventSource(`${API}/crawl/progress/${jobId}`);
    crawlESRef.current = es;

    es.addEventListener("progress", (e) => {
      try {
        const prog = JSON.parse(e.data);
        setCrawlJob(prog);
        if (prog.status === "done" || prog.status === "error") {
          es.close();
          if (prog.status === "done") {
            fetchCrawlResult(jobId);
          } else {
            setError(prog.message || "Crawl failed.");
          }
        }
      } catch {}
    });

    es.onerror = () => {
      es.close();
      fetchCrawlResult(jobId);
    };
  };

  const fetchCrawlResult = async (jobId) => {
    try {
      const res = await fetch(`${API}/crawl/result/${jobId}`);
      if (res.status === 202) return; // still running
      const data = await res.json();
      if (res.ok) {
        setCrawlResult(data);
        setCrawlJob((prev) => ({ ...prev, status: "done" }));
      }
    } catch {}
  };

  // ------------------------------------------------------------------
  // Indexing
  // ------------------------------------------------------------------

  const indexContent = async () => {
    if (!crawlResult?.pages?.length) { setError("Crawl a website first."); return; }
    setError("");
    setIndexing(true);
    setSuggestedQuestions([]);
    try {
      const res = await fetch(`${API}/index`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pages: crawlResult.pages,
          source_url: crawlResult.start_url,
          kb_name: kbName,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Indexing failed");
      setKbStatus(data);
      setSuggestedQuestions(data.suggested_questions || []);
      setMessages([{ role: "system", text: data.message }]);
      fetchKbList();
    } catch (err) {
      setError(err.message);
    } finally {
      setIndexing(false);
    }
  };

  // ------------------------------------------------------------------
  // Chat with SSE streaming
  // ------------------------------------------------------------------

  const sendQuestion = useCallback(async (q) => {
    const trimmed = (q || question).trim();
    if (!trimmed || asking) return;

    setError("");
    setQuestion("");
    setAsking(true);
    setActiveSource(null);

    const historyForReq = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, text: m.text }));

    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);

    // Streaming state
    let toolSteps = [];
    let tokenBuffer = "";
    const pendingTools = new Map(); // call_id -> step index

    setStreamingMsg({ text: "", toolSteps: [] });

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const onEvent = (evt) => {
      if (evt.event === "tool_call") {
        const step = {
          name: evt.data.name,
          args: evt.data.args,
          status: "running",
          summary: "",
        };
        const idx = toolSteps.length;
        pendingTools.set(evt.data.call_id, idx);
        toolSteps = [...toolSteps, step];
        setStreamingMsg({ text: tokenBuffer, toolSteps: [...toolSteps] });
      } else if (evt.event === "tool_result") {
        const idx = pendingTools.get(evt.data.call_id);
        if (idx !== undefined) {
          toolSteps = toolSteps.map((s, i) =>
            i === idx ? { ...s, status: "done", summary: evt.data.summary } : s
          );
        }
        setStreamingMsg({ text: tokenBuffer, toolSteps: [...toolSteps] });
      } else if (evt.event === "token") {
        tokenBuffer += evt.data.text;
        setStreamingMsg({ text: tokenBuffer, toolSteps: [...toolSteps] });
      } else if (evt.event === "done") {
        const finalMsg = {
          role: "assistant",
          text: tokenBuffer,
          toolSteps: [...toolSteps],
          sources: evt.data.sources || [],
          model: evt.data.model,
          mode: evt.data.mode,
        };
        setMessages((prev) => [...prev, finalMsg]);
        setStreamingMsg(null);
        setAsking(false);
        if ((evt.data.sources || []).length > 0) {
          setActiveSource(evt.data.sources[0]);
        }
        fetchKbStatus(kbName);
      } else if (evt.event === "error") {
        setError(evt.data.message || "Chat failed.");
        setStreamingMsg(null);
        setAsking(false);
      }
    };

    try {
      await streamPost(
        `${API}/chat/stream`,
        {
          question: trimmed,
          chat_history: historyForReq,
          model_id: selectedModel || null,
          kb_name: kbName,
        },
        onEvent,
        controller.signal,
      );
    } catch (err) {
      if (err.name !== "AbortError") {
        setError(err.message || "Chat request failed.");
      }
      setStreamingMsg(null);
      setAsking(false);
    }
  }, [question, asking, messages, selectedModel, kbName]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); }
  };

  // ------------------------------------------------------------------
  // Clear / Reset / Export
  // ------------------------------------------------------------------

  const clearChat = () => {
    setMessages([]);
    setStreamingMsg(null);
    setActiveSource(null);
    setSuggestedQuestions([]);
  };

  const deleteKb = async () => {
    if (!window.confirm(`Delete knowledge base "${kbName}"?`)) return;
    try {
      await fetch(`${API}/kb/${encodeURIComponent(kbName)}`, { method: "DELETE" });
      setKbStatus(null);
      setCrawlResult(null);
      setCrawlJob(null);
      clearChat();
      fetchKbList();
    } catch {
      setError("Failed to delete knowledge base.");
    }
  };

  const exportKb = async () => {
    try {
      const res = await fetch(`${API}/kb/${encodeURIComponent(kbName)}/export`);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `kb-${kbName}-export.json`;
      a.click();
    } catch {
      setError("Export failed.");
    }
  };

  const createKb = () => {
    const name = newKbName.trim();
    if (!name) return;
    setKbName(name);
    setNewKbName("");
    setCrawlResult(null);
    setCrawlJob(null);
    clearChat();
  };

  // ------------------------------------------------------------------
  // Stats
  // ------------------------------------------------------------------

  const stats = [
    { label: "Crawled Pages", value: crawlResult?.total_pages ?? kbStatus?.page_count ?? 0 },
    { label: "Indexed Pages", value: kbStatus?.indexed_pages ?? 0 },
    { label: "Text Chunks", value: kbStatus?.chunk_count ?? 0 },
  ];

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="control-panel">

        {/* Header row */}
        <div className="sidebar-top-row">
          <div className="hero-card">
            <p className="eyebrow">Crawler + RAG Workspace</p>
            <h1>Build a searchable website brain</h1>
            <p className="hero-copy">
              Crawl a site, index the content, then ask grounded questions
              powered by an agentic tool-calling loop.
            </p>
          </div>
          <button
            className="theme-toggle"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
            title="Toggle dark mode"
          >
            {theme === "light" ? "🌙" : "☀️"}
          </button>
        </div>

        {/* KB Selector */}
        <div className="panel-card">
          <label className="field-label">Knowledge Base</label>
          <div className="kb-row">
            <select
              value={kbName}
              onChange={(e) => {
                setKbName(e.target.value);
                clearChat();
              }}
            >
              <option value="default">default</option>
              {kbList
                .filter((kb) => kb.name !== "default")
                .map((kb) => (
                  <option key={kb.name} value={kb.name}>
                    {kb.name} ({kb.chunk_count} chunks)
                  </option>
                ))}
            </select>
            <button className="icon-btn danger" onClick={deleteKb} title="Delete this KB">
              🗑
            </button>
          </div>
          <div className="new-kb-row">
            <input
              placeholder="New KB name…"
              value={newKbName}
              onChange={(e) => setNewKbName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createKb()}
            />
            <button className="secondary-btn" onClick={createKb}>
              + Create
            </button>
          </div>
        </div>

        {/* Model */}
        <div className="panel-card">
          <label className="field-label" htmlFor="model-select">Chat Model</label>
          <div className="model-row">
            <select
              id="model-select"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={!availableModels.length}
            >
              {availableModels.map((m) => (
                <option key={m.model_id} value={m.model_id}>{m.label}</option>
              ))}
            </select>
            <span className="status-pill ready">
              {availableModels.length ? `${availableModels.length} models` : "Loading…"}
            </span>
          </div>
        </div>

        {/* Crawl */}
        <div className="panel-card">
          <label className="field-label" htmlFor="crawl-url">Website URL</label>
          <div className="crawl-bar">
            <input
              id="crawl-url"
              type="text"
              placeholder="https://example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && startCrawl()}
            />
            <button onClick={startCrawl} disabled={crawlJob?.status === "crawling"}>
              {crawlJob?.status === "crawling" ? "Crawling…" : "Crawl Site"}
            </button>
          </div>
          <div className="pages-limit-row">
            <label className="field-label" htmlFor="max-pages">Max pages</label>
            <div className="pages-limit-controls">
              {[25, 50, 100, 200].map((n) => (
                <button
                  key={n}
                  className={`limit-chip ${maxPages === n ? "active" : ""}`}
                  onClick={() => setMaxPages(n)}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          <CrawlProgressBar job={crawlJob} />

          <div className="action-row">
            <button
              className="secondary-btn"
              onClick={indexContent}
              disabled={indexing || !crawlResult?.pages?.length}
            >
              {indexing ? "Indexing…" : "Index Knowledge Base"}
            </button>
            <span className={`status-pill ${kbStatus?.is_ready ? "ready" : ""}`}>
              {kbStatus?.is_ready ? "KB Ready" : "Not Indexed"}
            </span>
          </div>

          {error && <div className="error-banner">{error}</div>}
        </div>

        {/* Stats */}
        <div className="stats-grid">
          {stats.map((item) => (
            <div key={item.label} className="stat-card">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>

        {/* Crawl results */}
        <div className="panel-card">
          <div className="section-heading">
            <h2>Crawl Results</h2>
            {crawlResult?.errors?.length ? (
              <span>{crawlResult.errors.length} page errors</span>
            ) : null}
          </div>
          <div className="pages-list">
            {crawlResult?.pages?.length ? (
              crawlResult.pages.map((page, i) => (
                <article key={`${page.url}-${i}`} className="page-card">
                  <a href={page.url} target="_blank" rel="noreferrer" className="page-url">
                    {page.title || page.url}
                  </a>
                  <p className="page-meta">{page.url}</p>
                  <p className="page-text">
                    {page.text
                      ? `${page.text.slice(0, 200)}${page.text.length > 200 ? "…" : ""}`
                      : "No extractable text."}
                  </p>
                  <div className="page-tags">
                    <span>{page.images.length} images</span>
                    <span>{page.links.length} links</span>
                  </div>
                </article>
              ))
            ) : (
              <div className="empty-state">Crawl a site to see pages before indexing.</div>
            )}
          </div>
        </div>
      </aside>

      {/* ── Chat Panel ── */}
      <main className="chat-panel">

        {/* Chat header */}
        <div className="chat-header">
          <div>
            <p className="eyebrow">Agentic RAG Chat</p>
            <h2>Ask questions with tool-calling intelligence</h2>
          </div>
          <div className="header-right">
            <div className="header-status">
              <span>Indexed site</span>
              <strong>{kbStatus?.source_url || "None"}</strong>
            </div>
            <div className="header-actions">
              <button className="icon-btn" onClick={exportKb} title="Export KB as JSON" disabled={!kbStatus?.is_ready}>
                ⬇ Export
              </button>
              <button className="icon-btn danger" onClick={clearChat} title="Clear chat">
                ✕ Clear
              </button>
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="chat-messages">
          {!messages.length && !streamingMsg ? (
            <div className="chat-empty">
              After indexing, ask anything. The agent will use tools to search, list pages,
              fetch summaries, run web searches, and extract structured data — automatically.
            </div>
          ) : (
            messages.map((msg, i) => (
              <MessageBubble
                key={i}
                msg={msg}
                activeSource={activeSource}
                onSourceClick={setActiveSource}
              />
            ))
          )}

          {/* Streaming message in progress */}
          {streamingMsg && (
            <div className="message assistant streaming">
              {streamingMsg.toolSteps.length > 0 && (
                <div className="tool-steps">
                  {streamingMsg.toolSteps.map((step, i) => (
                    <ToolStep key={i} step={step} />
                  ))}
                </div>
              )}
              {streamingMsg.text ? (
                <div className="message-text">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {streamingMsg.text}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="typing">
                  <span className="dot" /><span className="dot" /><span className="dot" />
                </div>
              )}
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Suggested questions */}
        {suggestedQuestions.length > 0 && !asking && (
          <div className="suggested-questions">
            <span className="suggestions-label">Suggested questions</span>
            <div className="suggestions-chips">
              {suggestedQuestions.map((q, i) => (
                <button key={i} className="suggestion-chip" onClick={() => sendQuestion(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Retrieval inspector */}
        <div className="retrieval-panel">
          <div className="section-heading">
            <h3>Retrieval Inspector</h3>
            <span>{activeSource ? `Chunk ${activeSource.chunk_index}  ·  score ${activeSource.score}` : "Select a source"}</span>
          </div>
          {activeSource ? (
            <div className="source-detail">
              <a href={activeSource.url} target="_blank" rel="noreferrer">
                {activeSource.title}
              </a>
              <p className="source-url">{activeSource.url}</p>
              <p>{activeSource.excerpt}</p>
            </div>
          ) : (
            <div className="empty-state">Source snippets from chat answers will appear here.</div>
          )}
        </div>

        {/* Input */}
        <div className="chat-input-bar">
          <textarea
            rows={3}
            placeholder={
              kbStatus?.is_ready
                ? "Ask something about the crawled website…"
                : "Index a website first to start chatting…"
            }
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!kbStatus?.is_ready || asking}
          />
          <button
            onClick={() => sendQuestion()}
            disabled={!kbStatus?.is_ready || asking || !question.trim()}
          >
            {asking ? "…" : "Send"}
          </button>
        </div>
      </main>
    </div>
  );
}
