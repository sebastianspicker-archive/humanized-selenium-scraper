from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import ScraperConfig
from .driver import create_driver
from .exceptions import SkipEntryError
from .extract_selenium import parse_phone_email_deep
from .human import do_infinite_scrolling, human_type, random_pause
from .relevance import evaluate_page
from .selenium_ops import click_cookie_consent_if_present, safe_get
from .spec import SearchSpec, render_templates
from .url_filter import is_relevant_url

# Common legal/contact link labels (DE + EN) for subpage link priority
IMPO_KEYWORDS = ("impressum", "kontakt", "datenschutz", "imprint", "contact", "privacy")


def link_priority(element: Any) -> int:
    """Sort key: contact/legal links first, everything else second."""
    try:
        text = (element.text or "").lower()
        href = (element.get_attribute("href") or "").lower()
        if any(keyword in text or keyword in href for keyword in IMPO_KEYWORDS):
            return 0
    except Exception as exc:
        logging.debug("link_priority failed: %s", exc)
    return 1


def page_is_relevant(page_source: str, row: dict[str, str], spec: SearchSpec) -> bool:
    """Evaluate a page source against the row's relevance rules."""
    keywords = [
        keyword.lower() for keyword in render_templates(spec.relevance.keyword_templates, row)
    ]
    return evaluate_page(
        page_source,
        keywords=keywords,
        min_keyword_hits=spec.relevance.min_total_keyword_hits,
        require_address=spec.relevance.require_address,
        street=row.get(spec.relevance.address.street_field, ""),
        plz=row.get(spec.relevance.address.zip_field, ""),
        city=row.get(spec.relevance.address.city_field, ""),
        address_min_score=spec.relevance.address.min_score,
    )


def _element_href(element: Any) -> str | None:
    try:
        return element.get_attribute("href")
    except StaleElementReferenceException:
        logging.warning("Stale link => skipping")
        return None


def find_relevant_page(
    driver: Any,
    config: ScraperConfig,
    *,
    url: str,
    row: dict[str, str],
    spec: SearchSpec,
    max_depth: int,
    _visited: set[str] | None = None,
) -> str | None:
    """Return a relevant URL at ``url`` or, failing that, in its same-domain subtree.

    The starting URL is checked first so an already-relevant page is returned
    as-is. Otherwise same-domain links (contact/legal pages first) are followed
    depth-first up to ``max_depth`` levels. Link-level load failures just skip
    that link.
    """
    if _visited is None:
        _visited = set()
    if url.lower().endswith(".pdf") or url in _visited:
        return None
    _visited.add(url)

    if not safe_get(driver, config, url):
        return None

    do_infinite_scrolling(driver, max_scroll=3, pause_s=1.2)
    if page_is_relevant(driver.page_source, row, spec):
        return url

    if max_depth <= 0:
        return None

    try:
        links = driver.find_elements(By.TAG_NAME, "a")[: spec.navigation.max_links_per_page]
    except StaleElementReferenceException as exc:
        logging.warning("Subpage links became stale => %s", exc)
        return None

    domain = urlparse(url).netloc.lower()
    for link in sorted(links, key=link_priority):
        href = _element_href(link)
        if not href or href.lower().endswith(".pdf"):
            continue
        if urlparse(href).netloc.lower() != domain:
            continue
        if href in _visited:
            continue

        found = find_relevant_page(
            driver,
            config,
            url=href,
            row=row,
            spec=spec,
            max_depth=max_depth - 1,
            _visited=_visited,
        )
        if found is not None:
            return found

    return None


