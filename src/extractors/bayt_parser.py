import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

from .utils import (
    HttpClient,
    HttpSettings,
    build_absolute_url,
    clean_text,
    get_logger,
    parse_relative_date,
)

@dataclass
class JobListing:
    searchUrl: str
    jobTitle: str
    jobLink: str
    jobSalary: str
    jobType: str
    jobCareerLevel: str
    jobCompanyLogo: str
    jobCompany: str
    jobLocation: str
    jobDescription: str
    jobCreatedAt: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "searchUrl": self.searchUrl,
            "jobTitle": self.jobTitle,
            "jobLink": self.jobLink,
            "jobSalary": self.jobSalary,
            "jobType": self.jobType,
            "jobCareerLevel": self.jobCareerLevel,
            "jobCompanyLogo": self.jobCompanyLogo,
            "jobCompany": self.jobCompany,
            "jobLocation": self.jobLocation,
            "jobDescription": self.jobDescription,
            "jobCreatedAt": self.jobCreatedAt,
        }

class BaytJobScraper:
    """
    Scraper responsible for crawling Bayt.com job listings for one or more search URLs.

    This implementation is defensive: if Bayt changes its HTML,
    it will fail gracefully and log details instead of crashing.
    """

    def __init__(
        self,
        http_settings: Optional[HttpSettings] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or get_logger(self.__class__.__name__)
        self.client = HttpClient(http_settings or HttpSettings(), logger=self.logger)

    def scrape_searches(
        self, searches: Iterable[Dict], max_items_fallback: int
    ) -> List[Dict[str, str]]:
        """
        Scrape multiple search configurations.

        Each search config is expected to be a dict with at least:
          - url: str
          - maxItems: Optional[int]
        """
        all_jobs: List[Dict[str, str]] = []
        for search in searches:
            url = search.get("url")
            if not url:
                self.logger.warning("Skipping search with missing 'url' key: %s", search)
                continue
            max_items = int(search.get("maxItems") or max_items_fallback)
            self.logger.info("Scraping Bayt search URL: %s (max_items=%s)", url, max_items)
            jobs = self._scrape_single_search(url, max_items)
            self.logger.info("Found %s jobs for search URL: %s", len(jobs), url)
            all_jobs.extend(job.to_dict() for job in jobs)
        return all_jobs

    def _scrape_single_search(self, search_url: str, max_items: int) -> List[JobListing]:
        """Scrape a single Bayt search URL with pagination."""
        results: List[JobListing] = []
        next_url: Optional[str] = search_url

        while next_url and len(results) < max_items:
            html = self.client.fetch(next_url)
            if html is None:
                self.logger.error("Failed to fetch page: %s", next_url)
                break

            jobs, next_url = self._parse_listing_page(html, search_url, next_url)
            for job in jobs:
                if len(results) >= max_items:
                    break
                results.append(job)

            if not next_url:
                break

        return results

    def _parse_listing_page(
        self, html: str, search_url: str, current_url: str
    ) -> Tuple[List[JobListing], Optional[str]]:
        """
        Parse a listing page and return (jobs, next_page_url).

        This method attempts several known patterns for Bayt.com markup.
        If none match, it logs debug information and returns an empty list.
        """
        soup = BeautifulSoup(html, "lxml")

        job_cards = self._find_job_cards(soup)
        if not job_cards:
            self.logger.warning("No job cards found for page: %s", current_url)

        jobs: List[JobListing] = []
        for card in job_cards:
            try:
                job = self._parse_job_card(card, search_url, current_url)
                if job:
                    jobs.append(job)
            except Exception as exc:  # defensive parsing
                self.logger.error("Error parsing job card on %s: %s", current_url, exc)

        next_page_url = self._find_next_page_url(soup, current_url)
        return jobs, next_page_url

    # --------- Parsing helpers --------- #

    def _find_job_cards(self, soup: BeautifulSoup) -> List:
        """
        Attempt to locate job cards using multiple possible CSS selectors.
        """
        selectors = [
            "div.has-pointer-d",  # one of Bayt's common job card classes
            "div.job-card",
            "li.job",  # generic
            "article.job",  # generic
        ]
        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                self.logger.debug("Found %s job cards using selector '%s'", len(cards), selector)
                return cards
        # Fallback: pick list items that look like job posts
        cards = soup.find_all("li")
        self.logger.debug("Using fallback selector; found %s li elements", len(cards))
        return cards

    def _parse_job_card(
        self, card: BeautifulSoup, search_url: str, current_url: str
    ) -> Optional[JobListing]:
        """
        Extract job information from a single card.

        Uses several heuristics for title, link, company, etc.
        """
        # Title and link
        title_el = card.select_one("h2 a, h3 a, a.job-title, a.js-job-title")
        if not title_el:
            # try any primary <a> in the card
            title_el = card.find("a")

        job_title = clean_text(title_el.get_text()) if title_el else ""
        job_link_raw = title_el.get("href") if title_el else ""
        job_link = build_absolute_url(current_url, job_link_raw)

        # Company
        company_el = card.select_one(".company, .company-name, .jbHeading span a, .jbHeading span")
        job_company = clean_text(company_el.get_text()) if company_el else ""

        # Location
        location_el = card.select_one(".location, .jbLoc, .job-location")
        job_location = clean_text(location_el.get_text()) if location_el else ""

        # Salary
        salary_el = card.select_one(".salary, .job-salary")
        job_salary = clean_text(salary_el.get_text()) if salary_el else ""

        # Type
        type_el = card.select_one(".job-type, .jbType, .employment-type")
        job_type = clean_text(type_el.get_text()) if type_el else ""

        # Career level
        career_el = card.find(string=lambda s: s and "Career Level" in s)
        job_career_level = ""
        if career_el:
            # Typically text like 'Career Level: Mid Career'
            text = career_el.strip()
            parts = text.split(":")
            if len(parts) > 1:
                job_career_level = clean_text(parts[1])

        # Company logo
        logo_el = card.select_one("img[alt*=logo], img[src*='logo']")
        job_company_logo = ""
        if logo_el and logo_el.get("src"):
            job_company_logo = build_absolute_url(current_url, logo_el["src"])

        # Description
        desc_el = card.select_one(".job-desc, .job-description, .jbDescription, p")
        job_description = clean_text(desc_el.get_text()) if desc_el else ""

        # Created at / date
        date_el = card.select_one(".date, .jbDate, .job-date")
        job_created_at_raw = clean_text(date_el.get_text()) if date_el else ""
        job_created_at = parse_relative_date(job_created_at_raw) if job_created_at_raw else ""

        if not job_title and not job_link:
            # This doesn't look like a real job card
            self.logger.debug("Skipping card without title and link on %s", current_url)
            return None

        return JobListing(
            searchUrl=search_url,
            jobTitle=job_title,
            jobLink=job_link,
            jobSalary=job_salary,
            jobType=job_type,
            jobCareerLevel=job_career_level,
            jobCompanyLogo=job_company_logo,
            jobCompany=job_company,
            jobLocation=job_location,
            jobDescription=job_description,
            jobCreatedAt=job_created_at,
        )

    def _find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """
        Try to discover the 'next page' link.

        Fallbacks to rel=next, specific classes, or numeric pagination.
        """
        # Common patterns
        link = soup.select_one("a[rel='next']")
        if link and link.get("href"):
            next_url = build_absolute_url(current_url, link["href"])
            self.logger.debug("Next page (rel=next) -> %s", next_url)
            return next_url

        link = soup.select_one("a.next, a.pagination-next, li.next a")
        if link and link.get("href"):
            next_url = build_absolute_url(current_url, link["href"])
            self.logger.debug("Next page (class-based) -> %s", next_url)
            return next_url

        # Try pagination with numeric pages, pick a selected page and go to next sibling
        current_page_li = soup.select_one("ul.pagination li.active, ul.pagination li.selected")
        if current_page_li:
            next_li = current_page_li.find_next_sibling("li")
            if next_li:
                next_link = next_li.find("a")
                if next_link and next_link.get("href"):
                    next_url = build_absolute_url(current_url, next_link["href"])
                    self.logger.debug("Next page (numeric pagination) -> %s", next_url)
                    return next_url

        self.logger.debug("No next page found for %s", current_url)
        return None