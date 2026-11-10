from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .redact import redact


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure()
        self.connection = sqlite3.connect(str(settings.db_path), timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                request TEXT NOT NULL,
                contract_json TEXT,
                report TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                agent TEXT NOT NULL,
                type TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                producer TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                run_id TEXT,
                name TEXT NOT NULL,
                passed INTEGER NOT NULL,
                detail TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                action TEXT NOT NULL,
                data_json TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
            CREATE INDEX IF NOT EXISTS idx_verifications_task ON verifications(task_id);
            CREATE INDEX IF NOT EXISTS idx_costs_task ON costs(task_id);
            CREATE INDEX IF NOT EXISTS idx_agent_events_agent ON agent_events(agent_id);
            """
        )
        self.connection.commit()
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(verifications)")
        }
        if "run_id" not in columns:
            self.connection.execute(
                "ALTER TABLE verifications ADD COLUMN run_id TEXT"
            )
            self.connection.commit()

    def create_task(self, request: str) -> str:
        task_id = "t_" + uuid.uuid4().hex[:12]
        now = utc_now()
        with self.connection:
            self.connection.execute(
                "INSERT INTO tasks (id, created_at, updated_at, status, request) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, now, now, "created", request),
            )
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_tasks(self, limit: int = 20) -> list[dict]:
        rows = self.connection.execute(
            "SELECT id, created_at, status, request FROM tasks "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_tasks_by_status(self, status: str, limit: int = 50) -> list[dict]:
        rows = self.connection.execute(
            "SELECT id, created_at, status, request FROM tasks "
            "WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, task_id: str, status: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), task_id),
            )

    def save_contract(self, task_id: str, contract_json: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET contract_json = ?, updated_at = ? WHERE id = ?",
                (contract_json, utc_now(), task_id),
            )

    def save_report(self, task_id: str, report: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET report = ?, updated_at = ? WHERE id = ?",
                (report, utc_now(), task_id),
            )

    def add_event(self, task_id: str, agent: str, event_type: str, data: dict) -> dict:
        ts = utc_now()
        payload = json.dumps(data, ensure_ascii=False, default=str)
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO events (task_id, ts, agent, type, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, ts, agent, event_type, payload),
            )
            event_id = cursor.lastrowid
        record = {
            "event_id": event_id,
            "task_id": task_id,
            "ts": ts,
            "agent": agent,
            "type": event_type,
            "data": data,
        }
        line = redact(
            json.dumps(record, ensure_ascii=False, default=str)
        )
        with open(self.settings.ledger_path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return record

    def get_events(self, task_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        return [
            {
                "event_id": row["id"],
                "task_id": row["task_id"],
                "ts": row["ts"],
                "agent": row["agent"],
                "type": row["type"],
                "data": json.loads(row["data_json"]),
            }
            for row in rows
        ]

    def add_artifact(
        self, task_id: str, path: str, data: bytes, sha256: str, producer: str
    ) -> dict:
        artifact_id = "art_" + uuid.uuid4().hex[:12]
        created_at = utc_now()
        stored = self.settings.artifacts_dir / sha256
        if not stored.exists():
            stored.write_bytes(data)
        with self.connection:
            self.connection.execute(
                "INSERT INTO artifacts "
                "(id, task_id, path, sha256, bytes, producer, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, task_id, path, sha256, len(data), producer, created_at),
            )
        return {
            "id": artifact_id,
            "task_id": task_id,
            "path": path,
            "sha256": sha256,
            "bytes": len(data),
            "producer": producer,
            "created_at": created_at,
        }

    def get_artifacts(self, task_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM artifacts WHERE task_id = ? ORDER BY rowid", (task_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def get_artifact_for_path(self, task_id: str, path: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM artifacts WHERE task_id = ? AND path = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (task_id, path),
        ).fetchone()
        return dict(row) if row else None

    def add_verification(
        self,
        task_id: str,
        run_id: str,
        name: str,
        passed: bool,
        detail: str,
        evidence: dict,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO verifications "
                "(task_id, run_id, name, passed, detail, evidence_json, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    run_id,
                    name,
                    int(passed),
                    detail,
                    json.dumps(evidence, ensure_ascii=False, default=str),
                    utc_now(),
                ),
            )

    def get_verifications(
        self, task_id: str, run_id: str | None = None
    ) -> list[dict]:
        if run_id is None:
            latest = self.connection.execute(
                "SELECT run_id FROM verifications "
                "WHERE task_id = ? AND run_id IS NOT NULL "
                "ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if latest is not None:
                run_id = latest["run_id"]
        if run_id is None:
            rows = self.connection.execute(
                "SELECT * FROM verifications WHERE task_id = ? ORDER BY id",
                (task_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM verifications "
                "WHERE task_id = ? AND run_id = ? ORDER BY id",
                (task_id, run_id),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "name": row["name"],
                "passed": bool(row["passed"]),
                "detail": row["detail"],
                "evidence": json.loads(row["evidence_json"]),
                "ts": row["ts"],
            }
            for row in rows
        ]

    def verification_run_count(self, task_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(DISTINCT run_id) FROM verifications "
            "WHERE task_id = ? AND run_id IS NOT NULL",
            (task_id,),
        ).fetchone()
        return int(row[0])

    def add_cost(
        self,
        task_id: str,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO costs "
                "(task_id, agent, model, prompt_tokens, completion_tokens, cost_usd, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    agent,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    utc_now(),
                ),
            )

    def get_costs(self, task_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM costs WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def total_cost(self, task_id: str) -> float:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM costs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return float(row[0])

    def total_tokens(self, task_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) "
            "FROM costs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row[0])

    def cost_summary(self) -> dict:
        total = self.connection.execute(
            "SELECT COALESCE(SUM(cost_usd), 0), "
            "COALESCE(SUM(prompt_tokens + completion_tokens), 0) FROM costs"
        ).fetchone()
        by_agent = [
            dict(row)
            for row in self.connection.execute(
                "SELECT agent, model, "
                "SUM(prompt_tokens) AS prompt_tokens, "
                "SUM(completion_tokens) AS completion_tokens, "
                "SUM(cost_usd) AS cost_usd, COUNT(*) AS calls "
                "FROM costs GROUP BY agent, model ORDER BY cost_usd DESC"
            ).fetchall()
        ]
        recent = [
            dict(row)
            for row in self.connection.execute(
                "SELECT task_id, SUM(cost_usd) AS cost_usd, "
                "SUM(prompt_tokens + completion_tokens) AS tokens, "
                "MAX(ts) AS last_ts FROM costs GROUP BY task_id "
                "ORDER BY last_ts DESC LIMIT 30"
            ).fetchall()
        ]
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat(timespec="seconds")
        monthly = self.connection.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM costs WHERE ts >= ?",
            (month_start,),
        ).fetchone()
        return {
            "total_cost_usd": float(total[0]),
            "total_tokens": int(total[1]),
            "monthly_cost_usd": float(monthly[0]),
            "by_agent": by_agent,
            "recent_tasks": recent,
        }

    def add_agent_event(self, agent_id: str, action: str, data: dict) -> dict:
        ts = utc_now()
        payload = json.dumps(data, ensure_ascii=False, default=str)
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO agent_events (agent_id, action, data_json, ts) "
                "VALUES (?, ?, ?, ?)",
                (agent_id, action, payload, ts),
            )
            event_id = cursor.lastrowid
        record = {
            "event_id": event_id,
            "scope": "agent_registry",
            "agent_id": agent_id,
            "action": action,
            "ts": ts,
            "data": data,
        }
        ledger = self.settings.data_dir / "agent_ledger.jsonl"
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write(redact(json.dumps(record, ensure_ascii=False, default=str)) + "\n")
        return record

    def get_agent_events(self, agent_id: str | None = None, limit: int = 100) -> list[dict]:
        if agent_id:
            rows = self.connection.execute(
                "SELECT * FROM agent_events WHERE agent_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM agent_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "event_id": row["id"],
                "agent_id": row["agent_id"],
                "action": row["action"],
                "data": json.loads(row["data_json"]),
                "ts": row["ts"],
            }
            for row in rows
        ]

    def close(self) -> None:
        self.connection.close()
