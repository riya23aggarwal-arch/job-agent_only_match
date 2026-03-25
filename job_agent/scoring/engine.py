"""
Match Scoring Engine

Scores a raw job against Riya's profile using weighted keyword matching.
No external API calls — fully deterministic, runs offline.

Decision thresholds:
  >= 90 → APPLY_NOW
  75-89 → REVIEW
  < 75  → DISCARD

KEY FIX: Skills have ALIASES — real job postings use short forms like
"Linux", "kernel", "drivers" rather than "Linux internals", "kernel debugging".
Each skill has a list of equivalent terms — any match counts.
"""

import re
from typing import Dict, List, Tuple

from job_agent.models import Decision, RawJob, ScoreResult
from job_agent.profile import CANDIDATE_PROFILE

# ── Weight constants ────────────────────────────────────────────────────────

W_HIGH   = 10    # core skills: C, Linux, drivers
W_MEDIUM = 5     # supporting: Python, automation
W_LOW    = 2     # nice-to-have
W_ANTI   = -15   # penalize unrelated tech (capped at -30)
W_ROLE_MATCH = 8
W_LOCATION   = 5
W_SENIORITY  = 4

SCORE_APPLY_NOW = 65
SCORE_REVIEW    = 35

# ── Skill aliases ───────────────────────────────────────────────────────────
# Each entry: canonical_name → [list of terms that count as a match]
# The scorer checks ALL aliases — if ANY match, the skill is matched.

HIGH_SKILL_ALIASES: Dict[str, List[str]] = {
    "C":                    ["c programming", "c/c++", "c language", "c-based", "c and python", "c and linux", "c on linux", "c for embedded", "languages: c", "written in c", "developed in c", "implemented in c", "experience in c", "expertise in c", "proficiency in c"],
    "linux internals":      ["linux internals", "linux kernel", "linux systems",
                             "linux", "linux-based", "linux environment"],
    "device drivers":       ["device drivers", "device driver", "kernel drivers",
                             "driver development", "driver programming", "drivers"],
    "BSP":                  ["bsp", "board support package", "board bring-up"],
    "hardware bring-up":    ["hardware bring-up", "bring-up", "hw bring-up",
                             "board bring-up", "hardware bringup", "chip bring-up"],
    "platform initialization": ["platform initialization", "platform init",
                                "platform software", "platform development",
                                "platform engineering", "platform subsystem"],
    "kernel debugging":     ["kernel debugging", "kernel debug", "kernel development",
                             "kernel modules", "kernel module", "kernel programming",
                             "linux kernel", "kernel"],
    "networking":           ["networking", "network stack", "network systems",
                             "network protocols", "network programming",
                             "network platform", "network operating system",
                             "tcp/ip", "ethernet", "packet processing"],
    "optics":               ["optics", "optical", "transceiver", "sfp", "qsfp",
                             "otn", "dwdm", "coherent", "pluggable"],
    "firmware":             ["firmware", "fw development", "fw debugging",
                             "embedded firmware", "fw engineer"],
    "multithreading":       ["multithreading", "multi-threading", "concurrency",
                             "concurrent programming", "pthreads", "threads",
                             "thread safety", "parallel programming"],
    "memory management":    ["memory management", "memory allocation", "heap",
                             "virtual memory", "mmu", "memory debugging",
                             "buffer management"],
}

MEDIUM_SKILL_ALIASES: Dict[str, List[str]] = {
    "Python":               ["python", "python3", "python scripting", "python programming"],
    "automation":           ["automation", "automated", "automate", "automation framework",
                             "test automation"],
    "debugging":            ["debugging", "debug", "troubleshooting", "root cause",
                             "rca", "log analysis"],
    "shell scripting":      ["shell scripting", "shell script", "bash", "bash scripting",
                             "shell", "zsh"],
    "PyATS":                ["pyats", "py-ats", "cisco pyats"],
    "pytest":               ["pytest", "py.test", "unit test", "unit testing"],
    "regression testing":   ["regression testing", "regression test", "regression",
                             "test framework", "test suite"],
    "system validation":    ["system validation", "system testing", "platform validation",
                             "hardware validation", "functional testing"],
    "GDB":                  ["gdb", "gnu debugger", "debugger", "debugging tools",
                             "lldb", "valgrind"],
    "log analysis":         ["log analysis", "log parsing", "logging", "syslog",
                             "dmesg", "ftrace", "strace"],
}

