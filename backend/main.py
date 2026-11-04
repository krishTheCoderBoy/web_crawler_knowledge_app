import asyncio
import json
import queue
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from agent import AgentChatSession
from auth import (
    Token,
    authenticate_user,
    change_password as auth_change_password,
    get_current_user,
    issue_token_for,
    register_user,
)
from crawler import run_crawler
from crypto import encrypt_secret
from database import (
    create_kb,
    create_chat_conversation,
    create_oauth_user,
    delete_api_key,
    delete_kb_record,
    delete_user,
    ensure_default_kb,
    get_doc_stats,
    get_chat_conversation,
    get_kb,
    get_user,
    get_user_by_oauth,
    init_db,
    list_api_keys,
    list_chat_conversations,
    list_kbs,
    list_sessions,
    record_index,
    revoke_session,
    upsert_api_key,
    update_chat_conversation,
)
from oauth import (
    consume_state,
    github_authorize_url,
    github_exchange_code,
    google_authorize_url,
    google_configured,
    google_exchange_code,
)
from rag import get_manager
from settings import settings

API_KEY_PROVIDERS = ["openai", "anthropic", "openrouter", "google"]

# ── App setup ─────────────────────────────────────────────────────────────

app = FastAPI(title="Crawler RAG API", version="3.0.0")
_executor = ThreadPoolExecutor(max_workers=4)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialise the SQLite metadata DB on startup
init_db()

# In-memory crawl job store  {job_id -> progress/result dict}
_crawl_jobs: dict[str, dict] = {}


# ── Request / Response models ─────────────────────────────────────────────

class CrawlStartRequest(BaseModel):
    url: str
    max_pages: int = 200


class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ApiKeyRequest(BaseModel):
    provider: str
    api_key: str


class KBCreateRequest(BaseModel):
    name: str


class IndexRequest(BaseModel):
    pages: list[dict] = Field(default_factory=list)
    source_url: Optional[str] = None
    # New: numeric KB id (preferred)
    knowledge_base_id: Optional[int] = None
    # Legacy: collection name — kept for backward compat
    kb_name: str = "default"


class ChatRequest(BaseModel):
    question: str
    chat_history: list[dict] = Field(default_factory=list)
    model_id: Optional[str] = None
    # New: numeric KB id (preferred)
    knowledge_base_id: Optional[int] = None
    # Legacy
    kb_name: str = "default"


class ChatConversationRequest(BaseModel):
    messages: list[dict] = Field(default_factory=list)


# ── Auth ──────────────────────────────────────────────────────────────────

@app.post("/auth/register", response_model=Token, status_code=201)
async def register(req: RegisterRequest, user_agent: str = Header(default="")):
    try:
        user = register_user(req.username, req.password, req.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = issue_token_for(user["username"], user_agent)
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "full_name": user["full_name"],
    }


@app.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), user_agent: str = Header(default="")):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = issue_token_for(user["username"], user_agent)
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "full_name": user.get("full_name", user["username"]),
    }


@app.post("/auth/change-password")
async def change_password_route(
    req: ChangePasswordRequest, current_user: dict = Depends(get_current_user)
):
    try:
        auth_change_password(current_user["username"], req.current_password, req.new_password)
        return {"message": "Password updated."}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/auth/sessions")
async def get_sessions(current_user: dict = Depends(get_current_user)):
    sessions = list_sessions(current_user["username"])
    return [
        {**s, "is_current": s["id"] == current_user.get("session_id")}
        for s in sessions
    ]


@app.delete("/auth/sessions/{session_id}")
async def revoke_session_route(session_id: str, current_user: dict = Depends(get_current_user)):
    if session_id == current_user.get("session_id"):
        raise HTTPException(status_code=400, detail="Cannot revoke your current session — sign out instead.")
    ok = revoke_session(session_id, current_user["username"])
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"revoked": session_id}


