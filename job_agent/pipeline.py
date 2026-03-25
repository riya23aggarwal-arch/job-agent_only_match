"""
Pipeline Orchestrator

Streaming pipeline: collect → score → store (APPLY_NOW + REVIEW only)

Two fetch modes:
  run(collector)                       — sequential, single source
  run_parallel(collector_class, list)  — parallel fetch + parallel AI scoring

AI Scoring:
  - Pass scorer= (from ScorerFactory) to use an AI backend
  - Results are cached permanently in ~/.job_agent/ai_cache.db
  - Cache hits are free (0 tokens, instant)
  - Scoring is parallelised — multiple API calls fire simultaneously
  - Falls back to the keyword engine automatically on any AI failure
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple, Type

from job_agent.collectors.base import BaseCollector
from job_agent.models import Decision, DiscardLog, RawJob, ScoreResult, ScoredJob
from job_agent.scoring.engine import ScoringEngine
from job_agent.storage.database import Database

logger = logging.getLogger(__name__)

# Number of parallel scoring threads. Keep ≤ 10 to stay well under
# OpenAI's rate limits (gpt-4o-mini: 500 RPM on tier-1).
_SCORE_WORKERS = 8


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
    tokens_used: int = 0        # live API tokens this run
    cache_hits: int = 0         # jobs answered from cache (no API call)
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
        cache_str = f" Cache={self.cache_hits}" if self.cache_hits else ""
        return (
            f"[{self.source}] Collected={self.collected} | "
            f"Apply={self.apply_now} Review={self.review} "
            f"Discarded={self.discarded} Dupes={self.skipped_duplicate} "
            f"Errors={self.errors}{cache_str} | {self.elapsed}"
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
        scorer: Optional[Any] = None,
    ):
        """
        Args:
            db:          Database instance (created if not provided)
            dry_run:     Score but don't store anything
            printer:     Callable(level, msg) for rich output
            match_limit: Stop after this many APPLY_NOW jobs. 0 = unlimited
            workers:     Thread count for parallel company fetching
            scorer:      Optional AI scorer (from ScorerFactory). Falls back to
                         keyword engine if None or on any failure.
        """
        self.db          = db or Database()
        self.engine      = ScoringEngine()   # keyword engine, always available
        self.scorer      = scorer
        self.dry_run     = dry_run
        self.match_limit = match_limit
        self.workers     = workers
        self.printer     = printer or (lambda level, msg: logger.info(msg))

        # Cache — loaded once, shared across all scoring threads
        self._cache = None
        if self.scorer is not None:
            try:
                from job_agent.scoring.ai_cache import AICache
                self._cache = AICache()
                cs = self._cache.stats()
                logger.info(
                    f"[cache] {cs['total_cached']} jobs cached "
                    f"(~{cs['total_tokens_saved']:,} tokens saved)"
                )
            except Exception as e:
                logger.warning(f"Could not load AI cache: {e}")

        # Build rubric once — shared across all scoring threads (read-only)
        self._rubric: Optional[str] = None
        if self.scorer is not None:
            try:
                from job_agent.scoring.rubric import get_standard_rubric
                self._rubric = get_standard_rubric()
            except Exception as e:
                logger.warning(f"Could not build scoring rubric: {e}")
                self.scorer = None

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
        Phase 1 — Parallel fetch:  all companies fetched simultaneously
        Phase 2 — Parallel score:  all AI calls fired simultaneously
        Phase 3 — Sequential store: DB writes + match_limit (thread-safe)

        Speedup example:
          100 jobs × 1.5s each sequential = 150s
          100 jobs with 8 parallel scorers = ~20s
        """
        source_name = f"{collector_class.source_name}-parallel"
        stats = PipelineStats(source=source_name)

        self.printer("header",
            f"Starting parallel pipeline — {collector_class.source_name} "
            f"({len(companies)} companies, {self.workers} workers)"
        )

        # ── Phase 1: Fetch ───────────────────────────────────────────────
        all_jobs: List[RawJob] = []
        lock = threading.Lock()

        def fetch_one(company):
            try:
                single = collector_class(companies=[company], **collector_kwargs)
                jobs = list(single.collect())
                with lock:
                    all_jobs.extend(jobs)
            except Exception as e:
                logger.warning(f"[parallel] fetch {company}: {e}")

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(fetch_one, c) for c in companies]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    logger.error(f"[parallel] worker error: {e}")
                    stats.errors += 1

        self.printer("counter",
            f"  ── Fetch done: {len(all_jobs)} jobs in {stats.elapsed}"
        )

        # ── Phase 2: Score in parallel ───────────────────────────────────
        # Filter dupes first (fast, no API) — no point scoring already-seen jobs
        to_score: List[RawJob] = []
        for job in all_jobs:
            stats.collected += 1
            if self.db.job_exists(job.apply_url):
                stats.skipped_duplicate += 1
                self.printer("dupe", f"  ↩  DUPE     {job.company} — {job.role}")
            else:
                to_score.append(job)

        if to_score:
            scored_pairs = self._score_jobs_parallel(to_score, stats)
        else:
            scored_pairs = []

        # ── Phase 3: Store sequentially ──────────────────────────────────
        stop = False
        for raw_job, scored in scored_pairs:
            if stop:
                break
            if scored is None:
                stats.errors += 1
                continue
            stop = self._route_job(raw_job, scored, stats)

        self._finalize(stats)
        return stats

    def score_single(self, raw_job: RawJob) -> ScoredJob:
        """Score one job without storing — for testing/diagnosis."""
        return ScoredJob(raw=raw_job, score_result=self.engine.score(raw_job))

    # ── Parallel scoring ───────────────────────────────────────────────────────

    def _score_jobs_parallel(
        self,
        jobs: List[RawJob],
        stats: PipelineStats,
    ) -> List[Tuple[RawJob, Optional[ScoredJob]]]:
        """
        Score all jobs using a thread pool.

        Returns list of (raw_job, scored_job) in original order.
        scored_job is None if scoring failed for that job.

        Cache hits are resolved before the thread pool — they don't consume
        a thread slot since there's no I/O to do.
        """
        results: List[Tuple[RawJob, Optional[ScoredJob]]] = [None] * len(jobs)

        # Separate cache hits from jobs that need an API call
        need_api: List[Tuple[int, RawJob]] = []   # (original_index, job)

        for i, raw_job in enumerate(jobs):
            cached = self._try_cache_get(raw_job)
            if cached is not None:
                stats.cache_hits += 1
                results[i] = (raw_job, cached)
            else:
                need_api.append((i, raw_job))

        if self._cache and need_api:
            cache_hits = stats.cache_hits
            logger.info(
                f"[cache] {cache_hits} hits / {len(need_api)} need API call"
            )

        if not need_api:
            return results

        # Fire API calls in parallel
        def score_one(idx_job: Tuple[int, RawJob]):
            idx, raw_job = idx_job
            try:
                scored = self._score_job_api(raw_job)
                return idx, raw_job, scored
            except Exception as e:
                logger.error(
                    f"[parallel] score error "
                    f"{raw_job.company}/{raw_job.role}: {e}"
                )
                self.printer(
                    "error",
                    f"  ⚠  SCORE ERROR  {raw_job.company} — {raw_job.role}: {e}"
                )
                return idx, raw_job, None

        with ThreadPoolExecutor(max_workers=_SCORE_WORKERS) as pool:
            futures = {pool.submit(score_one, item): item for item in need_api}
            for fut in as_completed(futures):
                idx, raw_job, scored = fut.result()
                results[idx] = (raw_job, scored)

        return results

    # ── Sequential pipeline (used by run()) ───────────────────────────────────

    def _process_job(self, raw_job: RawJob, stats: PipelineStats) -> bool:
        """Score + route one job. Returns True if match_limit reached."""
        stats.collected += 1

        if self.db.job_exists(raw_job.apply_url):
            stats.skipped_duplicate += 1
            self.printer("dupe", f"  ↩  DUPE     {raw_job.company} — {raw_job.role}")
            return False

        try:
            # Try cache first
            cached = self._try_cache_get(raw_job)
            if cached is not None:
                stats.cache_hits += 1
                scored = cached
            else:
                scored = self._score_job_api(raw_job)

            return self._route_job(raw_job, scored, stats)

        except Exception as e:
            logger.error(f"Pipeline error {raw_job.company}/{raw_job.role}: {e}")
            self.printer("error", f"  ⚠  ERROR  {raw_job.company} — {raw_job.role}: {e}")
            stats.errors += 1
            return False

    # ── Core scoring logic ─────────────────────────────────────────────────────

    def _try_cache_get(self, raw_job: RawJob) -> Optional[ScoredJob]:
        """
        Return a ScoredJob from cache if available, else None.
        Does NOT touch the API or the keyword engine.
        """
        if self._cache is None or self.scorer is None:
            return None
        cached_ai = self._cache.get(raw_job.apply_url)
        if cached_ai is None:
            return None

        score = cached_ai.score
        if score >= 70:
            decision = Decision.APPLY_NOW
        elif score >= 50:
            decision = Decision.REVIEW
        else:
            decision = Decision.DISCARD

        score_result = ScoreResult(
            score=score,
            decision=decision,
            matched_skills=cached_ai.reasons[:6],
            missing_skills=(cached_ai.true_blockers + cached_ai.learnable_gaps)[:6],
            explanation=(
                f"[{cached_ai.provider.upper()} {cached_ai.model}] "
                f"{cached_ai.verdict} | {cached_ai.confidence} confidence"
                f" [CACHED]"
            ),
            skill_breakdown={
                "role_family":    cached_ai.role_family,
                "verdict":        cached_ai.verdict,
                "confidence":     cached_ai.confidence,
                "true_blockers":  cached_ai.true_blockers,
                "learnable_gaps": cached_ai.learnable_gaps,
                "tokens_used":    0,  # cache hit
            },
        )
        logger.info(
            f"[cache] ♻  {raw_job.company} — {raw_job.role} "
            f"({score}/100, {cached_ai.verdict})"
        )
        return ScoredJob(raw=raw_job, score_result=score_result)

    def _score_job_api(self, raw_job: RawJob) -> ScoredJob:
        """
        Score using AI scorer (if configured) or keyword engine.
        Writes result to cache on success.
        Thread-safe: only reads self.scorer and self._rubric (immutable after init).
        """
        if self.scorer is not None and self._rubric is not None:
            try:
                job_dict = raw_job.to_dict()
                ai_result = self.scorer.score(job_dict, self._rubric)

                # Write to permanent cache immediately
                if self._cache is not None:
                    self._cache.put(
                        raw_job.apply_url,
                        raw_job.company,
                        raw_job.role,
                        ai_result,
                    )

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
                        "tokens_used":    ai_result.tokens_used,
                    },
                )

                # ── AI Result Banner ──────────────────────────────────────
                verdict_emoji = {
                    "strong match": "🟢", "good match": "🟡",
                    "viable match": "🟡", "stretch": "🟠", "weak match": "🔴",
                }.get(ai_result.verdict, "⚪")
                decision_emoji = {
                    Decision.APPLY_NOW: "✅",
                    Decision.REVIEW:    "👀",
                    Decision.DISCARD:   "❌",
                }.get(decision, "?")
                reasons_str  = " | ".join(ai_result.reasons[:3]) or "—"
                blockers_str = " | ".join(ai_result.true_blockers[:2]) or "none"
                gaps_str     = " | ".join(ai_result.learnable_gaps[:2]) or "none"
                logger.info(
                    f"\n"
                    f"  ┌─ 🤖 AI SCORED ───────────────────────────────────────────\n"
                    f"  │  {raw_job.company} — {raw_job.role}\n"
                    f"  │  Score:    {score}/100  {verdict_emoji} {ai_result.verdict.upper()}  ({ai_result.confidence} confidence)\n"
                    f"  │  Decision: {decision_emoji} {decision.value.upper()}\n"
                    f"  │  Family:   {ai_result.role_family}\n"
                    f"  │  Reasons:  {reasons_str}\n"
                    f"  │  Blockers: {blockers_str}\n"
                    f"  │  Gaps:     {gaps_str}\n"
                    f"  │  Tokens:   {ai_result.tokens_used}  (cached for future runs)\n"
                    f"  │  Model:    {ai_result.provider} / {ai_result.model}\n"
                    f"  └──────────────────────────────────────────────────────────"
                )
                # ─────────────────────────────────────────────────────────
                return ScoredJob(raw=raw_job, score_result=score_result)

            except Exception as e:
                logger.warning(f"AI scorer failed, using keyword engine: {e}")

        # Keyword engine fallback
        return ScoredJob(raw=raw_job, score_result=self.engine.score(raw_job))

    # ── Routing + storage ──────────────────────────────────────────────────────

    def _route_job(
        self,
        raw_job: RawJob,
        scored: ScoredJob,
        stats: PipelineStats,
    ) -> bool:
        """
        Store/discard a scored job and update stats.
        Returns True if match_limit has been reached.
        """
        stats.scored += 1
        stats.tokens_used += scored.score_result.skill_breakdown.get("tokens_used", 0)

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

        # Stop when APPLY_NOW limit reached
        if self.match_limit > 0 and stats.apply_now >= self.match_limit:
            self.printer("counter",
                f"  ── Match limit reached: {self.match_limit} APPLY_NOW — stopping early"
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
