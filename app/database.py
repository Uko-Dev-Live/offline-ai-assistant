"""SQLite-backed conversation storage. No external DB needed — fully offline."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Create the database file and schema if they do not already exist."""
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()


# ---------- Conversations ----------

def create_conversation(title: str) -> int:
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, now, now),
        )
        conn.commit()
        return cur.lastrowid


def list_conversations() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at "
            "FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_conversation(conv_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        return cur.rowcount > 0


def rename_conversation(conv_id: int, title: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), conv_id),
        )
        conn.commit()
        return cur.rowcount > 0


def touch_conversation(conv_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now(), conv_id),
        )
        conn.commit()


# ---------- Messages ----------

def add_message(conv_id: int, role: str, content: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (conv_id, role, content, _now()),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now(), conv_id),
        )
        conn.commit()
        return cur.lastrowid


def get_messages(conv_id: int, limit: int | None = None) -> list[dict]:
    sql = (
        "SELECT id, role, content, created_at FROM messages "
        "WHERE conversation_id = ? ORDER BY id ASC"
    )
    params: tuple = (conv_id,)
    if limit:
        # Take the most recent N, then return in chronological order.
        sql = (
            "SELECT * FROM (SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?) "
            "ORDER BY id ASC"
        )
        params = (conv_id, limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
