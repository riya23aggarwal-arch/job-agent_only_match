"""
Tests for the database layer.
"""

import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from job_agent.models import Decision, DiscardLog, RawJob, ScoreResult, ScoredJob
from job_agent.storage.database import Database


def make_scored_job(score=85, decision=Decision.REVIEW, company="Cisco", role="Linux Engineer") -> ScoredJob:
    raw = RawJob(
        company=company, role=role,
        location="San Jose, CA",
        description="Linux kernel debugging, C, device drivers",
        requirements="C, Linux, drivers",
        apply_url=f"https://example.com/{company.lower()}/{role.replace(' ', '-').lower()}",
        source="test",
    )
    result = ScoreResult(
        score=score,
        decision=decision,
        matched_skills=["c", "linux internals", "device drivers"],
        missing_skills=["bsp"],
        explanation=f"Score {score} — good match",
    )
    return ScoredJob(raw=raw, score_result=result)


def test_save_and_retrieve():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        job = make_scored_job(score=92, decision=Decision.APPLY_NOW)
        job_id = db.save_job(job)

        retrieved = db.get_job(job_id)
        assert retrieved is not None
        assert retrieved.company == "Cisco"
        assert retrieved.score == 92
        assert retrieved.decision == "apply_now"
        assert retrieved.status == "shortlisted"
        print(f"  Saved and retrieved: {job_id}")


def test_discard_not_stored():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        job = make_scored_job(score=40, decision=Decision.DISCARD)
        try:
            db.save_job(job)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print("  Discard correctly rejected from save_job()")


def test_discard_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        discard = DiscardLog(
            company="Acme", role="iOS Dev",
            score=10, reason="No C/Linux match",
            source="test", apply_url="https://example.com/ios",
        )
        db.log_discard(discard)
        stats = db.get_stats()
        assert stats["discarded_total"] == 1
        print("  Discard log works")


def test_dedup_by_url():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        job = make_scored_job()
        db.save_job(job)
        assert db.job_exists(job.raw.apply_url)
        assert not db.job_exists("https://example.com/different-job")
        print("  Dedup by URL works")


def test_status_update():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        job = make_scored_job(score=90, decision=Decision.APPLY_NOW)
        job_id = db.save_job(job)
        db.update_status(job_id, "interview", "Phone screen scheduled")
        retrieved = db.get_job(job_id)
        assert retrieved.status == "interview"
        assert retrieved.notes == "Phone screen scheduled"
        print("  Status update works")


def test_mark_applied():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        job = make_scored_job(score=90, decision=Decision.APPLY_NOW)
        job_id = db.save_job(job)
        db.mark_applied(job_id, "Applied via LinkedIn")
        retrieved = db.get_job(job_id)
        assert retrieved.status == "applied"
        assert retrieved.date_applied is not None
        print("  mark_applied() works")


def test_get_all_jobs_filtering():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        # Save 3 jobs with different decisions/scores
        j1 = make_scored_job(score=95, decision=Decision.APPLY_NOW, company="Apple", role="Kernel Eng")
        j2 = make_scored_job(score=80, decision=Decision.REVIEW, company="Nvidia", role="Platform Eng")
        j3 = make_scored_job(score=78, decision=Decision.REVIEW, company="AMD", role="Driver Eng")
        db.save_job(j1)
        db.save_job(j2)
        db.save_job(j3)

        all_jobs = db.get_all_jobs()
        assert len(all_jobs) == 3

        apply_now = db.get_apply_now()
        assert len(apply_now) == 1
        assert apply_now[0].company == "Apple"

        review = db.get_review()
        assert len(review) == 2

        high_score = db.get_all_jobs(min_score=85)
        assert len(high_score) == 1
        print(f"  Filtering works: all={len(all_jobs)} apply={len(apply_now)} review={len(review)}")


def test_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        db.save_job(make_scored_job(score=95, decision=Decision.APPLY_NOW, company="Apple", role="A"))
        db.save_job(make_scored_job(score=80, decision=Decision.REVIEW, company="Nvidia", role="B"))
        db.log_discard(DiscardLog(company="Acme", role="iOS", score=5, reason="mismatch",
                                   source="test", apply_url="https://x.com/1"))
        stats = db.get_stats()
        assert stats["total_stored"] == 2
        assert stats["discarded_total"] == 1
        assert stats["average_score"] > 0
        print(f"  Stats: {stats}")


def test_pipeline_run_logging():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        db.log_pipeline_run("greenhouse", 50, 48, 10, 15, 23, 2)
        # No assertion needed — just verify no crash
        print("  Pipeline run logging works")


if __name__ == "__main__":
    tests = [
        test_save_and_retrieve,
        test_discard_not_stored,
        test_discard_log,
        test_dedup_by_url,
        test_status_update,
        test_mark_applied,
        test_get_all_jobs_filtering,
        test_stats,
        test_pipeline_run_logging,
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
