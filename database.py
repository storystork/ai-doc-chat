
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL UNIQUE,
                  password_hash TEXT ,
                  plan TEXT NOT NULL DEFAULT 'free',
                  created_at TEXT NOT NULL
                );
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  doc_hash TEXT NOT NULL,
                  file_name TEXT NOT NULL,
                  file_mime TEXT,
                  chunk_count INTEGER,
                  created_at TEXT NOT NULL,
                  UNIQUE(user_id, doc_hash),
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  title TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_session_id INTEGER NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  metadata_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(chat_session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
                );
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS query_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  model TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  doc_hash TEXT NOT NULL,
                  file_name TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )

    # -------------------- Users --------------------
    def create_user(self, email: str, password_hash: str) -> int:
        with self.conn() as c:
            c.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, utcnow().isoformat()),
            )
            return int(c.execute("SELECT last_insert_rowid()").fetchone()[0])

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self.conn() as c:
            row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self.conn() as c:
            row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def set_user_plan(self, user_id: int, plan: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))

    # -------------------- Documents --------------------
    def doc_exists(self, user_id: int, doc_hash: str) -> bool:
        with self.conn() as c:
            row = c.execute(
                "SELECT id FROM documents WHERE user_id = ? AND doc_hash = ?",
                (user_id, doc_hash),
            ).fetchone()
            return row is not None

    def add_document(
        self,
        user_id: int,
        doc_hash: str,
        file_name: str,
        file_mime: Optional[str],
        chunk_count: Optional[int],
    ) -> None:
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO documents (user_id, doc_hash, file_name, file_mime, chunk_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, doc_hash, file_name, file_mime, chunk_count, utcnow().isoformat()),
            )

    def list_documents(self, user_id: int) -> List[Dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT id, file_name, file_mime, chunk_count, created_at, doc_hash
                FROM documents
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_document(self, user_id: int, doc_hash: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM documents WHERE user_id = ? AND doc_hash = ?", (user_id, doc_hash))

    # -------------------- Chat Sessions --------------------
    def create_chat_session(self, user_id: int, title: str) -> int:
        with self.conn() as c:
            c.execute(
                "INSERT INTO chat_sessions (user_id, title, created_at) VALUES (?, ?, ?)",
                (user_id, title, utcnow().isoformat()),
            )
            return int(c.execute("SELECT last_insert_rowid()").fetchone()[0])

    def list_chat_sessions(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT id, title, created_at
                FROM chat_sessions
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_chat_sessions(self, user_id: int, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        q = f"%{query.strip()}%"
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT cs.id, cs.title, cs.created_at
                FROM chat_sessions cs
                WHERE cs.user_id = ?
                  AND (
                    cs.title LIKE ?
                    OR EXISTS (
                      SELECT 1 FROM chat_messages cm
                      WHERE cm.chat_session_id = cs.id
                        AND cm.content LIKE ?
                    )
                  )
                ORDER BY cs.created_at DESC
                LIMIT ?
                """,
                (user_id, q, q, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chat_messages(self, chat_session_id: int) -> List[Dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                """
                SELECT role, content, metadata_json, created_at
                FROM chat_messages
                WHERE chat_session_id = ?
                ORDER BY created_at ASC
                """,
                (chat_session_id,),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                md = r["metadata_json"]
                out.append(
                    {
                        "role": r["role"],
                        "content": r["content"],
                        "metadata": json.loads(md) if md else None,
                        "created_at": r["created_at"],
                    }
                )
            return out

    def save_chat_message(
        self,
        chat_session_id: int,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata_json = json.dumps(metadata) if metadata else None
        with self.conn() as c:
            c.execute(
                """
                INSERT INTO chat_messages (chat_session_id, role, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_session_id, role, content, metadata_json, utcnow().isoformat()),
            )

    def delete_chat_session(self, user_id: int, chat_session_id: int) -> None:
        with self.conn() as c:
            c.execute(
                """
                DELETE FROM chat_sessions
                WHERE id = ? AND user_id = ?
                """,
                (chat_session_id, user_id),
            )

    # -------------------- Usage / Limits --------------------
    def log_query(self, user_id: int, model: Optional[str]) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO query_logs (user_id, created_at, model) VALUES (?, ?, ?)",
                (user_id, utcnow().isoformat(), model),
            )

    def log_upload(self, user_id: int, doc_hash: str, file_name: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO upload_logs (user_id, created_at, doc_hash, file_name) VALUES (?, ?, ?, ?)",
                (user_id, utcnow().isoformat(), doc_hash, file_name),
            )

    def _date_key_utc(self) -> str:
        return utcnow().date().isoformat()

    def count_today_queries(self, user_id: int) -> int:
        # Count by UTC date boundary.
        day = self._date_key_utc()
        with self.conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) as cnt
                FROM query_logs
                WHERE user_id = ?
                  AND substr(created_at, 1, 10) = ?
                """,
                (user_id, day),
            ).fetchone()
            return int(row["cnt"]) if row else 0

    def count_today_uploads(self, user_id: int) -> int:
        day = self._date_key_utc()
        with self.conn() as c:
            row = c.execute(
                """
                SELECT COUNT(*) as cnt
                FROM upload_logs
                WHERE user_id = ?
                  AND substr(created_at, 1, 10) = ?
                """,
                (user_id, day),
            ).fetchone()
            return int(row["cnt"]) if row else 0

    # -------------------- Analytics --------------------
    def get_dashboard_stats(self, user_id: int) -> Dict[str, Any]:
        with self.conn() as c:
            total_docs = c.execute(
                "SELECT COUNT(*) as cnt FROM documents WHERE user_id = ?",
                (user_id,),
            ).fetchone()["cnt"]
            total_queries_today = self.count_today_queries(user_id)
            return {
                "total_docs": int(total_docs),
                "total_queries_today": int(total_queries_today),
            }

