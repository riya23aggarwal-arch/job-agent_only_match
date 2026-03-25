"""
Permanent AI Scoring Cache

Stores AI evaluation results keyed by job URL so each job is only ever
sent to the AI once — across all future runs.

Lives at: ~/.job_agent/ai_cache.db
- Separate from jobs.db (never touched by 'rm ~/.job_agent/jobs.db')
- Never exposed in the CLI for clearing
- Survives DB resets, re-runs, everything
- Auto-recreates if somehow deleted — just means re-scoring on next run
- Uses SQLite WAL mode — safe for concurrent reads during parallel scoring
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from job_agent.scoring.base import JobScoringResult

logger = logging.getLogger(__name__)

CACHE_DB_PATH = Path.home() / ".job_agent" / "ai_cache.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_scores (
    apply_url      TEXT PRIMARY KEY,
    company        TEXT,
    role           TEXT,
    provider       TEXT,
    model          TEXT,
    score          INTEGER,
    verdict        TEXT,
    confidence     TEXT,
    role_family    TEXT,
    reasons        TEXT,       -- JSON array
    true_blockers  TEXT,       -- JSON array
    learnable_gaps TEXT,       -- JSON array
    tokens_used    INTEGER DEFAULT 0,
    scored_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ai_scores_url ON ai_scores(apply_url);
"""


class AICache:
    """
    Thread-safe read/write cache for AI scoring results.

    Usage:
        cache = AICache()

        # Before calling AI:
        result = cache.get(job.apply_url)
        if result:
            return result   # free, instant

        # After AI returns:
        cache.put(job.apply_url, job.company, job.role, ai_result)
    """

    def __init__(self, db_path: Path = CACHE_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.debug(f"[cache] Loaded from {self.db_path}")

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent access
        conn.execute("PRAGMA synchronous=NORMAL") # fast enough, safe
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, apply_url: str) -> Optional[JobScoringResult]:
        """
        Return cached AI result for this job URL, or None if not cached.
        tokens_used is set to 0 on cache hits — no new tokens consumed.
        """
        if not apply_url:
            return None
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_scores WHERE apply_url = ?", (apply_url,)
                ).fetchone()
            if not row:
                return None

            result = JobScoringResult(
                role_family=row["role_family"] or "mixed",
                score=int(row["score"]),
                confidence=row["confidence"] or "medium",
                verdict=row["verdict"] or "viable match",
                reasons=json.loads(row["reasons"] or "[]"),
                true_blockers=json.loads(row["true_blockers"] or "[]"),
                learnable_gaps=json.loads(row["learnable_gaps"] or "[]"),
                provider=row["provider"] or "cache",
                model=row["model"],
                tokens_used=0,  # cache hit = 0 new tokens
            )
            logger.debug(
                f"[cache] HIT: {row['company']} — {row['role']} "
                f"({result.score}/100, {result.verdict})"
            )
            return result

        except Exception as e:
            logger.warning(f"[cache] Read error for {apply_url}: {e}")
            return None

    def put(
        self,
        apply_url: str,
        company: str,
        role: str,
        result: JobScoringResult,
    ) -> None:
        """Store an AI result. Silently no-ops on write failure."""
        if not apply_url:
            return
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO ai_scores
                       (apply_url, company, role, provider, model, score,
                        verdict, confidence, role_family, reasons,
                        true_blockers, learnable_gaps, tokens_used)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        apply_url,
                        company,
                        role,
                        result.provider,
                        result.model,
                        result.score,
                        result.verdict,
                        result.confidence,
                        result.role_family,
                        json.dumps(result.reasons),
                        json.dumps(result.true_blockers),
                        json.dumps(result.learnable_gaps),
                        result.tokens_used,
                    ),
                )
            logger.debug(
                f"[cache] STORED: {company} — {role} "
                f"({result.score}/100, {result.verdict})"
            )
        except Exception as e:
            logger.warning(f"[cache] Write error for {apply_url}: {e}")

    def stats(self) -> dict:
        """Return cache statistics."""
        try:
            with self._conn() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM ai_scores"
                ).fetchone()[0]
                by_provider = conn.execute(
                    """SELECT provider, model, COUNT(*) as cnt
                       FROM ai_scores GROUP BY provider, model
                       ORDER BY cnt DESC"""
                ).fetchall()
                total_tokens = conn.execute(
                    "SELECT SUM(tokens_used) FROM ai_scores"
                ).fetchone()[0] or 0
            return {
                "total_cached": total,
                "total_tokens_saved": total_tokens,
                "by_provider": [dict(r) for r in by_provider],
                "db_path": str(self.db_path),
            }
        except Exception:
            return {"total_cached": 0, "total_tokens_saved": 0}

    def has(self, apply_url: str) -> bool:
        """Quick existence check without deserializing."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT 1 FROM ai_scores WHERE apply_url = ?", (apply_url,)
                ).fetchone()
            return row is not None
        except Exception:
            return False
