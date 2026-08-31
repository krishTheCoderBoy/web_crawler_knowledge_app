"""Minimal OAuth 2.0 authorization-code flow for GitHub (and Google, once
credentials are configured). No third-party OAuth library — just two HTTP
calls per provider: exchange the code for a token, then fetch the profile.
"""

import secrets
from typing import Optional
from urllib.parse import urlencode

import requests

from settings import settings

# In-memory CSRF state store: state -> True. Login attempts expire naturally
# since a server restart clears them and each is consumed exactly once.
_pending_states: set[str] = set()


def new_state() -> str:
    state = secrets.token_urlsafe(24)
    _pending_states.add(state)
    return state


def consume_state(state: str) -> bool:
    if state in _pending_states:
        _pending_states.discard(state)
        return True
    return False


# ── GitHub ──────────────────────────────────────────────────────────────────

def github_authorize_url() -> str:
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        "scope": "read:user user:email",
        "state": new_state(),
    }
    return f"https://github.com/login/oauth/authorize?{urlencode(params)}"


def github_exchange_code(code: str) -> Optional[dict]:
    """Returns the GitHub profile dict {id, login, name, email, avatar_url}
    or None if the exchange/profile fetch failed."""
    token_resp = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        },
        timeout=10,
    )
    if not token_resp.ok:
        return None
    access_token = token_resp.json().get("access_token")
    if not access_token:
        return None

    profile_resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    )
    if not profile_resp.ok:
        return None
    profile = profile_resp.json()

    email = profile.get("email")
    if not email:
        # Primary email is often private — GitHub requires a separate call for it.
        emails_resp = requests.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if emails_resp.ok:
            emails = emails_resp.json()
            primary = next((e for e in emails if e.get("primary")), None)
            email = (primary or (emails[0] if emails else {})).get("email")

    return {
        "id": str(profile.get("id")),
        "login": profile.get("login") or "",
        "name": profile.get("name") or profile.get("login") or "",
        "email": email or "",
        "avatar_url": profile.get("avatar_url") or "",
    }


# ── Google ──────────────────────────────────────────────────────────────────

def google_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def google_authorize_url() -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": new_state(),
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def google_exchange_code(code: str) -> Optional[dict]:
    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    if not token_resp.ok:
        return None
    access_token = token_resp.json().get("access_token")
    if not access_token:
        return None

    profile_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if not profile_resp.ok:
        return None
    profile = profile_resp.json()

    return {
        "id": profile.get("sub") or "",
        "login": (profile.get("email") or "").split("@")[0],
        "name": profile.get("name") or "",
        "email": profile.get("email") or "",
        "avatar_url": profile.get("picture") or "",
    }
