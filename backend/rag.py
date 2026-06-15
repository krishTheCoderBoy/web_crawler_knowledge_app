import json
import os
import re
from dataclasses import dataclass
from hashlib import md5
from pathlib import Path
from typing import Any, Generator

# Tell HuggingFace Hub to use only locally-cached files — no network calls.
# The embedding model is already cached after first download; this prevents
# SSL errors on corporate/VPN networks with self-signed certificate chains.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import chromadb
import requests
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from settings import AVAILABLE_MODELS, settings


CHROMA_DIR = Path(settings.CHROMA_PERSIST_DIR).resolve()
MAX_CONTEXT_CHUNKS = 6
MAX_TOOL_ITERATIONS = 5
AVAILABLE_MODEL_MAP = {m.model_id: m for m in AVAILABLE_MODELS}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _slug_from_url(url: str) -> str:
    return md5(url.encode("utf-8")).hexdigest()[:12]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()) // 3)


def _split_into_paragraphs(text: str) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text)
    return [_clean_whitespace(c) for c in normalized.split("\n\n") if _clean_whitespace(c)]


def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 180) -> list[str]:
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        single = _clean_whitespace(text)
        return [single] if single else []

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= chunk_size:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + chunk_size)
            piece = paragraph[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= len(paragraph):
                break
            start = max(end - overlap, start + 1)
        current = ""

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# KB snapshot
# ---------------------------------------------------------------------------

@dataclass
class KBSnapshot:
    name: str
    crawl_id: str | None = None
    source_url: str | None = None
    page_count: int = 0
    indexed_pages: int = 0
    chunk_count: int = 0
    last_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "crawl_id": self.crawl_id,
            "source_url": self.source_url,
            "page_count": self.page_count,
            "indexed_pages": self.indexed_pages,
            "chunk_count": self.chunk_count,
            "last_question": self.last_question,
            "is_ready": self.chunk_count > 0,
        }


# ---------------------------------------------------------------------------
# Web search helper (DuckDuckGo, no key needed)
# ---------------------------------------------------------------------------

def _web_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=5))
        if not results:
            return "No web search results found."
        lines = [
            f"{r.get('title', '')}\n{r.get('href', '')}\n{r.get('body', '')[:200]}"
            for r in results
        ]
        return "\n\n".join(lines)
    except ImportError:
        return (
            "Web search unavailable. "
            "Install the package: pip install duckduckgo-search"
        )
    except Exception as exc:
        return f"Web search failed: {exc}"


# ---------------------------------------------------------------------------
# KBManager — manages multiple named ChromaDB collections
# ---------------------------------------------------------------------------

