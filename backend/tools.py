TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search the indexed knowledge base for relevant content chunks. "
                "Call multiple times with different queries to gather comprehensive information. "
                "Always call this before answering questions about the indexed site."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant content chunks",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of chunks to retrieve (default 4, max 10)",
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
            "description": "List all pages currently indexed in the knowledge base with their titles and URLs. Use this to orient yourself before searching.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_summary",
            "description": "Retrieve all indexed content from a specific page URL. Use when you need the full content of one particular page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The exact URL of the page to retrieve (from list_indexed_pages or search results)",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_fallback",
            "description": "Search the live web when the knowledge base does not have enough information. Use as a last resort after exhausting knowledge base searches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Web search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_structured_data",
            "description": "Extract structured JSON data from a specific indexed page according to a schema. Useful for pulling out prices, names, dates, specifications, contact info, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the indexed page to extract from",
                    },
                    "schema": {
                        "type": "object",
                        "description": 'JSON schema describing fields to extract, e.g. {"price": "number", "name": "string", "description": "string"}',
                    },
                },
                "required": ["url", "schema"],
            },
        },
    },
]
