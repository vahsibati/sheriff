# Sheriff 🤠

An elegant, thread-safe, in-memory rate limiter for Python.

`sheriff` implements the **Token Bucket** algorithm, ensuring complete thread-safety with fine-grained locking and zero-leak memory management. It is designed to be lightweight, dependency-free, and extremely easy to integrate into any application or web framework (like FastAPI).

---

## Features

- 🔒 **Thread-Safe**: Uses fine-grained concurrent locks to ensure rate-limiting consistency across multiple threads.
- 🪣 **Token Bucket Algorithm**: Standard token bucket rate limiting with lazy, high-precision token replenishment.
- 🧹 **Self-Cleaning (Lazy Cleanup)**: Prunes stale/fully-replenished buckets from memory automatically to prevent memory leaks.
- ⚡ **Zero Dependencies**: Pure Python, built using standard library tools.
- 🚀 **FastAPI / Web Ready**: Fits perfectly into FastAPI's dependency injection (`Depends`) system.

---

## Installation

Install using `pip`:

```bash
pip install sheriff-limiter
```

---

## Quick Start

### Basic Usage

Use `is_allowed` for a simple boolean check:

```python
from sheriff import RateLimiter

# Default: 10 requests capacity, replenishes 1 token per second
limiter = RateLimiter()

# Check if allowed
if limiter.is_allowed("user_ip_address"):
    print("Request allowed!")
else:
    print("Rate limit exceeded.")
```

### Configuration Options

Initialize the limiter with custom parameters:

```python
from sheriff import RateLimiter

# Configured for max 100 requests per minute
limiter = RateLimiter(max_requests=100, period=60.0)

# Or set capacity and refill rate directly
# Capacity of 5 tokens, refilling 0.5 tokens/sec
limiter = RateLimiter(capacity=5.0, refill_rate=0.5)
```

---

## Advanced Features

### 1. Raising Exceptions on Exceeding Limits

You can use `.check()` which raises a `RateLimitExceeded` exception. The exception contains a `retry_after` parameter telling you how long to wait in seconds.

```python
from sheriff import RateLimiter, RateLimitExceeded

limiter = RateLimiter(max_requests=5, period=10.0)

try:
    # Consume 1 token
    limiter.check("client_1")
except RateLimitExceeded as e:
    print(f"Rate limit exceeded! Retry after {e.retry_after:.2f} seconds.")
```

### 2. Manual Resets

Clear specific keys or reset all rate limits entirely:

```python
# Reset a single client
limiter.reset("client_1")

# Reset all clients and clear the memory cache
limiter.reset_all()
```

---

## FastAPI Integration

`sheriff` is perfect for FastAPI dependencies. Here is how you can use it to rate-limit endpoints by IP address:

```python
from fastapi import FastAPI, Depends, Request, HTTPException, status
from sheriff import RateLimiter, RateLimitExceeded

app = FastAPI()

# 100 requests per minute limit
limiter = RateLimiter(max_requests=100, period=60.0)

def rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    try:
        limiter.check(client_ip)
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(int(e.retry_after or 0))}
        )

@app.get("/items", dependencies=[Depends(rate_limit)])
async def read_items():
    return {"status": "ok"}
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
