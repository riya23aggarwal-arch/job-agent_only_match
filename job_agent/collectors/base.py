"""
Base collector — all platform collectors inherit from this.
Handles HTTP sessions, rate limiting, dedup, and structured output.
"""

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from typing import Generator, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from job_agent.models import RawJob

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class BaseCollector(ABC):
    """
    Abstract base for all job collectors.
    Subclasses implement _fetch_jobs().
    """

    source_name: str = "unknown"
    rate_limit_seconds: float = 1.5   # be polite

    def __init__(self, keywords: List[str] = None, locations: List[str] = None):
        self.keywords = keywords or ["software engineer", "systems engineer", "linux engineer"]
        self.locations = locations or ["San Jose CA", "San Francisco CA", "Remote"]
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        return session

    def collect(self) -> Generator[RawJob, None, None]:
        """Main entry point — yields RawJob objects."""
        logger.info(f"[{self.source_name}] Starting collection")
        count = 0
        errors = 0

        for job in self._fetch_jobs():
            try:
                job.job_id = self._make_job_id(job)
                yield job
                count += 1
                # Rate limiting is handled inside each collector's _fetch_jobs()
                # No extra sleep here — it was doubling the delay
            except Exception as e:
                logger.warning(f"[{self.source_name}] Job processing error: {e}")
                errors += 1

        logger.info(f"[{self.source_name}] Done: {count} jobs collected, {errors} errors")

    @abstractmethod
    def _fetch_jobs(self) -> Generator[RawJob, None, None]:
        """Subclasses implement this to yield RawJob objects."""
        pass

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _get(self, url: str, params: dict = None, json_response: bool = False):
        """Safe GET with retry and error handling."""
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=8)
                resp.raise_for_status()
                return resp.json() if json_response else resp.text
            except requests.HTTPError as e:
                if e.response.status_code == 429:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"Rate limited — waiting {wait}s")
                    time.sleep(wait)
                elif e.response.status_code in (404, 410):
                    return None
                else:
                    raise
            except requests.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt+1}/3): {e}")
                time.sleep(1 * (attempt + 1))
        return None

    def _parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def _clean_text(self, text: str) -> str:
        """Strip excess whitespace from scraped text."""
        if not text:
            return ""
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _make_job_id(job: RawJob) -> str:
        """Deterministic ID from URL so we don't re-process the same job."""
        key = (job.apply_url or job.company + job.role).encode()
        return hashlib.sha1(key).hexdigest()[:12].upper()

    @staticmethod
    def _normalize_location(loc: str) -> str:
        if not loc:
            return "Unknown"
        loc = loc.strip()
        if any(r in loc.lower() for r in ["remote", "anywhere", "distributed"]):
            return "Remote"
        return loc
