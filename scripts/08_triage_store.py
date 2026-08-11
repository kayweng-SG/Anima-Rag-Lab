"""SQLite persistence for bilingual triage results."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional


DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "triage_results.db",
)


class TriageResultStore:
    """Persist triage outcomes with both Chinese and English answer fields."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.getenv("ANIMA_TRIAGE_DB", DEFAULT_DB_PATH)
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS triage_results (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    question TEXT NOT NULL,
                    chief_complaint TEXT,
                    species TEXT,
                    size TEXT,
                    heart_rate_bpm REAL,
                    crt_seconds REAL,
                    rectal_temp_f REAL,
                    rectal_temp_c REAL,
                    map_mmhg REAL,
                    extracted_symptoms_json TEXT NOT NULL DEFAULT '[]',
                    red_light_status TEXT,
                    intercepted INTEGER NOT NULL DEFAULT 0,
                    answer_zh TEXT NOT NULL,
                    answer_en TEXT NOT NULL,
                    recommendation_zh TEXT,
                    recommendation_en TEXT,
                    red_light_json TEXT,
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    retrieval_query TEXT,
                    model_used TEXT,
                    elapsed_ms REAL,
                    request_json TEXT,
                    response_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_triage_results_created_at
                ON triage_results(created_at DESC)
                """
            )

    def save(
        self,
        *,
        request: Dict[str, Any],
        response: Dict[str, Any],
    ) -> str:
        record_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        red_light = response.get("red_light") or {}
        answer_zh = response.get("answer_zh") or response.get("answer") or ""
        answer_en = response.get("answer_en") or response.get("answer") or ""
        recommendation_zh = (
            response.get("recommendation_zh")
            or red_light.get("recommendation_zh")
            or red_light.get("recommendation")
            or ""
        )
        recommendation_en = (
            response.get("recommendation_en")
            or red_light.get("recommendation_en")
            or ""
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO triage_results (
                    id, created_at, question, chief_complaint, species, size,
                    heart_rate_bpm, crt_seconds, rectal_temp_f, rectal_temp_c, map_mmhg,
                    extracted_symptoms_json, red_light_status, intercepted,
                    answer_zh, answer_en, recommendation_zh, recommendation_en,
                    red_light_json, sources_json, retrieval_query, model_used,
                    elapsed_ms, request_json, response_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    record_id,
                    created_at,
                    request.get("question") or "",
                    request.get("chief_complaint") or "",
                    request.get("species"),
                    request.get("size"),
                    request.get("heart_rate_bpm"),
                    request.get("crt_seconds"),
                    request.get("rectal_temp_f"),
                    request.get("rectal_temp_c"),
                    request.get("map_mmhg"),
                    json.dumps(response.get("extracted_symptoms") or [], ensure_ascii=False),
                    response.get("red_light_status"),
                    1 if response.get("intercepted") else 0,
                    answer_zh,
                    answer_en,
                    recommendation_zh,
                    recommendation_en,
                    json.dumps(red_light, ensure_ascii=False) if red_light else None,
                    json.dumps(response.get("sources") or [], ensure_ascii=False),
                    response.get("retrieval_query"),
                    response.get("model_used"),
                    response.get("elapsed_ms"),
                    json.dumps(request, ensure_ascii=False),
                    json.dumps(response, ensure_ascii=False),
                ),
            )
        return record_id

    def get(self, record_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM triage_results WHERE id = ?",
                (record_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM triage_results
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "question": row["question"],
            "chief_complaint": row["chief_complaint"],
            "species": row["species"],
            "size": row["size"],
            "heart_rate_bpm": row["heart_rate_bpm"],
            "crt_seconds": row["crt_seconds"],
            "rectal_temp_f": row["rectal_temp_f"],
            "rectal_temp_c": row["rectal_temp_c"],
            "map_mmhg": row["map_mmhg"],
            "extracted_symptoms": json.loads(row["extracted_symptoms_json"] or "[]"),
            "red_light_status": row["red_light_status"],
            "intercepted": bool(row["intercepted"]),
            "answer_zh": row["answer_zh"],
            "answer_en": row["answer_en"],
            "recommendation_zh": row["recommendation_zh"],
            "recommendation_en": row["recommendation_en"],
            "red_light": json.loads(row["red_light_json"]) if row["red_light_json"] else None,
            "sources": json.loads(row["sources_json"] or "[]"),
            "retrieval_query": row["retrieval_query"],
            "model_used": row["model_used"],
            "elapsed_ms": row["elapsed_ms"],
        }
