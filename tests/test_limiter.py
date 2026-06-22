import threading
import time
from unittest.mock import patch

import pytest

from sheriff.core import RateLimiter
from sheriff.exceptions import RateLimitExceeded


def test_limiter_creation_defaults(limiter):
    assert isinstance(limiter, RateLimiter)
    assert limiter.capacity == 10.0
    assert limiter.refill_rate == 1.0
    assert limiter.cleanup_interval == 60.0


def test_limiter_creation_custom():
    limiter = RateLimiter(capacity=20.0, refill_rate=2.5, cleanup_interval=30.0)
    assert limiter.capacity == 20.0
    assert limiter.refill_rate == 2.5
    assert limiter.cleanup_interval == 30.0


def test_limiter_creation_max_requests():
    limiter = RateLimiter(max_requests=100, period=60.0)
    assert limiter.capacity == 100.0
    assert limiter.refill_rate == 100.0 / 60.0


def test_limiter_creation_max_requests_no_period():
    limiter = RateLimiter(max_requests=50)
    assert limiter.capacity == 50.0
    assert limiter.refill_rate == 50.0


def test_invalid_parameters():
    with pytest.raises(ValueError, match="Capacity must be greater than zero"):
        RateLimiter(capacity=0)
    with pytest.raises(ValueError, match="Capacity must be greater than zero"):
        RateLimiter(capacity=-10)
    with pytest.raises(ValueError, match="Refill rate must be greater than zero"):
        RateLimiter(refill_rate=0)
    with pytest.raises(ValueError, match="Refill rate must be greater than zero"):
        RateLimiter(refill_rate=-1)
    with pytest.raises(ValueError, match="Cleanup interval must be greater than zero"):
        RateLimiter(cleanup_interval=0)
    with pytest.raises(ValueError, match="Cleanup interval must be greater than zero"):
        RateLimiter(cleanup_interval=-5)


def test_is_allowed_basic():
    limiter = RateLimiter(capacity=3.0, refill_rate=1.0)

    assert limiter.is_allowed("user-1", tokens=1.0) is True
    assert limiter.is_allowed("user-1", tokens=2.0) is True
    # Now empty
    assert limiter.is_allowed("user-1", tokens=1.0) is False


def test_token_replenishment():
    limiter = RateLimiter(capacity=5.0, refill_rate=2.0)

    start_time = 100.0
    with patch("time.monotonic", return_value=start_time):
        assert limiter.is_allowed("user-2", tokens=5.0) is True
        assert limiter.is_allowed("user-2", tokens=1.0) is False

    # After 1.5 seconds, we should replenish 1.5 * 2 = 3.0 tokens
    with patch("time.monotonic", return_value=start_time + 1.5):
        assert limiter.is_allowed("user-2", tokens=3.0) is True
        assert limiter.is_allowed("user-2", tokens=1.0) is False

    # After another 2.5 seconds, we should replenish up to capacity (max 5)
    with patch("time.monotonic", return_value=start_time + 4.0):
        assert limiter.is_allowed("user-2", tokens=5.0) is True
        assert limiter.is_allowed("user-2", tokens=1.0) is False


def test_check_raises_exception():
    limiter = RateLimiter(capacity=2.0, refill_rate=1.0)

    start_time = 100.0
    with patch("time.monotonic", return_value=start_time):
        limiter.check("user-3", tokens=2.0)

        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check("user-3", tokens=1.0)

        assert exc_info.value.retry_after == 1.0

        # If we need 2 tokens, it will require 2 seconds
        with pytest.raises(RateLimitExceeded) as exc_info2:
            limiter.check("user-3", tokens=2.0)

        assert exc_info2.value.retry_after == 2.0


def test_consume_returns_tuple():
    limiter = RateLimiter(capacity=2.0, refill_rate=0.5)

    start_time = 100.0
    with patch("time.monotonic", return_value=start_time):
        allowed, retry_after = limiter.consume("user-4", tokens=1.5)
        assert allowed is True
        assert retry_after == 0.0

        allowed, retry_after = limiter.consume("user-4", tokens=1.0)
        assert allowed is False
        # Needs 1.0 - 0.5 = 0.5 tokens. At refill_rate 0.5, needs 1.0 second.
        assert retry_after == 1.0


def test_get_tokens():
    limiter = RateLimiter(capacity=10.0, refill_rate=2.0)

    start_time = 100.0
    with patch("time.monotonic", return_value=start_time):
        assert limiter.get_tokens("user-5") == 10.0
        assert limiter.is_allowed("user-5", tokens=4.0) is True
        assert limiter.get_tokens("user-5") == 6.0

    with patch("time.monotonic", return_value=start_time + 1.5):
        # 6.0 + 1.5 * 2 = 9.0
        assert limiter.get_tokens("user-5") == 9.0


def test_reset_and_reset_all():
    limiter = RateLimiter(capacity=5.0, refill_rate=1.0)

    limiter.is_allowed("user-a", tokens=5.0)
    limiter.is_allowed("user-b", tokens=5.0)

    assert limiter.is_allowed("user-a", tokens=1.0) is False
    assert limiter.is_allowed("user-b", tokens=1.0) is False

    limiter.reset("user-a")
    assert limiter.is_allowed("user-a", tokens=5.0) is True
    assert limiter.is_allowed("user-b", tokens=1.0) is False

    limiter.is_allowed("user-a", tokens=5.0)
    limiter.reset_all()
    assert limiter.is_allowed("user-a", tokens=5.0) is True
    assert limiter.is_allowed("user-b", tokens=5.0) is True


def test_lazy_cleanup():
    limiter = RateLimiter(capacity=5.0, refill_rate=1.0, cleanup_interval=0.1)

    # Access a key to create a bucket
    assert limiter.is_allowed("key1", tokens=1.0) is True
    assert "key1" in limiter.buckets

    # Wait, but not long enough to fully replenish
    time.sleep(0.15)

    # Access key2 to trigger cleanup check
    assert limiter.is_allowed("key2", tokens=1.0) is True
    # key1 is not fully replenished, so it shouldn't be deleted
    assert "key1" in limiter.buckets

    # Wait long enough to fully replenish key1 (needs 1.0 second to recover 1.0 token)
    time.sleep(1.0)

    # Access key2 to trigger cleanup
    assert limiter.is_allowed("key2", tokens=1.0) is True
    # key1 is now fully replenished, so it should be deleted
    assert "key1" not in limiter.buckets


def test_concurrent_consumption():
    # Thread safety check: Ensure no double-consumption
    limiter = RateLimiter(capacity=50.0, refill_rate=0.0001)

    successes = [0]
    lock = threading.Lock()

    def worker():
        for _ in range(10):
            if limiter.is_allowed("concurrent-key", tokens=1.0):
                with lock:
                    successes[0] += 1

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # With 10 threads doing 10 attempts each, total 100 attempts,
    # but capacity is 50 and refill rate is negligible.
    # Therefore, exactly 50 should succeed.
    assert successes[0] == 50
