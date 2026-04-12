"""
Backward-compatible entrypoint.

Prefer running via:
  - `python -m humanized_selenium_scraper`
  - or `python HumanizedSeleniumScraper.py`
"""

from humanized_selenium_scraper.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
