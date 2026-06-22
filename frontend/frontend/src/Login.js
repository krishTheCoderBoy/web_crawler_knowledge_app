import React, { useState } from "react";
import "./Login.css";

const API = "http://127.0.0.1:8000";

// ── Shared logo ────────────────────────────────────────────────────────────
function Logo() {
  return (
    <div className="login-logo">
      <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
        <rect width="36" height="36" rx="11" fill="#4f46e5" />
        <path
          d="M9 18c0-5 4-9 9-9s9 4 9 9-4 9-9 9"
          stroke="#fff"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle cx="18" cy="18" r="3.5" fill="#fff" />
      </svg>
    </div>
  );
}

// ── Login form ─────────────────────────────────────────────────────────────
function LoginForm({ onLogin, onSwitch }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setError("");
    setLoading(true);
    try {
      const body = new URLSearchParams();
      body.append("username", username.trim());
      body.append("password", password);
      const res = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Login failed");
      localStorage.setItem("token", data.access_token);
      localStorage.setItem("username", data.username);
      localStorage.setItem("full_name", data.full_name || data.username);
      onLogin(data.access_token, data.username, data.full_name || data.username);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="login-brand">
        <Logo />
        <h1 className="login-title">Welcome back</h1>
        <p className="login-subtitle">Sign in to your workspace</p>
      </div>

      <form onSubmit={handleSubmit} className="login-form" noValidate>
        <div className="login-field">
          <label htmlFor="li-username">Username</label>
          <input
            id="li-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Enter your username"
            autoComplete="username"
            autoFocus
          />
        </div>

        <div className="login-field">
          <label htmlFor="li-password">Password</label>
          <div className="password-wrap">
            <input
              id="li-password"
              type={showPw ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
            />
            <button type="button" className="pw-toggle" onClick={() => setShowPw((v) => !v)}>
              {showPw ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        {error && <div className="login-error" role="alert"><ErrorIcon />{error}</div>}

        <button
          type="submit"
          className="login-submit"
          disabled={loading || !username.trim() || !password}
        >
          {loading ? <span className="login-spinner" /> : "Sign in"}
        </button>
      </form>

      <p className="login-hint">
        Default: <strong>admin</strong> / <strong>admin123</strong>
      </p>
      <p className="login-switch">
        Don't have an account?{" "}
        <button type="button" className="switch-link" onClick={onSwitch}>
          Create one
        </button>
      </p>
    </>
  );
}

// ── Register form ──────────────────────────────────────────────────────────
function RegisterForm({ onLogin, onSwitch }) {
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!fullName.trim() || !username.trim() || !password) return;
    if (password !== confirm) { setError("Passwords do not match"); return; }
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName.trim(),
          username: username.trim(),
          password,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Registration failed");
      localStorage.setItem("token", data.access_token);
      localStorage.setItem("username", data.username);
      localStorage.setItem("full_name", data.full_name || data.username);
      onLogin(data.access_token, data.username, data.full_name || data.username);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="login-brand">
        <Logo />
        <h1 className="login-title">Create account</h1>
        <p className="login-subtitle">Join your RAG workspace</p>
      </div>

      <form onSubmit={handleSubmit} className="login-form" noValidate>
        <div className="login-field">
          <label htmlFor="rg-fullname">Full name</label>
          <input
            id="rg-fullname"
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Your full name"
            autoComplete="name"
            autoFocus
          />
        </div>

        <div className="login-field">
          <label htmlFor="rg-username">Username</label>
          <input
            id="rg-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Choose a username (min 3 chars)"
            autoComplete="username"
          />
        </div>

        <div className="login-field">
          <label htmlFor="rg-password">Password</label>
          <div className="password-wrap">
            <input
              id="rg-password"
              type={showPw ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min 6 characters"
              autoComplete="new-password"
            />
            <button type="button" className="pw-toggle" onClick={() => setShowPw((v) => !v)}>
              {showPw ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        <div className="login-field">
          <label htmlFor="rg-confirm">Confirm password</label>
          <input
            id="rg-confirm"
            type={showPw ? "text" : "password"}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Repeat your password"
            autoComplete="new-password"
          />
        </div>

        {error && <div className="login-error" role="alert"><ErrorIcon />{error}</div>}

        <button
          type="submit"
          className="login-submit"
          disabled={loading || !fullName.trim() || !username.trim() || !password || !confirm}
        >
          {loading ? <span className="login-spinner" /> : "Create account"}
        </button>
      </form>

      <p className="login-switch">
        Already have an account?{" "}
        <button type="button" className="switch-link" onClick={onSwitch}>
          Sign in
        </button>
      </p>
    </>
  );
}

// ── Shared error icon ──────────────────────────────────────────────────────
function ErrorIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <circle cx="8" cy="8" r="7" stroke="#dc2626" strokeWidth="1.5" />
      <path d="M8 5v3.5M8 11h.01" stroke="#dc2626" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

// ── Root export ────────────────────────────────────────────────────────────
export default function Login({ onLogin }) {
  const [mode, setMode] = useState("login"); // "login" | "register"

  return (
    <div className="login-shell">
      <div className="login-bg-orb orb-1" />
      <div className="login-bg-orb orb-2" />

      <div className={`login-card ${mode === "register" ? "login-card--tall" : ""}`}>
        {/* Tab switcher */}
        <div className="login-tabs">
          <button
            className={`login-tab ${mode === "login" ? "active" : ""}`}
            onClick={() => setMode("login")}
          >
            Sign in
          </button>
          <button
            className={`login-tab ${mode === "register" ? "active" : ""}`}
            onClick={() => setMode("register")}
          >
            Register
          </button>
        </div>

        {mode === "login" ? (
          <LoginForm onLogin={onLogin} onSwitch={() => setMode("register")} />
        ) : (
          <RegisterForm onLogin={onLogin} onSwitch={() => setMode("login")} />
        )}
      </div>
    </div>
  );
}
