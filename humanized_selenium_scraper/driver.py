from __future__ import annotations

import os
import random
import re
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from .config import ScraperConfig

# Characters that could be used for command injection in Chrome arguments.
# Backslash is blocked here because it can be used for escaping in shell-like contexts.
_DANGEROUS_ARG_CHARS = re.compile(r'["\'\n\r\t`$\\]')
# Characters that are unsafe in profile directory input. Backslash is allowed
# to support Windows-style paths such as C:\Users\...\chrome_profile.
_DANGEROUS_PATH_CHARS = re.compile(r'["\'\n\r\t`$]')
_RNG = random.SystemRandom()


def _validate_safe_for_chrome_arg(value: str, name: str) -> str:
    """Validate that a string is safe to pass as a Chrome command-line argument.

    Raises ValueError if the value contains characters that could be used for
    command injection or argument splitting.
    """
    if _DANGEROUS_ARG_CHARS.search(value):
        raise ValueError(
            f"Invalid {name}: the value contains characters that are not allowed "
            f"(quotes, backticks, dollar signs, or backslashes). "
            f"Please remove these characters and try again."
        )
    return value


def _validate_path_safe(path: Path) -> Path:
    """Validate that a path is safe to use as a Chrome profile directory.

    Raises ValueError if the path contains dangerous characters or patterns.
    """
    path_str = str(path)
    if _DANGEROUS_PATH_CHARS.search(path_str):
        raise ValueError(
            f"Invalid Chrome profile directory path: {path_str!r}\n"
            "The path must not contain quotes, backticks, or dollar signs."
        )
    # Resolve to absolute path to prevent directory traversal
    return path.resolve()


def create_driver(config: ScraperConfig, *, profile_dir: Path) -> webdriver.Chrome:
    user_agents = config.user_agents or [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    ]
    window_sizes = config.window_sizes or [(1280, 720)]
    user_agent = _RNG.choice(user_agents)
    raw_w, raw_h = _RNG.choice(window_sizes)
    try:
        width = max(1, min(4096, int(raw_w)))
        height = max(1, min(4096, int(raw_h)))
    except (TypeError, ValueError):
        width, height = 1280, 720

    # Validate inputs to prevent command injection
    safe_user_agent = _validate_safe_for_chrome_arg(user_agent, "user agent")
    safe_profile_dir = _validate_path_safe(profile_dir)

    chrome_opts = Options()
    try:
        os.makedirs(safe_profile_dir, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            f"Cannot create Chrome profile directory at {safe_profile_dir}: {exc}"
        ) from exc
    chrome_opts.add_argument(f"--user-data-dir={safe_profile_dir}")
    chrome_opts.add_argument(f"--user-agent={safe_user_agent}")
    chrome_opts.add_argument(f"--window-size={width},{height}")

    driver = webdriver.Chrome(service=Service(), options=chrome_opts)
    driver.set_page_load_timeout(config.page_load_timeout_s)
    driver.implicitly_wait(config.implicit_wait_s)
    return driver
