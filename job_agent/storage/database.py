"""
Storage layer — SQLite-backed database for job tracking.
Only APPLY_NOW and REVIEW jobs are stored here.
Discards go to a separate log table.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from job_agent.models import (
    ApplicationStatus,
    Decision,
    DiscardLog,
    ScoredJob,
    StoredJob,
)

DEFAULT_DB_PATH = Path.home() / ".job_agent" / "jobs.db"


# ── Schema ─────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    company          TEXT NOT NULL,
    role             TEXT NOT NULL,
    location         TEXT,
    description      TEXT,
    requirements     TEXT,
    apply_url        TEXT,
    source           TEXT,
    date_found       TEXT,
    score            INTEGER,
    decision         TEXT,
    matched_skills   TEXT,   -- JSON array
    missing_skills   TEXT,   -- JSON array
    explanation      TEXT,
    status           TEXT DEFAULT 'shortlisted',
    notes            TEXT DEFAULT '',
    date_applied     TEXT,
    tailored_resume_path  TEXT,
    cover_letter_path     TEXT,
    remote           INTEGER DEFAULT 0,
    salary_range     TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS discard_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT,
    role        TEXT,
    score       INTEGER,
    reason      TEXT,
    source      TEXT,
    apply_url   TEXT,
    date_found  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT DEFAULT (datetime('now')),
    source      TEXT,
    collected   INTEGER DEFAULT 0,
    scored      INTEGER DEFAULT 0,
    apply_now   INTEGER DEFAULT 0,
    review      INTEGER DEFAULT 0,
    discarded   INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS question_answers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question        TEXT NOT NULL,
    question_hash   TEXT UNIQUE,
    answer          TEXT NOT NULL,
    company         TEXT,
    role            TEXT,
    frequency       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
"""


