"""
Mock scorer for testing without API keys or rate limits.

Provides deterministic scoring based on job content keywords.
Use with: --scoring-provider mock
"""

import logging

from job_agent.scoring.base import ScorerBase, JobScoringResult

logger = logging.getLogger(__name__)

_HARD_BLOCKS = {
    "devops":          ("DevOps/Kubernetes focus (not your domain)", "weak match"),
    "kubernetes":      ("DevOps/Kubernetes focus (not your domain)", "weak match"),
    "data engineer":   ("Data/ML focus (not your domain)",           "weak match"),
    "machine learning":("Data/ML focus (not your domain)",           "weak match"),
    "infosec":         ("Security focus (not your domain)",          "weak match"),
}

_POSITIVE_SIGNALS = [
    ("embedded",               20, "Embedded systems focus (strong match)"),
    ("firmware",               15, "Firmware development (strong match)"),
    ("linux",                  15, "Linux focus (core skill)"),
    ("driver",                 10, "Driver work (strong match)"),
    ("hardware",               10, "Hardware work (strong match)"),
    ("networking",             15, "Networking focus (core skill)"),
    ("tcp/ip",                 10, "TCP/IP networking (core skill)"),
    ("bgp",                    10, "Networking protocols (core skill)"),
    ("ospf",                   10, "Networking protocols (core skill)"),
    ("kernel",                 15, "Kernel work (core skill)"),
    ("validation",              5, "Validation/testing (valued skill)"),
    ("testing",                 5, "Validation/testing (valued skill)"),
]


class MockScorer(ScorerBase):
    """Deterministic scorer for offline testing."""

    def validate_config(self) -> bool:
        return True

    def get_name(self) -> str:
        return "mock"

    def get_models(self) -> list:
        return ["mock"]

    def score(self, job: dict, candidate_profile: str) -> JobScoringResult:
        """
        Score based on keyword heuristics — no API call needed.

        job must be a dict with keys: role, description, requirements,
        company, location, remote.
        """
        text = " ".join([
            job.get("role", ""),
            job.get("description", ""),
            job.get("requirements", ""),
        ]).lower()

        # ── Hard blocks ───────────────────────────────────────────────────
        for keyword, (reason, verdict) in _HARD_BLOCKS.items():
            if keyword in text:
                return JobScoringResult(
                    role_family="mixed",
                    score=0,
                    confidence="high",
                    verdict=verdict,
                    reasons=[f"{reason} — outside target domain"],
                    true_blockers=[reason],
                    learnable_gaps=[],
                    provider="mock",
                    model="mock",
                )

        # ── Positive signals ──────────────────────────────────────────────
        base_score = 50
        reasons = []
        for keyword, pts, label in _POSITIVE_SIGNALS:
            if keyword in text:
                base_score += pts
                reasons.append(label)

        # C/C++ bonus — avoid false-positive on "javascript", "c-suite", etc.
        if ("c programming" in text or "c/c++" in text or " in c " in text
                or "written in c" in text) and "javascript" not in text:
            base_score += 15
            reasons.append("C/C++ required (core skill)")

        if job.get("remote", False):
            base_score += 5
            reasons.append("Remote-friendly")

        if "senior" in job.get("role", "").lower():
            reasons.append("Senior level matches your 7 years experience")
        else:
            reasons.append("Mid-level role within your experience range")

        score = min(100, max(0, base_score))

        # ── Verdict ───────────────────────────────────────────────────────
        if score >= 80:
            verdict = "strong match"
        elif score >= 65:
            verdict = "good match"
        elif score >= 50:
            verdict = "viable match"
        elif score >= 40:
            verdict = "stretch"
        else:
            verdict = "weak match"

        # ── Learnable gaps ────────────────────────────────────────────────
        gaps = []
        if "golang" in text or " go " in text:
            gaps.append("Go language (learnable from C background)")
        if "rust" in text:
            gaps.append("Rust (learnable from C background)")

        role_family = self._classify_role(text)

        logger.debug(
            f"[mock] {job.get('company')} — {job.get('role')}: "
            f"{score}/100 ({verdict})"
        )

        return JobScoringResult(
            role_family=role_family,
            score=score,
            confidence="medium",
            verdict=verdict,
            reasons=reasons,
            true_blockers=[],
            learnable_gaps=gaps,
            provider="mock",
            model="mock",
        )

    @staticmethod
    def _classify_role(text: str) -> str:
        if "kernel" in text:
            return "linux_kernel"
        if "embedded" in text or "firmware" in text:
            return "embedded_systems"
        if "network" in text:
            return "networking_software"
        if "validation" in text or "test" in text:
            return "systems_validation"
        if "platform" in text:
            return "platform_software"
        return "mixed"