@app.delete("/auth/account")
async def delete_account(current_user: dict = Depends(get_current_user)):
    user_id = current_user["username"]
    if user_id == "admin":
        raise HTTPException(status_code=400, detail="The default admin account cannot be deleted.")
    # Best-effort purge of vector data for each of the user's knowledge bases
    for kb in list_kbs(user_id):
        try:
            get_manager().delete_kb(kb["collection"])
        except Exception:
            pass
    delete_user(user_id)
    return {"deleted": user_id}


# ── User API keys (bring-your-own-provider-key) ────────────────────────────

@app.get("/api-keys")
async def get_api_keys(current_user: dict = Depends(get_current_user)):
    stored = {row["provider"]: row for row in list_api_keys(current_user["username"])}
    return [
        {
            "provider": p,
            "configured": p in stored,
            "last4": stored[p]["last4"] if p in stored else None,
            "updated_at": stored[p]["created_at"] if p in stored else None,
        }
        for p in API_KEY_PROVIDERS
    ]


@app.post("/api-keys", status_code=201)
async def set_api_key(req: ApiKeyRequest, current_user: dict = Depends(get_current_user)):
    provider = req.provider.strip().lower()
    if provider not in API_KEY_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    last4 = key[-4:] if len(key) >= 4 else key
    upsert_api_key(current_user["username"], provider, encrypt_secret(key), last4)
    return {"provider": provider, "configured": True, "last4": last4}


@app.delete("/api-keys/{provider}")
async def remove_api_key(provider: str, current_user: dict = Depends(get_current_user)):
    ok = delete_api_key(current_user["username"], provider.strip().lower())
    if not ok:
        raise HTTPException(status_code=404, detail="No key stored for this provider")
    return {"deleted": provider}


# ── OAuth (GitHub / Google) ─────────────────────────────────────────────────

def _find_or_create_oauth_user(provider: str, profile: dict) -> dict:
    """profile: {id, login, name, email, avatar_url}. Links to an existing
    account with the same provider+id, otherwise creates a new one, picking
    a free username derived from the provider login/email."""
    existing = get_user_by_oauth(provider, profile["id"])
    if existing:
        return existing

    base = (profile.get("login") or profile.get("email", "").split("@")[0] or provider).strip().lower()
    base = "".join(c for c in base if c.isalnum() or c in "_-") or provider
    username = base
    suffix = 1
    while get_user(username) is not None:
        suffix += 1
        username = f"{base}{suffix}"

    return create_oauth_user(
        username=username,
        full_name=profile.get("name") or profile.get("login") or username,
        provider=provider,
        oauth_id=profile["id"],
        avatar_url=profile.get("avatar_url", ""),
    )


@app.get("/auth/github/login")
async def github_login():
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub sign-in is not configured.")
    return RedirectResponse(github_authorize_url())


@app.get("/auth/github/callback")
async def github_callback(code: str = "", state: str = "", error: str = ""):
    frontend_login = f"{settings.FRONTEND_URL}/"
    if error:
        return RedirectResponse(f"{frontend_login}?oauth_error={error}")
    if not code or not state or not consume_state(state):
        return RedirectResponse(f"{frontend_login}?oauth_error=invalid_request")

    profile = github_exchange_code(code)
    if not profile or not profile.get("id"):
        return RedirectResponse(f"{frontend_login}?oauth_error=github_exchange_failed")

    user = _find_or_create_oauth_user("github", profile)
    token = issue_token_for(user["username"], "GitHub OAuth")
    return RedirectResponse(
        f"{frontend_login}?oauth_token={token}&username={user['username']}&full_name={user['full_name']}"
    )


@app.get("/auth/google/login")
async def google_login():
    if not google_configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")
    return RedirectResponse(google_authorize_url())