@dataclass
class Session:
    config: ScraperConfig
    driver: Any
    counter: int = 0

    @classmethod
    def create(cls, config: ScraperConfig, *, profile_dir: Path) -> Session:
        return cls(config=config, driver=create_driver(config, profile_dir=profile_dir))

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception as exc:
            logging.debug("Driver quit failed (non-fatal): %s", exc)

    def maybe_restart_driver(self, *, profile_dir: Path) -> None:
        if self.counter == 0:
            return
        if self.config.restart_threshold <= 0:
            return
        if self.counter % self.config.restart_threshold != 0:
            return

        logging.info("Restart driver => threshold")
        new_driver = create_driver(self.config, profile_dir=profile_dir)
        try:
            self.driver.quit()
        except Exception as exc:
            logging.debug("Driver quit during restart failed (non-fatal): %s", exc)
        self.driver = new_driver

    def search(
        self, *, query: str, row: dict[str, str], spec: SearchSpec
    ) -> tuple[str | None, str | None, str | None]:
        """Search Google for one row and return (relevant URL, phone, email).

        An unreachable Google page skips the whole row (SkipEntryError). A failed
        candidate or subpage load only skips that candidate. Returns empty results
        when no candidate is relevant.
        """
        self.maybe_restart_driver(profile_dir=self.config.chrome_profile_root)
        self.counter += 1

        google_url = f"https://www.{self.config.google_domain}/"
        if not safe_get(self.driver, self.config, google_url):
            raise SkipEntryError(
                f"Could not load {google_url}. Google may be unreachable, blocking, or offline."
            )

        random_pause(1, 1.5)
        try:
            click_cookie_consent_if_present(self.driver)
        except Exception as exc:
            logging.debug("Cookie consent click failed (non-fatal): %s", exc)

        if not self._submit_search(query):
            raise SkipEntryError(
                "Google did not return a usable search page for this query; skipping the row."
            )

        for href in self._collect_result_hrefs(spec):
            if not self._is_candidate_url(query, href, spec):
                continue

            target_url = self._find_target(href, row, spec)
            if target_url is None:
                continue
            if not safe_get(self.driver, self.config, target_url):
                continue

            do_infinite_scrolling(self.driver, max_scroll=1, pause_s=1.0)
            phone, email = self._extract(spec)
            return target_url, phone, email

        return None, None, None

    def _submit_search(self, query: str) -> bool:
        try:
            search_box = WebDriverWait(self.driver, self.config.element_wait_timeout_s).until(
                EC.element_to_be_clickable((By.NAME, "q"))
            )
        except Exception as exc:
            logging.warning("Google search box not found: %s", exc)
            return False

        human_type(search_box, query)
        random_pause(0.5, 1.0)
        search_box.send_keys(Keys.RETURN)
        random_pause(1, 2)

        try:
            WebDriverWait(self.driver, self.config.search_results_timeout_s).until(
                EC.presence_of_element_located((By.ID, "search"))
            )
        except Exception as exc:
            logging.warning("Google did not return search results: %s", exc)
            return False

        do_infinite_scrolling(self.driver, max_scroll=2, pause_s=1.0)
        return True

    def _collect_result_hrefs(self, spec: SearchSpec) -> list[str]:
        """Return the candidate result hrefs from the current Google results page."""
        result_links = self.driver.find_elements(By.XPATH, "//a[contains(@href,'http')]")
        top = result_links[: spec.navigation.max_google_results]
        random.shuffle(top)

        hrefs: list[str] = []
        for link in top:
            href = _element_href(link)
            if href:
                hrefs.append(href)
        return hrefs

    def _is_candidate_url(self, query: str, href: str, spec: SearchSpec) -> bool:
        return is_relevant_url(
            query,
            href,
            allowed_tlds=spec.url_filter.allowed_tlds,
            domain_keyword_blacklist=spec.url_filter.domain_keyword_blacklist,
            domain_match=spec.url_filter.domain_match,
            min_query_part_len=spec.url_filter.min_query_part_len,
        )

    def _find_target(self, href: str, row: dict[str, str], spec: SearchSpec) -> str | None:
        """Return a relevant URL for a candidate, exploring subpages when configured."""
        if spec.navigation.subpage_depth <= 0:
            if safe_get(self.driver, self.config, href) and page_is_relevant(
                self.driver.page_source, row, spec
            ):
                return href
            return None

        return find_relevant_page(
            self.driver,
            self.config,
            url=href,
            row=row,
            spec=spec,
            max_depth=spec.navigation.subpage_depth,
        )

    def _extract(self, spec: SearchSpec) -> tuple[str | None, str | None]:
        if not (spec.extract_phone or spec.extract_email):
            return None, None
        phone, email = parse_phone_email_deep(self.driver)
        if not spec.extract_phone:
            phone = None
        if not spec.extract_email:
            email = None
        return phone, email
