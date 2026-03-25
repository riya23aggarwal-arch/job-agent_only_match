"""
Cover Letter + Recruiter Email Generator

Generates:
  1. Short recruiter email (cold outreach / post-apply follow-up)
  2. Concise cover letter
  3. Answers to common interview screening questions

All grounded in Riya's real experience — never fabricated.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

from job_agent.models import StoredJob
from job_agent.profile import CANDIDATE_PROFILE

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path.home() / ".job_agent" / "cover_letters"


class CoverLetterGenerator:

    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile = CANDIDATE_PROFILE

    # ── Main entry points ───────────────────────────────────────────────────

    def generate_all(self, job: StoredJob) -> Dict[str, Path]:
        """Generate recruiter email, cover letter, and Q&A for a job."""
        matched = json.loads(job.matched_skills)
        focus = self._determine_focus(job, matched)

        paths = {}
        paths["recruiter_email"] = self._save(
            job, "recruiter_email",
            self._recruiter_email(job, focus)
        )
        paths["cover_letter"] = self._save(
            job, "cover_letter",
            self._cover_letter(job, focus)
        )
        paths["qa_answers"] = self._save(
            job, "qa_answers",
            self._qa_answers(job, focus)
        )
        return paths

    # ── Recruiter Email ─────────────────────────────────────────────────────

    def _recruiter_email(self, job: StoredJob, focus: str) -> str:
        exp_snippet = self._experience_snippet(focus)
        return f"""Subject: {job.role} at {job.company} — Riya Aggarwal

Hi [Recruiter Name],

I'm a software engineer with 6+ years in {self._focus_phrase(focus)}, and I came across the {job.role} role at {job.company}. It's a strong match for my background.

{exp_snippet}

I'd love to connect and learn more about the role. Happy to share my resume or set up a call at your convenience.

Best,
Riya Aggarwal
{self.profile['email']} | {self.profile['phone']}
linkedin.com/in/ragrwl
"""

    # ── Cover Letter ────────────────────────────────────────────────────────

    def _cover_letter(self, job: StoredJob, focus: str) -> str:
        opening = self._opening(job, focus)
        body = self._body_paragraphs(job, focus)
        closing = self._closing(job)

        return f"""{self.profile['name']}
{self.profile['location']} | {self.profile['email']} | {self.profile['phone']}

Hiring Team
{job.company}

Re: {job.role}

Dear Hiring Team,

{opening}

{body}

{closing}

