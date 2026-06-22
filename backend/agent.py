"""
Agentic chat session with an extended tool set.

New tools: create_knowledge_base, list_knowledge_bases, crawl_website, index_documents
Existing RAG tools: search_knowledge_base, list_indexed_pages, get_page_summary,
                    web_search_fallback
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Generator

import requests as _requests

from database import create_kb, ensure_default_kb, get_kb, list_kbs, record_index
from crawler import run_crawler
from rag import get_manager
from settings import settings

# In-memory crawl cache: crawl_id -> {pages, start_url}
_crawl_cache: dict[str, dict] = {}

# ── Tool definitions ──────────────────────────────────────────────────────────

AGENT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_knowledge_base",
            "description": (
                "Create a new named knowledge base to organise and store documents. "
                "Use this when the user wants a dedicated KB for a topic or website."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name for the KB (e.g. 'Finance Reports', 'Product Docs')",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_knowledge_bases",
            "description": (
                "List all knowledge bases available to the user with their IDs, names, "
                "and readiness status. Call this to discover knowledge_base_id values."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crawl_website",
            "description": (
                "Crawl a website and extract text content from its pages. "
                "Returns a crawl_id you MUST pass to index_documents. "
                "Use max_pages 10-30 for most sites; maximum 50."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to crawl (e.g. https://example.com)",
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Maximum pages to crawl (default 20, max 50)",
                        "default": 20,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "index_documents",
            "description": (
                "Index crawled website content into a knowledge base for future search. "
                "Must be called after crawl_website; pass the crawl_id it returned."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "crawl_id": {
                        "type": "string",
                        "description": "The crawl_id value returned by crawl_website",
                    },
                    "knowledge_base_id": {
                        "type": "integer",
                        "description": "ID of the knowledge base to store the content in",
                    },
                },
                "required": ["crawl_id", "knowledge_base_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search the knowledge base for relevant content chunks. "
                "Call multiple times with varied queries for comprehensive results. "
                "ALWAYS call this before answering any factual question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "knowledge_base_id": {
                        "type": "integer",
                        "description": "Optional: KB to search (defaults to active KB)",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Chunks to retrieve (default 4, max 10)",
                        "default": 4,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_indexed_pages",
            "description": "List all pages currently indexed in the active knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge_base_id": {
                        "type": "integer",
                        "description": "Optional: KB to inspect (defaults to active KB)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_summary",
            "description": "Retrieve the full indexed content of a specific page by URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Exact URL of the page (from list_indexed_pages or search results)",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_fallback",
            "description": "Search the live web when the knowledge base has insufficient information. Use as a last resort.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Web search query"}
                },
                "required": ["query"],
            },
        },
    },
]

AGENT_SYSTEM_PROMPT = """You are an intelligent RAG assistant with full control over a web-crawler knowledge-base system.

## Capabilities
- **Manage knowledge bases**: create new ones, list existing ones
- **Crawl websites**: fetch and extract content from any URL
- **Index content**: store crawled content in a knowledge base for search
- **Answer questions**: search the KB and synthesise grounded, cited answers

## Workflow — adding a website to a knowledge base
1. (Optional) call create_knowledge_base if a new KB is needed
2. Call crawl_website with the target URL (use max_pages 10-30)
3. Call index_documents with the returned crawl_id and knowledge_base_id
4. Confirm completion and suggest what the user can now ask

## Workflow — answering a question
1. ALWAYS call search_knowledge_base first; never answer from memory alone
2. Synthesise the retrieved context into a clear, well-structured answer
3. Cite source URLs from the search results

