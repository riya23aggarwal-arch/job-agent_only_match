"""
Base interface for job scoring providers.

All AI scoring backends (OpenAI, Anthropic, mock) implement this protocol.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class VerdictType(str, Enum):
    STRONG_MATCH = "strong match"
    GOOD_MATCH = "good match"
    VIABLE_MATCH = "viable match"
    STRETCH = "stretch"
    WEAK_MATCH = "weak match"


@dataclass
class JobScoringResult:
    """Structured result from an AI scoring provider."""
    role_family: str
    score: int              # 0–100
    confidence: str         # "high" | "medium" | "low"
    verdict: str            # one of VerdictType values
    reasons: List[str]
    true_blockers: List[str]
    learnable_gaps: List[str]
    provider: str
    model: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "role_family":    self.role_family,
            "score":          self.score,
            "confidence":     self.confidence,
            "verdict":        self.verdict,
            "reasons":        self.reasons,
            "true_blockers":  self.true_blockers,
            "learnable_gaps": self.learnable_gaps,
            "provider":       self.provider,
            "model":          self.model,
        }


class ScorerBase(ABC):
    """Abstract base for all AI scoring providers."""

    @abstractmethod
    def score(self, job: dict, candidate_profile: str) -> JobScoringResult:
        """
        Score a job dict against the candidate profile string.

        Args:
            job: Dict with keys: company, role, description, requirements,
                 location, remote
            candidate_profile: Pre-formatted profile text from get_standard_rubric()

        Returns:
            JobScoringResult

        Raises:
            ValueError: Invalid inputs or response parsing failure
            Exception: Provider-specific errors (API failures, rate limits, etc.)
        """

    @abstractmethod
    def validate_config(self) -> bool:
        """Return True if provider is properly configured."""

    @abstractmethod
    def get_name(self) -> str:
        """Return provider name string."""

    @abstractmethod
    def get_models(self) -> List[str]:
        """Return list of available model names for this provider."""
