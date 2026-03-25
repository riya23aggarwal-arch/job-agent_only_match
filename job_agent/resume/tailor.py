"""
Resume Tailoring Engine

Takes a stored job and Riya's base resume profile,
produces a tailored resume reordering bullets for relevance.

Rules:
- NEVER invent experience
- Reorder and emphasize based on job requirements
- Output: markdown, plain text, or LaTeX
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from job_agent.models import StoredJob
from job_agent.profile import CANDIDATE_PROFILE

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path.home() / ".job_agent" / "resumes"


# ── Base resume template ────────────────────────────────────────────────────

BASE_RESUME = {
    "header": {
        "name": CANDIDATE_PROFILE["name"],
        "email": CANDIDATE_PROFILE["email"],
        "phone": CANDIDATE_PROFILE["phone"],
        "location": CANDIDATE_PROFILE["location"],
        "linkedin": CANDIDATE_PROFILE["linkedin"],
    },
    "summary_templates": {
        "linux_kernel": (
            "Systems software engineer with 6+ years of experience in Linux internals, "
            "kernel debugging, and device driver development. Proven track record debugging "
            "complex firmware/kernel issues at Google AR/VR and Cisco Systems."
        ),
        "networking": (
            "Systems engineer with 6+ years in C-based platform development, optics drivers, "
            "and network system automation. Deep experience at Cisco Systems building scalable "
            "platform subsystems and automation frameworks."
        ),
        "embedded": (
            "Embedded Linux engineer with 6+ years across firmware, BSP, hardware bring-up, "
            "and low-level driver development. Experience spanning automotive/AR prototype "
            "devices (Google) and programmable network hardware (Cisco)."
        ),
        "automation": (
            "Software engineer with 6+ years of experience in Linux systems and test automation. "
            "Built Python/PyATS automation frameworks at Cognizant and Capgemini, covering "
            "firmware validation, network health, and regression testing."
        ),
        "default": (
            "Software engineer with 6+ years of experience in Linux systems, C development, "
            "device drivers, and system automation. Industry experience across networking, "
            "AR/VR, and cloud-scale infrastructure."
        ),
    },
    "experience": CANDIDATE_PROFILE["experience"],
    "skills": {
        "Languages": ["C", "Python", "Shell/Bash"],
        "Systems": ["Linux Internals", "Kernel Debugging", "Device Drivers", "BSP", "Hardware Bring-up"],
        "Networking": ["Optics Platforms", "Ethernet", "Network Automation"],
        "Tools": ["GDB", "PyATS", "Pytest", "Git"],
        "Automation": ["Python Automation", "Regression Frameworks", "System Validation"],
    },
    "education": CANDIDATE_PROFILE["education"],
}


class ResumeTailor:

    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile = CANDIDATE_PROFILE

    def tailor(self, job: StoredJob, fmt: str = "markdown") -> Path:
        """
        Generate tailored resume for the given job.
        Returns path to the output file.
        """
        matched_skills = json.loads(job.matched_skills)
        focus = self._determine_focus(job, matched_skills)
        summary = BASE_RESUME["summary_templates"].get(
            focus, BASE_RESUME["summary_templates"]["default"]
        )
        ordered_exp = self._order_experience(job, matched_skills)
        skills = self._prioritize_skills(matched_skills)

        resume_data = {
            "header": BASE_RESUME["header"],
            "summary": summary,
            "experience": ordered_exp,
            "skills": skills,
            "education": BASE_RESUME["education"],
            "job_ref": {"company": job.company, "role": job.role},
        }

        if fmt == "markdown":
            content = self._render_markdown(resume_data)
            ext = "md"
        elif fmt == "text":
            content = self._render_text(resume_data)
            ext = "txt"
        elif fmt == "latex":
            content = self._render_latex(resume_data)
            ext = "tex"
        else:
            raise ValueError(f"Unknown format: {fmt}")

        filename = f"resume_{job.job_id}_{job.company.lower().replace(' ', '_')}.{ext}"
        path = self.output_dir / filename
        path.write_text(content, encoding="utf-8")
        logger.info(f"Resume saved: {path}")
        return path

    # ── Focus detection ─────────────────────────────────────────────────────

    def _determine_focus(self, job: StoredJob, matched_skills: List[str]) -> str:
        text = (job.role + " " + job.description).lower()
        skill_str = " ".join(matched_skills).lower()

        if any(k in text for k in ["network", "optic", "routing", "switching", "packet"]):
            return "networking"
        if any(k in text for k in ["kernel", "driver", "bsp", "firmware", "embedded"]):
            return "linux_kernel" if "kernel" in text else "embedded"
        if any(k in text for k in ["automat", "qa ", "testing", "pyats", "regression"]):
            return "automation"
        if "linux" in skill_str or "kernel" in skill_str:
            return "linux_kernel"
        return "default"

    # ── Experience ordering ─────────────────────────────────────────────────

    def _order_experience(self, job: StoredJob, matched_skills: List[str]) -> List[dict]:
        """Score each experience entry and reorder bullets by relevance."""
        job_text = (job.role + " " + job.description + " " + job.requirements).lower()

        ordered = []
        for exp in BASE_RESUME["experience"]:
            scored_bullets = []
            for bullet in exp["highlights"]:
                relevance = self._score_bullet(bullet, job_text, matched_skills)
                scored_bullets.append((bullet, relevance))

            # Sort bullets: most relevant first
            scored_bullets.sort(key=lambda x: x[1], reverse=True)
            ordered_bullets = [b for b, _ in scored_bullets]

            ordered.append({
                **exp,
                "highlights": ordered_bullets,
            })

        # Also reorder companies — most relevant first
        ordered.sort(
            key=lambda e: self._score_company_relevance(e, job_text),
            reverse=True,
        )
        return ordered

    def _score_bullet(self, bullet: str, job_text: str, matched_skills: List[str]) -> float:
        bullet_lower = bullet.lower()
        score = 0.0
        for skill in matched_skills:
            if skill in bullet_lower:
                score += 2.0
        # Check job text overlap
        words = set(re.findall(r'\b\w{5,}\b', bullet_lower))
        job_words = set(re.findall(r'\b\w{5,}\b', job_text))
        overlap = words & job_words
        score += len(overlap) * 0.5
        return score

    def _score_company_relevance(self, exp: dict, job_text: str) -> float:
        tag_str = " ".join(exp.get("tags", [])).lower()
        words = set(re.findall(r'\b\w{4,}\b', tag_str))
        job_words = set(re.findall(r'\b\w{4,}\b', job_text))
        return float(len(words & job_words))

    # ── Skills prioritization ───────────────────────────────────────────────

    def _prioritize_skills(self, matched_skills: List[str]) -> dict:
        """Put matched skills first in each category."""
        skills = {k: list(v) for k, v in BASE_RESUME["skills"].items()}
        matched_lower = [s.lower() for s in matched_skills]

        for category, skill_list in skills.items():
            skills[category] = sorted(
                skill_list,
                key=lambda s: (0 if s.lower() in matched_lower else 1),
            )
        return skills

    # ── Renderers ───────────────────────────────────────────────────────────

    def _render_markdown(self, data: dict) -> str:
        h = data["header"]
        lines = [
            f"# {h['name']}",
            f"{h['location']} | {h['email']} | {h['phone']} | {h['linkedin']}",
            "",
            "## Summary",
            data["summary"],
            "",
            "## Experience",
        ]
        for exp in data["experience"]:
            lines += [
                f"### {exp['title']} — {exp['company']}",
                f"*{exp['duration']}*",
                "",
            ]
            for bullet in exp["highlights"]:
                lines.append(f"- {bullet}")
            lines.append("")

        lines += ["## Skills", ""]
        for category, skill_list in data["skills"].items():
            lines.append(f"**{category}:** {', '.join(skill_list)}")
        lines.append("")

        lines += ["## Education", ""]
        for edu in data["education"]:
            lines.append(f"- {edu['degree']} — {edu['school']}")

        return "\n".join(lines)

    def _render_text(self, data: dict) -> str:
        h = data["header"]
        lines = [
            h["name"].upper(),
            f"{h['location']} | {h['email']} | {h['phone']}",
            h["linkedin"],
            "=" * 60,
            "",
            "SUMMARY",
            "-" * 40,
            data["summary"],
            "",
            "EXPERIENCE",
            "-" * 40,
        ]
        for exp in data["experience"]:
            lines += [
                f"{exp['title'].upper()} | {exp['company']}",
                exp["duration"],
            ]
            for bullet in exp["highlights"]:
                lines.append(f"  • {bullet}")
            lines.append("")

        lines += ["SKILLS", "-" * 40]
        for category, skill_list in data["skills"].items():
            lines.append(f"{category}: {', '.join(skill_list)}")

        lines += ["", "EDUCATION", "-" * 40]
        for edu in data["education"]:
            lines.append(f"{edu['degree']} | {edu['school']}")

        return "\n".join(lines)

    def _render_latex(self, data: dict) -> str:
        h = data["header"]

        def escape(s: str) -> str:
            return s.replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")

        def bullets(items):
            return "\n".join(rf"  \item {escape(b)}" for b in items)

        exp_sections = ""
        for exp in data["experience"]:
            exp_sections += rf"""
