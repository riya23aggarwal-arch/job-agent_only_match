#!/usr/bin/env python3
"""
job-agent diagnose — full scoring transparency tool

Shows you EXACTLY:
  1. What text was extracted from the job posting
  2. What each skill alias searched for
  3. Which terms matched and where in the text
  4. How the score was calculated step by step
  5. Why the decision was made

Usage:
  python diagnose.py                    # run against built-in test jobs
  python diagnose.py --url <URL>        # score a live job URL
  python diagnose.py --id <JOB_ID>      # score a stored job
"""

import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from job_agent.models import RawJob
from job_agent.scoring.engine import (
    ScoringEngine,
    HIGH_SKILL_ALIASES,
    MEDIUM_SKILL_ALIASES,
    LOW_SKILL_ALIASES,
    ANTI_SKILL_ALIASES,
    W_HIGH, W_MEDIUM, W_LOW, W_ANTI,
    W_ROLE_MATCH, W_LOCATION, W_SENIORITY,
    SCORE_APPLY_NOW, SCORE_REVIEW,
)

# ── ANSI colors (works in any terminal) ───────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def green(s):  return f"{GREEN}{s}{RESET}"
def yellow(s): return f"{YELLOW}{s}{RESET}"
def red(s):    return f"{RED}{s}{RESET}"
def cyan(s):   return f"{CYAN}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"
def bold(s):   return f"{BOLD}{s}{RESET}"

SEP  = "─" * 70
SEP2 = "═" * 70


def find_in_text(phrase: str, text: str):
    """Find phrase in text, return (found: bool, context: str)"""
    phrase_l = phrase.lower()
    if " " in phrase_l:
        idx = text.find(phrase_l)
    else:
        m = re.search(r"\b" + re.escape(phrase_l) + r"\b", text)
        idx = m.start() if m else -1

    if idx == -1:
        return False, ""

    # Extract surrounding context (40 chars either side)
    start = max(0, idx - 40)
    end   = min(len(text), idx + len(phrase_l) + 40)
    snippet = text[start:end].replace("\n", " ").strip()
    # Highlight the match
    match_text = text[idx:idx + len(phrase_l)]
    highlighted = snippet.replace(match_text, f"{GREEN}{BOLD}{match_text}{RESET}")
    return True, f"...{highlighted}..."


