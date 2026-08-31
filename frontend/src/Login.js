import React, { useEffect, useState } from "react";
import "./Login.css";

const API = "http://127.0.0.1:8000";

function GitHubIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 .5C5.73.5.5 5.73.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55v-2.15c-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.76 2.7 1.25 3.36.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.64 1.59.24 2.76.12 3.05.74.81 1.19 1.84 1.19 3.1 0 4.41-2.7 5.38-5.27 5.67.42.36.78 1.07.78 2.16v3.2c0 .3.21.66.79.55A10.52 10.52 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5z" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.25 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.85A11 11 0 0 0 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.43.34-2.09V7.06H2.18A11 11 0 0 0 1 12c0 1.77.43 3.45 1.18 4.94z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1a11 11 0 0 0-9.82 6.06l3.66 2.85c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
  );
}

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

// ── OAuth buttons ──────────────────────────────────────────────────────────
function OAuthButtons({ providers }) {
  if (!providers || (!providers.github && !providers.google)) return null;
  return (
    <div className="oauth-buttons">
      {providers.github && (
        <button
          type="button"
          className="oauth-btn"
          onClick={() => { window.location.href = `${API}/auth/github/login`; }}
        >
          <GitHubIcon />
          Continue with GitHub
        </button>
      )}
      {providers.google && (
        <button
          type="button"
          className="oauth-btn"
          onClick={() => { window.location.href = `${API}/auth/google/login`; }}
        >
          <GoogleIcon />
          Continue with Google
        </button>
      )}
      <div className="oauth-divider"><span>or</span></div>
    </div>
  );
}

// ── Root export ────────────────────────────────────────────────────────────
export default function Login({ onLogin }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [providers, setProviders] = useState(null);
  const [oauthError, setOauthError] = useState("");

  useEffect(() => {
    fetch(`${API}/auth/providers`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setProviders)
      .catch(() => setProviders(null));

    // Surface an OAuth failure redirected back with ?oauth_error=...
    const params = new URLSearchParams(window.location.search);
    const err = params.get("oauth_error");
    if (err) {
      setOauthError(
        err === "access_denied"
          ? "Sign-in was cancelled."
          : "GitHub/Google sign-in failed. Please try again or use your password."
      );
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

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

        {oauthError && <div className="login-error" role="alert"><ErrorIcon />{oauthError}</div>}

        <OAuthButtons providers={providers} />

        {mode === "login" ? (
          <LoginForm onLogin={onLogin} onSwitch={() => setMode("register")} />
        ) : (
          <RegisterForm onLogin={onLogin} onSwitch={() => setMode("login")} />
        )}
      </div>
    </div>
  );
}
