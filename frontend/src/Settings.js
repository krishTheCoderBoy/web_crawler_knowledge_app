import React, { useEffect, useState } from "react";
import "./Settings.css";

const API = "http://127.0.0.1:8000";

const MODEL_OPTIONS = [
  { id: "openrouter/free", label: "Auto (any available free model)", provider: "OpenRouter" },
  { id: "nvidia/nemotron-3-ultra-550b-a55b:free", label: "Nemotron 3 Ultra 550B", provider: "NVIDIA" },
  { id: "poolside/laguna-s-2.1:free", label: "Laguna S 2.1", provider: "Poolside" },
  { id: "dots-studio/dots-3-note-preview:free", label: "Dots 3 Note Preview", provider: "Dots Studio" },
];

const NAV_SECTIONS = [
  { id: "profile", label: "Profile" },
  { id: "appearance", label: "Appearance" },
  { id: "ai", label: "AI Preferences" },
  { id: "api-keys", label: "API Keys" },
  { id: "security", label: "Security" },
  { id: "danger", label: "Danger Zone" },
];

const PROVIDER_LABELS = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
  google: "Google",
};

function Toggle({ checked, onChange }) {
  return (
    <button
      type="button"
      className={`settings-toggle ${checked ? "on" : ""}`}
      onClick={() => onChange(!checked)}
      role="switch"
      aria-checked={checked}
    >
      <span className="settings-toggle-dot" />
    </button>
  );
}

function relativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso.replace(" ", "T") + "Z").getTime();
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