def diagnose_job(job: RawJob, label: str = ""):
    engine = ScoringEngine()
    result = engine.score(job)
    text = (job.role + " " + job.description + " " + job.requirements).lower()

    print(f"\n{SEP2}")
    print(bold(f"  JOB: {job.company} — {job.role}"))
    if label:
        print(dim(f"  ({label})"))
    print(f"  Location: {job.location}  |  Source: {job.source}")
    print(SEP2)

    # ── 1. Show extracted text ─────────────────────────────────────────────
    print(f"\n{bold('① EXTRACTED TEXT (what the scorer sees)')}")
    print(SEP)
    total_text = job.role + " " + job.description + " " + job.requirements
    print(f"  Total length: {len(total_text)} chars")
    print(f"  Role:         {job.role}")
    print(f"  Description:  {job.description[:200]}{'...' if len(job.description) > 200 else ''}")
    if job.requirements:
        print(f"  Requirements: {job.requirements[:200]}{'...' if len(job.requirements) > 200 else ''}")

    # ── 2. HIGH skills ─────────────────────────────────────────────────────
    print(f"\n{bold('② HIGH WEIGHT SKILLS')}  {green(f'(+{W_HIGH} each — core skills)')}")
    print(SEP)
    high_matched = []
    high_score = 0
    for canonical, aliases in HIGH_SKILL_ALIASES.items():
        matched_alias = None
        context = ""
        for alias in aliases:
            found, ctx = find_in_text(alias, text)
            if found:
                matched_alias = alias
                context = ctx
                break

        if matched_alias:
            high_matched.append(canonical)
            high_score += W_HIGH
            print(f"  {green('✅ MATCH')}  {bold(canonical):<28} via '{matched_alias}'")
            print(f"           {dim(context)}")
        else:
            tried = ", ".join(f"'{a}'" for a in aliases[:3])
            more = f" +{len(aliases)-3} more" if len(aliases) > 3 else ""
            print(f"  {red('❌ MISS ')}  {dim(canonical):<28} tried: {dim(tried + more)}")

    print(f"\n  → High skill score: {green(str(high_score))} pts  ({len(high_matched)}/{len(HIGH_SKILL_ALIASES)} matched)")

    # ── 3. MEDIUM skills ───────────────────────────────────────────────────
    print(f"\n{bold('③ MEDIUM WEIGHT SKILLS')}  {yellow(f'(+{W_MEDIUM} each — supporting skills)')}")
    print(SEP)
    medium_matched = []
    medium_score = 0
    for canonical, aliases in MEDIUM_SKILL_ALIASES.items():
        matched_alias = None
        context = ""
        for alias in aliases:
            found, ctx = find_in_text(alias, text)
            if found:
                matched_alias = alias
                context = ctx
                break

        if matched_alias:
            medium_matched.append(canonical)
            medium_score += W_MEDIUM
            print(f"  {green('✅ MATCH')}  {bold(canonical):<28} via '{matched_alias}'")
            print(f"           {dim(context)}")
        else:
            tried = ", ".join(f"'{a}'" for a in aliases[:3])
            print(f"  {yellow('⚪ MISS ')}  {dim(canonical):<28} tried: {dim(tried)}")

    print(f"\n  → Medium skill score: {yellow(str(medium_score))} pts  ({len(medium_matched)}/{len(MEDIUM_SKILL_ALIASES)} matched)")

    # ── 4. ANTI skills ─────────────────────────────────────────────────────
    print(f"\n{bold('④ ANTI-SKILLS (PENALTIES)')}  {red(f'({W_ANTI} each — wrong domain)')}")
    print(SEP)
    anti_hits = []
    for canonical, aliases in ANTI_SKILL_ALIASES.items():
        matched_alias = None
        context = ""
        for alias in aliases:
            found, ctx = find_in_text(alias, text)
            if found:
                matched_alias = alias
                context = ctx
                break
        if matched_alias:
            anti_hits.append(canonical)
            print(f"  {red('⚠  HIT  ')}  {bold(canonical):<28} via '{matched_alias}'")
            print(f"           {dim(context)}")
        else:
            print(f"  {green('✓ clean ')}  {dim(canonical)}")

    anti_penalty = max(-30, len(anti_hits) * W_ANTI)
    if anti_hits:
        print(f"\n  → Anti-skill penalty: {red(str(anti_penalty))} pts  ({len(anti_hits)} hits, capped at -30)")
    else:
        print(f"\n  → No penalties  {green('✓')}")

    # ── 5. Bonuses ─────────────────────────────────────────────────────────
    print(f"\n{bold('⑤ BONUSES')}")
    print(SEP)
    role_bonus     = engine._score_role_match(job.role)
    location_bonus = engine._score_location(job.location)
    seniority_bonus= engine._score_seniority(job.role, job.description)

    role_icon = green("✅") if role_bonus > 0 else red("❌")
    loc_icon  = green("✅") if location_bonus > 0 else red("❌")
    sen_icon  = green("✅") if seniority_bonus > 0 else yellow("⚪")

    print(f"  {role_icon}  Role title match:  {green(f'+{role_bonus}') if role_bonus else dim('0')}  (role='{job.role[:40]}')")
    print(f"  {loc_icon}  Location match:   {green(f'+{location_bonus}') if location_bonus else dim('0')}  (location='{job.location}')")
    print(f"  {sen_icon}  Seniority match:  {green(f'+{seniority_bonus}') if seniority_bonus else dim('0')}")

    # ── 6. Score calculation ───────────────────────────────────────────────
    realistic_max = (6*W_HIGH) + (4*W_MEDIUM) + (2*W_LOW) + W_ROLE_MATCH + W_LOCATION + W_SENIORITY
    low_score = result.skill_breakdown.get("bonus_skills", 0)
    raw = high_score + medium_score + low_score + anti_penalty + role_bonus + location_bonus + seniority_bonus
    normalized = min(100, max(0, int((max(0, raw) / realistic_max) * 100)))

    print(f"\n{bold('⑥ SCORE CALCULATION')}")
    print(SEP)
    print(f"  High skills:      {high_score:>4}  ({len(high_matched)} × {W_HIGH})")
    print(f"  Medium skills:    {medium_score:>4}  ({len(medium_matched)} × {W_MEDIUM})")
    print(f"  Low/bonus skills: {low_score:>4}")
    print(f"  Anti penalties:   {anti_penalty:>4}  ({len(anti_hits)} × {W_ANTI}, capped -30)")
    print(f"  Role bonus:       {role_bonus:>4}")
    print(f"  Location bonus:   {location_bonus:>4}")
    print(f"  Seniority bonus:  {seniority_bonus:>4}")
    print(f"  {SEP[:40]}")
    print(f"  Raw total:        {raw:>4}")
    print(f"  Realistic max:    {realistic_max:>4}  (6×high + 4×med + 2×low + bonuses)")
    print(f"  Formula:          {raw} / {realistic_max} × 100 = {normalized}")

    # ── 7. Final decision ──────────────────────────────────────────────────
    print(f"\n{bold('⑦ FINAL DECISION')}")
    print(SEP)
    if normalized >= SCORE_APPLY_NOW:
        dec_str = green(f"✅  APPLY NOW  ({normalized}/100 ≥ {SCORE_APPLY_NOW})")
    elif normalized >= SCORE_REVIEW:
        dec_str = yellow(f"👀  REVIEW     ({normalized}/100 ≥ {SCORE_REVIEW})")
    else:
        dec_str = red(f"❌  DISCARD    ({normalized}/100 < {SCORE_REVIEW})")

    print(f"  {bold(dec_str)}")

    # ── 8. What would make this score higher ──────────────────────────────
    missed_high = [s for s in HIGH_SKILL_ALIASES if s not in high_matched]
    if missed_high and normalized < SCORE_APPLY_NOW:
        needed = max(0, SCORE_APPLY_NOW - normalized)
        print(f"\n{bold(f'⑧ TO REACH APPLY NOW ({SCORE_APPLY_NOW}+)')}")
        print(SEP)
        print(f"  Need {needed} more points. Missing high-value skills in posting:")
        for skill in missed_high[:6]:
            aliases_preview = HIGH_SKILL_ALIASES[skill][:2]
            print(f"  {red('·')} {skill}  {dim('(job should mention: ' + ', '.join(aliases_preview) + ')')}")

    print(f"\n{SEP}\n")
    return result


