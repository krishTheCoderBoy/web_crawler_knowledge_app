import React, { useEffect, useState } from "react";
import "./Landing.css";

const MODELS = [
  { name: "Llama 3.3 70B", provider: "Meta" },
  { name: "GPT OSS 120B", provider: "OpenAI" },
  { name: "DeepSeek R1", provider: "DeepSeek" },
  { name: "Qwen3 235B", provider: "Alibaba" },
  { name: "Nemotron 3 Super", provider: "NVIDIA" },
  { name: "Gemma 3 27B", provider: "Google" },
  { name: "Kimi K2", provider: "Moonshot AI" },
  { name: "Mistral 7B", provider: "Mistral" },
  { name: "Phi-4", provider: "Microsoft" },
  { name: "GLM-4.5 Air", provider: "Z-AI" },
];

const TRACE_STEPS = [
  { time: "10:21:14", tool: null, label: "agent_started" },
  {
    time: "10:21:15",
    tool: "crawl_website",
    lines: ["https://your-docs-site.com/", "Discovering pages...", "128 / 240"],
    progress: 53,
  },
  {
    time: "10:21:23",
    tool: "index_documents",
    lines: ["3,482 chunks created", "Vector index ready"],
  },
  {
    time: "10:21:27",
    tool: "search_knowledge_base",
    lines: ['Query: "How do I authenticate requests?"', "6 relevant chunks found"],
  },
  {
    time: "10:21:29",
    tool: "generate_answer",
    lines: ["Streaming answer...", "ANSWER", "Requests are authenticated using a bearer token passed in the Authorization header…"],
    sources: ["[1] Authentication Guide", "[2] API Reference"],
  },
];

