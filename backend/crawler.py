import time

from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions

from settings import settings

MAX_PAGES = 50            # default cap
POLL_INTERVAL = 1.5       # seconds between crawl-status checks
CRAWL_TIMEOUT = 300        # seconds before giving up on a crawl job

_client: Firecrawl | None = None


def _get_client() -> Firecrawl:
    global _client
    if _client is None:
        if not settings.FIRECRAWL_API_KEY:
            raise RuntimeError(
                "FIRECRAWL_API_KEY is not set. Add it to backend/.env to enable crawling."
            )
        _client = Firecrawl(api_key=settings.FIRECRAWL_API_KEY)
    return _client


def _document_to_page(doc) -> dict:
    meta = doc.metadata
    url = (meta.url if meta else None) or ""
    title = (meta.title if meta else None) or url
    return {
        "url": url,
        "title": title,
        "text": (doc.markdown or "").strip(),
        "images": doc.images or [],
        "links": doc.links or [],
        "content_type": (meta.content_type if meta else None) or "text/html",
    }


def run_crawler(
    start_url: str,
    progress_store: dict | None = None,
    job_id: str | None = None,
    max_pages: int = MAX_PAGES,
) -> dict:
    """
    Crawl a site via Firecrawl. Starts an async crawl job, polls for progress,
    and maps the results back into this app's page-dict shape.
    """

    def _update(status: str, current_url: str = "", crawled: int = 0, total: int = 0) -> None:
        if progress_store is not None and job_id:
            progress_store[job_id] = {
                "status": status,
                "crawled": crawled,
                "max": max_pages,
                "current_url": current_url,
                "total_pages": total,
                "error_count": 0,
            }

    _update("starting")

    client = _get_client()
    crawl_response = client.start_crawl(
        start_url,
        limit=max_pages,
        scrape_options=ScrapeOptions(formats=["markdown", "links", "images"], only_main_content=True),
    )
    firecrawl_job_id = crawl_response.id

    _update("crawling", start_url)

    deadline = time.time() + CRAWL_TIMEOUT
    job = client.get_crawl_status(firecrawl_job_id)
    while job.status == "scraping" and time.time() < deadline:
        _update("crawling", start_url, crawled=job.completed, total=job.total)
        time.sleep(POLL_INTERVAL)
        job = client.get_crawl_status(firecrawl_job_id)

    pages = [_document_to_page(doc) for doc in job.data]
    pages = [p for p in pages if p["url"]]

    result = {
        "start_url": start_url,
        "total_pages": len(pages),
        "pages": pages,
        "errors": [] if job.status == "completed" else [{"url": start_url, "error": f"crawl ended with status: {job.status}"}],
        "max_pages": max_pages,
    }

    if progress_store is not None and job_id:
        progress_store[job_id] = {
            "status": "done",
            "crawled": len(pages),
            "max": max_pages,
            "current_url": "",
            "total_pages": len(pages),
            "error_count": len(result["errors"]),
            "result": result,
        }

    return result
