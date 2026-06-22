import pytest

from sheriff.core import RateLimiter


@pytest.fixture
def limiter():
    """Returns a basic RateLimiter instance."""
    return RateLimiter()