export default function Settings({
  fullName,
  username,
  theme,
  onThemeChange,
  onBackToChat,
  onLogout,
  token,
  selectedModel,
  onModelChange,
}) {
  const [active, setActive] = useState("profile");

  const authedFetch = (path, options = {}) =>
    fetch(`${API}${path}`, {
      ...options,
      headers: { ...options.headers, Authorization: `Bearer ${token}` },
    });

  // ── AI preferences (local, no backend endpoint for user prefs) ──────────
  const [defaultModel, setDefaultModel] = useState(
    () => selectedModel || localStorage.getItem("pref_default_model") || MODEL_OPTIONS[0].id
  );
  const [defaultMode, setDefaultMode] = useState(
    () => localStorage.getItem("pref_default_mode") || "standard"
  );
  const [showCitations, setShowCitations] = useState(
    () => localStorage.getItem("pref_show_citations") !== "false"
  );
  const [showAgentTrace, setShowAgentTrace] = useState(
    () => localStorage.getItem("pref_show_agent_trace") !== "false"
  );

  const persistModel = (id) => {
    setDefaultModel(id);
    localStorage.setItem("pref_default_model", id);
    onModelChange(id);
  };
  const persistMode = (mode) => {
    setDefaultMode(mode);
    localStorage.setItem("pref_default_mode", mode);
  };
  const persistCitations = (val) => {
    setShowCitations(val);
    localStorage.setItem("pref_show_citations", String(val));
  };
  const persistAgentTrace = (val) => {
    setShowAgentTrace(val);
    localStorage.setItem("pref_show_agent_trace", String(val));
  };

  // ── Profile / connected accounts ────────────────────────────────────────
  const [me, setMe] = useState(null);

  useEffect(() => {
    if (active !== "profile") return;
    authedFetch("/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── API keys ──────────────────────────────────────────────────────────
  const [apiKeys, setApiKeys] = useState([]);
  const [apiKeysLoading, setApiKeysLoading] = useState(true);
  const [editingProvider, setEditingProvider] = useState(null);
  const [keyInput, setKeyInput] = useState("");
  const [apiKeyError, setApiKeyError] = useState("");
  const [apiKeyBusy, setApiKeyBusy] = useState(false);

  const loadApiKeys = () => {
    setApiKeysLoading(true);
    authedFetch("/api-keys")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setApiKeys(data))
      .catch(() => setApiKeys([]))
      .finally(() => setApiKeysLoading(false));
  };

  useEffect(() => {
    if (active === "api-keys") loadApiKeys();
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveApiKey = async (provider) => {
    if (!keyInput.trim()) return;
    setApiKeyBusy(true);
    setApiKeyError("");
    try {
      const res = await authedFetch("/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: keyInput.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to save key");
      setEditingProvider(null);
      setKeyInput("");
      loadApiKeys();
    } catch (err) {
      setApiKeyError(err.message);
    } finally {
      setApiKeyBusy(false);
    }
  };

  const removeApiKey = async (provider) => {
    if (!window.confirm(`Remove your ${PROVIDER_LABELS[provider]} API key?`)) return;
    try {
      await authedFetch(`/api-keys/${provider}`, { method: "DELETE" });
      loadApiKeys();
    } catch {
      setApiKeyError("Failed to remove key.");
    }
  };

  // ── Security: change password ────────────────────────────────────────
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwError, setPwError] = useState("");
  const [pwSuccess, setPwSuccess] = useState("");
  const [pwBusy, setPwBusy] = useState(false);

  const submitPasswordChange = async (e) => {
    e.preventDefault();
    setPwError("");
    setPwSuccess("");
    if (newPw !== confirmPw) {
      setPwError("New passwords do not match.");
      return;
    }
    setPwBusy(true);
    try {
      const res = await authedFetch("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to change password");
      setPwSuccess("Password updated.");
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (err) {
      setPwError(err.message);
    } finally {
      setPwBusy(false);
    }
  };

  // ── Security: sessions ───────────────────────────────────────────────
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);

  const loadSessions = () => {
    setSessionsLoading(true);
    authedFetch("/auth/sessions")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setSessions(data))
      .catch(() => setSessions([]))
      .finally(() => setSessionsLoading(false));
  };

  useEffect(() => {
    if (active === "security") loadSessions();
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  const revokeSession = async (id) => {
    try {
      await authedFetch(`/auth/sessions/${id}`, { method: "DELETE" });
      loadSessions();
    } catch {}
  };

  // ── Danger zone: delete account ──────────────────────────────────────
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const isAdmin = username === "admin";

  const submitDeleteAccount = async () => {
    if (deleteConfirm !== "DELETE") return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      const res = await authedFetch("/auth/account", { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to delete account");
      onLogout();
    } catch (err) {
      setDeleteError(err.message);
      setDeleteBusy(false);
    }
  };

  const initial = (fullName || username || "?").trim().charAt(0).toUpperCase();

  return (
    <div className="settings-overlay">
      <div className="settings-shell">
        <aside className="settings-nav">
          <div className="settings-nav-header">
            <span className="settings-logo-mark" />
            <span>crawlmind</span>
          </div>
          <button className="settings-back-to-chat" onClick={onBackToChat}>
            ← Back to Chat
          </button>
          {NAV_SECTIONS.map((s) => (
            <button
              key={s.id}
              className={`settings-nav-item ${active === s.id ? "active" : ""} ${
                s.id === "danger" ? "danger" : ""
              }`}
              onClick={() => setActive(s.id)}
            >
              {s.label}
            </button>
          ))}
          <div className="settings-nav-spacer" />
        </aside>

        <div className="settings-content">
          <h1>Settings</h1>

          {active === "profile" && (
            <section className="settings-section">
              <div className="settings-eyebrow">PROFILE</div>
              <div className="settings-card">
                <div className="settings-row">
                  <div className="settings-profile-id">
                    <div className="settings-avatar">{initial}</div>
                    <div>
                      <div className="settings-name">{fullName || username}</div>
                      <div className="settings-sub mono">{username}</div>
                    </div>
                  </div>
                </div>
                <div className="settings-row">
                  <span>GitHub</span>
                  {me?.oauth_provider === "github" ? (
                    <span className="settings-sub mono">Connected</span>
                  ) : (
                    <span className="settings-sub">Not connected</span>
                  )}
                </div>
                <div className="settings-row">
                  <span>Google</span>
                  {me?.oauth_provider === "google" ? (
                    <span className="settings-sub mono">Connected</span>
                  ) : (
                    <span className="settings-sub">Not connected</span>
                  )}
                </div>
              </div>
            </section>
          )}

          {active === "appearance" && (
            <section className="settings-section">
              <div className="settings-eyebrow">APPEARANCE</div>
              <div className="settings-card settings-card-pad">
                <div className="settings-field-label">Theme</div>
                <div className="settings-choice-row">
                  <button
                    className={`settings-choice ${theme === "light" ? "active" : ""}`}
                    onClick={() => onThemeChange("light")}
                  >
                    Light
                  </button>
                  <button
                    className={`settings-choice ${theme === "dark" ? "active" : ""}`}
                    onClick={() => onThemeChange("dark")}
                  >
                    Dark
                  </button>
                </div>
                <p className="settings-hint">
                  Dark mode uses a terminal-inspired green accent. Light mode uses a
                  warmer, softer palette — not just an inverted dark theme.
                </p>
              </div>
            </section>
          )}

          {active === "ai" && (
            <section className="settings-section">
              <div className="settings-eyebrow">AI EXPERIENCE</div>
              <div className="settings-card">
                <div className="settings-row">
                  <span>Default model</span>
                  <select
                    className="settings-select"
                    value={defaultModel}
                    onChange={(e) => persistModel(e.target.value)}
                  >
                    {MODEL_OPTIONS.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label} · {m.provider}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="settings-row">
                  <span>Default chat mode</span>
                  <select
                    className="settings-select"
                    value={defaultMode}
                    onChange={(e) => persistMode(e.target.value)}
                  >
                    <option value="standard">Standard</option>
                    <option value="agent">Agent Mode</option>
                  </select>
                </div>
                <div className="settings-row">
                  <span>Show citations</span>
                  <Toggle checked={showCitations} onChange={persistCitations} />
                </div>
                <div className="settings-row">
                  <span>Show Agent Mode trace</span>
                  <Toggle checked={showAgentTrace} onChange={persistAgentTrace} />
                </div>
              </div>
              <p className="settings-hint">
                Standard Mode is recommended for most questions. Agent Mode exposes
                tool calls and retrieval steps for advanced inspection.
              </p>
            </section>
          )}

          {active === "api-keys" && (
            <section className="settings-section">
              <div className="settings-eyebrow">API KEYS</div>
              <div className="settings-card">
                {apiKeysLoading ? (
                  <div className="settings-row">
                    <span className="settings-sub">Loading…</span>
                  </div>
                ) : (
                  apiKeys.map((k) => (
                    <div className="settings-row settings-row-wrap" key={k.provider}>
                      <span>{PROVIDER_LABELS[k.provider] || k.provider}</span>

                      {editingProvider === k.provider ? (
                        <div className="settings-key-edit">
                          <input
                            className="settings-input settings-input-inline"
                            type="password"
                            placeholder="Paste API key"
                            value={keyInput}
                            onChange={(e) => setKeyInput(e.target.value)}
                            autoFocus
                          />
                          <button
                            className="settings-btn-ghost"
                            disabled={apiKeyBusy || !keyInput.trim()}
                            onClick={() => saveApiKey(k.provider)}
                          >
                            {apiKeyBusy ? "Saving…" : "Save"}
                          </button>
                          <button
                            className="settings-btn-ghost"
                            onClick={() => { setEditingProvider(null); setKeyInput(""); setApiKeyError(""); }}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : k.configured ? (
                        <div className="settings-key-edit">
                          <span className="settings-sub mono">••••••••••••{k.last4}</span>
                          <button
                            className="settings-btn-ghost"
                            onClick={() => { setEditingProvider(k.provider); setKeyInput(""); }}
                          >
                            Edit
                          </button>
                          <button
                            className="settings-btn-ghost"
                            onClick={() => removeApiKey(k.provider)}
                          >
                            Remove
                          </button>
                        </div>
                      ) : (
                        <div className="settings-key-edit">
                          <span className="settings-sub">Not configured</span>
                          <button
                            className="settings-btn-ghost"
                            onClick={() => { setEditingProvider(k.provider); setKeyInput(""); }}
                          >
                            Add API Key
                          </button>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
              {apiKeyError && <div className="settings-error">{apiKeyError}</div>}
              <p className="settings-hint">
                Keys are encrypted at rest and never shown in full again after saving.
                Bringing your own key lets you use paid models beyond Crawlmind's free tier.
              </p>
            </section>
          )}

          {active === "security" && (
            <section className="settings-section">
              <div className="settings-eyebrow">CHANGE PASSWORD</div>
              <form className="settings-card settings-card-pad" onSubmit={submitPasswordChange}>
                <label className="settings-field-label">Current password</label>
                <input
                  className="settings-input"
                  type="password"
                  value={currentPw}
                  onChange={(e) => setCurrentPw(e.target.value)}
                  autoComplete="current-password"
                />
                <label className="settings-field-label">New password</label>
                <input
                  className="settings-input"
                  type="password"
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  autoComplete="new-password"
                />
                <label className="settings-field-label">Confirm new password</label>
                <input
                  className="settings-input"
                  type="password"
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  autoComplete="new-password"
                />
                {pwError && <div className="settings-error">{pwError}</div>}
                {pwSuccess && <div className="settings-success">{pwSuccess}</div>}
                <button
                  type="submit"
                  className="settings-btn-ghost"
                  disabled={pwBusy || !currentPw || !newPw || !confirmPw}
                >
                  {pwBusy ? "Updating…" : "Update password"}
                </button>
              </form>

              <div className="settings-eyebrow" style={{ marginTop: 26 }}>ACTIVE SESSIONS</div>
              <div className="settings-card">
                {sessionsLoading ? (
                  <div className="settings-row"><span className="settings-sub">Loading…</span></div>
                ) : sessions.length === 0 ? (
                  <div className="settings-row"><span className="settings-sub">No active sessions.</span></div>
                ) : (
                  sessions.map((s) => (
                    <div className="settings-row" key={s.id}>
                      <div>
                        <div style={{ fontSize: 13.5 }}>
                          {s.user_agent || "Unknown device"}
                          {s.is_current && <span className="coming-soon-badge" style={{ marginLeft: 8 }}>This device</span>}
                        </div>
                        <div className="settings-sub mono">Last active {relativeTime(s.last_seen_at)}</div>
                      </div>
                      {!s.is_current && (
                        <button className="settings-btn-ghost" onClick={() => revokeSession(s.id)}>
                          Revoke
                        </button>
                      )}
                    </div>
                  ))
                )}
                <div className="settings-row">
                  <span>Sign out of this device</span>
                  <button className="settings-btn-ghost" onClick={onLogout}>
                    Log out
                  </button>
                </div>
              </div>
            </section>
          )}

          {active === "danger" && (
            <section className="settings-section">
              <div className="settings-eyebrow danger">DANGER ZONE</div>
              <div className="settings-card settings-card-danger">
                <div className="settings-name">Delete account</div>
                <p className="settings-hint" style={{ margin: "6px 0 16px" }}>
                  Permanently delete your Crawlmind account, knowledge bases, and
                  conversations. This action cannot be undone.
                </p>
                {isAdmin ? (
                  <div className="settings-danger-note">
                    The default admin account can't be deleted.
                  </div>
                ) : (
                  <>
                    {deleteError && <div className="settings-error">{deleteError}</div>}
                    <input
                      className="settings-input"
                      placeholder='Type "DELETE" to confirm'
                      value={deleteConfirm}
                      onChange={(e) => setDeleteConfirm(e.target.value)}
                    />
                    <button
                      className="settings-btn-danger"
                      disabled={deleteConfirm !== "DELETE" || deleteBusy}
                      onClick={submitDeleteAccount}
                    >
                      {deleteBusy ? "Deleting…" : "Permanently Delete Account"}
                    </button>
                  </>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
