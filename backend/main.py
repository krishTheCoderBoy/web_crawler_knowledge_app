import asyncio
import json
import queue
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from crawler import run_crawler
from rag import get_manager

app = FastAPI(title="Crawler RAG API", version="2.0.0")
_executor = ThreadPoolExecutor(max_workers=4)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002"
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory crawl job store  {job_id -> progress/result dict}
_crawl_jobs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CrawlStartRequest(BaseModel):
    url: str
    max_pages: int = 200


class IndexRequest(BaseModel):
    pages: list[dict] = Field(default_factory=list)
    source_url: str | None = None
    kb_name: str = "default"


class ChatRequest(BaseModel):
    question: str
    chat_history: list[dict] = Field(default_factory=list)
    model_id: str | None = None
    kb_name: str = "default"


# ---------------------------------------------------------------------------
# Health / Models
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/models")
def models():
    return get_manager().get_available_models()


# ---------------------------------------------------------------------------
# Crawling  (async job-based with SSE progress)
# ---------------------------------------------------------------------------

def _run_crawl_job(job_id: str, start_url: str, max_pages: int) -> None:
    """Runs in a thread-pool worker, updates _crawl_jobs in place."""
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
async def crawl_start(req: CrawlStartRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    job_id = str(uuid.uuid4())[:8]
    _crawl_jobs[job_id] = {"status": "starting", "crawled": 0, "max": req.max_pages, "total_pages": 0}
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_crawl_job, job_id, url, req.max_pages)
    return {"job_id": job_id}


@app.get("/crawl/progress/{job_id}")
async def crawl_progress(job_id: str):
    """SSE stream of crawl progress events."""
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
def crawl_result(job_id: str):
    job = _crawl_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "error":
        raise HTTPException(status_code=500, detail=job.get("message", "Crawl failed"))
    if job.get("status") != "done":
        raise HTTPException(status_code=202, detail="Crawl still in progress")
    return job.get("result", {})


# Legacy synchronous crawl endpoint (kept for backwards compat)
@app.get("/crawl")
def crawl_legacy(url: str):
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    return run_crawler(url.strip())


# ---------------------------------------------------------------------------
# Knowledge Bases
# ---------------------------------------------------------------------------

@app.get("/kb")
def list_kbs():
    return get_manager().list_kbs()


@app.get("/kb/{kb_name}/status")
def kb_status(kb_name: str):
    return get_manager().get_status(kb_name)


@app.delete("/kb/{kb_name}")
def delete_kb(kb_name: str):
    get_manager().delete_kb(kb_name)
    return {"deleted": kb_name}


@app.get("/kb/{kb_name}/export")
def export_kb(kb_name: str):
    return get_manager().export_kb(kb_name)


# Legacy endpoint
@app.get("/knowledge-base")
def knowledge_base_legacy():
    return get_manager().get_status("default")


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

@app.post("/index")
def index(req: IndexRequest):
    if not req.pages:
        raise HTTPException(status_code=400, detail="No pages provided for indexing")
    try:
        return get_manager().index_pages(req.kb_name, req.pages, source_url=req.source_url)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Indexing failed: {exc}")


# ---------------------------------------------------------------------------
# Chat  (SSE streaming with agentic tool calling)
# ---------------------------------------------------------------------------

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    manager = get_manager()
    event_queue: queue.Queue = queue.Queue()

    def producer():
        try:
            for event in manager.chat_stream(
                kb_name=req.kb_name,
                question=req.question.strip(),
                chat_history=req.chat_history,
                model_id=req.model_id,
            ):
                event_queue.put(event)
        except Exception as exc:
            event_queue.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            event_queue.put(None)  # sentinel

    async def generate():
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, producer)

        while True:
            # Poll queue without blocking the event loop
            try:
                event = await loop.run_in_executor(_executor, lambda: event_queue.get(timeout=120))
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
