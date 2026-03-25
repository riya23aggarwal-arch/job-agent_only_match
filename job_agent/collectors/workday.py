"""
Workday Collector

Uses Workday's CXS (Candidate Experience) API directly.

KEY INSIGHT: Workday job detail pages are JS-rendered — requests.get() returns
an empty shell. Instead, we use the Workday job detail API endpoint:
  POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{jobId}

This returns the full JSON job description without needing a browser.
"""

import logging
import re
import time
from typing import Generator, List, Tuple

from job_agent.collectors.base import BaseCollector
from job_agent.collectors.filters import passes_location_filter, passes_title_filter
from job_agent.models import RawJob

logger = logging.getLogger(__name__)

DEFAULT_WORKDAY_COMPANIES: List[Tuple[str, int, str, str]] = [
    # ── Verified working ────────────────────────────────────────────────────
    ("cisco",               5,  "Cisco_Careers",              "Cisco"),
    ("intel",               1,  "External",                   "Intel"),

    # ── High-value targets — verify with workday_verify.py ──────────────────
    ("nvidia",              5,  "NVIDIAExternalCareerSite",   "Nvidia"),
    ("qualcomm",            5,  "External",                   "Qualcomm"),
    ("broadcom",            1,  "External",                   "Broadcom"),
    ("marvell",             1,  "MarvellCareers",             "Marvell"),
    ("paloaltonetworks",    1,  "External",                   "Palo Alto Networks"),
    ("fortinet",            1,  "External",                   "Fortinet"),
    ("hpe",                 5,  "Jobsathpe",                  "HPE"),
    ("purestorage",         1,  "External",                   "Pure Storage"),
    ("juniper",             1,  "JuniperCareers",             "Juniper Networks"),
    ("waymo",               1,  "waymo",                      "Waymo"),
    ("rivian",              1,  "careers",                    "Rivian"),

    # 422 errors — need correct site name:
    # ("amd",               1,  "External",                   "AMD"),
    # ("servicenow",        1,  "External",                   "ServiceNow"),
    # ("netapp",            1,  "External",                   "NetApp"),
]

SEARCH_KEYWORDS = [
    "linux engineer",
    "platform engineer",
    "kernel engineer",
    "firmware engineer",
    "embedded engineer",
    "systems engineer",
    "network engineer",
    "driver engineer",
]