class KBManager:
    def __init__(self) -> None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self.embedder = SentenceTransformer(settings.EMBEDDING_MODEL)
        self.client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._snapshots: dict[str, KBSnapshot] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _col_name(self, kb_name: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", kb_name.strip())[:63]
        return safe or "default"

    def _collection(self, kb_name: str):
        return self.client.get_or_create_collection(self._col_name(kb_name))

    def _snapshot(self, kb_name: str) -> KBSnapshot:
        if kb_name not in self._snapshots:
            col = self._collection(kb_name)
            self._snapshots[kb_name] = KBSnapshot(name=kb_name, chunk_count=col.count())
        return self._snapshots[kb_name]

    # ------------------------------------------------------------------
    # KB management
    # ------------------------------------------------------------------

    def list_kbs(self) -> list[dict]:
        cols = self.client.list_collections()
        out = []
        for col in cols:
            if kb_name := col.name:
                snap = self._snapshots.get(kb_name, KBSnapshot(name=kb_name, chunk_count=col.count()))
                out.append(snap.to_dict())
        return out

    def delete_kb(self, kb_name: str) -> None:
        try:
            self.client.delete_collection(self._col_name(kb_name))
        except Exception:
            pass
        self._snapshots.pop(kb_name, None)

    def get_status(self, kb_name: str) -> dict[str, Any]:
        snap = self._snapshot(kb_name)
        snap.chunk_count = self._collection(kb_name).count()
        return snap.to_dict()

    def get_available_models(self) -> dict[str, Any]:
        return {
            "selected_model": settings.LLM_MODEL,
            "selected_provider": settings.LLM_PROVIDER,
            "available_models": [m.dict() for m in AVAILABLE_MODELS],
        }

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_pages(
        self,
        kb_name: str,
        pages: list[dict],
        source_url: str | None = None,
    ) -> dict[str, Any]:
        # Wipe existing collection for this KB
        try:
            self.client.delete_collection(self._col_name(kb_name))
        except Exception:
            pass
        collection = self._collection(kb_name)

        documents: list[str] = []
        ids: list[str] = []
        metadatas: list[dict] = []
        page_summaries: list[dict] = []
        indexed_pages = 0
        total_pages = len(pages)

        for page_number, page in enumerate(pages, start=1):
            text = _clean_whitespace(page.get("text", ""))
            if not text:
                continue
            page_url = page.get("url", source_url or f"page-{page_number}")
            page_title = _clean_whitespace(page.get("title", "Untitled page"))
            chunks = _chunk_text(text)
            if not chunks:
                continue

            indexed_pages += 1
            page_summaries.append({
                "url": page_url,
                "title": page_title,
                "chunks": len(chunks),
                "characters": len(text),
            })
            page_slug = _slug_from_url(page_url)
            for ci, chunk in enumerate(chunks):
                documents.append(chunk)
                ids.append(f"{page_slug}-{ci}")
                metadatas.append({
                    "url": page_url,
                    "title": page_title,
                    "page_number": page_number,
                    "chunk_index": ci,
                    "char_length": len(chunk),
                    "token_estimate": _estimate_tokens(chunk),
                })

        if not documents:
            return {
                **self.get_status(kb_name),
                "indexed_chunks": 0,
                "pages": [],
                "page_count": total_pages,
                "indexed_pages": 0,
                "chunk_count": 0,
                "suggested_questions": [],
                "message": "No indexable text found in the crawl.",
            }

        embeddings = self.embedder.encode(documents, show_progress_bar=False).tolist()
        collection.add(documents=documents, embeddings=embeddings, ids=ids, metadatas=metadatas)

        snap = KBSnapshot(
            name=kb_name,
            crawl_id=_slug_from_url(source_url or metadatas[0]["url"]),
            source_url=source_url or metadatas[0]["url"],
            page_count=total_pages,
            indexed_pages=indexed_pages,
            chunk_count=len(documents),
        )
        self._snapshots[kb_name] = snap

        suggested = self._generate_suggested_questions(page_summaries[:10])

        return {
            **snap.to_dict(),
            "indexed_chunks": len(documents),
            "pages": page_summaries,
            "suggested_questions": suggested,
            "message": f"Indexed {len(documents)} chunks from {indexed_pages} pages.",
        }

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(self, kb_name: str, query: str, top_k: int = MAX_CONTEXT_CHUNKS) -> dict[str, Any]:
        collection = self._collection(kb_name)
        count = collection.count()
        if count == 0:
            return {"matches": [], "context": "", "top_k": 0}

        embedding = self.embedder.encode([query], show_progress_bar=False).tolist()[0]
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, count),
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        matches: list[dict] = []
        context_parts: list[str] = []

        for i, (doc, meta) in enumerate(zip(documents, metadatas)):
            dist = float(distances[i]) if i < len(distances) else 0.0
            score = max(0.0, 1.0 - (dist / 2.0))
            matches.append({
                "rank": i + 1,
                "score": round(score, 3),
                "url": meta["url"],
                "title": meta.get("title", "Untitled"),
                "chunk_index": meta.get("chunk_index", 0),
                "excerpt": doc[:320].strip(),
            })
            context_parts.append(
                f"Source {i + 1}\nTitle: {meta.get('title', 'Untitled')}\n"
                f"URL: {meta['url']}\nChunk: {meta.get('chunk_index', 0)}\n"
                f"Content:\n{doc}"
            )

        return {
            "matches": matches,
            "context": "\n\n---\n\n".join(context_parts),
            "top_k": len(matches),
        }

    def list_pages(self, kb_name: str) -> list[dict]:
        collection = self._collection(kb_name)
        if collection.count() == 0:
            return []
        results = collection.get(include=["metadatas"])
        seen: dict[str, dict] = {}
        for meta in (results.get("metadatas") or []):
            url = meta.get("url", "")
            if url and url not in seen:
                seen[url] = {"url": url, "title": meta.get("title", "Untitled")}
        return list(seen.values())

    def get_page_summary(self, kb_name: str, url: str) -> dict[str, Any]:
        collection = self._collection(kb_name)
        results = collection.get(where={"url": url}, include=["documents", "metadatas"])
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        if not docs:
            return {"url": url, "found": False, "content": "", "title": "", "chunks": 0}
        return {
            "url": url,
            "title": metas[0].get("title", "Untitled") if metas else "Untitled",
            "found": True,
            "chunks": len(docs),
            "content": "\n\n".join(docs)[:4000],
        }

    def export_kb(self, kb_name: str) -> dict[str, Any]:
        collection = self._collection(kb_name)
        results = collection.get(include=["documents", "metadatas"])
        snap = self._snapshot(kb_name)
        return {
            "kb_name": kb_name,
            "snapshot": snap.to_dict(),
            "total_chunks": len(results.get("ids") or []),
            "ids": results.get("ids") or [],
            "documents": results.get("documents") or [],
            "metadatas": results.get("metadatas") or [],
        }

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        stream: bool = False,
    ) -> requests.Response:
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.OPENROUTER_SITE_URL,
            "X-Title": settings.OPENROUTER_APP_NAME,
        }
        payload: dict[str, Any] = {
            "model": model or settings.LLM_MODEL,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = requests.post(
            settings.OPENROUTER_BASE_URL,
            headers=headers,
            json=payload,
            timeout=90,
            stream=stream,
        )
        resp.raise_for_status()
        return resp

    def _execute_tool(self, kb_name: str, tool_name: str, tool_args: dict) -> str:
        try:
            if tool_name == "search_knowledge_base":
                result = self.search(kb_name, tool_args["query"], tool_args.get("top_k", 4))
                matches = result["matches"]
                if not matches:
                    return "No relevant content found in the knowledge base for that query."
                return "\n\n".join(
                    f"{m['rank']}. {m['title']} (score: {m['score']})\n   URL: {m['url']}\n   {m['excerpt']}"
                    for m in matches
                )

            elif tool_name == "list_indexed_pages":
                pages = self.list_pages(kb_name)
                if not pages:
                    return "No pages indexed yet."
                return "\n".join(f"- {p['title']}: {p['url']}" for p in pages)

            elif tool_name == "get_page_summary":
                result = self.get_page_summary(kb_name, tool_args["url"])
                if not result["found"]:
                    return f"Page not found in knowledge base: {tool_args['url']}"
                return f"Title: {result['title']}\n\n{result['content']}"

            elif tool_name == "web_search_fallback":
                return _web_search(tool_args["query"])

            elif tool_name == "extract_structured_data":
                page = self.get_page_summary(kb_name, tool_args["url"])
                if not page["found"]:
                    return f"Page not found: {tool_args['url']}"
                schema = tool_args.get("schema", {})
                extract_prompt = (
                    f"Extract these fields from the web page content as valid JSON.\n"
                    f"Schema: {json.dumps(schema)}\n\n"
                    f"Content:\n{page['content'][:3000]}\n\n"
                    "Return ONLY valid JSON. No explanation."
                )
                if not settings.OPENROUTER_API_KEY:
                    return "LLM not configured for structured extraction."
                try:
                    resp = self._call_llm(
                        [{"role": "user", "content": extract_prompt}],
                        model=settings.LLM_MODEL,
                    )
                    return resp.json()["choices"][0]["message"]["content"].strip()
                except Exception as exc:
                    return f"Extraction failed: {exc}"

            return f"Unknown tool: {tool_name}"

        except Exception as exc:
            return f"Tool execution error ({tool_name}): {exc}"

    # ------------------------------------------------------------------
    # Suggested questions
    # ------------------------------------------------------------------

    def _generate_suggested_questions(self, page_summaries: list[dict]) -> list[str]:
        if not settings.OPENROUTER_API_KEY or not page_summaries:
            return []
        titles = [p.get("title", "") for p in page_summaries if p.get("title")][:8]
        prompt = (
            "Based on these web page titles from a crawled website, generate exactly 4 concise "
            "questions a user might ask. Return ONLY a JSON array of 4 strings, nothing else.\n\n"
            f"Titles: {json.dumps(titles)}"
        )
        try:
            resp = self._call_llm(
                [{"role": "user", "content": prompt}],
                model=settings.LLM_MODEL,
            )
            content = resp.json()["choices"][0]["message"]["content"].strip()
            match = re.search(r"\[.*?\]", content, re.DOTALL)
            if match:
                qs = json.loads(match.group())
                return [q for q in qs if isinstance(q, str)][:4]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Agentic streaming chat
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        kb_name: str,
        question: str,
        chat_history: list[dict] | None = None,
        model_id: str | None = None,
    ) -> Generator[dict, None, None]:
        """
        Yields SSE event dicts:
          {"event": "tool_call",   "data": {"name", "args", "call_id"}}
          {"event": "tool_result", "data": {"name", "summary", "call_id"}}
          {"event": "token",       "data": {"text"}}
          {"event": "done",        "data": {"sources", "model", "mode"}}
          {"event": "error",       "data": {"message"}}
        """
        from tools import TOOL_DEFINITIONS

        system = (
            "You are a retrieval-augmented assistant for crawled websites. "
            "Use available tools to search the knowledge base before answering. "
            "Always cite source URLs when referencing specific content."
        )
        messages: list[dict] = [{"role": "system", "content": system}]
        for msg in (chat_history or [])[-6:]:
            role = msg.get("role", "user")
            text = _clean_whitespace(msg.get("text", ""))
            if text and role in ("user", "assistant"):
                messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": question})

        model = model_id or settings.LLM_MODEL
        all_sources: list[dict] = []

        # No API key — retrieval-only fallback
        if not settings.OPENROUTER_API_KEY:
            yield {"event": "tool_call", "data": {"name": "search_knowledge_base", "args": {"query": question}, "call_id": "0"}}
            retrieval = self.search(kb_name, question)
            all_sources = retrieval["matches"]
            summary = self._execute_tool(kb_name, "search_knowledge_base", {"query": question, "top_k": 4})
            yield {"event": "tool_result", "data": {"name": "search_knowledge_base", "summary": summary[:200], "call_id": "0"}}
            answer = self._build_fallback_answer(question, all_sources)
            yield {"event": "token", "data": {"text": answer}}
            yield {"event": "done", "data": {"sources": all_sources, "model": model, "mode": "retrieval-only"}}
            return

        # Agentic tool loop
        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                resp = self._call_llm(messages, tools=TOOL_DEFINITIONS, model=model)
                data = resp.json()
            except Exception as exc:
                yield {"event": "error", "data": {"message": str(exc)}}
                return

            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                # Final answer — stream word by word for progressive display
                content = msg.get("content", "") or ""
                words = content.split(" ")
                for i, word in enumerate(words):
                    text = word if i == 0 else " " + word
                    yield {"event": "token", "data": {"text": text}}

                yield {"event": "done", "data": {
                    "sources": all_sources,
                    "model": data.get("model", model),
                    "mode": "grounded-generation" if all_sources else "direct",
                }}
                return

            # Execute each tool call
            messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                call_id = tc.get("id", "")
                yield {"event": "tool_call", "data": {"name": tool_name, "args": tool_args, "call_id": call_id}}

                result = self._execute_tool(kb_name, tool_name, tool_args)

                # Accumulate sources from KB searches
                if tool_name == "search_knowledge_base":
                    retrieval = self.search(
                        kb_name,
                        tool_args.get("query", ""),
                        tool_args.get("top_k", 4),
                    )
                    for m in retrieval["matches"]:
                        already = any(
                            s["url"] == m["url"] and s["chunk_index"] == m["chunk_index"]
                            for s in all_sources
                        )
                        if not already:
                            all_sources.append(m)

                yield {"event": "tool_result", "data": {
                    "name": tool_name,
                    "summary": result[:300],
                    "call_id": call_id,
                }}
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                })

        # Max iterations reached
        yield {"event": "token", "data": {"text": "I gathered as much information as I could. Please try a more specific question."}}
        yield {"event": "done", "data": {"sources": all_sources, "model": model, "mode": "max-iterations"}}

    def _build_fallback_answer(self, question: str, matches: list[dict]) -> str:
        if not matches:
            return (
                "No indexed content available. "
                "Please crawl and index a website first, then ask your question."
            )
        lead = matches[0]
        related = ", ".join(m["title"] for m in matches[:3] if m.get("title"))
        return (
            f"**Retrieval-only mode** (no LLM configured).\n\n"
            f"**Best match:** {lead['title']} — {lead['url']}\n\n"
            f"**Excerpt:** {lead['excerpt']}\n\n"
            f"**Also relevant:** {related}"
        )


# ---------------------------------------------------------------------------
# Module-level singleton + compatibility shims
# ---------------------------------------------------------------------------

_manager = KBManager()


def get_manager() -> KBManager:
    return _manager


# Legacy shims used by original main.py
def get_available_models() -> dict[str, Any]:
    return _manager.get_available_models()


def get_kb_status() -> dict[str, Any]:
    return _manager.get_status("default")


def index_pages(pages: list[dict], source_url: str | None = None) -> dict[str, Any]:
    return _manager.index_pages("default", pages, source_url)


def chat(
    question: str,
    chat_history: list[dict] | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    events = list(_manager.chat_stream("default", question, chat_history, model_id))
    tokens = [e["data"]["text"] for e in events if e["event"] == "token"]
    done = next((e["data"] for e in events if e["event"] == "done"), {})
    return {
        "answer": "".join(tokens),
        "sources": done.get("sources", []),
        "mode": done.get("mode", "unknown"),
        "model": done.get("model", model_id or settings.LLM_MODEL),
    }
