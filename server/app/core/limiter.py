from collections.abc import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


def rate_limit(limit_string: str) -> Callable:
    """RATE_LIMIT_ENABLED=false이면 no-op 데코레이터를 반환한다."""
    from app.core.config import get_settings

    if not get_settings().RATE_LIMIT_ENABLED:

        def _noop(func: Callable) -> Callable:
            return func

        return _noop
    return limiter.limit(limit_string)
