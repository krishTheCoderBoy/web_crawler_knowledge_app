import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Login from "./Login";
import Landing from "./Landing";
import Settings from "./Settings";
import "./App.css";

const API = "http://127.0.0.1:8000";
const DEFAULT_MODEL = "openrouter/free";
const MODEL_ID_ALIASES = {
  "gpt-oss-120b": DEFAULT_MODEL,
  "openai/gpt-oss-120b:free": DEFAULT_MODEL,
  "llama-3.3-70b": DEFAULT_MODEL,
  "meta-llama/llama-3.3-70b-instruct:free": DEFAULT_MODEL,
  "deepseek-r1": DEFAULT_MODEL,
  "deepseek/deepseek-r1-0528:free": DEFAULT_MODEL,
  "qwen3-235b": DEFAULT_MODEL,
  "qwen/qwen3-235b-a22b:free": DEFAULT_MODEL,
  "glm-4.5-air": DEFAULT_MODEL,
  "z-ai/glm-4.5-air:free": DEFAULT_MODEL,
  "gemma-3-27b": DEFAULT_MODEL,
  "google/gemma-3-27b-it:free": DEFAULT_MODEL,
};
const MODEL_LABELS = {
  "openrouter/free": "Auto Free Model",
  "nvidia/nemotron-3-ultra-550b-a55b:free": "Nemotron 3 Ultra 550B",
  "poolside/laguna-s-2.1:free": "Laguna S 2.1",
  "dots-studio/dots-3-note-preview:free": "Dots 3 Note Preview",
};

function getPreferredModel() {
  const saved = localStorage.getItem("pref_default_model");
  const model = MODEL_ID_ALIASES[saved] || saved;
  if (!model || !MODEL_LABELS[model]) {
    localStorage.setItem("pref_default_model", DEFAULT_MODEL);
    return DEFAULT_MODEL;
  }
  if (model !== saved) localStorage.setItem("pref_default_model", model);
  return model;
}

// ── SSE helpers ────────────────────────────────────────────────────────────

function parseSSEChunk(text) {
  const events = [];
  for (const block of text.split("\n\n")) {
    const lines = block.split("\n");
    let eventName = "message";
    let dataStr = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) eventName = line.slice(7).trim();
      else if (line.startsWith("data: ")) dataStr = line.slice(6).trim();
    }
    if (dataStr) {
      try { events.push({ event: eventName, data: JSON.parse(dataStr) }); } catch {}
    }
  }
  return events;
}

async function streamPost(url, body, onEvent, signal, token) {
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
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
    for (const part of parts)
      for (const e of parseSSEChunk(part + "\n\n")) onEvent(e);
  }
  if (buffer.trim())
    for (const e of parseSSEChunk(buffer)) onEvent(e);
}

// ── Tool display ───────────────────────────────────────────────────────────

const TOOL_ICONS = {
  // RAG tools
  search_knowledge_base: "🔍",
  list_indexed_pages: "📋",
  get_page_summary: "📄",
  web_search_fallback: "🌐",
  extract_structured_data: "🗂️",
  // Agent tools
  create_knowledge_base: "🗄️",
  list_knowledge_bases: "📚",
  crawl_website: "🕷️",
  index_documents: "📥",
};
const TOOL_LABELS = {
  // RAG tools
  search_knowledge_base: (a) => `Searching KB: "${a.query}"`,
  list_indexed_pages: () => "Listing all indexed pages",
  get_page_summary: (a) => `Reading page: ${a.url}`,
  web_search_fallback: (a) => `Web search: "${a.query}"`,
  extract_structured_data: (a) => `Extracting data from ${a.url}`,
  // Agent tools
  create_knowledge_base: (a) => `Creating knowledge base: "${a.name}"`,
  list_knowledge_bases: () => "Listing all knowledge bases",
  crawl_website: (a) => `Crawling: ${a.url}`,
  index_documents: (a) => `Indexing into knowledge base #${a.knowledge_base_id}`,
};

