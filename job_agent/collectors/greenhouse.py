"""
Greenhouse Collector

Public API: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
No auth needed. Returns all job postings as structured JSON.

SLUGS: Find correct slug by visiting boards.greenhouse.io/{slug}
       If it returns JSON, the slug is correct.
       All slugs below are verified working.
"""

import logging
from typing import Generator, List

from job_agent.collectors.base import BaseCollector
from job_agent.collectors.filters import passes_location_filter, passes_title_filter
from job_agent.models import RawJob

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

# Greenhouse slugs — format: boards.greenhouse.io/{slug}
# Verified: slug returns JSON from the API
# Each slug confirmed by checking the actual Greenhouse board URL

# ── VERIFIED working Greenhouse slugs ─────────────────────────────────────
# Only slugs confirmed to return jobs from live API responses
# To verify a new slug: curl https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
# 200 + jobs array = working, 404 = wrong slug

DEFAULT_COMPANIES = [
    # CDN / Networking SaaS — confirmed working
    "cloudflare",       # 560+ jobs ✅
    "fastly",           # 55 jobs ✅

    # Automotive / Robotics — confirmed working
    "waymo",            # ✅
    "nuro",             # ✅

    # Security — confirmed working
    "crowdstrike",      # ✅
    "zscaler",          # 292 jobs ✅
    "illumio",          # ✅

    # Optical / Telecom — confirmed working
    "ciena",            # ✅
    "infinera",         # ✅
    "calix",            # ✅

    # Silicon — confirmed working
    "rambus",           # ✅

    # ── To verify manually (may work, may 404) ─────────────────────────────
    # Visit boards.greenhouse.io/{slug} to confirm before adding back:
    # "aristaeosplatform"    — Arista (aristaeosplatform? arista? arista-eos?)
    # "rivian"               — 404 so far
    # "aurora"               — 404 so far
    # "zooxtech"             — 404 so far
    # "lattice-semiconductor"— 404 so far
    # "astera-labs"          — 404 so far
    # "anduril"              — unverified
]


class GreenhouseCollector(BaseCollector):
    source_name = "greenhouse"

    def __init__(
        self,
        companies: List[str] = None,
        keywords: List[str] = None,
        locations: List[str] = None,
        filter_location: bool = True,
    ):
        super().__init__(keywords=keywords, locations=locations)
        self.companies = companies or DEFAULT_COMPANIES
        self.filter_location = filter_location

    def _fetch_jobs(self) -> Generator[RawJob, None, None]:
        for company in self.companies:
            yield from self._collect_company(company)

    def _collect_company(self, company: str) -> Generator[RawJob, None, None]:
        url = GREENHOUSE_API.format(slug=company)
        logger.info(f"[greenhouse] ⟳  Fetching {company} ...")
        data = self._get(url, params={"content": "true"}, json_response=True)

        if not data or "jobs" not in data:
            logger.info(f"[greenhouse] ✗  {company}: not on Greenhouse or wrong slug")
            return

        all_jobs = data["jobs"]
        total = len(all_jobs)
        passed, blocked_title, blocked_loc = [], 0, 0

        for job_data in all_jobs:
            title = job_data.get("title", "")

            # Level 1: title filter
            ok, reason = passes_title_filter(title)
            if not ok:
                blocked_title += 1
                logger.debug(f"[greenhouse]   title-filtered '{title}' — {reason}")
                continue

            # Level 2: location filter
            if self.filter_location:
                offices = job_data.get("offices", [])
                location = offices[0]["name"] if offices else ""
                loc_ok, loc_reason = passes_location_filter(location)
                if not loc_ok:
                    blocked_loc += 1
                    logger.info(f"[greenhouse]   ✗ loc: '{title}' — {loc_reason} ({location})")
                    continue

            passed.append(job_data)

        logger.info(
            f"[greenhouse] ✓  {company}: {total} total "
            f"→ {blocked_title} title-filtered, {blocked_loc} loc-filtered "
            f"→ [bold]{len(passed)} to score[/bold]"
        )

        for job_data in passed:
            job = self._parse_job(job_data, company)
            if job:
                yield job

    # Known HQ locations for companies that don't include office data
    COMPANY_LOCATIONS = {
        "nuro": "Mountain View, CA",
        "zooxtech": "Foster City, CA",
        "aurora": "Pittsburgh, PA",
        "illumio": "Sunnyvale, CA",
        "astera-labs": "Santa Clara, CA",
        "rambus": "San Jose, CA",
        "calix": "San Jose, CA",
        "ciena": "Hanover, MD",
        "infinera": "San Jose, CA",
        "lattice-semiconductor": "Hillsboro, OR",
    }

    def _parse_job(self, data: dict, company: str) -> RawJob:
        try:
            offices = data.get("offices", [])
            if offices and offices[0].get("name"):
                location = self._normalize_location(offices[0]["name"])
            else:
                # Fall back to known HQ if Greenhouse doesn't return office data
                location = self.COMPANY_LOCATIONS.get(company, "United States")
            content = data.get("content", "")
            description, requirements = self._split_description(content)
            return RawJob(
                company=company.replace("-", " ").title(),
                role=data.get("title", ""),
                location=location,
                description=description,
                requirements=requirements,
                apply_url=data.get("absolute_url", ""),
                source="greenhouse",
                remote="remote" in location.lower(),
            )
        except Exception as e:
            logger.warning(f"[greenhouse] Parse error for {company}: {e}")
            return None

    def _split_description(self, html_content: str):
        if not html_content:
            return "", ""
        soup = self._parse_html(html_content)
        text = self._clean_text(soup.get_text("\n"))
        lines = text.splitlines()
        req_start = None
        for i, line in enumerate(lines):
            if any(kw in line.lower() for kw in
                   ["requirements", "qualifications", "what you'll need",
                    "you have", "you bring", "minimum qualifications",
                    "basic qualifications", "required experience"]):
                req_start = i
                break
        if req_start:
            return "\n".join(lines[:req_start]).strip()[:3000], "\n".join(lines[req_start:]).strip()[:2000]
        return text[:3000], ""
