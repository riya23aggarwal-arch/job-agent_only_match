"""
OpenAI-powered job scoring using GPT models.

Requires: pip install openai>=1.0.0
Requires: OPENAI_API_KEY environment variable
"""

import json
import logging
import os
import re
from typing import Optional

from job_agent.scoring.base import ScorerBase, JobScoringResult
from job_agent.scoring.rubric import OPENAI_SYSTEM_PROMPT, OPENAI_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {"weak match", "stretch", "viable match", "good match", "strong match"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


class OpenAIScorer(ScorerBase):
    """Score jobs using OpenAI GPT models."""

    AVAILABLE_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
    ]

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Args:
            api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
            model:   Model name. Default: gpt-4o-mini (fast + cheap).
        """
        try:
            from openai import OpenAI, APIError, RateLimitError
            self._OpenAI = OpenAI
            self._APIError = APIError
            self._RateLimitError = RateLimitError
        except ImportError:
            raise ImportError(
                "OpenAI SDK not installed.\n"
                "Fix: pip install 'openai>=1.0.0'"
            )

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found.\n"
                "Fix: export OPENAI_API_KEY=sk-..."
            )
        self.model = model
        self.client = self._OpenAI(api_key=self.api_key)

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)

    def get_name(self) -> str:
        return "openai"

    def get_models(self) -> list:
        return self.AVAILABLE_MODELS

    def score(self, job: dict, candidate_profile: str) -> JobScoringResult:
        """
        Score a job using OpenAI.

        Args:
            job:               Dict with company, role, description, requirements,
                               location, remote
            candidate_profile: Formatted string from get_standard_rubric()

        Returns:
            JobScoringResult with tokens_used set from the actual API response
        """
        user_prompt = OPENAI_USER_PROMPT_TEMPLATE.format(
            candidate_profile=candidate_profile,
            company=job.get("company", "Unknown"),
            role=job.get("role", "Unknown"),
            location=job.get("location", "Unknown"),
            level="Senior (7 years experience)",
            remote="Yes" if job.get("remote", False) else "No",
            description=(job.get("description", "") or "")[:2000],
            requirements=(job.get("requirements", "") or "")[:1000],
        )

        logger.debug(f"[openai] scoring {job.get('company')} — {job.get('role')}")
        logger.debug(
            f"[openai] ── PROMPT ──────────────────────────\n"
            f"{user_prompt}\n"
            f"────────────────────────────────────────"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=800,
            )

            response_text = response.choices[0].message.content.strip()
            logger.debug(
                f"[openai] ── RESPONSE ─────────────────────────\n"
                f"{response_text}\n"
                f"────────────────────────────────────────"
            )

            result = self._parse_response(response_text)
            result.provider = "openai"
            result.model = self.model

            # ── Capture actual token usage from the API response ──────────
            if response.usage:
                result.tokens_used = response.usage.total_tokens
            # ─────────────────────────────────────────────────────────────

            logger.debug(
                f"[openai] {result.score}/100 ({result.verdict}, "
                f"{result.confidence}) | {result.tokens_used} tokens"
            )
            return result

        except self._RateLimitError as e:
            logger.error(f"[openai] rate limit: {e}")
            raise
        except self._APIError as e:
            logger.error(f"[openai] API error: {e}")
            raise
        except Exception as e:
            logger.error(f"[openai] unexpected error: {e}")
            raise

    def _parse_response(self, text: str) -> JobScoringResult:
        """Parse OpenAI JSON response into JobScoringResult."""
        text = re.sub(r"```(?:json)?", "", text).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise ValueError(f"No JSON in response: {text[:300]}")
            data = json.loads(match.group())

        required = ["role_family", "score", "confidence", "verdict",
                    "reasons", "true_blockers", "learnable_gaps"]
        missing_fields = [f for f in required if f not in data]
        if missing_fields:
            raise ValueError(f"Response missing fields: {missing_fields}")

        score = int(data["score"])
        if not 0 <= score <= 100:
            raise ValueError(f"Score out of range: {score}")

        confidence = str(data["confidence"]).lower()
        if confidence not in _VALID_CONFIDENCE:
            confidence = "medium"

        verdict = str(data["verdict"]).lower()
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"Invalid verdict: {verdict!r}")

        def to_list(v):
            if isinstance(v, list):
                return [str(x) for x in v]
            return [str(v)] if v else []

        return JobScoringResult(
            role_family=str(data.get("role_family", "mixed")),
            score=score,
            confidence=confidence,
            verdict=verdict,
            reasons=to_list(data.get("reasons")),
            true_blockers=to_list(data.get("true_blockers")),
            learnable_gaps=to_list(data.get("learnable_gaps")),
            provider="openai",
            model=self.model,
            # tokens_used set by caller after response.usage is read
        )
