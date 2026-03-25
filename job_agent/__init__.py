"""
job_agent — Riya's personal job application system.

Public API:
  from job_agent import Pipeline, Database, ScoringEngine
  from job_agent.models import RawJob, ScoredJob, Decision
"""

from job_agent.models import (
    ApplicationStatus,
    Decision,
    DiscardLog,
    RawJob,
    ScoreResult,
    ScoredJob,
    StoredJob,
)
from job_agent.pipeline import Pipeline
from job_agent.profile import CANDIDATE_PROFILE
from job_agent.scoring.engine import ScoringEngine
from job_agent.storage.database import Database

__version__ = "1.0.0"
__author__ = "Riya Aggarwal"

__all__ = [
    "Pipeline",
    "Database",
    "ScoringEngine",
    "CANDIDATE_PROFILE",
    "RawJob",
    "ScoredJob",
    "StoredJob",
    "ScoreResult",
    "DiscardLog",
    "Decision",
    "ApplicationStatus",
]