# ── Built-in test jobs ─────────────────────────────────────────────────────────

REAL_TEST_JOBS = [
    RawJob(
        company="Cloudflare",
        role="Systems Engineer, Linux Networking",
        location="Austin, TX",
        description=(
            "Cloudflare is looking for a Systems Engineer to join our Linux networking team. "
            "You will work on the Linux kernel networking stack, developing and debugging "
            "network subsystems in C. You'll write kernel modules, work with device drivers, "
            "and debug low-level system issues using GDB and kernel tracing tools. "
            "Experience with TCP/IP, packet processing, and network protocols required. "
            "Python scripting for automation is a plus."
        ),
        requirements=(
            "5+ years of C programming on Linux. "
            "Deep understanding of Linux kernel internals and networking stack. "
            "Experience with device drivers or kernel modules. "
            "Proficiency with GDB and kernel debugging tools. "
            "Knowledge of TCP/IP and networking protocols."
        ),
        apply_url="https://boards.greenhouse.io/cloudflare/jobs/test1",
        source="greenhouse",
    ),
    RawJob(
        company="Intel",
        role="Linux Kernel Engineer",
        location="US, Oregon, Hillsboro",
        description="Linux Kernel Engineer",  # Workday title-only (no detail fetched)
        requirements="",
        apply_url="https://intel.wd1.myworkdayjobs.com/test",
        source="workday",
    ),
    RawJob(
        company="Cloudflare",
        role="Customer Solutions Engineer",
        location="Remote",
        description=(
            "As a Customer Solutions Engineer you will work with enterprise customers "
            "to understand their technical requirements and demonstrate Cloudflare products. "
            "You will conduct technical presentations, proof of concepts, and help customers "
            "onboard to our platform. Strong communication and customer-facing skills required."
        ),
        requirements="Customer-facing experience, networking knowledge, technical presentations",
        apply_url="https://boards.greenhouse.io/cloudflare/jobs/test2",
        source="greenhouse",
    ),
    RawJob(
        company="Arista Networks",
        role="Senior Software Engineer - EOS Platform",
        location="Santa Clara, CA",
        description=(
            "Arista is hiring a Senior Software Engineer to work on EOS, our network operating "
            "system. You will develop platform subsystems in C, work on Linux-based systems, "
            "and implement device drivers for networking hardware. Experience with BSP development, "
            "hardware bring-up, and kernel debugging required. Python automation for testing. "
            "Multithreading and memory management expertise needed."
        ),
        requirements=(
            "BS/MS in CS or EE. 5+ years C on Linux. "
            "Device driver development. BSP and platform initialization experience. "
            "Kernel debugging. Networking systems knowledge. Python scripting."
        ),
        apply_url="https://boards.greenhouse.io/arista/jobs/test3",
        source="greenhouse",
    ),
    RawJob(
        company="Plaid",
        role="Senior Software Engineer - Fullstack",
        location="San Francisco",
        description=(
            "Build and scale Plaid's core financial data infrastructure. "
            "Work across the full stack using React, Node.js, and PostgreSQL. "
            "Strong JavaScript/TypeScript skills. REST API design. "
            "Experience with AWS and distributed systems."
        ),
        requirements="React, Node.js, TypeScript, PostgreSQL, AWS",
        apply_url="https://jobs.lever.co/plaid/test4",
        source="lever",
    ),
]


