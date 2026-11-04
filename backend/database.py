"""
SQLite metadata layer for Knowledge Base management.
ChromaDB still handles vector storage; this module tracks KB identity,
ownership, and document history.
"""

import json
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

            CREATE TABLE IF NOT EXISTS chat_conversations (
                id          TEXT PRIMARY KEY,
                user_id     TEXT    NOT NULL,
                kb_id       INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                title       TEXT    NOT NULL,
                messages    TEXT    NOT NULL DEFAULT '[]',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS users (
                username        TEXT PRIMARY KEY,
                hashed_password TEXT,
                full_name       TEXT NOT NULL,
                oauth_provider  TEXT,
                oauth_id        TEXT,
                avatar_url      TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                user_agent  TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_api_keys (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                provider      TEXT NOT NULL,
                encrypted_key TEXT NOT NULL,
                last4         TEXT NOT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(username, provider)
            );
        """)
        # Migrations for DBs created before OAuth support was added: SQLite's
        # CREATE TABLE IF NOT EXISTS won't retrofit new columns onto an
        # existing `users` table, so add them individually if missing.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for col_sql in (
            "ALTER TABLE users ADD COLUMN oauth_provider TEXT",
            "ALTER TABLE users ADD COLUMN oauth_id TEXT",
            "ALTER TABLE users ADD COLUMN avatar_url TEXT",
        ):
            col_name = col_sql.split("ADD COLUMN ")[1].split(" ")[0]
            if col_name not in existing_cols:
                conn.execute(col_sql)

        # hashed_password was originally NOT NULL — OAuth-only accounts have
        # no local password, so an older table needs rebuilding with the
        # constraint relaxed. SQLite can't ALTER a column's NOT NULL directly,
        # and renaming the referenced table also silently repoints any other
        # table's "REFERENCES users(...)" clause to follow the rename — so
        # instead of renaming `users` away, save the two dependent tables'
        # rows, drop everything, rebuild in dependency order, reload the rows.
        users_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if users_sql and "hashed_password TEXT NOT NULL" in users_sql["sql"]:
            conn.execute("PRAGMA foreign_keys = OFF")
            old_sessions = [dict(r) for r in conn.execute("SELECT * FROM user_sessions")]
            old_api_keys = [dict(r) for r in conn.execute("SELECT * FROM user_api_keys")]
            old_users = [dict(r) for r in conn.execute("SELECT username, hashed_password, full_name, created_at FROM users")]

            conn.executescript("""
                DROP TABLE user_sessions;
                DROP TABLE user_api_keys;
                DROP TABLE users;
                CREATE TABLE users (
                    username        TEXT PRIMARY KEY,
                    hashed_password TEXT,
                    full_name       TEXT NOT NULL,
                    oauth_provider  TEXT,
                    oauth_id        TEXT,
                    avatar_url      TEXT,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE user_sessions (
                    id          TEXT PRIMARY KEY,
                    username    TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                    user_agent  TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE user_api_keys (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                    provider      TEXT NOT NULL,
                    encrypted_key TEXT NOT NULL,
                    last4         TEXT NOT NULL,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(username, provider)
                );
            """)

            conn.executemany(
                "INSERT INTO users (username, hashed_password, full_name, created_at) VALUES (:username,:hashed_password,:full_name,:created_at)",
                old_users,
            )
            conn.executemany(
                "INSERT INTO user_sessions (id, username, user_agent, created_at, last_seen_at) VALUES (:id,:username,:user_agent,:created_at,:last_seen_at)",
                old_sessions,
            )
            conn.executemany(
                "INSERT INTO user_api_keys (id, username, provider, encrypted_key, last4, created_at) VALUES (:id,:username,:provider,:encrypted_key,:last4,:created_at)",
                old_api_keys,
            )
            conn.execute("PRAGMA foreign_keys = ON")

        conn.commit()
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


# ── Chat conversations ────────────────────────────────────────────────────

def create_chat_conversation(
    conversation_id: str, user_id: str, kb_id: int, title: str, messages: list[dict]
) -> dict:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO chat_conversations (id, user_id, kb_id, title, messages)
               VALUES (?,?,?,?,?)""",
            (conversation_id, user_id, kb_id, title, json.dumps(messages)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, kb_id, title, created_at, updated_at FROM chat_conversations WHERE id=?",
            (conversation_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_chat_conversations(user_id: str, kb_id: int) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT id, kb_id, title, created_at, updated_at
               FROM chat_conversations WHERE user_id=? AND kb_id=?
               ORDER BY updated_at DESC, created_at DESC""",
            (user_id, kb_id),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_chat_conversation(conversation_id: str, user_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM chat_conversations WHERE id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone()
        if not row:
            return None
        conversation = dict(row)
        conversation["messages"] = json.loads(conversation["messages"])
        return conversation
    finally:
        conn.close()


def update_chat_conversation(
    conversation_id: str, user_id: str, messages: list[dict]
) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            """UPDATE chat_conversations
               SET messages=?, updated_at=datetime('now')
               WHERE id=? AND user_id=?""",
            (json.dumps(messages), conversation_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Users ─────────────────────────────────────────────────────────────────

def get_user(username: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_user(username: str, hashed_password: str, full_name: str) -> dict:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO users (username, hashed_password, full_name) VALUES (?,?,?)",
            (username, hashed_password, full_name),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())
    except sqlite3.IntegrityError:
        raise ValueError("Username already taken")
    finally:
        conn.close()


def get_user_by_oauth(provider: str, oauth_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE oauth_provider=? AND oauth_id=?", (provider, oauth_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_oauth_user(
    username: str, full_name: str, provider: str, oauth_id: str, avatar_url: str = ""
) -> dict:
    """Creates a user with no local password — sign-in is only possible via
    the linked OAuth provider. `username` must already be de-duplicated by
    the caller (see main.py's OAuth callback)."""
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO users (username, full_name, oauth_provider, oauth_id, avatar_url)
               VALUES (?,?,?,?,?)""",
            (username, full_name, provider, oauth_id, avatar_url),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())
    except sqlite3.IntegrityError:
        raise ValueError("Username already taken")
    finally:
        conn.close()


def update_user_password(username: str, hashed_password: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET hashed_password=? WHERE username=?", (hashed_password, username)
        )
        conn.commit()
    finally:
        conn.close()


def delete_user(username: str) -> None:
    """Deletes the user row; ON DELETE CASCADE removes their sessions, API keys,
    and knowledge bases (kb_documents cascade from knowledge_bases)."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM knowledge_bases WHERE user_id=?", (username,))
        conn.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()
    finally:
        conn.close()


# ── Sessions ──────────────────────────────────────────────────────────────

def create_session(session_id: str, username: str, user_agent: str = "") -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO user_sessions (id, username, user_agent) VALUES (?,?,?)",
            (session_id, username, user_agent),
        )
        conn.commit()
    finally:
        conn.close()


def touch_session(session_id: str) -> bool:
    """Bumps last_seen_at; returns False if the session no longer exists (revoked)."""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE user_sessions SET last_seen_at=datetime('now') WHERE id=?", (session_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_sessions(username: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM user_sessions WHERE username=? ORDER BY last_seen_at DESC",
            (username,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def revoke_session(session_id: str, username: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM user_sessions WHERE id=? AND username=?", (session_id, username)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def revoke_other_sessions(username: str, keep_session_id: str) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM user_sessions WHERE username=? AND id!=?", (username, keep_session_id)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── API keys ──────────────────────────────────────────────────────────────

def list_api_keys(username: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT provider, last4, created_at FROM user_api_keys WHERE username=? ORDER BY provider",
            (username,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_api_key(username: str, provider: str, encrypted_key: str, last4: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO user_api_keys (username, provider, encrypted_key, last4)
               VALUES (?,?,?,?)
               ON CONFLICT(username, provider)
               DO UPDATE SET encrypted_key=excluded.encrypted_key, last4=excluded.last4""",
            (username, provider, encrypted_key, last4),
        )
        conn.commit()
    finally:
        conn.close()


def get_api_key(username: str, provider: str) -> str | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT encrypted_key FROM user_api_keys WHERE username=? AND provider=?",
            (username, provider),
        ).fetchone()
        return row["encrypted_key"] if row else None
    finally:
        conn.close()


def delete_api_key(username: str, provider: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM user_api_keys WHERE username=? AND provider=?", (username, provider)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
