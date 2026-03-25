"""
Core data models for Job Agent system.
All structured data flows through these models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class Decision(str, Enum):
    APPLY_NOW = "apply_now"
    REVIEW = "review"
    DISCARD = "discard"


class ApplicationStatus(str, Enum):
    SHORTLISTED = "shortlisted"
    READY_TO_APPLY = "ready_to_apply"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"


@dataclass
class RawJob:
    """Raw job as collected from source — before scoring."""
    company: str
    role: str
    location: str
    description: str
    requirements: str
    apply_url: str
    source: str
    date_found: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    job_id: Optional[str] = None
    remote: bool = False
    salary_range: Optional[str] = None
    employment_type: Optional[str] = None  # full-time, contract, etc.

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "company": self.company,
            "role": self.role,
            "location": self.location,
            "description": self.description,
            "requirements": self.requirements,
            "apply_url": self.apply_url,
            "source": self.source,
            "date_found": self.date_found,
            "remote": self.remote,
            "salary_range": self.salary_range,
            "employment_type": self.employment_type,
        }


@dataclass
class ScoreResult:
    """Result of scoring a job against the candidate profile."""
    score: int                             # 0–100
    decision: Decision
    matched_skills: List[str]
    missing_skills: List[str]
    explanation: str
    skill_breakdown: dict = field(default_factory=dict)  # category → score

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "decision": self.decision.value,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "explanation": self.explanation,
            "skill_breakdown": self.skill_breakdown,
        }


@dataclass
class ScoredJob:
    """A job that has been scored. Only APPLY_NOW and REVIEW get stored."""
    raw: RawJob
    score_result: ScoreResult

    @property
    def job_id(self) -> str:
        return self.raw.job_id or ""

    @property
    def decision(self) -> Decision:
        return self.score_result.decision

    def to_dict(self) -> dict:
        d = self.raw.to_dict()
        d.update(self.score_result.to_dict())
        return d


@dataclass
class StoredJob:
    """A job stored in the database (APPLY_NOW or REVIEW only)."""
    job_id: str
    company: str
    role: str
    location: str
    description: str
    requirements: str
    apply_url: str
    source: str
    date_found: str
    score: int
    decision: str
    matched_skills: str   # JSON string in DB
    missing_skills: str   # JSON string in DB
    explanation: str
    status: str = ApplicationStatus.SHORTLISTED.value
    notes: str = ""
    date_applied: Optional[str] = None
    tailored_resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None
    remote: bool = False
    salary_range: Optional[str] = None


@dataclass
class DiscardLog:
    """Log entry for a discarded job."""
    company: str
    role: str
    score: int
    reason: str
    source: str
    apply_url: str
    date_found: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class QuestionAnswer:
    """Q&A database entry."""
    question: str
    answer: str
    question_hash: str = ""
    company: str = ""
    role: str = ""
    frequency: int = 1
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
