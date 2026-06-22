"""
SQLite metadata layer for Knowledge Base management.
ChromaDB still handles vector storage; this module tracks KB identity,
ownership, and document history.
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "kb_metadata.db"


# ── Connection ────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL,
                name        TEXT    NOT NULL,
                collection  TEXT    NOT NULL,
                is_default  INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS kb_documents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id       INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                source_url  TEXT,
                page_count  INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                indexed_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)
    finally:
        conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:28]


# ── Default KB ────────────────────────────────────────────────────────────

def ensure_default_kb(user_id: str) -> dict:
    """Return the user's Default KB, creating it if it doesn't exist.
    Uses 'default' as the ChromaDB collection for backward compatibility
    with data indexed before the KB management feature was added."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE user_id=? AND is_default=1", (user_id,)
        ).fetchone()
        if row:
            return dict(row)

        conn.execute(
            """INSERT OR IGNORE INTO knowledge_bases
               (user_id, name, collection, is_default) VALUES (?,?,?,1)""",
            (user_id, "Default Knowledge Base", "default"),
        )
        conn.commit()
        return dict(
            conn.execute(
                "SELECT * FROM knowledge_bases WHERE user_id=? AND is_default=1", (user_id,)
            ).fetchone()
        )
    finally:
        conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────

def list_kbs(user_id: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT * FROM knowledge_bases
               WHERE user_id=?
               ORDER BY is_default DESC, created_at ASC""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_kb(user_id: str, name: str) -> dict:
    name = name.strip()
    ts = int(datetime.now().timestamp())
    collection = f"kb_{_slug(user_id)}_{_slug(name)}_{ts}"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO knowledge_bases (user_id, name, collection) VALUES (?,?,?)",
            (user_id, name, collection),
        )
        conn.commit()
        return dict(
            conn.execute(
                "SELECT * FROM knowledge_bases WHERE user_id=? AND name=?",
                (user_id, name),
            ).fetchone()
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"Knowledge base '{name}' already exists")
    finally:
        conn.close()


def get_kb(kb_id: int, user_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE id=? AND user_id=?", (kb_id, user_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_kb_record(kb_id: int, user_id: str) -> str:
    """Delete KB row; returns the ChromaDB collection name so caller can clean it up."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT is_default, collection FROM knowledge_bases WHERE id=? AND user_id=?",
            (kb_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("Knowledge base not found")
        if row["is_default"]:
            raise ValueError("Cannot delete the default knowledge base")
        collection = row["collection"]
        conn.execute("DELETE FROM knowledge_bases WHERE id=? AND user_id=?", (kb_id, user_id))
        conn.commit()
        return collection
    finally:
        conn.close()


def record_index(kb_id: int, source_url: str, page_count: int, chunk_count: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO kb_documents (kb_id, source_url, page_count, chunk_count)
               VALUES (?,?,?,?)""",
            (kb_id, source_url or "", page_count, chunk_count),
        )
        conn.execute(
            "UPDATE knowledge_bases SET updated_at=datetime('now') WHERE id=?", (kb_id,)
        )
        conn.commit()
    finally:
        conn.close()


def get_doc_stats(kb_id: int) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT COUNT(*)            AS doc_count,
                      COALESCE(SUM(page_count),  0) AS total_pages,
                      COALESCE(SUM(chunk_count), 0) AS total_chunks
               FROM kb_documents WHERE kb_id=?""",
            (kb_id,),
        ).fetchone()
        return dict(row) if row else {"doc_count": 0, "total_pages": 0, "total_chunks": 0}
    finally:
        conn.close()
