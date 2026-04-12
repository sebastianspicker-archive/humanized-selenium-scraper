from __future__ import annotations

import random
import time

_RNG = random.SystemRandom()


def human_type(element, text: str) -> None:
    for ch in text:
        element.send_keys(ch)
        time.sleep(_RNG.uniform(0.05, 0.3))


def random_pause(base_s: float = 1.0, var_s: float = 2.0) -> None:
    time.sleep(base_s + _RNG.random() * var_s)


def do_infinite_scrolling(driver, max_scroll: int = 3, pause_s: float = 1.0) -> None:
    height_script = "return document.body ? document.body.scrollHeight : 0"
    last_height = driver.execute_script(height_script) or 0
    for _ in range(max_scroll):
        driver.execute_script("var b = document.body; if (b) window.scrollTo(0, b.scrollHeight);")
        time.sleep(pause_s)
        new_height = driver.execute_script(height_script) or 0
        if new_height == last_height:
            break
        last_height = new_height
