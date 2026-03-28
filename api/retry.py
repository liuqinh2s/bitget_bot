"""
重试装饰器：统一处理网络异常
"""
from __future__ import annotations

import functools
import time
from typing import Callable, TypeVar

from ..infra.logger import log

F = TypeVar("F", bound=Callable)

_RETRYABLE = (ConnectionError, TimeoutError, OSError)


def retry(
    max_attempts: int = 3,
    delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple = _RETRYABLE,
) -> Callable[[F], F]:
    """
    重试装饰器

    :param max_attempts: 最大重试次数
    :param delay:        初始延迟（秒）
    :param backoff:      延迟倍增系数
    :param exceptions:   需要重试的异常类型
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            wait = delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    log.warning(
                        "%s 第 %d/%d 次重试，异常: %s",
                        func.__name__, attempt, max_attempts, e,
                    )
                    if attempt < max_attempts:
                        time.sleep(wait)
                        wait *= backoff
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
