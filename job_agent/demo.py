#!/usr/bin/env python3
"""
job-agent demo — runs the complete pipeline with mock data.

Shows the full system working without any network calls:
  1. Pipeline with realistic mock jobs
  2. Scoring breakdown
  3. Resume tailoring output
  4. Cover letter generation
  5. Application tracker board

Usage:
    python demo.py
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from job_agent.models import RawJob, Decision
from job_agent.pipeline import Pipeline
from job_agent.scoring.engine import ScoringEngine
from job_agent.storage.database import Database
from job_agent.resume.tailor import ResumeTailor
from job_agent.cover_letter.generator import CoverLetterGenerator
from job_agent.tracker.tracker import Tracker
from job_agent.utils.helpers import score_bar, decision_emoji, status_emoji

SEPARATOR = "─" * 70


DEMO_JOBS = [
    RawJob(
        company="Arista Networks",
        role="Senior Linux Platform Engineer",
        location="Santa Clara, CA",
        description=(
            "Arista is looking for an experienced Linux platform engineer to develop and maintain "
            "platform subsystems in C for our EOS network operating system. You will work on "
            "Linux internals, device drivers, BSP integration, and hardware bring-up for "
            "next-generation networking hardware. Kernel debugging, multithreading, and memory "
            "management expertise is required. Experience with networking systems and optics "
            "platform development is strongly preferred."
        ),
        requirements=(
            "6+ years of experience in C and Linux internals. "
            "Device driver development and BSP experience required. "
            "Kernel debugging proficiency (GDB, ftrace, perf). "
            "Firmware and hardware bring-up experience. "
            "Python scripting and automation skills valued. "
            "Networking systems knowledge strongly preferred."
        ),
        apply_url="https://boards.greenhouse.io/arista/jobs/linux-platform-2024",
        source="greenhouse",
    ),
    RawJob(
        company="Nvidia",
        role="Linux Kernel Engineer",
        location="Santa Clara, CA",
        description=(
            "Join NVIDIA's platform engineering team to develop Linux kernel modules and "
            "device drivers for GPU hardware. You will work on Linux internals, kernel debugging, "
            "driver development for our hardware platforms. Strong C programming, deep Linux "
            "kernel knowledge, multithreading and memory management expertise required. "
            "BSP experience and hardware bring-up background valued."
        ),
        requirements=(
            "5+ years C, Linux kernel, device drivers. "
            "Strong understanding of kernel memory management and multithreading. "
            "GDB and kernel tracing tools. BSP and firmware experience a plus."
        ),
        apply_url="https://nvidia.wd5.myworkdayjobs.com/jobs/kernel-engineer-2024",
        source="workday",
    ),
    RawJob(
        company="Google",
        role="Systems Software Engineer, Android Platform",
        location="Mountain View, CA",
        description=(
            "Work on Android platform infrastructure including kernel and driver development, "
            "BSP bring-up, and firmware debugging. Debug Linux-based mobile devices across "
            "firmware, kernel, and application layers. Python automation tooling experience "
            "valued for validation workflows."
        ),
        requirements=(
            "5+ years systems engineering. C and Linux required. "
            "Device driver experience required. Python automation helpful."
        ),
        apply_url="https://careers.google.com/jobs/systems-sw-android-2024",
        source="career_page",
    ),
    RawJob(
        company="Stripe",
        role="Backend Infrastructure Engineer",
        location="San Francisco, CA",
        description=(
            "Build and operate Stripe's core payment infrastructure. "
            "Java, Ruby, distributed systems experience. Microservices and Kubernetes. "
            "Strong backend engineering fundamentals in JVM languages."
        ),
        requirements="Java, Ruby, distributed systems, Kubernetes, microservices",
        apply_url="https://stripe.com/jobs/backend-infra-2024",
        source="lever",
    ),
    RawJob(
        company="Meta",
        role="Frontend Engineer, React Infrastructure",
        location="Menlo Park, CA",
        description=(
            "Build Meta's React-based frontend infrastructure. Deep React expertise, "
            "JavaScript/TypeScript, front-end performance optimization, UI engineering."
        ),
        requirements="React, JavaScript, TypeScript, CSS, frontend",
        apply_url="https://meta.com/careers/frontend-infra-2024",
        source="career_page",
    ),
    RawQ := RawJob(
        company="Juniper Networks",
        role="Network Systems Automation Engineer",
        location="Sunnyvale, CA",
        description=(
            "Build Python and PyATS automation frameworks for network platform validation. "
            "Linux environment, shell scripting, regression testing. Network system knowledge "
            "valuable. Experience with Pytest and automation pipeline design."
        ),
        requirements="Python, PyATS, pytest, automation, Linux, networking, shell scripting",
        apply_url="https://juniper.com/careers/network-auto-2024",
        source="greenhouse",
    ),
]

# remove walrus assignment artifact
DEMO_JOBS[-1] = DEMO_JOBS[-1]  # noqa


def section(title: str):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def run_demo():
    print("\n" + "=" * 70)
    print("  JOB-AGENT — FULL SYSTEM DEMO")
    print("  Candidate: Riya Aggarwal | riya23aggarwal@gmail.com")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "demo.db"
        resume_dir = Path(tmpdir) / "resumes"
        cover_dir = Path(tmpdir) / "cover_letters"

        db = Database(db_path)

        # ── PHASE 1+2+3: Pipeline ─────────────────────────────────────────

        section("PHASE 1–3: STREAMING PIPELINE (collect → score → store)")
        print()

        engine = ScoringEngine()

        class DemoCollector:
            source_name = "demo"
            def collect(self):
                return iter(DEMO_JOBS)

        stats_collect = 0
        stats_apply = 0
        stats_review = 0
        stats_discard = 0

        for job in DEMO_JOBS:
            result = engine.score(job)
            stats_collect += 1

            bar = score_bar(result.score, width=15)
            emoji = decision_emoji(result.decision.value)

            print(f"  {emoji} {bar}  {job.company:<22} {job.role[:35]}")

            if result.decision == Decision.APPLY_NOW:
                stats_apply += 1
            elif result.decision == Decision.REVIEW:
                stats_review += 1
            else:
                stats_discard += 1

        print(f"\n  Collected: {stats_collect}  "
              f"Apply Now: {stats_apply}  "
              f"Review: {stats_review}  "
              f"Discarded: {stats_discard}")

        # ── Run actual pipeline (stores APPLY_NOW + REVIEW) ───────────────

        from job_agent.pipeline import Pipeline
        from job_agent.collectors.base import BaseCollector

        class MockCollector(BaseCollector):
            source_name = "demo"
            rate_limit_seconds = 0
            def __init__(self): pass
            def _fetch_jobs(self):
                for job in DEMO_JOBS:
                    yield job

        pipeline = Pipeline(db=db)
        stats = pipeline.run(MockCollector())

        # ── PHASE 4: Resume Tailoring ─────────────────────────────────────

        section("PHASE 4: RESUME TAILORING")
        print()

        tailor = ResumeTailor(output_dir=resume_dir)
        stored_jobs = db.get_all_jobs()

        for job in stored_jobs[:2]:  # Demo first 2
            path = tailor.tailor(job, fmt="markdown")
            content = path.read_text()
            lines = content.splitlines()

            print(f"  📄 {job.company} — {job.role}")
            print(f"     Decision: {decision_emoji(job.decision)} {job.decision}  "
                  f"Score: {job.score}")
            print(f"     Format: Markdown → {path.name}")
            # Show first 8 lines of resume
            print(f"\n  {'─'*50}")
            for line in lines[:8]:
                print(f"  {line}")
            print(f"  … ({len(lines)} total lines)")
            print()

        # ── PHASE 5: Cover Letter ─────────────────────────────────────────

        section("PHASE 5: COVER LETTER + RECRUITER EMAIL + Q&A")
        print()

        gen = CoverLetterGenerator(output_dir=cover_dir)
        top_job = stored_jobs[0]

        paths = gen.generate_all(top_job)
        print(f"  Generated for: {top_job.company} — {top_job.role}")
        print()

        for doc_type, path in paths.items():
            content = path.read_text()
            lines = [l for l in content.splitlines() if l.strip()]
            print(f"  📝 {doc_type.upper().replace('_', ' ')} → {path.name}")
            # Show excerpt
            for line in lines[:4]:
                print(f"     {line[:80]}")
            print(f"     … ({len(lines)} lines total)\n")

        # ── PHASE 7: Tracker Board ────────────────────────────────────────

        section("PHASE 7: APPLICATION TRACKER BOARD")

        # Simulate some status changes
        all_jobs = db.get_all_jobs()
        if len(all_jobs) >= 2:
            db.mark_applied(all_jobs[0].job_id, "Demo applied")
            db.update_status(all_jobs[1].job_id, "ready_to_apply", "Resume tailored, ready to go")

        tracker = Tracker(db=db)
        tracker.print_board()

        # ── PHASE 8: CLI Reference ────────────────────────────────────────

        section("PHASE 8: CLI COMMANDS REFERENCE")
        print("""
  After installing with `pip install -e .`:

  job-agent collect                         # Collect from all sources
  job-agent collect --source greenhouse     # Greenhouse only
  job-agent collect --dry-run               # Score but don't store

  job-agent shortlist                       # All stored jobs by score
  job-agent shortlist --decision apply_now  # Only APPLY_NOW

  job-agent view <JOB_ID>                   # Full job detail

  job-agent tailor <JOB_ID>                 # Tailored resume (markdown)
  job-agent tailor <JOB_ID> --format latex  # LaTeX output

  job-agent cover-letter <JOB_ID>           # Cover letter + email + Q&A

  job-agent apply <JOB_ID>                  # Playwright assisted apply
  job-agent apply <JOB_ID> --mode semi_auto

  job-agent track <JOB_ID> --status applied --notes "Applied via LinkedIn"
  job-agent track <JOB_ID> --status interview

  job-agent stats                           # Pipeline statistics
  job-agent export                          # Export to CSV
        """)

        # ── Final summary ─────────────────────────────────────────────────

        print("=" * 70)
        final_stats = db.get_stats()
        print(f"  DEMO COMPLETE")
        print(f"  Jobs in DB: {final_stats['total_stored']} stored + "
              f"{final_stats['discarded_total']} discarded")
        print(f"  Average score: {final_stats['average_score']}")
        print(f"  Resume files generated: {len(list(resume_dir.glob('*.md')))}")
        print(f"  Cover letter files: {len(list(cover_dir.glob('*.md')))}")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    # Fix walrus operator issue in DEMO_JOBS definition
    DEMO_JOBS[5] = RawJob(
        company="Juniper Networks",
        role="Network Systems Automation Engineer",
        location="Sunnyvale, CA",
        description=(
            "Build Python and PyATS automation frameworks for network platform validation. "
            "Linux environment, shell scripting, regression testing. Network system knowledge "
            "valuable. Experience with Pytest and automation pipeline design."
        ),
        requirements="Python, PyATS, pytest, automation, Linux, networking, shell scripting",
        apply_url="https://juniper.com/careers/network-auto-2024",
        source="greenhouse",
    )
    run_demo()