LOW_SKILL_ALIASES: Dict[str, List[str]] = {
    "embedded systems":     ["embedded", "embedded systems", "embedded linux",
                             "rtos", "bare metal", "microcontroller"],
    "cross-compilation":    ["cross-compilation", "cross-compile", "cross-compiling",
                             "toolchain", "yocto", "buildroot"],
    "git":                  ["git", "github", "gitlab", "version control"],
    "CI/CD":                ["ci/cd", "ci cd", "jenkins", "github actions",
                             "continuous integration"],
}

ANTI_SKILL_ALIASES: Dict[str, List[str]] = {
    "React":        ["react", "reactjs", "react.js", "react developer"],
    "Angular":      ["angular", "angularjs"],
    "Vue":          ["vue.js", "vuejs", " vue "],
    "frontend":     ["frontend engineer", "front-end engineer", "ui engineer",
                     "frontend developer"],
    "iOS":          ["ios developer", "ios engineer", "swift", "objective-c",
                     "xcode", "ios app"],
    "Android":      ["android developer", "android engineer", "kotlin", "android app"],
    "ML engineer":  ["machine learning engineer", "ml engineer", "deep learning",
                     "neural network", "tensorflow", "pytorch", "llm engineer"],
    "data science": ["data scientist", "data science", "data analyst",
                     "business intelligence"],
    "Ruby":         ["ruby on rails", "rails developer", " ruby "],
    "Java only":    ["java developer", "java engineer", "spring boot", "jvm engineer"],
}


