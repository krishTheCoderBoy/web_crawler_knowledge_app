import asyncio
import json
import queue
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from agent import AgentChatSession
from auth import Token, authenticate_user, create_access_token, get_current_user, register_user
from crawler import run_crawler
from database import (
    create_kb,
    delete_kb_record,
    ensure_default_kb,
    get_doc_stats,
    get_kb,
    init_db,
    list_kbs,
    record_index,
)
from rag import get_manager

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


# ── Auth ──────────────────────────────────────────────────────────────────

@app.post("/auth/register", response_model=Token, status_code=201)
async def register(req: RegisterRequest):
    try:
        user = register_user(req.username, req.password, req.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    token = create_access_token({"sub": user["username"]})
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "full_name": user["full_name"],
    }


@app.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token({"sub": user["username"]})
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "full_name": user.get("full_name", user["username"]),
    }


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


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