@app.get("/auth/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    frontend_login = f"{settings.FRONTEND_URL}/"
    if error:
        return RedirectResponse(f"{frontend_login}?oauth_error={error}")
    if not code or not state or not consume_state(state):
        return RedirectResponse(f"{frontend_login}?oauth_error=invalid_request")

    profile = google_exchange_code(code)
    if not profile or not profile.get("id"):
        return RedirectResponse(f"{frontend_login}?oauth_error=google_exchange_failed")

    user = _find_or_create_oauth_user("google", profile)
    token = issue_token_for(user["username"], "Google OAuth")
    return RedirectResponse(
        f"{frontend_login}?oauth_token={token}&username={user['username']}&full_name={user['full_name']}"
    )


@app.get("/auth/providers")
async def auth_providers():
    return {
        "github": bool(settings.GITHUB_CLIENT_ID),
        "google": google_configured(),
    }


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.get("/auth/me")
async def auth_me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user["username"],
        "full_name": current_user["full_name"],
        "oauth_provider": current_user.get("oauth_provider"),
        "avatar_url": current_user.get("avatar_url"),
        "has_password": bool(current_user.get("hashed_password")),
    }


@app.get("/models")
def models(_: dict = Depends(get_current_user)):
    return get_manager().get_available_models()


# ── Knowledge Base Management (new, ID-based) ─────────────────────────────

@app.get("/knowledge-bases")
def get_knowledge_bases(current_user: dict = Depends(get_current_user)):
    user_id = current_user["username"]
    ensure_default_kb(user_id)
    kbs = list_kbs(user_id)
    # Attach live ChromaDB chunk count to each KB
    mgr = get_manager()
    result = []
    for kb in kbs:
        try:
            status = mgr.get_status(kb["collection"])
            chunk_count = status.get("chunk_count", 0)
            is_ready = status.get("is_ready", False)
        except Exception:
            chunk_count = 0
            is_ready = False
        db_stats = get_doc_stats(kb["id"])
        result.append({
            **kb,
            "chunk_count": chunk_count,
            "is_ready": is_ready,
            "doc_count": db_stats["doc_count"],
            "total_pages": db_stats["total_pages"],
        })
    return result


