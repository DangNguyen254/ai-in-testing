"""Decorators shared by tests: retry for known-flaky steps, browser and deployment skips."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

import pytest
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

from framework.config import CONFIG

F = TypeVar("F", bound=Callable[..., Any])

RETRYABLE: tuple[type[BaseException], ...] = (
    AssertionError,
    TimeoutException,
    StaleElementReferenceException,
)


def retry(times: int = 2, delay: float = 1.0) -> Callable[[F], F]:
    """Re-run a flaky test body up to ``times`` extra times. Flakiness is handled in code."""

    def decorate(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(times + 1):
                try:
                    return func(*args, **kwargs)
                except RETRYABLE:
                    if attempt == times:
                        raise
                    time.sleep(delay)
            return None  # unreachable

        return wrapper  # type: ignore[return-value]

    return decorate


def skip_browser(*browsers: str, reason: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(CONFIG.browser in browsers, reason=f"{CONFIG.browser}: {reason}")


cloud_only = pytest.mark.skipif(CONFIG.deployment != "cloud", reason="cloud-only test")
on_prem_only = pytest.mark.skipif(CONFIG.deployment != "on_prem", reason="on-prem-only test")
