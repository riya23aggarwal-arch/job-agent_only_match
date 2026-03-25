"""
Generic Career Page Collector

For companies that host their own career pages (not on Greenhouse/Lever/Workday).
Configured with company-specific parsing rules.

Each entry in CAREER_PAGES defines how to find jobs on that company's page.
"""

import logging
from typing import Dict, Generator, List

from job_agent.collectors.base import BaseCollector
from job_agent.models import RawJob

logger = logging.getLogger(__name__)


# Config per company: url, list_selector, title_selector, link_selector, location_selector
CAREER_PAGES: List[Dict] = [
    {
        "company": "Marvell",
        "url": "https://www.marvell.com/company/careers/search-jobs.html",
        "job_list_selector": ".job-listing-item",
        "title_selector": ".job-title",
        "location_selector": ".job-location",
        "link_selector": "a",
        "base_url": "https://www.marvell.com",
    },
    {
        "company": "Arista Networks",
        "url": "https://www.arista.com/en/careers",
        "job_list_selector": ".career-listing",
        "title_selector": "h3",
        "location_selector": ".location",
        "link_selector": "a",
        "base_url": "https://www.arista.com",
    },
    {
        "company": "Juniper Networks",
        "url": "https://www.juniper.net/us/en/company/careers/careers-overview.html",
        "job_list_selector": ".job-item",
        "title_selector": ".job-title",
        "location_selector": ".location",
        "link_selector": "a",
        "base_url": "",
    },
]

# Simple keyword-based career pages (RSS or search)
SIMPLE_SEARCH_PAGES: List[Dict] = [
    {
        "company": "Amazon",
        "search_url": "https://www.amazon.jobs/en/search.json",
        "params": {
            "base_query": "linux systems engineer",
            "loc_query": "San Jose, California, USA",
            "latitude": "37.3382",
            "longitude": "-121.8863",
            "radius": "24km",
            "job_function_id[]": ["engineering-software"],
        },
        "parser": "amazon",
    },
]


class CareerPageCollector(BaseCollector):
    source_name = "career_page"

    def __init__(self, companies: List[Dict] = None, **kwargs):
        super().__init__(**kwargs)
        self.career_configs = companies or CAREER_PAGES

    def _fetch_jobs(self) -> Generator[RawJob, None, None]:
        for config in self.career_configs:
            yield from self._scrape_career_page(config)

    def _scrape_career_page(self, config: Dict) -> Generator[RawJob, None, None]:
        company = config["company"]
        url = config["url"]

        html = self._get(url)
        if not html:
            logger.warning(f"[career_page] Could not fetch {company} careers page")
            return

        soup = self._parse_html(html)
        job_items = soup.select(config.get("job_list_selector", ".job"))

        if not job_items:
            logger.debug(f"[career_page] No jobs found for {company} with selector")
            return

        logger.info(f"[career_page] {company}: {len(job_items)} items found")

        for item in job_items:
            job = self._parse_item(item, config, company)
            if job and self._is_relevant_title(job.role):
                yield job

    def _parse_item(self, item, config: Dict, company: str) -> RawJob:
        try:
            title_el = item.select_one(config.get("title_selector", "h2"))
            loc_el = item.select_one(config.get("location_selector", ".location"))
            link_el = item.select_one(config.get("link_selector", "a"))

            title = title_el.get_text(strip=True) if title_el else ""
            location = loc_el.get_text(strip=True) if loc_el else "Unknown"
            location = self._normalize_location(location)

            href = link_el.get("href", "") if link_el else ""
            base = config.get("base_url", "")
            if href and not href.startswith("http"):
                href = base + href

            # Get job description from detail page (only if title looks relevant)
            description = ""
            requirements = ""
            if href:
                description, requirements = self._fetch_detail(href)

            return RawJob(
                company=company,
                role=title,
                location=location,
                description=description,
                requirements=requirements,
                apply_url=href,
                source="career_page",
                remote="remote" in location.lower(),
            )
        except Exception as e:
            logger.warning(f"[career_page] Error parsing {company} item: {e}")
            return None

    def _fetch_detail(self, url: str):
        """Fetch job description from detail page."""
        html = self._get(url)
        if not html:
            return "", ""

        soup = self._parse_html(html)

        # Generic approach: grab main content
        for selector in ["main", "article", ".job-description", "#job-description", ".description"]:
            el = soup.select_one(selector)
            if el:
                text = self._clean_text(el.get_text("\n"))
                lines = text.splitlines()
                # Try to split on requirements
                req_start = None
                for i, line in enumerate(lines):
                    if any(kw in line.lower() for kw in ["requirements", "qualifications", "you have"]):
                        req_start = i
                        break
                if req_start:
                    return (
                        "\n".join(lines[:req_start])[:3000],
                        "\n".join(lines[req_start:])[:2000],
                    )
                return text[:3000], ""

        return "", ""

    def _is_relevant_title(self, title: str) -> bool:
        title_lower = title.lower()
        relevant = ["engineer", "developer", "architect", "linux", "kernel", "platform", "systems"]
        irrelevant = ["manager", "director", "sales", "marketing", "finance", "legal", "hr", "recruiter"]
        has_relevant = any(r in title_lower for r in relevant)
        has_irrelevant = any(r in title_lower for r in irrelevant)
        return has_relevant and not has_irrelevant


class AmazonJobsCollector(BaseCollector):
    """Amazon uses a semi-public search JSON API."""
    source_name = "amazon_jobs"

    SEARCH_API = "https://www.amazon.jobs/en/search.json"

    def _fetch_jobs(self) -> Generator[RawJob, None, None]:
        for keyword in ["linux systems", "embedded linux", "platform engineer", "kernel engineer"]:
            data = self._get(
                self.SEARCH_API,
                params={
                    "base_query": keyword,
                    "loc_query": "San Jose, California, USA",
                    "latitude": "37.3382",
                    "longitude": "-121.8863",
                    "radius": "50km",
                    "result_limit": 10,
                },
                json_response=True,
            )
            if not data:
                continue

            for posting in data.get("jobs", []):
                job = self._parse_amazon_job(posting)
                if job:
                    yield job

    def _parse_amazon_job(self, data: dict) -> RawJob:
        try:
            location = data.get("city", "") + ", " + data.get("state", "")
            apply_url = "https://www.amazon.jobs" + data.get("job_path", "")
            return RawJob(
                company="Amazon",
                role=data.get("title", ""),
                location=self._normalize_location(location),
                description=data.get("description", "")[:3000],
                requirements=data.get("basic_qualifications", "")[:2000],
                apply_url=apply_url,
                source="amazon_jobs",
                remote="remote" in data.get("location", "").lower(),
            )
        except Exception as e:
            logger.warning(f"[amazon] Parse error: {e}")
            return None