class WorkdayCollector(BaseCollector):
    source_name = "workday"
    rate_limit_seconds = 0.5

    def __init__(
        self,
        companies: List[Tuple] = None,
        keywords: List[str] = None,
        locations: List[str] = None,
        filter_location: bool = True,
    ):
        super().__init__(keywords=keywords, locations=locations)
        self.companies = companies or DEFAULT_WORKDAY_COMPANIES
        self.search_keywords = keywords or SEARCH_KEYWORDS
        self.filter_location = filter_location

    def _fetch_jobs(self) -> Generator[RawJob, None, None]:
        if not self.companies:
            logger.info("[workday] No companies configured — skipping")
            return
        for entry in self.companies:
            tenant, wd_num, site, display_name = entry
            yield from self._collect_workday(tenant, wd_num, site, display_name)

    def _collect_workday(
        self, tenant: str, wd_num: int, site: str, display_name: str
    ) -> Generator[RawJob, None, None]:
        base_url = f"https://{tenant}.wd{wd_num}.myworkdayjobs.com"
        api_url  = f"{base_url}/wday/cxs/{tenant}/{site}/jobs"

        headers = {
            **self.session.headers,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        seen_ids = set()

        for keyword in self.search_keywords:
            payload = {
                "appliedFacets": {},
                "limit": 20,
                "offset": 0,
                "searchText": keyword,
            }

            try:
                resp = self.session.post(
                    api_url, json=payload, headers=headers, timeout=8
                )

                if resp.status_code == 404:
                    logger.info(
                        f"[workday] ✗  {display_name}: 404 — wrong site name '{site}'\n"
                        f"           Run: python job_agent/collectors/workday_verify.py --company {tenant}"
                    )
                    return

                if resp.status_code == 422:
                    logger.debug(f"[workday] ✗  {display_name} / '{keyword}': 422")
                    continue

                resp.raise_for_status()
                data = resp.json()

            except Exception as e:
                logger.info(f"[workday] ✗  {display_name} / '{keyword}': {str(e)[:60]}")
                time.sleep(1)
                continue

            job_postings = data.get("jobPostings", [])
            if not job_postings:
                continue

            passed = []
            for posting in job_postings:
                title    = posting.get("title", "")
                job_path = posting.get("externalPath", "")

                if job_path and job_path in seen_ids:
                    continue
                if job_path:
                    seen_ids.add(job_path)

                ok, reason = passes_title_filter(title)
                if not ok:
                    logger.debug(f"[workday]   title-filtered '{title}' — {reason}")
                    continue

                if self.filter_location:
                    location = posting.get("locationsText", "")
                    loc_ok, loc_reason = passes_location_filter(location)
                    if not loc_ok:
                        logger.info(f"[workday]   ✗ loc-filtered: '{title}' — {loc_reason}")
                        continue

                passed.append(posting)

            if passed:
                logger.info(
                    f"[workday] ✓  {display_name} / '{keyword}': "
                    f"{len(job_postings)} results → {len(passed)} to score"
                )

            for posting in passed:
                job = self._parse_posting(
                    posting, display_name, base_url, api_url, tenant, site, headers
                )
                if job:
                    yield job
                    time.sleep(self.rate_limit_seconds)

    def _parse_posting(
        self,
        posting: dict,
        display_name: str,
        base_url: str,
        api_url: str,
        tenant: str,
        site: str,
        headers: dict,
    ) -> RawJob:
        try:
            title         = posting.get("title", "")
            external_path = posting.get("externalPath", "")

            # Build human-facing apply URL
            # API path:   /wday/cxs/{tenant}/{site}/job/Location/Title_ID
            # Human URL:  /en-US/{site}/job/Location/Title_ID
            if external_path:
                if not external_path.startswith("/"):
                    external_path = "/" + external_path
                human_path = re.sub(
                    r"^/wday/cxs/[^/]+/([^/]+)",
                    r"/en-US/\1",
                    external_path
                )
                apply_url = f"{base_url}{human_path}"
                # Reject invalid redirect URLs
                if "community.workday" in apply_url or "invalid-url" in apply_url:
                    logger.debug(f"[workday] Invalid apply URL rejected: {apply_url}")
                    apply_url = f"{base_url}/en-US/{site}/job"
            else:
                apply_url = ""

            location = self._normalize_location(posting.get("locationsText", "Unknown"))

            # Fetch full description via Workday detail API
            description, requirements = self._fetch_detail_api(
                api_url, external_path, display_name, title
            )

            # Fallback to listing brief if API failed
            if not description:
                description = (
                    posting.get("jobDescription", "")
                    or posting.get("brief", "")
                    or title
                )
                logger.debug(f"[workday] Used brief fallback for '{title}'")

            return RawJob(
                company=display_name,
                role=title,
                location=location,
                description=description[:3000],
                requirements=requirements[:2000],
                apply_url=apply_url,
                source="workday",
                remote="remote" in location.lower(),
            )
        except Exception as e:
            logger.warning(f"[workday] Parse error for {display_name}: {e}")
            return None

    def _fetch_detail_api(
        self,
        api_url: str,
        external_path: str,
        company: str,
        title: str,
    ) -> tuple:
        """
        Fetch full job description using Workday's detail API endpoint.
        Returns (description, requirements) tuple.
        """
        if not external_path:
            return "", ""

        parts = external_path.rstrip("/").split("/")
        if not parts:
            return "", ""

        detail_url = api_url.rstrip("/jobs") + f"/job{external_path}"

        try:
            resp = self.session.post(
                detail_url,
                json={},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=8,
            )

            if resp.status_code == 200:
                data = resp.json()

                info = data.get("jobPostingInfo", {})
                desc_html = (
                    info.get("jobDescription", "")
                    or info.get("jobSummary", "")
                    or data.get("jobDescription", "")
                )

                if desc_html:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(desc_html, "html.parser")
                    text = self._clean_text(soup.get_text("\n"))

                    lines = text.splitlines()
                    req_start = None
                    for i, line in enumerate(lines):
                        if any(kw in line.lower() for kw in
                               ["minimum qualifications", "basic qualifications",
                                "requirements", "qualifications", "you have",
                                "what you'll need", "required experience"]):
                            req_start = i
                            break

                    if req_start:
                        desc = "\n".join(lines[:req_start])
                        reqs = "\n".join(lines[req_start:])
                    else:
                        desc = text
                        reqs = ""

                    logger.debug(f"[workday] Got {len(text)} chars from detail API: '{title}'")
                    return desc[:3000], reqs[:2000]

        except Exception as e:
            logger.debug(f"[workday] Detail API failed for '{title}': {e}")

        return "", ""
