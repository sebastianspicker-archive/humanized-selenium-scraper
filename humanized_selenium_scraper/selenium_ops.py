from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

from selenium.common.exceptions import (
    ElementNotInteractableException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import ScraperConfig
from .human import random_pause


def click_element_robust(driver, elem, tries: int = 2) -> bool:
    for attempt in range(tries):
        try:
            elem.click()
            return True
        except ElementNotInteractableException:
            logging.warning(
                "element not interactable (attempt %s) => scroll + actionchains fallback",
                attempt + 1,
            )
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                time.sleep(0.5)
                ActionChains(driver).move_to_element(elem).pause(0.5).click().perform()
                return True
            except Exception as exc:
                logging.warning("ActionChains fallback failed: %s", exc)
        except Exception as exc:
            logging.warning("click_element_robust failed: %s", exc)
            return False
    return False


def click_cookie_consent_if_present(driver) -> None:
    # Selectors for common consent buttons (EN + DE wording)
    possible_selectors = [
        (
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),'akzeptieren')]"
        ),
        "//button[contains(.,'Alle akzeptieren')]",
        "//button[contains(@id,'accept')]",
        "//button[contains(.,'Zustimmen')]",
        "//div[contains(.,'Zustimmen')]",
        "//button[@aria-label='Accept all']",
        "//button[contains(@class,'cookie') and contains(@class,'accept')]",
    ]

    def _try_selectors(d):
        for selector in possible_selectors:
            try:
                # Use a short timeout per selector to avoid long hangs
                btn = WebDriverWait(d, 1).until(EC.element_to_be_clickable((By.XPATH, selector)))
                if click_element_robust(d, btn, tries=1):
                    time.sleep(0.5)
                    logging.info("Cookie consent clicked by selector: %s", selector)
                    return True
            except Exception as exc:
                logging.debug("Cookie selector %s failed: %s", selector, exc)
                continue
        return False

    # 1. Try main document
    if _try_selectors(driver):
        return

    # 2. Try common iframes
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            if _try_selectors(driver):
                driver.switch_to.default_content()
                return
            driver.switch_to.default_content()
        except Exception as exc:
            try:
                driver.switch_to.default_content()
            except Exception as inner:
                logging.debug("switch_to.default_content failed: %s", inner)
            logging.debug("Cookie consent iframe check failed: %s", exc)
            continue

    logging.info("No matching cookie consent selector found (not critical).")


def safe_get(driver, config: ScraperConfig, url: str) -> bool:
    """Navigate to ``url``, returning whether the page loaded.

    Returns False without navigating for URLs the scraper refuses to load:
    PDFs, non-http(s) schemes, and pages whose certificate is invalid. Transient
    load failures are retried up to ``config.max_retries`` times, after which
    False is returned. Callers decide whether a failed load should skip the row
    or just the candidate (see ``scraper.Session.search``).
    """
    if url.lower().strip().endswith(".pdf"):
        logging.info("SKIP PDF => %s", url)
        return False

    if urlparse(url).scheme not in ("http", "https"):
        logging.info("SKIP non-http(s) URL => %s", url)
        return False

    for attempt in range(config.max_retries):
        try:
            if driver.current_url == url:
                return True
            driver.get(url)
            # Wait for body but also check for typical error indicators
            WebDriverWait(driver, config.element_wait_timeout_s).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            return True
        except TimeoutException:
            logging.warning(
                "Timeout => attempt=%s/%s, url=%s", attempt + 1, config.max_retries, url
            )
        except WebDriverException as exc:
            if "ERR_CERT_DATE_INVALID" in str(exc):
                logging.info("Skipping insecure (cert) => %s", url)
                return False
            logging.warning(
                "WebDriverException => %s (attempt=%s/%s)", exc, attempt + 1, config.max_retries
            )

        if attempt + 1 < config.max_retries:
            random_pause(1, 1.5)

    return False
