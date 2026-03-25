"""
Pipeline Orchestrator

Streaming pipeline: collect → score → store (APPLY_NOW + REVIEW only)

Two modes:
  run(collector)                       — sequential, single source
  run_parallel(collector_class, list)  — parallel fetch, 5-10x faster

AI Scoring:
  Pass a scorer= argument (from ScorerFactory) to use an AI backend.
  Falls back to the keyword engine automatically on any AI failure.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, List, Optional, Type

from job_agent.collectors.base import BaseCollector
from job_agent.models import Decision, DiscardLog, RawJob, ScoreResult, ScoredJob
from job_agent.scoring.engine import ScoringEngine
from job_agent.storage.database import Database

logger = logging.getLogger(__name__)


# ── Pipeline Stats ─────────────────────────────────────────────────────────────

@dataclass
class PipelineStats:
    source: str
    collected: int = 0
    scored: int = 0
    apply_now: int = 0
    review: int = 0
    discarded: int = 0
    skipped_duplicate: int = 0
    errors: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def stored(self) -> int:
        return self.apply_now + self.review

    @property
    def elapsed(self) -> str:
        s = int(time.time() - self.started_at)
        m, s = divmod(s, 60)
        return f"{m}m {s:02d}s" if m else f"{s}s"

    def summary(self) -> str:
        return (
            f"[{self.source}] Collected={self.collected} | "
            f"Apply={self.apply_now} Review={self.review} "
            f"Discarded={self.discarded} Dupes={self.skipped_duplicate} "
            f"Errors={self.errors} | {self.elapsed}"
        )


# ── Pipeline ───────────────────────────────────────────────────────────────────

class Pipeline:

    def __init__(
        self,
        db: Database = None,
        dry_run: bool = False,
        printer=None,
        match_limit: int = 0,
        workers: int = 5,
        scorer: Optional[Any] = None,  # ScorerBase instance (AI backend)
    ):
        """
        Args:
            db:          Database instance (created if not provided)
            dry_run:     Score but don't store anything
            printer:     Callable(level, msg) for rich output
            match_limit: Stop after this many stored jobs (apply+review). 0=unlimited
            workers:     Thread count for parallel mode
            scorer:      Optional AI scorer (from ScorerFactory). Falls back to
                         keyword engine if None or on failure.
        """
        self.db = db or Database()
        self.engine = ScoringEngine()          # keyword engine — always available
        self.scorer = scorer                   # optional AI scorer
        self.dry_run = dry_run
        self.match_limit = match_limit
        self.workers = workers
        self.printer = printer or (lambda level, msg: logger.info(msg))

        # Cache the rubric string once — avoid re-building it per job
        self._rubric: Optional[str] = None
        if self.scorer is not None:
            try:
                from job_agent.scoring.rubric import get_standard_rubric
                self._rubric = get_standard_rubric()
            except Exception as e:
                logger.warning(f"Could not build scoring rubric: {e}")
                self.scorer = None  # disable AI scorer if rubric fails

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, collector: BaseCollector) -> PipelineStats:
        """Sequential: one collector, process jobs as they stream in."""
        stats = PipelineStats(source=collector.source_name)
        self.printer("header", f"Starting pipeline — source: {collector.source_name}")
        for raw_job in collector.collect():
            if self._process_job(raw_job, stats):
                break
        self._finalize(stats)
        return stats

    def run_all(self, collectors: List[BaseCollector]) -> List[PipelineStats]:
        """Run multiple collectors sequentially."""
        return [self.run(c) for c in collectors]

    def run_parallel(
        self,
        collector_class: Type[BaseCollector],
        companies: list,
        **collector_kwargs,
    ) -> PipelineStats:
        """
        Parallel fetch of all companies, sequential scoring.

        WHY: Network I/O (fetching) is the bottleneck — parallelize that.
             Scoring is CPU-bound + hits the DB — keep it sequential.

        SPEEDUP: 17 companies × 2s each = 34s sequential → ~4s with 10 workers
        """
        source_name = f"{collector_class.source_name}-parallel"
        stats = PipelineStats(source=source_name)

        self.printer("header",
            f"Starting parallel pipeline — {collector_class.source_name} "
            f"({len(companies)} companies, {self.workers} workers)"
        )

        all_jobs: List[RawJob] = []
        lock = threading.Lock()

        def fetch_one(company):
            try:
                single = collector_class(companies=[company], **collector_kwargs)
                jobs = list(single.collect())
                with lock:
                    all_jobs.extend(jobs)
            except Exception as e:
                logger.warning(f"[parallel] {company}: {e}")

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(fetch_one, c) for c in companies]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    logger.error(f"[parallel] worker error: {e}")
                    stats.errors += 1

        self.printer("counter",
            f"  ── Parallel fetch done: {len(all_jobs)} jobs in {stats.elapsed}"
        )

        for raw_job in all_jobs:
            if self._process_job(raw_job, stats):
                break

        self._finalize(stats)
        return stats

    def score_single(self, raw_job: RawJob) -> ScoredJob:
        """Score one job without storing — for testing/diagnosis."""
        return ScoredJob(raw=raw_job, score_result=self.engine.score(raw_job))

    # ── Internal ───────────────────────────────────────────────────────────────

    def _process_job(self, raw_job: RawJob, stats: PipelineStats) -> bool:
        """
        Score and route one job.

        Returns True if match_limit has been reached (caller should stop).
        """
        stats.collected += 1

        if self.db.job_exists(raw_job.apply_url):
            stats.skipped_duplicate += 1
            self.printer("dupe", f"  ↩  DUPE     {raw_job.company} — {raw_job.role}")
            return False

        try:
            scored = self._score_job(raw_job)
            stats.scored += 1

            if scored.decision == Decision.APPLY_NOW:
                self._store(scored)
                stats.apply_now += 1
                self.printer("apply",
                    f"  ✅ APPLY NOW  [{scored.score_result.score:3d}]  "
                    f"{raw_job.company} — {raw_job.role}  |  {raw_job.location}"
                )
                self.printer("skills",
                    f"     Skills: {', '.join(scored.score_result.matched_skills[:6])}"
                )

            elif scored.decision == Decision.REVIEW:
                self._store(scored)
                stats.review += 1
                self.printer("review",
                    f"  👀 REVIEW     [{scored.score_result.score:3d}]  "
                    f"{raw_job.company} — {raw_job.role}  |  {raw_job.location}"
                )
                self.printer("skills",
                    f"     Skills: {', '.join(scored.score_result.matched_skills[:6])}"
                )

            else:
                self._discard(raw_job, scored)
                stats.discarded += 1
                self.printer("discard",
                    f"  ❌ DISCARD    [{scored.score_result.score:3d}]  "
                    f"{raw_job.company} — {raw_job.role}  |  {raw_job.location}"
                )

            if stats.scored % 25 == 0:
                self.printer("counter",
                    f"  ── {stats.scored} scored  "
                    f"✅ {stats.apply_now}  👀 {stats.review}  "
                    f"❌ {stats.discarded}  ⏱ {stats.elapsed}"
                )

        except Exception as e:
            logger.error(f"Pipeline error {raw_job.company}/{raw_job.role}: {e}")
            self.printer("error", f"  ⚠  ERROR  {raw_job.company} — {raw_job.role}: {e}")
            stats.errors += 1
            return False

        # Stop if stored job limit reached (counts apply_now + review)
        if self.match_limit > 0 and stats.stored >= self.match_limit:
            self.printer("counter",
                f"  ── Match limit reached: {self.match_limit} — stopping early"
            )
            return True

        return False

    def _score_job(self, raw_job: RawJob) -> ScoredJob:
        """
        Score a job using AI scorer if available, else keyword engine.

        The AI scorer requires a dict; RawJob.to_dict() handles the conversion.
        Falls back to keyword engine on any AI failure.
        """
        if self.scorer is not None and self._rubric is not None:
            try:
                # Convert RawJob → dict (scorer.score() expects dict, not RawJob)
                job_dict = raw_job.to_dict()
                ai_result = self.scorer.score(job_dict, self._rubric)

                # Map AI verdict → Decision
                score = ai_result.score
                if score >= 70:
                    decision = Decision.APPLY_NOW
                elif score >= 50:
                    decision = Decision.REVIEW
                else:
                    decision = Decision.DISCARD

                score_result = ScoreResult(
                    score=score,
                    decision=decision,
                    matched_skills=ai_result.reasons[:6],
                    missing_skills=(ai_result.true_blockers + ai_result.learnable_gaps)[:6],
                    explanation=(
                        f"[{ai_result.provider.upper()} {ai_result.model}] "
                        f"{ai_result.verdict} | {ai_result.confidence} confidence"
                    ),
                    skill_breakdown={
                        "role_family":    ai_result.role_family,
                        "verdict":        ai_result.verdict,
                        "confidence":     ai_result.confidence,
                        "true_blockers":  ai_result.true_blockers,
                        "learnable_gaps": ai_result.learnable_gaps,
                    },
                )
                return ScoredJob(raw=raw_job, score_result=score_result)

            except Exception as e:
                logger.warning(f"AI scorer failed, using keyword engine: {e}")
                # Fall through to keyword engine

        # Keyword engine fallback
        return ScoredJob(raw=raw_job, score_result=self.engine.score(raw_job))

    def _store(self, scored: ScoredJob):
        if not self.dry_run:
            self.db.save_job(scored)

    def _discard(self, raw_job: RawJob, scored: ScoredJob):
        if not self.dry_run:
            self.db.log_discard(DiscardLog(
                company=raw_job.company,
                role=raw_job.role,
                score=scored.score_result.score,
                reason=scored.score_result.explanation,
                source=raw_job.source,
                apply_url=raw_job.apply_url,
                date_found=raw_job.date_found,
            ))

    def _finalize(self, stats: PipelineStats):
        if not self.dry_run:
            self.db.log_pipeline_run(
                source=stats.source,
                collected=stats.collected,
                scored=stats.scored,
                apply_now=stats.apply_now,
                review=stats.review,
                discarded=stats.discarded,
                errors=stats.errors,
            )
        self.printer("summary", stats.summary())
