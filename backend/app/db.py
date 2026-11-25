"""SQLite database layer – async via aiosqlite, WAL mode, parameterized queries."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);
"""


async def _get_conn() -> aiosqlite.Connection:
    """Return a NEW connection (caller must close)."""
    db_path = settings.db_path
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db() -> None:
    """Create tables + indexes if they don't exist."""
    conn = await _get_conn()
    try:
        await conn.executescript(_SCHEMA)
        await conn.commit()
    finally:
        await conn.close()


async def check_db() -> bool:
    """Quick health probe."""
    try:
        conn = await _get_conn()
        try:
            await conn.execute("SELECT 1")
            return True
        finally:
            await conn.close()
    except Exception:
        return False


# ── Sessions ──────────────────────────────────────────────────────────────────

async def get_session_prompt(session_id: str) -> Optional[str]:
    conn = await _get_conn()
    try:
        cursor = await conn.execute(
            "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return row["system_prompt"]
    finally:
        await conn.close()


async def session_exists(session_id: str) -> bool:
    conn = await _get_conn()
    try:
        cursor = await conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        )
        return (await cursor.fetchone()) is not None
    finally:
        await conn.close()


async def upsert_session(session_id: str, system_prompt: Optional[str] = None) -> None:
    conn = await _get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT INTO sessions (session_id, system_prompt, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt)""",
            (session_id, system_prompt, now),
        )
        await conn.commit()
    finally:
        await conn.close()


# ── Messages ──────────────────────────────────────────────────────────────────

async def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    conn = await _get_conn()
    try:
        cursor = await conn.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            msg: Dict[str, Any] = {"role": r["role"], "content": r["content"]}
            if r["metadata"]:
                msg["metadata"] = json.loads(r["metadata"])
            result.append(msg)
        return result
    finally:
        await conn.close()


async def save_turn(
    session_id: str,
    user_content: str,
    assistant_content: str,
    metadata: Dict[str, Any],
    system_prompt: Optional[str] = None,
) -> None:
    """Persist user + assistant messages in one transaction, ensuring session exists."""
    conn = await _get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        # Ensure session row exists
        await conn.execute(
            """INSERT INTO sessions (session_id, system_prompt, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt)""",
            (session_id, system_prompt, now),
        )
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, "user", user_content, None, now),
        )
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, "assistant", assistant_content, json.dumps(metadata), now),
        )
        await conn.commit()
    finally:
        await conn.close()