Sincerely,
{self.profile['name']}
"""

    def _opening(self, job: StoredJob, focus: str) -> str:
        phrases = {
            "networking": (
                f"I'm excited to apply for the {job.role} position at {job.company}. "
                f"With 6+ years of systems engineering experience — including platform development "
                f"in C and optics driver work at Cisco — I'm drawn to this role's focus on "
                f"network systems."
            ),
            "linux_kernel": (
                f"I'm applying for the {job.role} role at {job.company}. "
                f"My 6+ years of Linux kernel debugging, device driver development, and firmware "
                f"work — across Google AR/VR prototypes and Cisco programmable hardware — align "
                f"closely with what you're building."
            ),
            "embedded": (
                f"I'm applying for the {job.role} position at {job.company}. "
                f"My background spans embedded Linux development, BSP work, and hardware bring-up "
                f"across real prototype and production systems, making this role a natural fit."
            ),
            "automation": (
                f"I'm applying for the {job.role} at {job.company}. "
                f"My Python and PyATS automation experience — building regression frameworks "
                f"and system validation tools at both Cognizant and Capgemini — lines up well "
                f"with this position."
            ),
            "default": (
                f"I'm applying for the {job.role} role at {job.company}. "
                f"With 6+ years building systems software in C and Python across Linux "
                f"environments, I believe I can contribute immediately to your engineering team."
            ),
        }
        return phrases.get(focus, phrases["default"])

    def _body_paragraphs(self, job: StoredJob, focus: str) -> str:
        paragraphs = {
            "networking": [
                (
                    "At Cisco Systems, I developed platform subsystems in C for programmable "
                    "hardware devices and integrated optics drivers into a modular framework "
                    "designed for platform scalability. I also built an Ethernet link verification "
                    "system and developed a PyATS-based automation framework for network platform "
                    "health at Capgemini."
                ),
                (
                    "At Cognizant (supporting Google AR/VR), I debugged complex Linux-based "
                    "prototype devices at the firmware, kernel, and application layer — developing "
                    "a systematic approach to cross-stack root cause analysis."
                ),
            ],
            "linux_kernel": [
                (
                    "At Cognizant on Google AR/VR, I worked daily with Linux kernel debugging, "
                    "tracing firmware issues through kernel and application layers on prototype "
                    "hardware. I built automation tools in Python and shell that reduced "
                    "manual validation cycles significantly."
                ),
                (
                    "At Cisco, I developed C-based platform subsystems for programmable hardware, "
                    "resolving deep device driver and memory management issues. I have hands-on "
                    "experience with GDB, kernel tracing, and log-based debugging across "
                    "complex system stacks."
                ),
            ],
            "embedded": [
                (
                    "My experience spans both consumer prototype hardware (Google AR/VR devices) "
                    "and production network equipment (Cisco). I've performed hardware bring-up, "
                    "BSP integration, and low-level debugging across both environments."
                ),
                (
                    "I'm comfortable moving between firmware, kernel, and application layers — "
                    "debugging multithreading issues, memory management problems, and platform "
                    "initialization failures in resource-constrained environments."
                ),
            ],
            "automation": [
                (
                    "At Cognizant, I built Python and shell automation tools for debugging and "
                    "system validation on Google AR/VR devices. At Capgemini, I developed a full "
                    "PyATS-based regression framework for Cisco NCS2K platform health testing."
                ),
                (
                    "My automation work has always been close to the hardware — validating firmware "
                    "behavior, Linux kernel states, and network system health. This gives my "
                    "automation a depth that purely software-focused engineers often lack."
                ),
            ],
        }
        paras = paragraphs.get(focus, [
            (
                "Over 6+ years, I've built and debugged systems software across Linux internals, "
                "device drivers, and C-based platform development — at Google (via Cognizant), "
                "Cisco Systems, and Capgemini."
            ),
            (
                "I'm most effective in environments where software, firmware, and hardware "
                "intersect — and I bring both coding discipline and a systematic debugging "
                "methodology to every role."
            ),
        ])
        return "\n\n".join(paras)

    def _closing(self, job: StoredJob) -> str:
        return (
            f"I'd welcome the opportunity to discuss how my background maps to the "
            f"{job.role} role at {job.company}. Thank you for your time and consideration."
        )

    # ── Q&A Answers ─────────────────────────────────────────────────────────

    def _qa_answers(self, job: StoredJob, focus: str) -> str:
        lines = [
            f"# Screening Q&A — {job.role} at {job.company}",
            "",
            "---",
            "",
            "## Why this role?",
            self._answer_why_role(job, focus),
            "",
            "## Why this company?",
            self._answer_why_company(job),
            "",
            "## Most relevant experience?",
            self._answer_relevant_experience(focus),
            "",
            "## Key strengths?",
            self._answer_strengths(focus),
            "",
            "## Walk me through a challenging debugging problem.",
            self._answer_debug_story(focus),
        ]
        return "\n".join(lines)

    def _answer_why_role(self, job: StoredJob, focus: str) -> str:
        snippets = {
            "linux_kernel": (
                f"The {job.role} role directly builds on what I've been doing — kernel debugging, "
                f"driver development, and firmware-level troubleshooting. I want to go deeper in "
                f"this space, and this role offers exactly that."
            ),
            "networking": (
                f"My most impactful work at Cisco was in networking systems — optics drivers, "
                f"platform subsystems, and network automation. The {job.role} role feels like a "
                f"natural continuation and deepening of that work."
            ),
            "default": (
                f"This role aligns with my core skills in C, Linux, and systems-level engineering. "
                f"I'm looking for an environment where these skills are central, not peripheral."
            ),
        }
        return snippets.get(focus, snippets["default"])

    def _answer_why_company(self, job: StoredJob) -> str:
        return (
            f"{job.company} works on problems that matter at the systems level. "
            f"I'm drawn to organizations where the software is close to hardware, "
            f"and where correctness and performance are taken seriously. "
            f"From what I've seen of {job.company}'s engineering culture, "
            f"it seems like a place where that mindset thrives."
        )

    def _answer_relevant_experience(self, focus: str) -> str:
        bullets = {
            "linux_kernel": self.profile["resume_bullets"]["linux_kernel"],
            "networking": self.profile["resume_bullets"]["networking"],
            "embedded": self.profile["resume_bullets"]["device_drivers"],
            "automation": self.profile["resume_bullets"]["automation"],
        }
        items = bullets.get(focus, self.profile["resume_bullets"]["linux_kernel"])
        return "\n".join(f"- {b}" for b in items)

    def _answer_strengths(self, focus: str) -> str:
        return (
            "1. **Low-level debugging**: I'm methodical across firmware, kernel, and "
            "application layers — comfortable with GDB, kernel tracing, and log analysis.\n"
            "2. **C systems programming**: 6+ years writing and debugging C for real hardware.\n"
            "3. **Automation mindset**: I naturally automate repetitive validation tasks — "
            "PyATS, pytest, shell scripting.\n"
            "4. **Cross-stack reasoning**: Comfortable following a bug from hardware through "
            "BSP, driver, kernel, and application layers."
        )

    def _answer_debug_story(self, focus: str) -> str:
        if focus in ("linux_kernel", "embedded"):
            return (
                "At Google AR/VR, we had a device intermittently hanging under specific workloads. "
                "Initial kernel logs showed no clear panic. I added targeted ftrace probes around "
                "suspect subsystems and found a race condition in the power management driver "
                "interacting with a vendor firmware callback. Fixed by serializing the callback "
                "path and adding proper locking. That bug had been open for weeks — I resolved "
                "it in two days using systematic tracing rather than guesswork."
            )
        elif focus == "networking":
            return (
                "At Cisco, an optics driver was reporting link flaps on specific hardware "
                "revisions only. I wrote a small C test harness that triggered the initialization "
                "sequence under different thermal conditions and captured register state. Found "
                "that a timing window in platform init was too tight on that hardware revision. "
                "Adjusted the sequencing, added a verification loop, and the flaps stopped."
            )
        return (
            "At Cisco, I debugged a memory leak in a platform subsystem that only manifested "
            "after 48+ hours of runtime. Used Valgrind and GDB watchpoints to trace the "
            "allocation path, identified a missing free in an error cleanup path, and fixed it. "
            "Added a unit test to prevent regression."
        )

    # ── Utilities ────────────────────────────────────────────────────────────

    def _determine_focus(self, job: StoredJob, matched_skills: list) -> str:
        text = (job.role + " " + job.description).lower()
        if any(k in text for k in ["network", "optic", "routing", "ethernet"]):
            return "networking"
        if any(k in text for k in ["kernel", "driver", "bsp", "firmware"]):
            return "linux_kernel" if "kernel" in text else "embedded"
        if any(k in text for k in ["automat", "qa ", "testing", "pyats"]):
            return "automation"
        return "default"

    def _focus_phrase(self, focus: str) -> str:
        return {
            "networking": "C-based networking systems and optics platforms",
            "linux_kernel": "Linux kernel debugging and device driver development",
            "embedded": "embedded Linux, BSP, and hardware bring-up",
            "automation": "Python automation and systems validation",
            "default": "Linux systems and C development",
        }.get(focus, "Linux systems engineering")

    def _experience_snippet(self, focus: str) -> str:
        snips = {
            "networking": (
                "Most recently, I built platform subsystems in C at Cisco and developed "
                "PyATS-based network automation at Capgemini."
            ),
            "linux_kernel": (
                "Most recently, I've been debugging Linux-based AR prototype devices at "
                "Google (via Cognizant), working across firmware, kernel, and application layers."
            ),
            "embedded": (
                "My experience spans Google AR/VR prototype hardware and Cisco production "
                "programmable devices — covering BSP, driver development, and hardware bring-up."
            ),
            "automation": (
                "I've built automation frameworks in Python and PyATS for both firmware "
                "validation and network platform health testing."
            ),
        }
        return snips.get(focus, "I've built systems software across Google, Cisco, and Capgemini.")

    def _save(self, job: StoredJob, doc_type: str, content: str) -> Path:
        company_slug = job.company.lower().replace(" ", "_")
        path = self.output_dir / f"{doc_type}_{job.job_id}_{company_slug}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(f"Saved {doc_type}: {path}")
        return path