@app.post("/knowledge-bases", status_code=201)
def create_knowledge_base(
    req: KBCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["username"]
    ensure_default_kb(user_id)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Knowledge base name cannot be empty")
    try:
        kb = create_kb(user_id, req.name)
        return kb
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.delete("/knowledge-bases/{kb_id}")
def delete_knowledge_base(
    kb_id: int,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["username"]
    try:
        collection = delete_kb_record(kb_id, user_id)
        # Also purge vectors from ChromaDB
        try:
            get_manager().delete_kb(collection)
        except Exception:
            pass  # ChromaDB collection may not exist yet — that's fine
        return {"deleted": kb_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/knowledge-bases/{kb_id}/status")
def knowledge_base_status(
    kb_id: int,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["username"]
    kb = get_kb(kb_id, user_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    try:
        status = get_manager().get_status(kb["collection"])
    except Exception:
        status = {"is_ready": False, "chunk_count": 0}
    db_stats = get_doc_stats(kb_id)
    return {
        **kb,
        **status,
        **db_stats,
    }


@app.get("/knowledge-bases/{kb_id}/chat-conversations")
def get_knowledge_base_chat_conversations(
    kb_id: int,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["username"]
    if not get_kb(kb_id, user_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return list_chat_conversations(user_id, kb_id)


@app.get("/knowledge-bases/{kb_id}/agent-questions")
def get_knowledge_base_agent_questions(
    kb_id: int,
    model_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    kb = get_kb(kb_id, current_user["username"])
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return {"questions": get_manager().generate_agent_questions(kb["collection"], model_id)}


@app.post("/knowledge-bases/{kb_id}/chat-conversations", status_code=201)
def create_knowledge_base_chat_conversation(
    kb_id: int,
    req: ChatConversationRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["username"]
    if not get_kb(kb_id, user_id):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    first_user_message = next(
        (message.get("text", "").strip() for message in req.messages if message.get("role") == "user"),
        "New conversation",
    )
    title = first_user_message[:77].rstrip()
    if len(first_user_message) > 80:
        title += "..."
    return create_chat_conversation(
        str(uuid.uuid4()), user_id, kb_id, title or "New conversation", req.messages
    )


@app.get("/chat-conversations/{conversation_id}")
def get_chat_conversation_route(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    conversation = get_chat_conversation(conversation_id, current_user["username"])
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.put("/chat-conversations/{conversation_id}")
def update_chat_conversation_route(
    conversation_id: str,
    req: ChatConversationRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["username"]
    if not update_chat_conversation(conversation_id, user_id, req.messages):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return get_chat_conversation(conversation_id, user_id)


# ── Crawling (async job-based with SSE progress) ──────────────────────────

def _run_crawl_job(job_id: str, start_url: str, max_pages: int) -> None:
    try:
        run_crawler(
            start_url,
            progress_store=_crawl_jobs,
            job_id=job_id,
            max_pages=max_pages,
        )
    except Exception as exc:
        _crawl_jobs[job_id] = {"status": "error", "message": str(exc)}


@app.post("/crawl/start")
async def crawl_start(req: CrawlStartRequest, _: dict = Depends(get_current_user)):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    job_id = str(uuid.uuid4())[:8]
    _crawl_jobs[job_id] = {
        "status": "starting", "crawled": 0,
        "max": req.max_pages, "total_pages": 0,
    }
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_crawl_job, job_id, url, req.max_pages)
    return {"job_id": job_id}


@app.get("/crawl/progress/{job_id}")
async def crawl_progress(job_id: str, _: dict = Depends(get_current_user)):
    async def generate():
        while True:
            job = _crawl_jobs.get(job_id)
            if not job:
                yield f"event: error\ndata: {json.dumps({'message': 'Job not found'})}\n\n"
                return
            yield f"event: progress\ndata: {json.dumps({k: v for k, v in job.items() if k != 'result'})}\n\n"
            if job.get("status") in ("done", "error"):
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/crawl/result/{job_id}")
def crawl_result(job_id: str, _: dict = Depends(get_current_user)):
    job = _crawl_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "error":
        raise HTTPException(status_code=500, detail=job.get("message", "Crawl failed"))
    if job.get("status") != "done":
        raise HTTPException(status_code=202, detail="Crawl still in progress")
    return job.get("result", {})


@app.get("/crawl")
def crawl_legacy(url: str, _: dict = Depends(get_current_user)):
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    return run_crawler(url.strip())


# ── Helper: resolve ChromaDB collection name ───────────────────────────────

def _resolve_collection(req_kb_id: Optional[int], req_kb_name: str, user_id: str) -> tuple[str, int]:
    """Return (collection_name, kb_id) for the request, creating default if needed."""
    if req_kb_id is not None:
        kb = get_kb(req_kb_id, user_id)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        return kb["collection"], kb["id"]

    # Legacy path: use kb_name or fall back to default
    ensure_default_kb(user_id)
    kbs = list_kbs(user_id)
    if req_kb_name and req_kb_name != "default":
        # Try to find a KB whose collection matches the legacy name
        match = next((k for k in kbs if k["collection"] == req_kb_name), None)
        if match:
            return match["collection"], match["id"]
        # Otherwise use the literal name (old ChromaDB collection)
        default_kb = next(k for k in kbs if k["is_default"])
        return req_kb_name, default_kb["id"]

    default_kb = next(k for k in kbs if k["is_default"])
    return default_kb["collection"], default_kb["id"]


# ── Indexing ──────────────────────────────────────────────────────────────

@app.post("/index")
def index(req: IndexRequest, current_user: dict = Depends(get_current_user)):
    if not req.pages:
        raise HTTPException(status_code=400, detail="No pages provided for indexing")
    user_id = current_user["username"]
    collection, kb_id = _resolve_collection(req.knowledge_base_id, req.kb_name, user_id)
    try:
        result = get_manager().index_pages(collection, req.pages, source_url=req.source_url)
        record_index(
            kb_id,
            req.source_url or "",
            len(req.pages),
            result.get("chunk_count", 0),
        )
        return result
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Indexing failed: {exc}")


# ── Chat (SSE streaming) ──────────────────────────────────────────────────

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    user_id = current_user["username"]
    collection, _ = _resolve_collection(req.knowledge_base_id, req.kb_name, user_id)

    manager = get_manager()
    event_queue: queue.Queue = queue.Queue()

    def producer():
        try:
            for event in manager.chat_stream(
                kb_name=collection,
                question=req.question.strip(),
                chat_history=req.chat_history,
                model_id=req.model_id,
            ):
                event_queue.put(event)
        except Exception as exc:
            event_queue.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            event_queue.put(None)

    async def generate():
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, producer)
        while True:
            try:
                event = await loop.run_in_executor(
                    _executor, lambda: event_queue.get(timeout=120)
                )
            except Exception:
                yield f"event: error\ndata: {json.dumps({'message': 'Timeout'})}\n\n"
                return
            if event is None:
                return
            name = event.get("event", "message")
            data = json.dumps(event.get("data", {}))
            yield f"event: {name}\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/agent/answer/stream")
async def agent_answer_stream(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if req.knowledge_base_id is None:
        raise HTTPException(status_code=400, detail="Knowledge Base is required")

    kb = get_kb(req.knowledge_base_id, current_user["username"])
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    event_queue: queue.Queue = queue.Queue()
    manager = get_manager()

    def producer():
        try:
            for event in manager.grounded_chat_stream(
                kb_name=kb["collection"],
                question=req.question.strip(),
                model_id=req.model_id,
            ):
                event_queue.put(event)
        except Exception as exc:
            event_queue.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            event_queue.put(None)

    async def generate():
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, producer)
        while True:
            try:
                event = await loop.run_in_executor(
                    _executor, lambda: event_queue.get(timeout=120)
                )
            except Exception:
                yield f"event: error\ndata: {json.dumps({'message': 'Timeout'})}\n\n"
                return
            if event is None:
                return
            name = event.get("event", "message")
            data = json.dumps(event.get("data", {}))
            yield f"event: {name}\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Agent chat (SSE streaming, extended tool set) ─────────────────────

@app.post("/agent/chat/stream")
async def agent_chat_stream(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    user_id = current_user["username"]
    # Resolve KB id — same as regular chat
    _, kb_id = _resolve_collection(req.knowledge_base_id, req.kb_name, user_id)

    session = AgentChatSession(user_id=user_id, knowledge_base_id=kb_id)
    event_queue: queue.Queue = queue.Queue()

    def producer():
        try:
            for event in session.chat_stream(
                question=req.question.strip(),
                chat_history=req.chat_history,
                model_id=req.model_id,
            ):
                event_queue.put(event)
        except Exception as exc:
            event_queue.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            event_queue.put(None)

    async def generate():
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, producer)
        while True:
            try:
                event = await loop.run_in_executor(
                    _executor, lambda: event_queue.get(timeout=180)
                )
            except Exception:
                yield f"event: error\ndata: {json.dumps({'message': 'Timeout'})}\n\n"
                return
            if event is None:
                return
            name = event.get("event", "message")
            data = json.dumps(event.get("data", {}))
            yield f"event: {name}\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Legacy /kb/* endpoints (kept for backward compat) ────────────────────

@app.get("/kb")
def list_kbs_legacy(_: dict = Depends(get_current_user)):
    return get_manager().list_kbs()


@app.get("/kb/{kb_name}/status")
def kb_status_legacy(kb_name: str, _: dict = Depends(get_current_user)):
    return get_manager().get_status(kb_name)


@app.delete("/kb/{kb_name}")
def delete_kb_legacy(kb_name: str, _: dict = Depends(get_current_user)):
    get_manager().delete_kb(kb_name)
    return {"deleted": kb_name}


@app.get("/kb/{kb_name}/export")
def export_kb(kb_name: str, _: dict = Depends(get_current_user)):
    return get_manager().export_kb(kb_name)