// ── Sub-components ─────────────────────────────────────────────────────────

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  return (
    <button className="copy-btn" onClick={copy} title="Copy">
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

// Long-answer text collapses behind a max-height clamp with a Show More /
// Show Less toggle, so a very long response can't push the chat viewport
// (and therefore the page) taller — see ExpandableAnswer below.
const ANSWER_COLLAPSE_PX = 260;

function ExpandableAnswer({ text }) {
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const bodyRef = useRef(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    setOverflows(el.scrollHeight > ANSWER_COLLAPSE_PX + 4);
  }, [text]);

  return (
    <div className="answer-block">
      <div
        ref={bodyRef}
        className={`message-text answer-body ${!expanded && overflows ? "collapsed" : ""}`}
        style={!expanded && overflows ? { maxHeight: ANSWER_COLLAPSE_PX } : undefined}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
      {overflows && (
        <button className="show-more-btn" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show Less ▲" : "Show More ▼"}
        </button>
      )}
    </div>
  );
}

function MessageBubble({ msg, activeSource, onSourceClick, onRegenerateAnswer, asking }) {
  if (msg.role === "user")
    return (
      <div className="message user">
        <div className="message-text">{msg.text}</div>
        <CopyButton text={msg.text} />
      </div>
    );

  if (msg.role === "system")
    return (
      <div className="message system">
        <div className="message-text">{msg.text}</div>
      </div>
    );

  return (
    <div className="message assistant">
      {msg.toolSteps?.length > 0 && (
        <div className="tool-steps">
          {msg.toolSteps.map((s, i) => <ToolStep key={i} step={s} />)}
        </div>
      )}
      <ExpandableAnswer text={msg.text} />
      {msg.model && <div className="model-used">Answered with: {msg.model}</div>}
      {msg.sources?.length > 0 && (
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
      {msg.agentGenerated && (
        <button
          className="regenerate-answer-btn"
          onClick={() => onRegenerateAnswer(msg)}
          disabled={asking}
          title="Regenerate answer from this Knowledge Base"
          aria-label="Regenerate answer"
        >
          🔁
        </button>
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
          {isError ? "Crawl failed" : isDone
            ? `Done — ${total_pages} pages`
            : `Crawling… ${crawled} pages`}
        </span>
        {error_count > 0 && <span className="progress-errors">{error_count} errors</span>}
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

// ── Main App ───────────────────────────────────────────────────────────────

export default function App() {
  // Auth
  const [token, setToken] = useState(() => localStorage.getItem("token") || "");
  const [username, setUsername] = useState(() => localStorage.getItem("username") || "");
  const [fullName, setFullName] = useState(() => localStorage.getItem("full_name") || "");

  // Theme
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");

  // Settings overlay
  const [showSettings, setShowSettings] = useState(false);

  // Logged-out routing: land on the marketing page first, "Get Started" reveals the sign-in form
  const [showAuthForm, setShowAuthForm] = useState(false);

  // Knowledge bases
  const [kbList, setKbList] = useState([]);
  const [selectedKbId, setSelectedKbId] = useState(null);
  const [newKbName, setNewKbName] = useState("");
  const [kbStatus, setKbStatus] = useState(null);

  // Index modal
  const [showIndexModal, setShowIndexModal] = useState(false);
  const [indexTargetKbId, setIndexTargetKbId] = useState(null);

  const [selectedModel, setSelectedModel] = useState(getPreferredModel);

  // Agent mode toggle
  const [agentMode, setAgentMode] = useState(false);
  const [agentQuestions, setAgentQuestions] = useState([]);
  const [loadingAgentQuestions, setLoadingAgentQuestions] = useState(false);
  const [agentQuestionsRefresh, setAgentQuestionsRefresh] = useState(0);

  // Crawl
  const [url, setUrl] = useState("");
  const [crawlJob, setCrawlJob] = useState(null);
  const [crawlResult, setCrawlResult] = useState(null);
  const [maxPages, setMaxPages] = useState(50);

  // Chat
  const [messages, setMessages] = useState([]);
  const [chatConversations, setChatConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [streamingMsg, setStreamingMsg] = useState(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [suggestedQuestions, setSuggestedQuestions] = useState([]);
  const [activeSource, setActiveSource] = useState(null);

  const [indexing, setIndexing] = useState(false);
  const [error, setError] = useState("");

  const chatEndRef = useRef(null);
  const abortRef = useRef(null);
  const crawlESRef = useRef(null);

  // ── Auth helpers ───────────────────────────────────────────────────────

  const authedFetch = useCallback(
    (url, options = {}) =>
      fetch(url, {
        ...options,
        headers: { ...options.headers, Authorization: `Bearer ${token}` },
      }),
    [token]
  );

  const handleLogin = (tok, user, name) => {
    setToken(tok);
    setUsername(user);
    setFullName(name || user);
  };

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    localStorage.removeItem("full_name");
    setToken("");
    setUsername("");
    setFullName("");
    setKbList([]);
    setSelectedKbId(null);
    setMessages([]);
    setShowAuthForm(false); // land back on the landing page, not the sign-in form
  };

  // ── Effects ────────────────────────────────────────────────────────────

  // Catch the redirect back from /auth/github/callback or /auth/google/callback
  // (?oauth_token=&username=&full_name=) and complete sign-in the same way a
  // normal password login would, then strip the params from the URL.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const oauthToken = params.get("oauth_token");
    if (!oauthToken) return;
    const oauthUser = params.get("username") || "";
    const oauthName = params.get("full_name") || oauthUser;
    localStorage.setItem("token", oauthToken);
    localStorage.setItem("username", oauthUser);
    localStorage.setItem("full_name", oauthName);
    setToken(oauthToken);
    setUsername(oauthUser);
    setFullName(oauthName);
    setShowAuthForm(true);
    window.history.replaceState({}, "", window.location.pathname);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingMsg]);

  useEffect(() => {
    if (!token) return;
    fetchKbList();
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (selectedKbId != null) fetchKbStatus(selectedKbId);
  }, [selectedKbId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (selectedKbId == null) {
      setChatConversations([]);
      return;
    }
    let cancelled = false;
    setChatConversations([]);
    authedFetch(`${API}/knowledge-bases/${selectedKbId}/chat-conversations`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => { if (!cancelled) setChatConversations(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [selectedKbId, authedFetch]);

  useEffect(() => {
    if (!agentMode || selectedKbId == null) {
      setAgentQuestions([]);
      setLoadingAgentQuestions(false);
      return;
    }
    let cancelled = false;
    setAgentQuestions([]);
    setLoadingAgentQuestions(true);
    authedFetch(`${API}/knowledge-bases/${selectedKbId}/agent-questions?model_id=${encodeURIComponent(selectedModel)}`)
      .then((res) => (res.ok ? res.json() : { questions: [] }))
      .then((data) => {
        if (!cancelled) setAgentQuestions(data.questions || []);
      })
      .catch(() => { if (!cancelled) setAgentQuestions([]); })
      .finally(() => { if (!cancelled) setLoadingAgentQuestions(false); });
    return () => { cancelled = true; };
  }, [agentMode, selectedKbId, agentQuestionsRefresh, selectedModel, authedFetch]);

  // ── API calls ──────────────────────────────────────────────────────────

  const fetchKbList = async () => {
    try {
      const res = await authedFetch(`${API}/knowledge-bases`);
      if (!res.ok) return;
      const data = await res.json();
      setKbList(data);
      if (data.length > 0) {
        setSelectedKbId((prev) => {
          if (prev && data.find((k) => k.id === prev)) return prev;
          return (data.find((k) => k.is_default) || data[0]).id;
        });
        setIndexTargetKbId((prev) => {
          if (prev && data.find((k) => k.id === prev)) return prev;
          return (data.find((k) => k.is_default) || data[0]).id;
        });
      }
    } catch {}
  };

  const fetchKbStatus = async (kbId) => {
    try {
      const res = await authedFetch(`${API}/knowledge-bases/${kbId}/status`);
      if (!res.ok) return;
      setKbStatus(await res.json());
    } catch {}
  };

  // ── Crawling ────────────────────────────────────────────────────────────

  const startCrawl = async () => {
    const trimmed = url.trim();
    if (!trimmed) { setError("Enter a website URL to crawl."); return; }
    setError("");
    setCrawlResult(null);
    setCrawlJob({ status: "starting", crawled: 0, max: maxPages, total_pages: 0 });
    if (crawlESRef.current) crawlESRef.current.close();

    let jobId;
    try {
      const res = await authedFetch(`${API}/crawl/start`, {
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

    const es = new EventSource(
      `${API}/crawl/progress/${jobId}?token=${encodeURIComponent(token)}`
    );
    crawlESRef.current = es;

    es.addEventListener("progress", (e) => {
      try {
        const prog = JSON.parse(e.data);
        setCrawlJob(prog);
        if (prog.status === "done" || prog.status === "error") {
          es.close();
          if (prog.status === "done") fetchCrawlResult(jobId);
          else setError(prog.message || "Crawl failed.");
        }
      } catch {}
    });
    es.onerror = () => { es.close(); fetchCrawlResult(jobId); };
  };

  const fetchCrawlResult = async (jobId) => {
    try {
      const res = await authedFetch(`${API}/crawl/result/${jobId}`);
      if (res.status === 202) return;
      const data = await res.json();
      if (res.ok) {
        setCrawlResult(data);
        setCrawlJob((prev) => ({ ...prev, status: "done" }));
      }
    } catch {}
  };

  // ── Indexing ────────────────────────────────────────────────────────────

  const indexContent = async (kbId) => {
    if (!crawlResult?.pages?.length) { setError("Crawl a website first."); return; }
    setError("");
    setIndexing(true);
    setShowIndexModal(false);
    setSuggestedQuestions([]);
    try {
      const res = await authedFetch(`${API}/index`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pages: crawlResult.pages,
          source_url: crawlResult.start_url,
          knowledge_base_id: kbId,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Indexing failed");
      setKbStatus(data);
      setSuggestedQuestions(data.suggested_questions || []);
      setAgentQuestionsRefresh((version) => version + 1);
      setMessages([{ role: "system", text: data.message || "Indexing complete." }]);
      setSelectedKbId(kbId);
      fetchKbList();
    } catch (err) {
      setError(err.message);
    } finally {
      setIndexing(false);
    }
  };

  // ── Knowledge Base management ────────────────────────────────────────────

  const createKb = async () => {
    const name = newKbName.trim();
    if (!name) return;
    try {
      const res = await authedFetch(`${API}/knowledge-bases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to create KB");
      setNewKbName("");
      await fetchKbList();
    } catch (err) {
      setError(err.message);
    }
  };

  const deleteKb = async (kbId) => {
    const kb = kbList.find((k) => k.id === kbId);
    if (!window.confirm(`Delete knowledge base "${kb?.name}"? This will remove all indexed data.`))
      return;
    try {
      await authedFetch(`${API}/knowledge-bases/${kbId}`, { method: "DELETE" });
      if (selectedKbId === kbId) {
        const def = kbList.find((k) => k.is_default && k.id !== kbId);
        setSelectedKbId(def?.id ?? null);
        clearChat();
      }
      fetchKbList();
    } catch {
      setError("Failed to delete knowledge base.");
    }
  };

  const exportKb = async () => {
    const kb = kbList.find((k) => k.id === selectedKbId);
    if (!kb) return;
    try {
      const res = await authedFetch(
        `${API}/kb/${encodeURIComponent(kb.collection)}/export`
      );
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `kb-${kb.name.replace(/\s+/g, "_")}-export.json`;
      a.click();
    } catch {
      setError("Export failed.");
    }
  };

  // ── Chat ───────────────────────────────────────────────────────────────

  const clearChat = () => {
    setMessages([]);
    setActiveConversationId(null);
    setStreamingMsg(null);
    setActiveSource(null);
    setSuggestedQuestions([]);
  };

  const openConversation = async (conversationId) => {
    try {
      const res = await authedFetch(`${API}/chat-conversations/${conversationId}`);
      if (!res.ok) throw new Error("Could not load this conversation.");
      const conversation = await res.json();
      setSelectedKbId(conversation.kb_id);
      setActiveConversationId(conversation.id);
      setMessages(conversation.messages || []);
      setStreamingMsg(null);
      setActiveSource(null);
      setSuggestedQuestions([]);
      setError("");
    } catch (err) {
      setError(err.message || "Could not load this conversation.");
    }
  };

  const sendQuestion = useCallback(
    async (q, { selectedKbOnly = false } = {}) => {
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

      let toolSteps = [];
      let tokenBuffer = "";
      const pendingTools = new Map();
      setStreamingMsg({ text: "", toolSteps: [] });

      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const onEvent = (evt) => {
        if (evt.event === "tool_call") {
          const step = { name: evt.data.name, args: evt.data.args, status: "running", summary: "" };
          pendingTools.set(evt.data.call_id, toolSteps.length);
          toolSteps = [...toolSteps, step];
          setStreamingMsg({ text: tokenBuffer, toolSteps: [...toolSteps] });
        } else if (evt.event === "tool_result") {
          const idx = pendingTools.get(evt.data.call_id);
          if (idx !== undefined)
            toolSteps = toolSteps.map((s, i) =>
              i === idx ? { ...s, status: "done", summary: evt.data.summary } : s
            );
          setStreamingMsg({ text: tokenBuffer, toolSteps: [...toolSteps] });
        } else if (evt.event === "token") {
          tokenBuffer += evt.data.text;
          setStreamingMsg({ text: tokenBuffer, toolSteps: [...toolSteps] });
        } else if (evt.event === "done") {
          const assistantMessage = {
            role: "assistant",
            text: tokenBuffer,
            toolSteps: [...toolSteps],
            sources: evt.data.sources || [],
            model: evt.data.model,
            ...(selectedKbOnly ? { agentGenerated: true, question: trimmed } : {}),
          };
          const completedMessages = [
            ...messages,
            { role: "user", text: trimmed },
            assistantMessage,
          ];
          setMessages(completedMessages);
          setStreamingMsg(null);
          if ((evt.data.sources || []).length > 0) setActiveSource(evt.data.sources[0]);
          fetchKbStatus(selectedKbId);
          // Refresh KB list — agent may have created KBs or indexed content
          if (agentMode) fetchKbList();
          (async () => {
            try {
              const isNewConversation = !activeConversationId;
              const url = isNewConversation
                ? `${API}/knowledge-bases/${selectedKbId}/chat-conversations`
                : `${API}/chat-conversations/${activeConversationId}`;
              const res = await authedFetch(url, {
                method: isNewConversation ? "POST" : "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ messages: completedMessages }),
              });
              if (!res.ok) throw new Error("Could not save chat history.");
              const conversation = await res.json();
              setActiveConversationId(conversation.id);
              const historyRes = await authedFetch(
                `${API}/knowledge-bases/${selectedKbId}/chat-conversations`
              );
              if (historyRes.ok) setChatConversations(await historyRes.json());
            } catch {
              setError("Chat completed, but its history could not be saved.");
            } finally {
              setAsking(false);
            }
          })();
        } else if (evt.event === "error") {
          setError(evt.data.message || "Chat failed.");
          setStreamingMsg(null);
          setAsking(false);
        }
      };

      try {
        await streamPost(
          selectedKbOnly
            ? `${API}/agent/answer/stream`
            : agentMode ? `${API}/agent/chat/stream` : `${API}/chat/stream`,
          {
            question: trimmed,
            chat_history: historyForReq,
            model_id: selectedModel || null,
            knowledge_base_id: selectedKbId,
          },
          onEvent,
          controller.signal,
          token,
        );
      } catch (err) {
        if (err.name !== "AbortError") setError(err.message || "Chat request failed.");
        setStreamingMsg(null);
        setAsking(false);
      }
    },
    [question, asking, messages, selectedModel, selectedKbId, token, authedFetch, agentMode, activeConversationId] // eslint-disable-line
  );

  const regenerateAgentAnswer = (message) => {
    if (message.question) sendQuestion(message.question, { selectedKbOnly: true });
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); }
  };

  // ── Derived ────────────────────────────────────────────────────────────

  const selectedKb = kbList.find((k) => k.id === selectedKbId);

  const stats = [
    { label: "Crawled Pages", value: crawlResult?.total_pages ?? kbStatus?.page_count ?? 0 },
    { label: "Indexed Pages", value: kbStatus?.indexed_pages ?? kbStatus?.total_pages ?? 0 },
    { label: "Text Chunks",   value: kbStatus?.chunk_count ?? 0 },
  ];

  // ── Auth gate ──────────────────────────────────────────────────────────

  if (!token) {
    if (!showAuthForm) {
      return (
        <Landing
          onGetStarted={() => setShowAuthForm(true)}
          theme={theme}
          onThemeChange={setTheme}
        />
      );
    }
    return <Login onLogin={handleLogin} />;
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="app-shell">

      {/* ── Full-width page header ── */}
      <header className="page-header">
        <div className="hero-card">
          <p className="eyebrow">Crawler + RAG Workspace</p>
          <h1>Build a searchable website brain</h1>
          <p className="hero-copy">
            Crawl a site, index the content, then ask grounded questions
            powered by an agentic tool-calling loop.
          </p>
        </div>
        <div className="header-user-row">
          <button
            className="theme-toggle"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
            title="Toggle dark mode"
          >
            {theme === "light" ? "🌙" : "☀️"}
          </button>
          <button
            className="theme-toggle"
            onClick={() => setShowSettings(true)}
            title="Settings"
          >
            ⚙
          </button>
          <div className="header-user">
            <span className="header-username">{fullName || username}</span>
            <button className="logout-btn" onClick={logout}>Sign out</button>
          </div>
        </div>
      </header>

      {showSettings && (
        <Settings
          fullName={fullName}
          username={username}
          theme={theme}
          onThemeChange={setTheme}
          onBackToChat={() => setShowSettings(false)}
          onLogout={() => { setShowSettings(false); logout(); }}
          token={token}
          selectedModel={selectedModel}
          onModelChange={(model) => {
            setSelectedModel(model);
            localStorage.setItem("pref_default_model", model);
          }}
        />
      )}

      <div className="app-body">

        {/* ── Sidebar ── */}
        <aside className="control-panel">

          {/* ── Knowledge Base section ── */}
          <div className="panel-card kb-panel">
            <div className="section-heading">
              <h2>Knowledge Bases</h2>
              <span className="kb-count-badge">{kbList.length}</span>
            </div>

            <div className="kb-list">
              {kbList.map((kb) => (
                <div
                  key={kb.id}
                  className={`kb-item ${selectedKbId === kb.id ? "active" : ""}`}
                  onClick={() => { setSelectedKbId(kb.id); clearChat(); }}
                >
                  <div className="kb-item-left">
                    <span className={`kb-dot ${kb.is_ready ? "ready" : ""}`} />
                    <div className="kb-item-info">
                      <span className="kb-item-name">{kb.name}</span>
                      <span className="kb-item-meta">
                        {kb.is_default
                          ? "Default"
                          : `${kb.chunk_count ?? 0} chunks`}
                      </span>
                    </div>
                  </div>
                  <div className="kb-item-right">
                    {kb.is_ready && <span className="kb-ready-pill">Ready</span>}
                    {!kb.is_default && (
                      <button
                        className="kb-delete-btn"
                        onClick={(e) => { e.stopPropagation(); deleteKb(kb.id); }}
                        title="Delete KB"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="new-kb-row">
              <input
                placeholder="New knowledge base name…"
                value={newKbName}
                onChange={(e) => setNewKbName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && createKb()}
              />
              <button className="secondary-btn" onClick={createKb}>
                + Create
              </button>
            </div>
          </div>

          {/* ── Chat History ── */}
          <div className="panel-card history-panel">
            <div className="section-heading">
              <h2>Chat History</h2>
              <span className="kb-count-badge">{chatConversations.length}</span>
            </div>
            {!selectedKbId ? (
              <p className="history-empty">Select a Knowledge Base to view conversations.</p>
            ) : chatConversations.length === 0 ? (
              <p className="history-empty">No conversations yet.</p>
            ) : (
              <div className="conversation-list">
                {chatConversations.map((conversation) => (
                  <button
                    key={conversation.id}
                    className={`conversation-item ${activeConversationId === conversation.id ? "active" : ""}`}
                    onClick={() => openConversation(conversation.id)}
                    title={conversation.title}
                  >
                    <span className="conversation-title">{conversation.title}</span>
                    <time className="conversation-date">
                      {new Date(`${conversation.created_at.replace(" ", "T")}Z`).toLocaleString(undefined, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </time>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* ── Crawl ── */}
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
              <label className="field-label">Max pages</label>
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

            {/* ── Index flow ── */}
            {showIndexModal ? (
              <div className="index-modal">
                <p className="index-modal-title">Select Knowledge Base</p>
                <p className="index-modal-sub">
                  Where should this crawled content be stored?
                </p>
                <select
                  value={indexTargetKbId ?? ""}
                  onChange={(e) => setIndexTargetKbId(Number(e.target.value))}
                >
                  {kbList.map((kb) => (
                    <option key={kb.id} value={kb.id}>{kb.name}</option>
                  ))}
                </select>
                <div className="index-modal-actions">
                  <button
                    className="secondary-btn"
                    onClick={() => setShowIndexModal(false)}
                  >
                    Cancel
                  </button>
                  <button
                    disabled={indexing || !indexTargetKbId}
                    onClick={() => indexContent(indexTargetKbId)}
                  >
                    {indexing ? "Indexing…" : "Index Now"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="action-row">
                <button
                  className="secondary-btn"
                  disabled={indexing || !crawlResult?.pages?.length}
                  onClick={() => {
                    if (!crawlResult?.pages?.length) {
                      setError("Crawl a website first.");
                      return;
                    }
                    setShowIndexModal(true);
                  }}
                >
                  {indexing ? "Indexing…" : "Index Knowledge Base"}
                </button>
                <span className={`status-pill ${kbStatus?.is_ready ? "ready" : ""}`}>
                  {kbStatus?.is_ready ? "KB Ready" : "Not Indexed"}
                </span>
              </div>
            )}

            {error && <div className="error-banner">{error}</div>}
          </div>

          {/* ── Stats ── */}
          <div className="stats-grid">
            {stats.map((item) => (
              <div key={item.label} className="stat-card">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>

        </aside>

        {/* ── Chat Panel ── */}
        <main className="chat-panel">

          {/* Chat header — single horizontal toolbar */}
          <div className="chat-header">
            <div className="header-left">
              <p className="eyebrow">{agentMode ? "Agent Chat" : "RAG Chat"}</p>
              <h2>
                {agentMode
                  ? "Agent: crawl, manage KBs, and search"
                  : "Ask questions about the indexed site"}
              </h2>
            </div>
            <div className="header-right">
              <span className="selected-model-indicator" title={selectedModel}>
                {MODEL_LABELS[selectedModel] || selectedModel}
              </span>
              <button
                className={`agent-toggle ${agentMode ? "active" : ""}`}
                onClick={() => { setAgentMode((m) => !m); clearChat(); }}
                title={agentMode ? "Switch to RAG mode" : "Switch to Agent mode"}
              >
                <span className="toggle-dot" />
                {agentMode ? "Agent On" : "Agent Off"}
              </button>
              <div className="chat-kb-selector">
                <span className="field-label">Chatting with</span>
                <select
                  value={selectedKbId ?? ""}
                  onChange={(e) => { setSelectedKbId(Number(e.target.value)); clearChat(); }}
                >
                  {kbList.map((kb) => (
                    <option key={kb.id} value={kb.id}>{kb.name}</option>
                  ))}
                </select>
              </div>
              <div className="header-actions">
                <button
                  className="icon-btn"
                  onClick={exportKb}
                  title="Export KB as JSON"
                  disabled={!kbStatus?.is_ready}
                >
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
                {agentMode
                  ? "Agent mode: ask me to crawl a site, create a knowledge base, index content, or answer questions."
                  : selectedKb
                  ? "Index a website, then ask anything about it."
                  : "Index a website first to start chatting."}
              </div>
            ) : (
              messages.map((msg, i) => (
                <MessageBubble
                  key={i}
                  msg={msg}
                  activeSource={activeSource}
                  onSourceClick={setActiveSource}
                  onRegenerateAnswer={regenerateAgentAnswer}
                  asking={asking}
                />
              ))
            )}

            {streamingMsg && (
              <div className="message assistant streaming">
                {streamingMsg.toolSteps.length > 0 && (
                  <div className="tool-steps">
                    {streamingMsg.toolSteps.map((s, i) => <ToolStep key={i} step={s} />)}
                  </div>
                )}
                {streamingMsg.text ? (
                  <div className="message-text streaming-text">
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
          {agentMode && !asking && (loadingAgentQuestions || agentQuestions.length > 0) && (
            <div className="agent-question-panel">
              <span className="suggestions-label">Questions from this Knowledge Base</span>
              {loadingAgentQuestions ? (
                <div className="agent-question-loading">Generating questions from indexed pages…</div>
              ) : (
                <div className="agent-question-grid">
                  {agentQuestions.map((q, i) => (
                    <button
                      key={`${q}-${i}`}
                      className="agent-question-card"
                      onClick={() => sendQuestion(q, { selectedKbOnly: true })}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {!agentMode && suggestedQuestions.length > 0 && !asking && (
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

          {/* Input */}
          <div className="chat-input-bar">
            <textarea
              rows={3}
              placeholder={
                agentMode
                  ? `Tell the agent what to do — crawl, index, search, or ask questions…`
                  : kbStatus?.is_ready
                  ? `Ask something about "${selectedKb?.name || "the knowledge base"}"…`
                  : "Index a website first to start chatting…"
              }
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={(!agentMode && !kbStatus?.is_ready) || asking}
            />
            <button
              onClick={() => sendQuestion()}
              disabled={(!agentMode && !kbStatus?.is_ready) || asking || !question.trim()}
            >
              {asking ? "…" : "Send"}
            </button>
          </div>

        </main>
      </div>
    </div>
  );
}
