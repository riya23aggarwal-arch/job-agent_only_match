"""
Integration test for the full pipeline:
  collect -> score -> route -> store
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from job_agent.models import Decision, RawJob
from job_agent.pipeline import Pipeline
from job_agent.storage.database import Database
from job_agent.collectors.base import BaseCollector


class MockCollector(BaseCollector):
    """Collector that yields pre-defined test jobs."""
    source_name = "mock"
    rate_limit_seconds = 0

    def __init__(self, jobs):
        self._jobs = jobs

    def _fetch_jobs(self):
        for job in self._jobs:
            yield job


MOCK_JOBS = [
    RawJob(
        company="Cisco", role="Linux Platform Engineer",
        location="San Jose, CA",
        description=(
            "Develop C-based platform subsystems for Linux devices. "
            "Linux internals, device drivers, BSP, kernel debugging, hardware bring-up. "
            "Multithreading, memory management, firmware experience needed."
        ),
        requirements="C, Linux, device drivers, BSP, kernel debugging",
        apply_url="https://cisco.com/jobs/linux-platform-1",
        source="mock",
    ),
    RawJob(
        company="React Corp", role="Frontend React Developer",
        location="New York, NY",
        description="Build React components. Angular, Vue, JavaScript, TypeScript. UI engineer.",
        requirements="React, Angular, JavaScript",
        apply_url="https://reactcorp.com/jobs/frontend-1",
        source="mock",
    ),
    RawJob(
        company="Nvidia", role="Senior Linux Kernel Engineer",
        location="Santa Clara, CA",
        description=(
            "Deep Linux kernel expertise required. Device drivers, firmware, C programming. "
            "Linux internals, kernel debugging, multithreading, memory management, BSP. "
            "Networking and optics platform experience valued. Python automation skills."
        ),
        requirements="C, Linux kernel, device drivers, BSP, firmware",
        apply_url="https://nvidia.com/jobs/kernel-1",
        source="mock",
    ),
    RawJob(
        company="Startup", role="Mobile iOS Developer",
        location="Remote",
        description="iOS app development, Swift, Objective-C, Android experience nice to have.",
        requirements="Swift, iOS, mobile development",
        apply_url="https://startup.com/jobs/ios-1",
        source="mock",
    ),
]


def test_pipeline_routes_correctly():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        pipeline = Pipeline(db=db)
        collector = MockCollector(MOCK_JOBS)
        stats = pipeline.run(collector)

        print(f"  Pipeline stats: collected={stats.collected} apply={stats.apply_now} "
              f"review={stats.review} discarded={stats.discarded}")

        assert stats.collected == 4
        assert stats.discarded >= 2      # React and iOS should be discarded
        assert stats.apply_now + stats.review >= 1  # At least Cisco/Nvidia stored

        stored = db.get_all_jobs()
        discarded_urls = {
            "https://reactcorp.com/jobs/frontend-1",
            "https://startup.com/jobs/ios-1",
        }
        for job in stored:
            assert job.apply_url not in discarded_urls, f"Discarded job was stored: {job.apply_url}"


def test_pipeline_deduplication():
    """Same URL should not be processed twice."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        pipeline = Pipeline(db=db)
        collector = MockCollector(MOCK_JOBS[:1])  # Just Cisco

        stats1 = pipeline.run(collector)
        stats2 = pipeline.run(MockCollector(MOCK_JOBS[:1]))  # Same job again

        assert stats1.collected == 1
        assert stats2.skipped_duplicate == 1, f"Expected duplicate skip, got {stats2}"
        print("  Deduplication works across runs")


def test_pipeline_dry_run():
    """Dry run should score but not store anything."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        pipeline = Pipeline(db=db, dry_run=True)
        collector = MockCollector(MOCK_JOBS)
        pipeline.run(collector)

        stored = db.get_all_jobs()
        assert len(stored) == 0, f"Dry run stored {len(stored)} jobs — should be 0"
        print("  Dry run stores nothing")


def test_pipeline_score_single():
    """score_single() returns ScoredJob without storing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        pipeline = Pipeline(db=db)
        job = MOCK_JOBS[0]  # Cisco Linux Platform Engineer
        result = pipeline.score_single(job)
        assert result.score_result.score > 0
        assert result.decision in Decision.__members__.values()
        stored = db.get_all_jobs()
        assert len(stored) == 0, "score_single() should not store"
        print(f"  score_single(): {result.score_result.score} -> {result.decision}")


if __name__ == "__main__":
    tests = [
        test_pipeline_routes_correctly,
        test_pipeline_deduplication,
        test_pipeline_dry_run,
        test_pipeline_score_single,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  -> PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  -> FAIL: {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