function LiveTrace() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setStep((s) => (s + 1) % TRACE_STEPS.length);
    }, 2200);
    return () => clearInterval(id);
  }, []);

  const visible = TRACE_STEPS.slice(0, step + 1);

  return (
    <div className="lp-trace-card">
      <div className="lp-trace-head">
        <div className="lp-trace-head-left">
          <span className="mono lp-trace-label">LIVE AGENT MODE</span>
          <span className="lp-pill mono">OPTIONAL</span>
        </div>
        <div className="lp-trace-head-right">
          <span className="lp-live-dot" />
          <span className="mono">LIVE</span>
        </div>
      </div>
      <div className="lp-trace-body mono">
        {visible.map((s, i) => (
          <div className="lp-trace-step" key={i}>
            <div className="lp-trace-time">{s.time}</div>
            {s.tool ? (
              <div className="lp-trace-tool">{s.tool}</div>
            ) : (
              <div className="lp-trace-dim">{s.label}</div>
            )}
            {s.lines?.map((line, j) =>
              line === "ANSWER" ? null : (
                <div
                  key={j}
                  className={
                    j === 0 && s.tool === "search_knowledge_base"
                      ? "lp-trace-dim"
                      : line.startsWith('"') || (s.tool === "generate_answer" && j > 1)
                      ? "lp-trace-answer"
                      : "lp-trace-dim"
                  }
                >
                  {line}
                </div>
              )
            )}
            {s.progress != null && (
              <div className="lp-trace-progress">
                <div className="lp-trace-progress-fill" style={{ width: `${s.progress}%` }} />
              </div>
            )}
            {s.sources && (
              <div className="lp-trace-sources">
                <div className="lp-trace-sources-label">SOURCES</div>
                {s.sources.map((src) => (
                  <div key={src} className="lp-trace-dim">{src}</div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Landing({ onGetStarted, theme, onThemeChange }) {
  return (
    <div className="lp-root" data-theme={theme}>
      {/* NAV */}
      <div className="lp-nav">
        <div className="lp-nav-brand">
          <span className="lp-logo-mark" />
          <span>crawlmind</span>
        </div>
        <div className="lp-nav-links">
          <a href="#how">How it works</a>
          <a href="#models">Models</a>
          <a href="#kb">Knowledge Bases</a>
        </div>
        <div className="lp-nav-actions">
          <button
            className="lp-theme-btn"
            onClick={() => onThemeChange(theme === "light" ? "dark" : "light")}
            title="Toggle theme"
          >
            {theme === "light" ? "🌙" : "☀️"}
          </button>
          <button className="lp-btn-ghost" onClick={onGetStarted}>Sign in</button>
          <button className="lp-btn-primary" onClick={onGetStarted}>Get Started →</button>
        </div>
      </div>

      {/* HERO */}
      <div className="lp-hero">
        <div className="lp-hero-left">
          <div className="lp-pill mono lp-eyebrow-pill">AI KNOWLEDGE AGENT</div>
          <h1 className="lp-h1">
            Crawl any website.<br />Index everything.<br />Chat with knowledge.
          </h1>
          <p className="lp-hero-copy">
            Crawl websites into searchable knowledge bases and ask questions with
            cited answers. Use Standard Mode for a simple experience, or turn on
            Agent Mode to inspect the AI's tool execution.
          </p>
          <div className="lp-url-bar">
            <span className="mono lp-url-scheme">https://</span>
            <span className="mono lp-url-text">your-docs-site.com/</span>
            <button className="lp-btn-primary lp-url-btn" onClick={onGetStarted}>Get Started →</button>
          </div>
          <div className="mono lp-hero-note">No credit card. Free models included.</div>
        </div>
        <div className="lp-hero-right">
          <LiveTrace />
        </div>
      </div>

      {/* HOW IT WORKS */}
      <div id="how" className="lp-section">
        <div className="lp-eyebrow mono">HOW IT WORKS</div>
        <h2 className="lp-h2">The pipeline, not the pitch.</h2>
        <div className="lp-pipeline-grid">
          <div className="lp-pipeline-card">
            <div className="mono lp-pipeline-cmd">$ crawl_website</div>
            <div className="mono lp-pipeline-key">INPUT</div>
            <div className="mono lp-pipeline-val">A website URL</div>
            <div className="mono lp-pipeline-key">OUTPUT</div>
            <div className="mono lp-pipeline-val lp-pipeline-out">Pages<br />Links<br />Extracted text</div>
          </div>
          <div className="lp-pipeline-card">
            <div className="mono lp-pipeline-cmd">$ index_documents</div>
            <div className="mono lp-pipeline-key">INPUT</div>
            <div className="mono lp-pipeline-val">Crawled pages</div>
            <div className="mono lp-pipeline-key">OUTPUT</div>
            <div className="mono lp-pipeline-val lp-pipeline-out">Chunks<br />Vector index ready</div>
          </div>
          <div className="lp-pipeline-card">
            <div className="mono lp-pipeline-cmd">$ search_knowledge_base</div>
            <div className="mono lp-pipeline-key">INPUT</div>
            <div className="mono lp-pipeline-val">User query</div>
            <div className="mono lp-pipeline-key">OUTPUT</div>
            <div className="mono lp-pipeline-val lp-pipeline-out">Relevant chunks<br />Ranked by score</div>
          </div>
          <div className="lp-pipeline-card">
            <div className="mono lp-pipeline-cmd">$ generate_answer</div>
            <div className="mono lp-pipeline-key">INPUT</div>
            <div className="mono lp-pipeline-val">Query + chunks</div>
            <div className="mono lp-pipeline-key">OUTPUT</div>
            <div className="mono lp-pipeline-val lp-pipeline-out">Cited answer<br />Streaming</div>
          </div>
        </div>
        <div className="lp-callout mono">
          Every observable step is visible. Nothing important happens behind a black box.
        </div>
      </div>

      {/* MODELS */}
      <div id="models" className="lp-section">
        <div className="lp-eyebrow mono">MODELS</div>
        <h2 className="lp-h2">Free models, real choice.</h2>
        <p className="lp-section-sub">
          Pick per conversation. Every model below is available at no cost.
        </p>
        <div className="lp-model-grid">
          {MODELS.map((m) => (
            <div className="lp-model-card" key={m.name}>
              <span className="mono lp-model-name">{m.name}</span>
              <span className="lp-model-provider">{m.provider}</span>
              <div className="lp-model-status">
                <span className="lp-live-dot lp-live-dot-sm" />
                <span className="mono">Available</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* KNOWLEDGE BASES */}
      <div id="kb" className="lp-section">
        <div className="lp-eyebrow mono">KNOWLEDGE BASES</div>
        <h2 className="lp-h2">Organize by source, not by mess.</h2>
        <p className="lp-section-sub">
          Create as many independent knowledge bases as you need — one per site,
          per project, or per client.
        </p>
        <div className="lp-kb-illustration">
          <div className="lp-kb-list-mock">
            <div className="lp-kb-item-mock active">
              <span className="lp-live-dot lp-live-dot-sm" />
              Product Docs
            </div>
            <div className="lp-kb-item-mock">
              <span className="lp-dot-idle" />
              Internal Wiki
            </div>
            <div className="lp-kb-item-mock">
              <span className="lp-dot-idle" />
              Marketing Site
            </div>
            <div className="lp-kb-item-mock lp-kb-new">+ New Knowledge Base</div>
          </div>
          <div className="lp-kb-detail-mock">
            <div className="lp-kb-detail-head">
              <span className="lp-kb-detail-title">Product Docs</span>
              <span className="lp-pill mono">ACTIVE</span>
            </div>
            <div className="lp-kb-stats">
              <div><div className="mono lp-kb-stat-key">PAGES</div><div className="mono lp-kb-stat-val">240</div></div>
              <div><div className="mono lp-kb-stat-key">CHUNKS</div><div className="mono lp-kb-stat-val">3,482</div></div>
              <div><div className="mono lp-kb-stat-key">STATUS</div><div className="mono lp-kb-stat-val">Ready</div></div>
            </div>
          </div>
        </div>
      </div>

      {/* CLOSING CTA */}
      <div className="lp-closing">
        <h2 className="lp-h1 lp-closing-h1">
          Your data.<br />Your knowledge.<br />Your agent.
        </h2>
        <p className="lp-section-sub">Crawl it. Index it. Ask anything.</p>
        <button className="lp-btn-primary lp-closing-btn" onClick={onGetStarted}>Get Started →</button>
      </div>

      <div className="lp-footer">
        <span className="mono">crawlmind</span>
        <span className="mono lp-footer-note">Standard Mode default · Agent Mode optional</span>
      </div>
    </div>
  );
}
