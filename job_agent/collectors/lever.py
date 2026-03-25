"""
Lever Collector

Lever public API:
  GET https://api.lever.co/v0/postings/{slug}?mode=json

Only a small number of companies actually work on this API.
Most large companies (Netflix, Stripe, etc.) have moved off public Lever
or block the API. Only verified-working slugs are listed here.
"""

import logging
from typing import Generator, List

from job_agent.collectors.base import BaseCollector
from job_agent.collectors.filters import passes_location_filter, passes_title_filter
from job_agent.models import RawJob

logger = logging.getLogger(__name__)

LEVER_API = "https://api.lever.co/v0/postings/{company}"

# Only keep companies that actually respond to the Lever API
# Verified from live run: plaid works, everything else times out/404
DEFAULT_COMPANIES = [
    # ✅ Confirmed working
    "plaid",

    # ⚠ May work — lower priority, systems-relevant companies
    "tailscale",
    "1password",
    "wiz-io",
    "aquasecurity",
    "lacework",

    # Removed — confirmed dead/timeout from live logs:
    # netflix, twitch, coinbase, stripe, scale-ai, databricks,
    # reddit, hashicorp, figma — all timeout or 404
]


class LeverCollector(BaseCollector):
    source_name = "lever"
    rate_limit_seconds = 1.0  # faster since fewer companies

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
        url = LEVER_API.format(company=company)
        logger.info(f"[lever] ⟳  Fetching {company} ...")

        data = self._get(url, params={"mode": "json", "commitment": "Full-time"},
                         json_response=True)

        if not data:
            logger.info(f"[lever] ✗  {company}: no data (not on Lever or API blocked)")
            return

        postings = data if isinstance(data, list) else data.get("postings", [])
        total = len(postings)

        passed = []
        blocked_count = 0
        for posting in postings:
            title = posting.get("text", "")
            ok, reason = passes_title_filter(title)
            if not ok:
                blocked_count += 1
                continue

            if self.filter_location:
                categories = posting.get("categories", {})
                location = categories.get("location", "")
                loc_ok, loc_reason = passes_location_filter(location)
                if not loc_ok:
                    blocked_count += 1
                    logger.debug(f"[lever]   location-filtered '{title}' — {location}")
                    continue

            passed.append(posting)

        logger.info(
            f"[lever] ✓  {company}: {total} total → "
            f"{blocked_count} filtered → {len(passed)} to score"
        )

        for posting in passed:
            job = self._parse_posting(posting, company)
            if job:
                yield job

    def _parse_posting(self, posting: dict, company: str) -> RawJob:
        try:
            categories = posting.get("categories", {})
            location = self._normalize_location(categories.get("location", "Unknown"))

            description_plain = posting.get("descriptionPlain", "")
            if not description_plain:
                soup = self._parse_html(posting.get("description", ""))
                description_plain = self._clean_text(soup.get_text("\n"))

            requirements_parts = []
            for section in posting.get("lists", []):
                header = section.get("text", "")
                content_soup = self._parse_html(section.get("content", ""))
                content = self._clean_text(content_soup.get_text("\n"))
                requirements_parts.append(f"{header}\n{content}")

            requirements = "\n\n".join(requirements_parts)
            apply_url = posting.get("hostedUrl") or posting.get("applyUrl", "")

            return RawJob(
                company=company.replace("-", " ").title(),
                role=posting.get("text", ""),
                location=location,
                description=description_plain[:3000],
                requirements=requirements[:2000],
                apply_url=apply_url,
                source="lever",
                remote="remote" in location.lower(),
            )
        except Exception as e:
            logger.warning(f"[lever] Parse error for {company}: {e}")
            return None
