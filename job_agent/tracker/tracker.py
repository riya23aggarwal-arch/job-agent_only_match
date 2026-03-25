"""
Application Tracker

Displays the full state of Riya's job pipeline in a structured view.
Used by `job-agent track` and `job-agent shortlist`.
"""

import json
from dataclasses import dataclass
from typing import List, Optional

from job_agent.models import ApplicationStatus, StoredJob
from job_agent.storage.database import Database


@dataclass
class TrackerSummary:
    total: int
    by_status: dict
    by_decision: dict
    avg_score: float
    ready_to_apply: List[StoredJob]
    apply_now_unactioned: List[StoredJob]
    in_progress: List[StoredJob]  # applied, interview


class Tracker:

    def __init__(self, db: Database = None):
        self.db = db or Database()

    def summary(self) -> TrackerSummary:
        all_jobs = self.db.get_all_jobs()
        stats = self.db.get_stats()

        ready = [j for j in all_jobs if j.status == ApplicationStatus.READY_TO_APPLY.value]
        apply_now_unactioned = [
            j for j in all_jobs
            if j.decision == "apply_now" and j.status == ApplicationStatus.SHORTLISTED.value
        ]
        in_progress = [
            j for j in all_jobs
            if j.status in (ApplicationStatus.APPLIED.value, ApplicationStatus.INTERVIEW.value)
        ]

        return TrackerSummary(
            total=stats["total_stored"],
            by_status=stats.get("by_status", {}),
            by_decision=stats.get("by_decision", {}),
            avg_score=stats.get("average_score", 0.0),
            ready_to_apply=ready,
            apply_now_unactioned=apply_now_unactioned,
            in_progress=in_progress,
        )

    def get_next_action(self) -> Optional[StoredJob]:
        """Return the highest-priority job to action next."""
        apply_now = self.db.get_apply_now()
        # Prefer ready_to_apply first, then shortlisted
        for job in apply_now:
            if job.status == ApplicationStatus.READY_TO_APPLY.value:
                return job
        for job in apply_now:
            if job.status == ApplicationStatus.SHORTLISTED.value:
                return job
        return None

    def print_board(self):
        """Print a Kanban-style board of all applications."""
        all_jobs = self.db.get_all_jobs()

        columns = {
            "SHORTLISTED": [],
            "READY_TO_APPLY": [],
            "APPLIED": [],
            "INTERVIEW": [],
            "OFFER": [],
            "REJECTED": [],
        }

        for job in all_jobs:
            key = job.status.upper()
            if key in columns:
                columns[key].append(job)

        print("\n" + "="*80)
        print("APPLICATION BOARD")
        print("="*80)

        for status, jobs in columns.items():
            if not jobs:
                continue
            print(f"\n── {status} ({len(jobs)}) " + "─"*(60 - len(status)))
            for j in jobs:
                decision_marker = "🟢" if j.decision == "apply_now" else "🟡"
                matched = json.loads(j.matched_skills)[:3]
                print(f"  {decision_marker} [{j.score:3d}] {j.job_id}  {j.company} — {j.role}")
                print(f"         {j.location} | Skills: {', '.join(matched)}")

        print("\n" + "="*80)
        stats = self.db.get_stats()
        print(f"Total stored: {stats['total_stored']} | "
              f"Average score: {stats['average_score']} | "
              f"Discarded: {stats['discarded_total']}")
        print("="*80 + "\n")
