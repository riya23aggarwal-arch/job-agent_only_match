"""
Pipeline Orchestrator

Streaming pipeline: collect → score → store (APPLY_NOW + REVIEW only)

Two modes:
  run(collector)                    — sequential, single source
  run_parallel(collector_class, companies) — parallel company fetching, 5-10x faster
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Type

from job_agent.collectors.base import BaseCollector
from job_agent.models import Decision, DiscardLog, RawJob, ScoredJob
from job_agent.scoring.engine import ScoringEngine
from job_agent.storage.database import Database

logger = logging.getLogger(__name__)


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


class Pipeline:

    def __init__(
        self,
        db: Database = None,
        dry_run: bool = False,
        printer=None,
        match_limit: int = 0,
        workers: int = 5,
    ):
        self.db = db or Database()
        self.engine = ScoringEngine()
        self.dry_run = dry_run
        self.match_limit = match_limit
        self.workers = workers
        self.printer = printer or (lambda level, msg: logger.info(msg))

    # ── Public API ─────────────────────────────────────────────────────────

    def run(self, collector: BaseCollector) -> PipelineStats:
        """Sequential: one collector, process jobs as they stream in."""
        stats = PipelineStats(source=collector.source_name)
        self.printer("header", f"Starting pipeline — source: {collector.source_name}")

        for raw_job in collector.collect():
            if self._process_job(raw_job, stats):
                break  # match_limit reached

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
        Parallel: fetch all companies simultaneously, score sequentially.
        
        HOW IT WORKS:
          - Spawns N worker threads (default 5)
          - Each thread fetches ONE company independently
          - All fetched jobs go into a thread-safe list
          - Main thread scores everything sequentially after all fetches complete
        
        WHY NOT SCORE IN PARALLEL:
          - Scoring is CPU-bound + accesses shared DB — no benefit from parallelism
          - Network I/O (fetching) is the bottleneck — that's what we parallelize
        
        SPEEDUP:
          17 companies × 2s each = 34s sequential
          17 companies with 10 workers = ~4s parallel
        """
        source_name = f"{collector_class.source_name}-parallel"
        stats = PipelineStats(source=source_name)
        
        self.printer("header",
            f"Starting parallel pipeline — source: {collector_class.source_name} "
            f"({len(companies)} companies, {self.workers} workers)"
        )

        # Thread-safe job collection
        all_jobs: List[RawJob] = []
        lock = threading.Lock()

        def fetch_one(company):
            """Fetch jobs from one company. Runs in thread pool."""
            try:
                # Create a single-company collector for this thread
                if isinstance(company, tuple):
                    # Workday: (tenant, wd_num, site, display_name)
                    single = collector_class(companies=[company], **collector_kwargs)
                else:
                    # Greenhouse/Lever: company slug string
                    single = collector_class(companies=[company], **collector_kwargs)
                
                jobs = list(single.collect())
                with lock:
                    all_jobs.extend(jobs)
                logger.debug(f"[parallel] {company}: {len(jobs)} jobs")
            except Exception as e:
                logger.warning(f"[parallel] {company}: {e}")

        # Fetch all companies in parallel
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(fetch_one, c) for c in companies]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"[parallel] worker error: {e}")
                    stats.errors += 1

        self.printer("counter",
            f"  ── Parallel fetch complete: {len(all_jobs)} jobs collected in {stats.elapsed}"
        )

        # Score sequentially
        for raw_job in all_jobs:
            if self._process_job(raw_job, stats):
                break  # match_limit reached

        self._finalize(stats)
        return stats

    def score_single(self, raw_job: RawJob) -> ScoredJob:
        """Score one job without storing — for testing/diagnosis."""
        return ScoredJob(raw=raw_job, score_result=self.engine.score(raw_job))

    # ── Internal ───────────────────────────────────────────────────────────

    def _process_job(self, raw_job: RawJob, stats: PipelineStats) -> bool:
        """
        Score and route one job. Returns True if match_limit reached.
        """
        stats.collected += 1

        if self.db.job_exists(raw_job.apply_url):
            stats.skipped_duplicate += 1
            self.printer("dupe", f"  ↩  DUPE     {raw_job.company} — {raw_job.role}")
            return False

        try:
            scored = ScoredJob(raw=raw_job, score_result=self.engine.score(raw_job))
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

        # Return True to signal early stop
        if self.match_limit > 0 and stats.stored >= self.match_limit:
            self.printer("counter",
                f"  ── Match limit reached: {self.match_limit} — stopping early"
            )
            return True
        return False

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
