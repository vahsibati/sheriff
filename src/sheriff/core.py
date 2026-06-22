import time
from threading import Lock
from typing import Dict, Optional, Tuple

from sheriff.exceptions import RateLimitExceeded


class TokenBucket:
    """Represents a single Token Bucket for rate limiting a specific key."""

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_updated = time.monotonic()
        self.lock = Lock()

    def consume(self, tokens: float = 1.0) -> Tuple[bool, float]:
        """Consume tokens from the bucket.

        Returns:
            Tuple[bool, float]: (allowed, retry_after)
            where allowed is True if consumed, False otherwise.
            retry_after is the number of seconds to wait before there's enough tokens.
        """
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_updated
            if elapsed > 0:
                self.tokens = min(
                    self.capacity, self.tokens + elapsed * self.refill_rate
                )
                self.last_updated = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, 0.0

            needed = tokens - self.tokens
            retry_after = needed / self.refill_rate
            return False, retry_after

    def get_tokens(self) -> float:
        """Returns the current number of tokens in the bucket after replenishment."""
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_updated
            if elapsed > 0:
                self.tokens = min(
                    self.capacity, self.tokens + elapsed * self.refill_rate
                )
                self.last_updated = now
            return self.tokens

    def reset(self) -> None:
        """Resets the bucket to its full capacity."""
        with self.lock:
            self.tokens = self.capacity
            self.last_updated = time.monotonic()

    def is_full(self, now: float) -> bool:
        """Check if the bucket is fully replenished.
        Must be called under RateLimiter container lock or self.lock.
        """
        with self.lock:
            elapsed = now - self.last_updated
            current_tokens = min(
                self.capacity, self.tokens + elapsed * self.refill_rate
            )
            return current_tokens >= self.capacity


class RateLimiter:
    """Core class representing the Sheriff thread-safe, in-memory rate limiter."""

    def __init__(
        self,
        capacity: float = 10.0,
        refill_rate: float = 1.0,
        max_requests: Optional[int] = None,
        period: Optional[float] = None,
        cleanup_interval: float = 60.0,
    ):
        """Initializes the RateLimiter.

        Args:
            capacity: Maximum number of tokens a bucket can hold. Defaults to 10.0.
            refill_rate: Number of tokens added to the bucket per second.
                Defaults to 1.0.
            max_requests: Optional parameter to initialize capacity using requests.
            period: Optional parameter to specify the period in seconds for
                max_requests.
            cleanup_interval: Time in seconds between periodic cleanup sweeps of
                fully replenished buckets. Defaults to 60.0.
        """
        if max_requests is not None:
            capacity = float(max_requests)
            if period is not None:
                refill_rate = capacity / period
            else:
                refill_rate = capacity

        if capacity <= 0:
            raise ValueError("Capacity must be greater than zero.")
        if refill_rate <= 0:
            raise ValueError("Refill rate must be greater than zero.")
        if cleanup_interval <= 0:
            raise ValueError("Cleanup interval must be greater than zero.")

        self.capacity = capacity
        self.refill_rate = refill_rate
        self.cleanup_interval = cleanup_interval

        self.buckets: Dict[str, TokenBucket] = {}
        self.lock = Lock()
        self.last_cleanup = time.monotonic()

    def _get_bucket(self, key: str) -> TokenBucket:
        """Thread-safe retrieval or creation of a TokenBucket for a given key.
        Also triggers lazy cleanup if the cleanup interval has elapsed.
        """
        with self.lock:
            self._maybe_cleanup()
            if key not in self.buckets:
                self.buckets[key] = TokenBucket(self.capacity, self.refill_rate)
            return self.buckets[key]

    def _maybe_cleanup(self) -> None:
        """Prunes fully replenished buckets from memory.
        Must be called with self.lock held.
        """
        now = time.monotonic()
        if now - self.last_cleanup >= self.cleanup_interval:
            keys_to_delete = []
            for key, bucket in self.buckets.items():
                if bucket.is_full(now):
                    keys_to_delete.append(key)
            for key in keys_to_delete:
                del self.buckets[key]
            self.last_cleanup = now

    def is_allowed(self, key: str, tokens: float = 1.0) -> bool:
        """Check if the request is allowed under the rate limit.

        Args:
            key: Unique identifier for the client or bucket.
            tokens: Number of tokens to consume. Defaults to 1.0.

        Returns:
            bool: True if the request is allowed, False otherwise.
        """
        bucket = self._get_bucket(key)
        allowed, _ = bucket.consume(tokens)
        return allowed

    def check(self, key: str, tokens: float = 1.0) -> None:
        """Check if the request is allowed under the rate limit.
        Raises RateLimitExceeded if not.

        Args:
            key: Unique identifier for the client or bucket.
            tokens: Number of tokens to consume. Defaults to 1.0.

        Raises:
            RateLimitExceeded: If the key is rate-limited.
        """
        bucket = self._get_bucket(key)
        allowed, retry_after = bucket.consume(tokens)
        if not allowed:
            raise RateLimitExceeded(
                message=f"Rate limit exceeded for key: {key}",
                retry_after=retry_after,
            )

    def consume(self, key: str, tokens: float = 1.0) -> Tuple[bool, float]:
        """Consume tokens from the bucket for the given key.

        Args:
            key: Unique identifier for the client or bucket.
            tokens: Number of tokens to consume. Defaults to 1.0.

        Returns:
            Tuple[bool, float]: (allowed, retry_after)
                where allowed is True if consumed, False otherwise.
                retry_after is the number of seconds to wait before there are
                enough tokens.
        """
        bucket = self._get_bucket(key)
        return bucket.consume(tokens)

    def get_tokens(self, key: str) -> float:
        """Returns the current number of tokens available in the bucket for the key.

        Args:
            key: Unique identifier for the client or bucket.

        Returns:
            float: Current number of tokens.
        """
        bucket = self._get_bucket(key)
        return bucket.get_tokens()

    def reset(self, key: str) -> None:
        """Reset the rate limit bucket for the given key.

        Args:
            key: Unique identifier for the client or bucket.
        """
        with self.lock:
            bucket = self.buckets.get(key)
            if bucket is not None:
                bucket.reset()

    def reset_all(self) -> None:
        """Reset all rate limit buckets, clearing the internal cache."""
        with self.lock:
            self.buckets.clear()