class ScoringEngine:

    def __init__(self):
        self.profile = CANDIDATE_PROFILE
        self.target_roles = [r.lower() for r in self.profile["target_roles"]]
        self.preferred_locations = [l.lower() for l in self.profile["preferred_locations"]]

    def score(self, job: RawJob) -> ScoreResult:
        text = self._build_search_text(job)

        matched_high,   score_high   = self._match_aliases(text, HIGH_SKILL_ALIASES,   W_HIGH)
        matched_medium, score_medium = self._match_aliases(text, MEDIUM_SKILL_ALIASES, W_MEDIUM)
        matched_low,    score_low    = self._match_aliases(text, LOW_SKILL_ALIASES,    W_LOW)
        anti_hits,      anti_penalty = self._match_anti(text)

        role_bonus     = self._score_role_match(job.role)
        location_bonus = self._score_location(job.location)
        seniority_bonus = self._score_seniority(job.role, job.description)

        raw_score = (
            score_high + score_medium + score_low
            + anti_penalty
            + role_bonus + location_bonus + seniority_bonus
        )

        # Realistic max: a job that mentions ~6 high + 4 medium + 2 low + all bonuses
        realistic_max = (
            6 * W_HIGH      # 60
            + 4 * W_MEDIUM  # 20
            + 2 * W_LOW     #  4
            + W_ROLE_MATCH  #  8
            + W_LOCATION    #  5
            + W_SENIORITY   #  4
        )                   # = 101

        normalized = min(100, max(0, int((max(0, raw_score) / realistic_max) * 100)))
        decision   = self._decide(normalized)

        all_matched = matched_high + matched_medium + matched_low
        all_skills  = list(HIGH_SKILL_ALIASES) + list(MEDIUM_SKILL_ALIASES)
        missing     = [s for s in all_skills if s not in all_matched][:8]

        explanation = self._build_explanation(
            normalized, decision, matched_high, matched_medium,
            missing, anti_hits, role_bonus > 0
        )

        return ScoreResult(
            score=normalized,
            decision=decision,
            matched_skills=all_matched,
            missing_skills=missing,
            explanation=explanation,
            skill_breakdown={
                "core_skills":       score_high,
                "supporting_skills": score_medium,
                "bonus_skills":      score_low,
                "anti_penalty":      anti_penalty,
                "role_match":        role_bonus,
                "location_match":    location_bonus,
                "seniority_match":   seniority_bonus,
            },
        )

    # ── Matching helpers ────────────────────────────────────────────────────

    def _build_search_text(self, job: RawJob) -> str:
        return " ".join(
            p for p in [job.role, job.description, job.requirements, job.company]
            if p
        ).lower()

    def _match_aliases(
        self, text: str, alias_map: Dict[str, List[str]], weight: int
    ) -> Tuple[List[str], int]:
        """
        For each skill, check all its aliases against the text.
        If ANY alias matches, the skill is counted once.
        """
        matched = []
        for canonical, aliases in alias_map.items():
            for alias in aliases:
                if self._phrase_in_text(alias.lower(), text):
                    matched.append(canonical)
                    break  # only count once per skill
        return matched, len(matched) * weight

    def _match_anti(self, text: str) -> Tuple[List[str], int]:
        hits = []
        for canonical, aliases in ANTI_SKILL_ALIASES.items():
            for alias in aliases:
                if self._phrase_in_text(alias.lower(), text):
                    hits.append(canonical)
                    break
        penalty = max(-30, len(hits) * W_ANTI)
        return hits, penalty

    def _phrase_in_text(self, phrase: str, text: str) -> bool:
        """Match a phrase — whole word for single words, substring for multi-word."""
        if " " in phrase:
            return phrase in text
        pattern = r"\b" + re.escape(phrase) + r"\b"
        return bool(re.search(pattern, text))

    def _score_role_match(self, role: str) -> int:
        role_lower = role.lower()

        # Strong title keywords — these almost always mean a relevant role
        strong_title_signals = [
            "linux kernel", "kernel engineer", "kernel developer",
            "linux platform", "linux driver", "linux system",
            "device driver", "driver development", "bsp engineer",
            "firmware engineer", "embedded linux", "platform engineer",
            "systems engineer", "network platform", "networking engineer",
        ]
        for signal in strong_title_signals:
            if signal in role_lower:
                return W_ROLE_MATCH * 2  # double bonus for exact title match

        # Partial match — one keyword from target roles
        for target in self.target_roles:
            if any(w in role_lower for w in target.split() if len(w) > 4):
                return W_ROLE_MATCH
        return 0

    def _score_location(self, location: str) -> int:
        if not location:
            return 0
        loc = location.lower()
        if any(r in loc for r in ["remote", "hybrid", "anywhere"]):
            return W_LOCATION
        for pref in self.preferred_locations:
            pref_l = pref.lower().strip()
            # Check both directions: pref in loc AND loc contains pref
            if pref_l in loc or loc in pref_l:
                return W_LOCATION
        return 0

    def _score_seniority(self, role: str, description: str) -> int:
        text = (role + " " + description).lower()
        exp_match = re.search(r"(\d+)\+?\s*years?", text)
        if exp_match:
            return W_SENIORITY if int(exp_match.group(1)) <= 8 else 0
        negative = ["principal", "distinguished", "vp ", "director", "intern",
                    "entry level", "junior", "new grad"]
        positive = ["senior", "staff", "mid", "engineer ii", "engineer iii", "lead"]
        if any(s in text for s in negative):
            return 0
        if any(s in text for s in positive):
            return W_SENIORITY
        return W_SENIORITY // 2

    def _decide(self, score: int) -> Decision:
        if score >= SCORE_APPLY_NOW:
            return Decision.APPLY_NOW
        elif score >= SCORE_REVIEW:
            return Decision.REVIEW
        return Decision.DISCARD

    def _build_explanation(self, score, decision, matched_high,
                           matched_medium, missing, anti_hits, role_match):
        lines = [f"Score: {score}/100 → {decision.value.upper()}"]
        if matched_high:
            lines.append(f"Core skills: {', '.join(matched_high[:6])}")
        else:
            lines.append("⚠ No core skills matched")
        if matched_medium:
            lines.append(f"Supporting: {', '.join(matched_medium[:4])}")
        if role_match:
            lines.append("✓ Role title match")
        if anti_hits:
            lines.append(f"⚠ Mismatched tech: {', '.join(anti_hits)}")
        if missing:
            lines.append(f"Not in posting: {', '.join(missing[:4])}")
        return " | ".join(lines)


def score_and_route(job: RawJob, engine: ScoringEngine = None):
    if engine is None:
        engine = ScoringEngine()
    result = engine.score(job)
    should_store = result.decision in (Decision.APPLY_NOW, Decision.REVIEW)
    return result, should_store