class Database:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Job storage ────────────────────────────────────────────────────────────

    def save_job(self, scored_job: ScoredJob) -> str:
        """Save a APPLY_NOW or REVIEW job. Returns job_id."""
        if scored_job.decision == Decision.DISCARD:
            raise ValueError("Cannot save a discarded job — log it instead.")

        job_id = scored_job.job_id or str(uuid.uuid4())[:8].upper()
        r = scored_job.raw
        s = scored_job.score_result

        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    job_id, company, role, location, description, requirements,
                    apply_url, source, date_found, score, decision,
                    matched_skills, missing_skills, explanation,
                    status, remote, salary_range
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    r.company,
                    r.role,
                    r.location,
                    r.description,
                    r.requirements,
                    r.apply_url,
                    r.source,
                    r.date_found,
                    s.score,
                    s.decision.value,
                    json.dumps(s.matched_skills),
                    json.dumps(s.missing_skills),
                    s.explanation,
                    ApplicationStatus.SHORTLISTED.value,
                    int(r.remote),
                    r.salary_range,
                ),
            )
        return job_id

    def log_discard(self, discard: DiscardLog):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO discard_log (company, role, score, reason, source, apply_url, date_found)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discard.company,
                    discard.role,
                    discard.score,
                    discard.reason,
                    discard.source,
                    discard.apply_url,
                    discard.date_found,
                ),
            )

    # ── Queries ────────────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[StoredJob]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_stored(row) if row else None

    def get_all_jobs(
        self,
        decision: Optional[str] = None,
        status: Optional[str] = None,
        min_score: int = 0,
    ) -> List[StoredJob]:
        query = "SELECT * FROM jobs WHERE score >= ?"
        params: list = [min_score]

        if decision:
            query += " AND decision = ?"
            params.append(decision)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY score DESC, date_found DESC"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_stored(r) for r in rows]

    def get_apply_now(self) -> List[StoredJob]:
        return self.get_all_jobs(decision=Decision.APPLY_NOW.value)

    def get_review(self) -> List[StoredJob]:
        return self.get_all_jobs(decision=Decision.REVIEW.value)

    def update_status(self, job_id: str, status: str, notes: str = ""):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, notes = ? WHERE job_id = ?",
                (status, notes, job_id),
            )

    def mark_applied(self, job_id: str, notes: str = ""):
        with self._conn() as conn:
            conn.execute(
                """UPDATE jobs SET status = 'applied', date_applied = ?, notes = ?
                   WHERE job_id = ?""",
                (datetime.utcnow().isoformat(), notes, job_id),
            )

    def update_resume_path(self, job_id: str, path: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET tailored_resume_path = ? WHERE job_id = ?",
                (path, job_id),
            )

    def update_cover_letter_path(self, job_id: str, path: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET cover_letter_path = ? WHERE job_id = ?",
                (path, job_id),
            )

    def job_exists(self, apply_url: str) -> bool:
        """Check if a job from this URL was already collected."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE apply_url = ?", (apply_url,)
            ).fetchone()
            if row:
                return True
            row = conn.execute(
                "SELECT 1 FROM discard_log WHERE apply_url = ?", (apply_url,)
            ).fetchone()
            return row is not None

    def log_pipeline_run(
        self,
        source: str,
        collected: int,
        scored: int,
        apply_now: int,
        review: int,
        discarded: int,
        errors: int = 0,
    ):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO pipeline_runs
                   (source, collected, scored, apply_now, review, discarded, errors)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source, collected, scored, apply_now, review, discarded, errors),
            )

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            by_decision = conn.execute(
                "SELECT decision, COUNT(*) FROM jobs GROUP BY decision"
            ).fetchall()
            by_status = conn.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            ).fetchall()
            discarded = conn.execute(
                "SELECT COUNT(*) FROM discard_log"
            ).fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(score) FROM jobs"
            ).fetchone()[0]

        return {
            "total_stored": total,
            "discarded_total": discarded,
            "by_decision": {row[0]: row[1] for row in by_decision},
            "by_status": {row[0]: row[1] for row in by_status},
            "average_score": round(avg_score or 0, 1),
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def save_qa(self, question: str, answer: str, company: str = "", role: str = ""):
        """Save or update a Q&A pair."""
        import hashlib
        q_hash = hashlib.md5(question.lower().encode()).hexdigest()
        
        with self._conn() as conn:
            # Check if exists
            existing = conn.execute(
                "SELECT id, frequency FROM question_answers WHERE question_hash = ?",
                (q_hash,)
            ).fetchone()
            
            if existing:
                # Update
                conn.execute(
                    "UPDATE question_answers SET answer = ?, frequency = frequency + 1, updated_at = datetime('now') WHERE question_hash = ?",
                    (answer, q_hash)
                )
            else:
                # Insert
                conn.execute(
                    "INSERT INTO question_answers (question, question_hash, answer, company, role) VALUES (?, ?, ?, ?, ?)",
                    (question, q_hash, answer, company, role)
                )

    def get_qa(self, question: str) -> Optional[str]:
        """Retrieve answer for a question."""
        import hashlib
        q_hash = hashlib.md5(question.lower().encode()).hexdigest()
        
        with self._conn() as conn:
            row = conn.execute(
                "SELECT answer FROM question_answers WHERE question_hash = ?",
                (q_hash,)
            ).fetchone()
            return row["answer"] if row else None

    def list_qa(self) -> list:
        """List all saved Q&A pairs."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT question, answer, frequency, created_at FROM question_answers ORDER BY frequency DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _row_to_stored(row: sqlite3.Row) -> StoredJob:
        return StoredJob(
            job_id=row["job_id"],
            company=row["company"],
            role=row["role"],
            location=row["location"] or "",
            description=row["description"] or "",
            requirements=row["requirements"] or "",
            apply_url=row["apply_url"] or "",
            source=row["source"] or "",
            date_found=row["date_found"] or "",
            score=row["score"],
            decision=row["decision"],
            matched_skills=row["matched_skills"] or "[]",
            missing_skills=row["missing_skills"] or "[]",
            explanation=row["explanation"] or "",
            status=row["status"],
            notes=row["notes"] or "",
            date_applied=row["date_applied"],
            tailored_resume_path=row["tailored_resume_path"],
            cover_letter_path=row["cover_letter_path"],
            remote=bool(row["remote"]),
            salary_range=row["salary_range"],
        )
