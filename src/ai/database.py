"""Chat history database — follows PydanticAI chat_app.py pattern exactly.

Stores ModelMessage objects via ModelMessagesTypeAdapter for full conversation
continuity including tool calls and results.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from concurrent.futures.thread import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter

from src.utils.logging import debug


P_args = Any
R = Any


@dataclass
class Database:
    """SQLite database for chat messages — async via ThreadPoolExecutor.

    Follows the exact pattern from the PydanticAI chat_app.py example.
    """
    con: sqlite3.Connection
    _loop: asyncio.AbstractEventLoop
    _executor: ThreadPoolExecutor

    @classmethod
    def connect(cls, file: Path) -> Database:
        """Synchronous connect."""
        file.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(file), check_same_thread=False)
        cur = con.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, message_list TEXT);"
        )
        con.commit()
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        return cls(con=con, _loop=loop, _executor=ThreadPoolExecutor(max_workers=1))

    async def add_messages(self, messages: bytes) -> None:
        """Store new messages from agent run (bytes from result.new_messages_json())."""
        await self._asyncify(
            self._execute,
            "INSERT INTO messages (message_list) VALUES (?);",
            messages,
            commit=True,
        )

    async def get_messages(self) -> list[ModelMessage]:
        """Load full conversation history as ModelMessage list."""
        c = await self._asyncify(
            self._execute, "SELECT message_list FROM messages ORDER BY id"
        )
        rows = await self._asyncify(c.fetchall)
        messages: list[ModelMessage] = []
        for row in rows:
            msg_data = row[0]
            if isinstance(msg_data, str):
                msg_data = msg_data.encode("utf-8")
            messages.extend(ModelMessagesTypeAdapter.validate_json(msg_data))
        return messages

    async def clear(self) -> int:
        """Clear all messages, return count deleted."""
        c = await self._asyncify(self._execute, "SELECT COUNT(*) FROM messages")
        rows = await self._asyncify(c.fetchone)
        count = rows[0] if rows else 0
        await self._asyncify(self._execute, "DELETE FROM messages", commit=True)
        return count

    def _execute(self, sql: str, *args: Any, commit: bool = False) -> sqlite3.Cursor:
        cur = self.con.cursor()
        cur.execute(sql, args)
        if commit:
            self.con.commit()
        return cur

    async def _asyncify(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, partial(func, **kwargs), *args
        )

    def close(self) -> None:
        self.con.close()
        self._executor.shutdown(wait=False)


# ── Global DB cache per job ───────────────────────────────────────────────────

_dbs: dict[str, Database] = {}


def get_db(job_id: str, output_dir: Path) -> Database:
    """Get or create a Database for a job."""
    if job_id not in _dbs:
        db_path = output_dir / job_id / ".chat_history.sqlite"
        _dbs[job_id] = Database.connect(db_path)
    return _dbs[job_id]


def close_all() -> None:
    for db in _dbs.values():
        db.close()
    _dbs.clear()
