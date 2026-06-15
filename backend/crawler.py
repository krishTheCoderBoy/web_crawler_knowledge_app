from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


CONCURRENT_REQUESTS = 10   # pages fetched in parallel
REQUEST_TIMEOUT = 6        # seconds per request (was 10)
MAX_PAGES = 50             # default cap — keeps crawls under ~30s
USER_AGENT = "Mozilla/5.0 (compatible; WebCrawlerRAG/1.0)"


def is_valid(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.netloc.endswith(domain)


def _extract_pdf_text(response: requests.Response) -> str:
    try:
        reader = PdfReader(BytesIO(response.content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(text.strip() for text in pages if text.strip())
    except Exception:
        return ""


def _extract_html_text(soup: BeautifulSoup) -> str:
    text_nodes = soup.find_all(
        ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "article", "section"]
    )
    text_content = "\n".join(node.get_text(" ", strip=True) for node in text_nodes)
    if text_content.strip():
        return text_content.strip()
    body = soup.body.get_text("\n", strip=True) if soup.body else ""
    return body.strip()


def _extract_page_content(
    url: str, response: requests.Response, soup: BeautifulSoup | None
) -> dict:
    content_type = (response.headers.get("content-type") or "").lower()
    is_pdf = "application/pdf" in content_type or url.lower().endswith(".pdf")

    if is_pdf:
        title = url.rsplit("/", 1)[-1] or url
        text_content = _extract_pdf_text(response)
        image_links: list[str] = []
        links_on_page: list[str] = []
    else:
        title = soup.title.get_text(" ", strip=True) if soup and soup.title else url
        text_content = _extract_html_text(soup) if soup else ""
        image_links = (
            [urljoin(url, img.get("src")) for img in soup.find_all("img") if img.get("src")]
            if soup
            else []
        )
        links_on_page = (
            [urljoin(url, a["href"]) for a in soup.find_all("a", href=True)]
            if soup
            else []
        )

    return {
        "url": url,
        "title": title,
        "text": text_content.strip(),
        "images": image_links,
        "links": links_on_page,
        "content_type": content_type or ("application/pdf" if is_pdf else "text/html"),
    }


def _fetch_one(url: str, session: requests.Session) -> dict:
    """Fetch and parse a single URL. Returns page dict or error dict."""
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        is_pdf = "application/pdf" in content_type or url.lower().endswith(".pdf")
        soup = None if is_pdf else BeautifulSoup(response.text, "html.parser")
        return _extract_page_content(url, response, soup)
    except Exception as exc:
        return {"url": url, "_error": str(exc)}


def run_crawler(
    start_url: str,
    progress_store: dict | None = None,
    job_id: str | None = None,
    max_pages: int = MAX_PAGES,
) -> dict:
    """
    BFS crawler with concurrent page fetching.
    Processes up to CONCURRENT_REQUESTS pages simultaneously.
    """
    visited: set[str] = set()
    queue: list[str] = [start_url]
    all_output: list[dict] = []
    errors: list[dict] = []
    domain = urlparse(start_url).netloc

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    # Share one session across threads (requests.Session is thread-safe for reads)
    session.max_redirects = 5

    def _update(status: str, current_url: str = "") -> None:
        if progress_store is not None and job_id:
            progress_store[job_id] = {
                "status": status,
                "crawled": len(visited),
                "max": max_pages,
                "current_url": current_url,
                "total_pages": len(all_output),
                "error_count": len(errors),
            }

    _update("starting")

    with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        while queue and len(visited) < max_pages:
            # Build next batch — skip already-visited
            batch: list[str] = []
            while queue and len(batch) < CONCURRENT_REQUESTS and len(visited) + len(batch) < max_pages:
                url = queue.pop(0)
                if url not in visited:
                    visited.add(url)
                    batch.append(url)

            if not batch:
                break

            _update("crawling", batch[0])

            # Fetch batch in parallel
            future_to_url = {executor.submit(_fetch_one, url, session): url for url in batch}
            for future in as_completed(future_to_url):
                page = future.result()
                if "_error" in page:
                    errors.append({"url": page["url"], "error": page["_error"]})
                else:
                    all_output.append(page)
                    # Enqueue new links discovered (deduplicated)
                    for link in page.get("links", []):
                        if (
                            is_valid(link, domain)
                            and link not in visited
                            and link not in queue
                        ):
                            queue.append(link)

    result = {
        "start_url": start_url,
        "total_pages": len(all_output),
        "pages": all_output,
        "errors": errors,
        "max_pages": max_pages,
    }

    if progress_store is not None and job_id:
        progress_store[job_id] = {
            "status": "done",
            "crawled": len(visited),
            "max": max_pages,
            "current_url": "",
            "total_pages": len(all_output),
            "error_count": len(errors),
            "result": result,
        }

    return result
