"""Хранилище сообщений и бизнес-подключений на SQLite (aiosqlite)."""
from __future__ import annotations

import os
import time
from asyncio import Lock
from dataclasses import dataclass

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    connection_id TEXT PRIMARY KEY,
    owner_id      INTEGER NOT NULL,
    user_chat_id  INTEGER,
    is_enabled    INTEGER NOT NULL DEFAULT 1,
    can_reply     INTEGER NOT NULL DEFAULT 0,
    updated       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    connection_id TEXT NOT NULL,
    chat_id       INTEGER NOT NULL,
    message_id    INTEGER NOT NULL,
    from_id       INTEGER,
    from_name     TEXT,
    chat_title    TEXT,
    outgoing      INTEGER NOT NULL DEFAULT 0,
    text          TEXT,
    media_type    TEXT,
    file_id       TEXT,
    forward_from  TEXT,
    date          INTEGER NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conn ON messages(connection_id);
"""


@dataclass(slots=True)
class StoredMessage:
    connection_id: str
    chat_id: int
    message_id: int
    from_id: int | None
    from_name: str | None
    chat_title: str | None
    outgoing: bool
    text: str | None
    media_type: str | None
    file_id: str | None
    date: int
    forward_from: str | None = None


@dataclass(slots=True)
class ConnectionOwner:
    owner_id: int
    user_chat_id: int | None


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = Lock()

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        # Unicode-регистронезависимость: встроенные LOWER/NOCASE в SQLite
        # сворачивают только ASCII, поэтому регистрируем Python-функцию.
        await self._db.create_function(
            "pylower", 1, lambda s: s.lower() if s else s, deterministic=True
        )
        await self._db.executescript(SCHEMA)
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        """Лёгкие миграции для баз, созданных старой версией."""
        assert self._db is not None
        cur = await self._db.execute("PRAGMA table_info(messages)")
        cols = {row["name"] for row in await cur.fetchall()}
        if "forward_from" not in cols:
            await self._db.execute("ALTER TABLE messages ADD COLUMN forward_from TEXT")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # --- Подключения -------------------------------------------------------
    async def save_connection(
        self,
        connection_id: str,
        owner_id: int,
        user_chat_id: int | None,
        is_enabled: bool,
        can_reply: bool,
    ) -> None:
        assert self._db is not None
        async with self._lock:
            await self._db.execute(
                """
                INSERT INTO connections
                    (connection_id, owner_id, user_chat_id, is_enabled, can_reply, updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    owner_id     = excluded.owner_id,
                    user_chat_id = excluded.user_chat_id,
                    is_enabled   = excluded.is_enabled,
                    can_reply    = excluded.can_reply,
                    updated      = excluded.updated
                """,
                (
                    connection_id,
                    owner_id,
                    user_chat_id,
                    int(is_enabled),
                    int(can_reply),
                    int(time.time()),
                ),
            )
            await self._db.commit()

    async def get_owner(self, connection_id: str) -> ConnectionOwner | None:
        assert self._db is not None
        async with self._lock:
            cur = await self._db.execute(
                "SELECT owner_id, user_chat_id FROM connections WHERE connection_id = ?",
                (connection_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return ConnectionOwner(owner_id=row["owner_id"], user_chat_id=row["user_chat_id"])

    async def list_connections(self, owner_id: int) -> list[aiosqlite.Row]:
        assert self._db is not None
        async with self._lock:
            cur = await self._db.execute(
                "SELECT * FROM connections WHERE owner_id = ? ORDER BY updated DESC",
                (owner_id,),
            )
            return list(await cur.fetchall())

    # --- Сообщения ---------------------------------------------------------
    async def save_message(self, msg: StoredMessage) -> None:
        assert self._db is not None
        async with self._lock:
            await self._db.execute(
                """
                INSERT INTO messages
                    (connection_id, chat_id, message_id, from_id, from_name,
                     chat_title, outgoing, text, media_type, file_id,
                     forward_from, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    text         = excluded.text,
                    media_type   = excluded.media_type,
                    file_id      = excluded.file_id,
                    from_id      = excluded.from_id,
                    from_name    = excluded.from_name,
                    chat_title   = excluded.chat_title,
                    forward_from = excluded.forward_from
                """,
                (
                    msg.connection_id,
                    msg.chat_id,
                    msg.message_id,
                    msg.from_id,
                    msg.from_name,
                    msg.chat_title,
                    int(msg.outgoing),
                    msg.text,
                    msg.media_type,
                    msg.file_id,
                    msg.forward_from,
                    msg.date,
                ),
            )
            await self._db.commit()

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> StoredMessage:
        return StoredMessage(
            connection_id=row["connection_id"],
            chat_id=row["chat_id"],
            message_id=row["message_id"],
            from_id=row["from_id"],
            from_name=row["from_name"],
            chat_title=row["chat_title"],
            outgoing=bool(row["outgoing"]),
            text=row["text"],
            media_type=row["media_type"],
            file_id=row["file_id"],
            date=row["date"],
            forward_from=row["forward_from"],
        )

    async def get_message(self, chat_id: int, message_id: int) -> StoredMessage | None:
        assert self._db is not None
        async with self._lock:
            cur = await self._db.execute(
                "SELECT * FROM messages WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            )
            row = await cur.fetchone()
        return self._row_to_message(row) if row is not None else None

    async def search_messages(
        self, owner_id: int, query: str, limit: int = 20
    ) -> list[StoredMessage]:
        """Поиск по тексту сохранённых сообщений (регистронезависимо)."""
        assert self._db is not None
        pattern = f"%{query}%"
        async with self._lock:
            cur = await self._db.execute(
                """
                SELECT * FROM messages
                WHERE connection_id IN (
                    SELECT connection_id FROM connections WHERE owner_id = ?
                )
                  AND text IS NOT NULL
                  AND pylower(text) LIKE pylower(?)
                ORDER BY date DESC
                LIMIT ?
                """,
                (owner_id, pattern, limit),
            )
            rows = await cur.fetchall()
        return [self._row_to_message(r) for r in rows]

    async def all_messages(self, owner_id: int) -> list[StoredMessage]:
        """Все сохранённые сообщения владельца для экспорта (по чату, затем по времени)."""
        assert self._db is not None
        async with self._lock:
            cur = await self._db.execute(
                """
                SELECT * FROM messages
                WHERE connection_id IN (
                    SELECT connection_id FROM connections WHERE owner_id = ?
                )
                ORDER BY chat_title, date
                """,
                (owner_id,),
            )
            rows = await cur.fetchall()
        return [self._row_to_message(r) for r in rows]

    def db_size_bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    async def distinct_owners(self) -> list[int]:
        assert self._db is not None
        async with self._lock:
            cur = await self._db.execute("SELECT DISTINCT owner_id FROM connections")
            return [row["owner_id"] for row in await cur.fetchall()]

    async def clear_messages(self, owner_id: int) -> tuple[int, int]:
        """Удаляет сообщения владельца, но ОСТАВЛЯЕТ подключение. Сжимает БД.

        Для авто-обслуживания: освобождает место, бот продолжает работать без
        переподключения. Возвращает (удалено сообщений, освобождено байт).
        """
        assert self._db is not None

        def _size() -> int:
            try:
                return os.path.getsize(self.path)
            except OSError:
                return 0

        size_before = _size()
        async with self._lock:
            cur = await self._db.execute(
                """
                SELECT COUNT(*) AS c FROM messages
                WHERE connection_id IN (
                    SELECT connection_id FROM connections WHERE owner_id = ?
                )
                """,
                (owner_id,),
            )
            count = int((await cur.fetchone())["c"])
            await self._db.execute(
                """
                DELETE FROM messages
                WHERE connection_id IN (
                    SELECT connection_id FROM connections WHERE owner_id = ?
                )
                """,
                (owner_id,),
            )
            await self._db.commit()
            await self._db.execute("VACUUM")
            await self._db.commit()
            size_after = _size()
        return count, max(0, size_before - size_after)

    async def wipe_all(self) -> tuple[int, int, int]:
        """Полностью очищает БД: ВСЕ сообщения и ВСЕ подключения, затем VACUUM.

        Это «чистый лист»: на сервере не остаётся ни переписки, ни записи о
        подключении. Бот восстановит подключение сам (getBusinessConnection)
        при следующем событии. Возвращает (сообщений, подключений, байт освобождено).
        """
        assert self._db is not None

        def _size() -> int:
            try:
                return os.path.getsize(self.path)
            except OSError:
                return 0

        size_before = _size()
        async with self._lock:
            cur = await self._db.execute("SELECT COUNT(*) AS c FROM messages")
            msg_count = int((await cur.fetchone())["c"])
            cur = await self._db.execute("SELECT COUNT(*) AS c FROM connections")
            conn_count = int((await cur.fetchone())["c"])

            await self._db.execute("DELETE FROM messages")
            await self._db.execute("DELETE FROM connections")
            await self._db.commit()

            # VACUUM нельзя внутри транзакции — после commit() она закрыта.
            await self._db.execute("VACUUM")
            await self._db.commit()
            size_after = _size()

        freed = max(0, size_before - size_after)
        return msg_count, conn_count, freed

    async def count_messages(self, owner_id: int) -> int:
        assert self._db is not None
        async with self._lock:
            cur = await self._db.execute(
                """
                SELECT COUNT(*) AS c FROM messages
                WHERE connection_id IN (
                    SELECT connection_id FROM connections WHERE owner_id = ?
                )
                """,
                (owner_id,),
            )
            row = await cur.fetchone()
        return int(row["c"]) if row else 0