def main():
    parser = argparse.ArgumentParser(description="Diagnose job scoring")
    parser.add_argument("--url",  help="Fetch and diagnose a live job URL")
    parser.add_argument("--id",   help="Diagnose a stored job by ID")
    parser.add_argument("--job",  choices=["1","2","3","4","5"], help="Run built-in test job (1-5)")
    args = parser.parse_args()

    print(f"\n{SEP2}")
    print(bold("  JOB-AGENT SCORING DIAGNOSTIC"))
    print(f"  Thresholds: APPLY NOW ≥ {SCORE_APPLY_NOW}  |  REVIEW ≥ {SCORE_REVIEW}  |  DISCARD < {SCORE_REVIEW}")
    print(f"  High skills: +{W_HIGH} each  |  Medium: +{W_MEDIUM}  |  Anti-skills: {W_ANTI}")
    print(SEP2)

    if args.url:
        import requests
        from bs4 import BeautifulSoup
        print(f"\nFetching: {args.url}")
        resp = requests.get(args.url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text("\n")[:4000]
        job = RawJob(company="Unknown", role="Unknown", location="",
                     description=text, requirements="", apply_url=args.url, source="manual")
        diagnose_job(job, "fetched from URL")

    elif args.id:
        from job_agent.storage.database import Database
        db = Database()
        job = db.get_job(args.id)
        if not job:
            print(red(f"Job {args.id} not found"))
            sys.exit(1)
        raw = RawJob(company=job.company, role=job.role, location=job.location,
                     description=job.description, requirements=job.requirements,
                     apply_url=job.apply_url, source=job.source)
        diagnose_job(raw, f"stored job {args.id}")

    elif args.job:
        idx = int(args.job) - 1
        job = REAL_TEST_JOBS[idx]
        diagnose_job(job, "built-in test")

    else:
        # Run all built-in test jobs
        labels = [
            "Cloudflare Linux Networking — GOOD JD, should APPLY NOW",
            "Intel Linux Kernel — Workday title-only, sparse",
            "Cloudflare Customer Solutions — sales role, should DISCARD",
            "Arista EOS Platform — rich JD, should APPLY NOW",
            "Plaid Fullstack — web role, should DISCARD",
        ]
        for i, (job, label) in enumerate(zip(REAL_TEST_JOBS, labels)):
            diagnose_job(job, label)

        # Summary
        engine = ScoringEngine()
        print(f"\n{SEP2}")
        print(bold("  SUMMARY"))
        print(SEP2)
        for job, label in zip(REAL_TEST_JOBS, labels):
            r = engine.score(job)
            if r.score >= SCORE_APPLY_NOW:
                icon = green("✅ APPLY NOW")
            elif r.score >= SCORE_REVIEW:
                icon = yellow("👀 REVIEW   ")
            else:
                icon = red("❌ DISCARD  ")
            print(f"  {icon}  [{r.score:3d}]  {job.company} — {job.role[:45]}")
        print(f"\n  {dim('Run: python diagnose.py --job 1   (to see detail for job 1 only)')}")
        print(f"  {dim('Run: python diagnose.py --id <ID>  (to diagnose a stored job)')}")
        print(f"  {dim('Run: python diagnose.py --url <URL> (to score a live posting)')}")
        print()


if __name__ == "__main__":
    main()
