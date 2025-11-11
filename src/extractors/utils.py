import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from dateutil.relativedelta import relativedelta

DEFAULT_LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"

def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a sensible default format."""
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)

def get_logger(name: str) -> logging.Logger:
    """Get a configured logger."""
    return logging.getLogger(name)

@dataclass
class HttpSettings:
    user_agent: str = "Mozilla/5.0 (compatible; BaytJobsScraper/1.0)"
    timeout: int = 15
    max_retries: int = 3
    backoff_factor: float = 0.5
    proxies: Optional[Dict[str, str]] = None
    delay_between_requests_seconds: float = 1.0

class HttpClient:
    """Simple HTTP client with retry and backoff."""

    def __init__(self, settings: HttpSettings, logger: Optional[logging.Logger] = None) -> None:
        self.settings = settings
        self.logger = logger or get_logger(self.__class__.__name__)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.settings.user_agent})

    def fetch(self, url: str) -> Optional[str]:
        """Fetch a URL with retries. Returns response text or None on failure."""
        delay = self.settings.backoff_factor
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                self.logger.debug("Requesting URL (attempt %s): %s", attempt, url)
                response = self.session.get(
                    url,
                    timeout=self.settings.timeout,
                    proxies=self.settings.proxies,
                )
                if response.status_code >= 400:
                    self.logger.warning(
                        "Non-success status code %s for %s", response.status_code, url
                    )
                response.raise_for_status()
                if self.settings.delay_between_requests_seconds > 0:
                    time.sleep(self.settings.delay_between_requests_seconds)
                return response.text
            except requests.RequestException as exc:
                self.logger.error(
                    "Error fetching %s on attempt %s/%s: %s",
                    url,
                    attempt,
                    self.settings.max_retries,
                    exc,
                )
                if attempt == self.settings.max_retries:
                    break
                time.sleep(delay)
                delay *= 2
        return None

def clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    if text is None:
        return ""
    # Remove HTML entities-like artifacts if present
    cleaned = re.sub(r"\s+", " ", text)
    return cleaned.strip()

def build_absolute_url(base_url: str, link: str) -> str:
    """Turn a relative link into an absolute URL based on the base_url."""
    if not link:
        return ""
    return urljoin(base_url, link)

def parse_relative_date(date_str: str, now: Optional[datetime] = None) -> str:
    """
    Parse a relative date like '10 days ago' into ISO-8601 date string.
    If parsing fails, return the original string.
    """
    if not date_str:
        return ""
    now = now or datetime.utcnow()
    text = date_str.strip().lower()

    # Handle 'today', 'yesterday'
    if text == "today":
        return now.date().isoformat()
    if text == "yesterday":
        return (now - timedelta(days=1)).date().isoformat()

    # Basic 'X day(s)/week(s)/month(s)/year(s) ago'
    match = re.match(r"(\d+)\s+(day|days|week|weeks|month|months|year|years)\s+ago", text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        delta_kwargs: Dict[str, int] = {}

        if "day" in unit:
            delta_kwargs["days"] = value
        elif "week" in unit:
            delta_kwargs["weeks"] = value
        elif "month" in unit:
            delta_kwargs["months"] = value
        elif "year" in unit:
            delta_kwargs["years"] = value

        parsed = (now - relativedelta(**delta_kwargs)).date().isoformat()
        return parsed

    # Fallback: return original string
    return date_str.strip()

def load_json_file(path: Path, logger: Optional[logging.Logger] = None) -> Any:
    """Load JSON from a file with basic error handling."""
    log = logger or get_logger("load_json_file")
    try:
        if not path.exists():
            log.error("JSON file does not exist: %s", path)
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        log.error("Failed to decode JSON from %s: %s", path, exc)
        return None
    except OSError as exc:
        log.error("Error reading JSON file %s: %s", path, exc)
        return None

def ensure_directory(path: Path) -> None:
    """Ensure a directory exists."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger = get_logger("ensure_directory")
        logger.error("Unable to create directory %s: %s", path, exc)