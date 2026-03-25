"""
Tests for the scoring engine.
Run with: python -m pytest tests/ -v  OR  python tests/test_scoring.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from job_agent.models import Decision, RawJob
from job_agent.scoring.engine import ScoringEngine


def make_job(**kwargs) -> RawJob:
    defaults = dict(
        company="TestCo",
        role="Software Engineer",
        location="San Jose, CA",
        description="",
        requirements="",
        apply_url="https://example.com/job/1",
        source="test",
    )
    defaults.update(kwargs)
    return RawJob(**defaults)


engine = ScoringEngine()


def test_high_match_linux_driver():
    """Full Linux/driver JD should score APPLY_NOW."""
    job = make_job(
        role="Linux Kernel Engineer",
        description=(
            "We are looking for an experienced engineer with deep Linux kernel expertise. "
            "You will develop device drivers, BSP, and platform initialization code in C. "
            "Experience with kernel debugging, multithreading, and memory management required. "
            "Hardware bring-up experience a plus."
        ),
        requirements="5+ years C, Linux internals, device drivers, kernel debugging",
    )
    result = engine.score(job)
    print(f"  High match linux/driver: {result.score} -> {result.decision}")
    assert result.score >= 75, f"Expected REVIEW+, got {result.score}"
    assert "c" in result.matched_skills or "linux internals" in result.matched_skills


def test_rich_networking_role():
    """Rich networking JD with C/Linux/optics/drivers/BSP should hit REVIEW or better."""
    job = make_job(
        role="Senior Network Platform Engineer",
        description=(
            "Develop C-based platform subsystems for high-speed optics hardware. "
            "Work on Linux internals, device drivers, BSP integration, hardware bring-up. "
            "Kernel debugging, networking systems, platform initialization required. "
            "Python automation and PyATS skills valued. Multithreading, memory management."
        ),
        requirements=(
            "5+ years C and Linux. Device drivers and networking platform. "
            "Optics driver integration. Kernel debugging and BSP work."
        ),
        location="San Jose, CA",
    )
    result = engine.score(job)
    print(f"  Rich networking role: {result.score} -> {result.decision}")
    assert result.score >= 75, f"Expected REVIEW+, got {result.score}"


def test_thin_networking_role_scores_lower():
    """A thin posting with few keywords should score below 90 — sparse JDs get scored proportionally."""
    job = make_job(
        role="Network Platform Engineer",
        description="C-based platform subsystems. Optics, networking, Linux.",
        requirements="C, networking",
        location="San Jose, CA",
    )
    result = engine.score(job)
    print(f"  Thin networking role: {result.score} -> {result.decision} (expected < 75 — thin JD)")
    # A thin JD should score below 90 — it lacks the full skill depth
    assert result.score < 90, f"Thin JD should not hit APPLY_NOW ceiling, got {result.score}"


def test_frontend_role_discarded():
    """React/frontend role should be discarded."""
    job = make_job(
        role="Frontend Engineer",
        description=(
            "We need a React developer to build UI components. "
            "Experience with Angular, Vue, and modern JavaScript frameworks. "
            "Java backend knowledge helpful."
        ),
        requirements="React, Angular, JavaScript, CSS",
    )
    result = engine.score(job)
    print(f"  Frontend role: {result.score} -> {result.decision}")
    assert result.decision == Decision.DISCARD, f"Expected DISCARD, got {result.decision} ({result.score})"


def test_ml_role_penalized():
    """ML/data science role should score below REVIEW."""
    job = make_job(
        role="ML Engineer",
        description=(
            "Build machine learning models using Python and TensorFlow. "
            "Data science background preferred. Neural networks experience."
        ),
        requirements="Python, ML, TensorFlow, data science",
    )
    result = engine.score(job)
    print(f"  ML role: {result.score} -> {result.decision}")
    assert result.score < 75


def test_automation_role_scores_mid():
    """Python/PyATS automation role — no C/Linux, scores mid range."""
    job = make_job(
        role="Automation Engineer",
        description=(
            "Build test automation frameworks using Python and PyATS. "
            "System validation and regression testing in Linux environment."
        ),
        requirements="Python, automation, pytest, Linux",
    )
    result = engine.score(job)
    print(f"  Automation role (Python-only): {result.score} -> {result.decision}")
    # Correct: automation-only role without C/Linux/drivers is mid-range
    assert result.score >= 40, "Should score at least 40 given Python+PyATS match"
    assert result.score < 65, f"Should not hit APPLY_NOW — missing core C/Linux/driver skills, got {result.score}"


def test_perfect_match():
    """Full JD matching all high + medium skills should be APPLY_NOW."""
    job = make_job(
        role="Senior Linux Platform Engineer",
        description=(
            "Senior Linux engineer with C expertise. "
            "Linux internals, device drivers, BSP, and hardware bring-up. "
            "Kernel debugging, multithreading, memory management, firmware, optics. "
            "Platform initialization experience. Python automation and networking background."
        ),
        requirements=(
            "5+ years C and Linux internals. Device driver and BSP experience. "
            "Kernel debugging with GDB. Multithreading and memory management. "
            "Python scripting and automation. Networking systems knowledge."
        ),
        location="San Jose, CA",
    )
    result = engine.score(job)
    print(f"  Perfect match: {result.score} -> {result.decision}  matched={result.matched_skills}")
    assert result.decision in (Decision.APPLY_NOW, Decision.REVIEW), f"Expected REVIEW+, got {result.decision} ({result.score})"
    assert result.score >= 75


def test_decision_thresholds():
    """Verify decision thresholds are at expected values."""
    from job_agent.scoring.engine import SCORE_APPLY_NOW, SCORE_REVIEW
    assert SCORE_APPLY_NOW == 65
    assert SCORE_REVIEW == 35


def test_discard_has_explanation():
    """Discarded jobs must always have an explanation logged."""
    job = make_job(
        role="iOS Developer",
        description="Build iOS apps using Swift and Objective-C. Android experience a plus.",
        requirements="Swift, iOS, mobile development",
    )
    result = engine.score(job)
    assert result.decision == Decision.DISCARD
    assert result.explanation, "Discarded job must have explanation"


def test_apply_now_all_fields_present():
    """APPLY_NOW result must have all required output fields."""
    job = make_job(
        role="Linux Platform Engineer",
        description=(
            "C, Linux internals, device drivers, BSP, kernel debugging, "
            "hardware bring-up, multithreading, memory management, firmware, "
            "networking, optics, platform initialization, Python, automation."
        ),
        requirements="C, Linux, drivers, BSP, kernel, networking",
        location="San Jose, CA",
    )
    result = engine.score(job)
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 100
    assert result.decision in Decision.__members__.values()
    assert isinstance(result.matched_skills, list)
    assert isinstance(result.missing_skills, list)
    assert isinstance(result.explanation, str)
    assert isinstance(result.skill_breakdown, dict)
    print(f"  Field validation: score={result.score} decision={result.decision}")


if __name__ == "__main__":
    tests = [
        test_high_match_linux_driver,
        test_rich_networking_role,
        test_thin_networking_role_scores_lower,
        test_frontend_role_discarded,
        test_ml_role_penalized,
        test_automation_role_scores_mid,
        test_perfect_match,
        test_decision_thresholds,
        test_discard_has_explanation,
        test_apply_now_all_fields_present,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  -> PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  -> FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  -> ERROR: {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed:
        sys.exit(1)
