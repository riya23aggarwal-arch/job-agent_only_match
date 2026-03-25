"""
Scoring rubrics, prompts, and candidate profile formatter.

Used by all AI scoring backends to evaluate job-candidate fit.
"""

# ── Candidate Profile Template ─────────────────────────────────────────────────

CANDIDATE_PROFILE_TEMPLATE = """\
CANDIDATE: {name}
EXPERIENCE: {years} years in {domains}

CORE COMPETENCIES (Tier 1):
{tier1_skills}

SECONDARY SKILLS (Tier 2):
{tier2_skills}

VALUED SOFT SKILLS:
- Ownership and systems thinking
- Hardware-software co-design understanding
- Low-level troubleshooting capability
- Validation and testing rigor
- Performance profiling and optimization

EXPLICITLY NOT INTERESTED IN:
- Security roles (info sec, vulnerability research)
- Data engineering / ML / AI
- DevOps / container orchestration / Kubernetes
- Research-only roles
- Staff/Principal/Research roles (targeting {target_level})

PREFERRED ROLE TYPES:
{role_types}
"""

# ── AI System Prompt ────────────────────────────────────────────────────────────

OPENAI_SYSTEM_PROMPT = """\
You are an expert technical hiring evaluator for systems/embedded/networking roles.

Assess candidate-job fit based on actual work content, NOT keyword matching.
Think like a hiring manager who values:
- Systems depth and understanding
- Hardware-software interaction knowledge
- Ownership and impact
- Transferable skills and learning ability
- Ability to debug and optimize at low levels

DISTINGUISH BETWEEN:
- TRUE BLOCKERS: Deal-breaker gaps requiring 6+ months to learn
- LEARNABLE GAPS: Skills acquirable in weeks/months given the candidate's background

CREDIT:
- Debugging and troubleshooting capability
- Low-level systems knowledge
- Performance optimization experience
- Hardware-software boundary work
- Linux/kernel familiarity
- C/embedded programming background

DO NOT OVER-PENALIZE:
- Vendor-specific buzzwords (Cisco IOS, specific tools)
- Exact tech stack mismatches
- Missing certifications or formal training

RECOGNIZE THAT:
- A Linux systems engineer can learn Cisco IOS
- A C programmer adapts to new language variants quickly
- Hardware debugging experience transfers across domains
- Kernel knowledge applies to many embedded systems

ROLE FAMILY CLASSIFICATION:
Classify the role as one of:
- embedded_systems: Firmware, microcontroller, embedded C, BSP
- linux_kernel: Kernel development, kernel drivers, kernel internals
- platform_software: System software, platform services, reliability
- networking_software: Network protocols, network stack, network tools
- systems_validation: Validation, testing, diagnostics, troubleshooting
- firmware: Firmware, bootloaders, BIOS, device initialization
- mixed: Hybrid or unclear role

SCORING:
- 0–20:  Fundamentally mismatched
- 20–40: Weak match (some relevant skills, major gaps)
- 40–60: Viable match (foundational skills present, gaps learnable)
- 60–75: Good match (strong core skills, some specific gaps)
- 75–90: Strong match (most skills present)
- 90–100: Excellent match

CONFIDENCE:
- high:   Clear verdict from clear role description
- medium: Some ambiguity in role or candidate fit
- low:    Vague role description or uncertain assessment

VERDICT:
- 0–40:  "weak match"
- 40–50: "stretch"
- 50–65: "viable match"
- 65–80: "good match"
- 80+:   "strong match"

CRITICAL: Return ONLY valid JSON matching the schema below. No markdown, no extra text.
"""

OPENAI_USER_PROMPT_TEMPLATE = """\
Evaluate this job opportunity for the candidate.

CANDIDATE PROFILE:
{candidate_profile}

JOB DETAILS:
Company: {company}
Title: {role}
Location: {location}
Level: {level}
Remote: {remote}

JOB DESCRIPTION:
{description}

KEY REQUIREMENTS:
{requirements}

Return ONLY valid JSON matching this exact schema:
{{
  "role_family": "embedded_systems|linux_kernel|platform_software|networking_software|systems_validation|firmware|mixed",
  "score": <integer 0-100>,
  "confidence": "high|medium|low",
  "verdict": "weak match|stretch|viable match|good match|strong match",
  "reasons": ["reason1", "reason2"],
  "true_blockers": ["blocker1"],
  "learnable_gaps": ["gap1", "gap2"]
}}
"""

# Reuse same prompts for Anthropic backend if added later
ANTHROPIC_SYSTEM_PROMPT = OPENAI_SYSTEM_PROMPT
ANTHROPIC_USER_PROMPT_TEMPLATE = OPENAI_USER_PROMPT_TEMPLATE


# ── Candidate Profile Builder ──────────────────────────────────────────────────

def get_standard_rubric() -> str:
    """
    Build and return the formatted candidate profile string for AI scoring.

    Reads from job_agent.profile.CANDIDATE_PROFILE and formats it using
    CANDIDATE_PROFILE_TEMPLATE. This is passed as `candidate_profile` to
    every scorer.score() call.

    Returns:
        Formatted multi-line string describing the candidate.
    """
    from job_agent.profile import CANDIDATE_PROFILE
    p = CANDIDATE_PROFILE

    tier1 = "\n".join(f"  - {s}" for s in p.get("skills_high", []))
    tier2 = "\n".join(f"  - {s}" for s in p.get("skills_medium", []))
    roles = "\n".join(f"  - {r}" for r in p.get("target_roles", []))

    base = CANDIDATE_PROFILE_TEMPLATE.format(
        name=p.get("name", "Candidate"),
        years=p.get("years_experience", ""),
        domains="Linux systems, embedded software, networking, firmware",
        tier1_skills=tier1,
        tier2_skills=tier2,
        target_level="Senior / Staff (SWE II–III equivalent)",
        role_types=roles,
    )

    # Append experience highlights
    exp_lines = ["\nEXPERIENCE HIGHLIGHTS:"]
    for e in p.get("experience", []):
        exp_lines.append(f"  {e['company']} | {e['title']} | {e['duration']}")
        for h in e.get("highlights", []):
            exp_lines.append(f"    • {h}")

    return base + "\n".join(exp_lines)
