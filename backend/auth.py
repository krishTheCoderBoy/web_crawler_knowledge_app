import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from database import (
    create_session,
    create_user,
    get_user,
    init_db,
    touch_session,
    update_user_password,
)
from settings import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# init_db() is idempotent (CREATE TABLE IF NOT EXISTS) — safe to call here too,
# since this module's bootstrap check below needs the users table to exist
# regardless of whether main.py has called init_db() yet at import time.
init_db()

# Bootstrap a default admin account on first run, matching the previous
# in-memory default so existing dev workflows ("admin"/"admin123") keep working.
if get_user("admin") is None:
    try:
        create_user("admin", pwd_context.hash("admin123"), "Administrator")
    except ValueError:
        pass


class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    full_name: str


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def authenticate_user(username: str, password: str) -> dict | None:
    user = get_user(username.strip().lower())
    if not user or not user["hashed_password"]:
        # No local password set (e.g. an OAuth-only account) — password login is unavailable.
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def register_user(username: str, password: str, full_name: str) -> dict:
    username = username.strip().lower()
    if not username or not password or not full_name.strip():
        raise ValueError("All fields are required")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    return create_user(username, pwd_context.hash(password), full_name.strip())


def change_password(username: str, current_password: str, new_password: str) -> None:
    user = get_user(username)
    if not user:
        raise ValueError("User not found")
    if not user["hashed_password"]:
        raise ValueError(
            "This account signed up with GitHub/Google and has no password to change. "
            "Set one by using 'Forgot password' — coming soon."
        )
    if not verify_password(current_password, user["hashed_password"]):
        raise ValueError("Current password is incorrect")
    if len(new_password) < 6:
        raise ValueError("New password must be at least 6 characters")
    update_user_password(username, pwd_context.hash(new_password))


def create_access_token(data: dict, session_id: Optional[str] = None) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["sid"] = session_id or str(uuid.uuid4())
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def issue_token_for(username: str, user_agent: str = "") -> str:
    session_id = str(uuid.uuid4())
    create_session(session_id, username, user_agent)
    return create_access_token({"sub": username}, session_id=session_id)


async def get_current_user(
    header_token: Optional[str] = Depends(oauth2_scheme),
    query_token: Optional[str] = Query(None, alias="token"),
) -> dict:
    """Accepts Bearer token from Authorization header OR ?token= query param.
    The query param variant is required for EventSource (browser SSE) which
    cannot set custom headers."""
    raw = header_token or query_token
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(raw, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        session_id: str = payload.get("sid", "")
        if not username:
            raise ValueError("empty sub")
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if session_id and not touch_session(session_id):
        # Session row is gone — it was revoked from the Active Sessions list.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = dict(user)
    user["session_id"] = session_id
    return user