## Rules
- When told "crawl X and index it", execute the full workflow automatically without asking
- If you need to know what KBs exist, call list_knowledge_bases first
- Prefer the user's active knowledge_base_id unless told otherwise
- If the KB is empty, say so and offer to crawl a website"""


class AgentChatSession:
    """Stateless per-request agent session. Holds user context for tool execution."""

    def __init__(self, user_id: str, knowledge_base_id: int | None) -> None:
        self.user_id = user_id
        self.kb_id = knowledge_base_id
        kb = get_kb(knowledge_base_id, user_id) if knowledge_base_id else None
        self.collection: str = kb["collection"] if kb else "default"

    # ── Helpers ───────────────────────────────────────────────────────────

    def _collection_for(self, kb_id: int | None) -> str:
        if kb_id and kb_id != self.kb_id:
            kb = get_kb(kb_id, self.user_id)
            if kb:
                return kb["collection"]
        return self.collection

    # ── Tool execution ────────────────────────────────────────────────────

    def _execute(self, tool_name: str, tool_args: dict) -> str:  # noqa: C901
        mgr = get_manager()

        if tool_name == "create_knowledge_base":
            name = (tool_args.get("name") or "").strip()
            if not name:
                return "Error: name is required"
            try:
                kb = create_kb(self.user_id, name)
                return f"Created knowledge base '{kb['name']}' with ID {kb['id']}."
            except ValueError as exc:
                return f"Error: {exc}"

        if tool_name == "list_knowledge_bases":
            ensure_default_kb(self.user_id)
            kbs = list_kbs(self.user_id)
            if not kbs:
                return "No knowledge bases found."
            lines = []
            for kb in kbs:
                try:
                    status = mgr.get_status(kb["collection"])
                    chunks = status.get("chunk_count", 0)
                    ready = "ready" if status.get("is_ready") else "empty"
                except Exception:
                    chunks, ready = 0, "unknown"
                tag = " (Default)" if kb["is_default"] else ""
                lines.append(f"- ID {kb['id']}: {kb['name']}{tag} — {ready}, {chunks} chunks")
            return "\n".join(lines)

        if tool_name == "crawl_website":
            url = (tool_args.get("url") or "").strip()
            if not url:
                return "Error: url is required"
            max_pages = min(int(tool_args.get("max_pages") or 20), 50)
            result = run_crawler(url, max_pages=max_pages)
            pages = result.get("pages", [])
            if not pages:
                return f"No pages could be crawled from {url}. Verify the URL is accessible."
            crawl_id = str(uuid.uuid4())[:8]
            _crawl_cache[crawl_id] = {"pages": pages, "start_url": url}
            sample = ", ".join((p.get("title") or p["url"])[:40] for p in pages[:3])
            return (
                f"Crawled {len(pages)} pages from {url}.\n"
                f"crawl_id: {crawl_id}\n"
                f"Sample pages: {sample}"
            )

        if tool_name == "index_documents":
            crawl_id = tool_args.get("crawl_id", "")
            kb_id = tool_args.get("knowledge_base_id")
            if not crawl_id or crawl_id not in _crawl_cache:
                return "Error: crawl_id not found — call crawl_website first."
            if not kb_id:
                return "Error: knowledge_base_id is required"
            kb = get_kb(kb_id, self.user_id)
            if not kb:
                return f"Error: knowledge base {kb_id} not found"
            cached = _crawl_cache.pop(crawl_id)
            pages = cached["pages"]
            source_url = cached["start_url"]
            result = mgr.index_pages(kb["collection"], pages, source_url=source_url)
            chunks = result.get("chunk_count", result.get("indexed_chunks", 0))
            record_index(kb_id, source_url, len(pages), chunks)
            if kb_id == self.kb_id:
                self.collection = kb["collection"]
            return (
                f"Indexed {len(pages)} pages ({chunks} chunks) from {source_url} "
                f"into knowledge base '{kb['name']}' (ID {kb_id})."
            )

        if tool_name == "search_knowledge_base":
            collection = self._collection_for(tool_args.get("knowledge_base_id"))
            query = tool_args.get("query", "")
            top_k = tool_args.get("top_k", 4)
            result = mgr.search(collection, query, top_k)
            matches = result["matches"]
            if not matches:
                return "No relevant content found in the knowledge base for that query."
            return "\n\n".join(
                f"{m['rank']}. {m['title']} (score: {m['score']})\n   URL: {m['url']}\n   {m['excerpt']}"
                for m in matches
            )

        if tool_name == "list_indexed_pages":
            collection = self._collection_for(tool_args.get("knowledge_base_id"))
            pages = mgr.list_pages(collection)
            if not pages:
                return "No pages indexed yet."
            return "\n".join(f"- {p['title']}: {p['url']}" for p in pages)

        # Delegate remaining tools to the RAG manager's existing handler
        return mgr._execute_tool(self.collection, tool_name, tool_args)

    # ── Streaming chat ────────────────────────────────────────────────────

    def chat_stream(
        self,
        question: str,
        chat_history: list[dict] | None = None,
        model_id: str | None = None,
    ) -> Generator[dict, None, None]:
        """
        Yields SSE event dicts (same format as KBManager.chat_stream):
          {"event": "tool_call",   "data": {"name", "args", "call_id"}}
          {"event": "tool_result", "data": {"name", "summary", "call_id"}}
          {"event": "token",       "data": {"text"}}
          {"event": "done",        "data": {"sources", "model", "mode"}}
          {"event": "error",       "data": {"message"}}
        """
        model = model_id or settings.LLM_MODEL
        all_sources: list[dict] = []

        messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
        for msg in (chat_history or [])[-6:]:
            role = msg.get("role", "user")
            text = re.sub(r"\s+", " ", msg.get("text", "") or "").strip()
            if text and role in ("user", "assistant"):
                messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": question})

        # No API key — fallback to retrieval-only
        if not settings.OPENROUTER_API_KEY:
            yield {
                "event": "tool_call",
                "data": {"name": "search_knowledge_base", "args": {"query": question}, "call_id": "0"},
            }
            retrieval = get_manager().search(self.collection, question)
            all_sources = retrieval["matches"]
            yield {
                "event": "tool_result",
                "data": {
                    "name": "search_knowledge_base",
                    "summary": f"{len(all_sources)} result(s) found",
                    "call_id": "0",
                },
            }
            answer = get_manager()._build_fallback_answer(question, all_sources)
            yield {"event": "token", "data": {"text": answer}}
            yield {"event": "done", "data": {"sources": all_sources, "model": model, "mode": "retrieval-only"}}
            return

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.OPENROUTER_SITE_URL,
            "X-Title": settings.OPENROUTER_APP_NAME,
        }

        for _iter in range(8):
            payload = {
                "model": model,
                "messages": messages,
                "temperature": settings.LLM_TEMPERATURE,
                "max_tokens": settings.LLM_MAX_TOKENS,
                "stream": False,
                "tools": AGENT_TOOL_DEFINITIONS,
                "tool_choice": "auto",
            }
            try:
                resp = _requests.post(
                    settings.OPENROUTER_BASE_URL,
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                yield {"event": "error", "data": {"message": str(exc)}}
                return

            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                content = msg.get("content", "") or ""
                words = content.split(" ")
                for i, word in enumerate(words):
                    yield {"event": "token", "data": {"text": word if i == 0 else " " + word}}
                yield {
                    "event": "done",
                    "data": {
                        "sources": all_sources,
                        "model": data.get("model", model),
                        "mode": "agent-grounded" if all_sources else "agent-direct",
                    },
                }
                return

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

                tool_result = self._execute(tool_name, tool_args)

                # Collect KB search sources
                if tool_name == "search_knowledge_base":
                    collection = self._collection_for(tool_args.get("knowledge_base_id"))
                    retrieval = get_manager().search(
                        collection, tool_args.get("query", ""), tool_args.get("top_k", 4)
                    )
                    for m in retrieval["matches"]:
                        if not any(
                            s["url"] == m["url"] and s["chunk_index"] == m["chunk_index"]
                            for s in all_sources
                        ):
                            all_sources.append(m)

                yield {
                    "event": "tool_result",
                    "data": {"name": tool_name, "summary": tool_result[:300], "call_id": call_id},
                }
                messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_result})

        yield {
            "event": "token",
            "data": {"text": "I've completed all available steps. Let me know what else you need."},
        }
        yield {
            "event": "done",
            "data": {"sources": all_sources, "model": model, "mode": "agent-max-iterations"},
        }