\subsection{{{escape(exp['title'])} --- {escape(exp['company'])}}}
\textit{{{escape(exp['duration'])}}}
\begin{{itemize}}
{bullets(exp['highlights'])}
\end{{itemize}}
"""

        skill_lines = "\n".join(
            rf"\textbf{{{cat}}}: {escape(', '.join(skills))}\\"
            for cat, skills in data["skills"].items()
        )

        edu_lines = "\n".join(
            rf"\textbf{{{escape(e['degree'])}}} --- {escape(e['school'])}\\"
            for e in data["education"]
        )

        return rf"""
\documentclass[11pt,a4paper]{{article}}
\usepackage[margin=1in]{{geometry}}
\usepackage{{enumitem}}
\usepackage{{hyperref}}
\pagestyle{{empty}}
\begin{{document}}

\begin{{center}}
  {{\LARGE \textbf{{{escape(h['name'])}}}}} \\[4pt]
  {escape(h['location'])} $\cdot$ {escape(h['email'])} $\cdot$ {escape(h['phone'])} \\
  \href{{https://{escape(h['linkedin'])}}}{{{escape(h['linkedin'])}}}
\end{{center}}

\section*{{Summary}}
{escape(data['summary'])}

\section*{{Experience}}
{exp_sections}

\section*{{Skills}}
{skill_lines}

\section*{{Education}}
{edu_lines}

\end{{document}}
"""
