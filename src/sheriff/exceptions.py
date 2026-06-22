from typing import Optional


class SheriffError(Exception):
    """Base exception for all Sheriff rate limiter errors."""

    pass


class RateLimitExceeded(SheriffError):
    """Exception raised when a rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
