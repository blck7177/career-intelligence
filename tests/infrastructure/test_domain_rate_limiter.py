from __future__ import annotations

import time

import redis

from packages.infrastructure.redis.domain_rate_limiter import (
    DomainRateLimiter,
    extract_host,
)


class FakeRedis:
    """Minimal in-memory stand-in for the SET NX EX calls the limiter needs."""

    def __init__(self) -> None:
        self._store: dict[str, float] = {}  # key -> expiry (monotonic time)

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        now = time.monotonic()
        expiry = self._store.get(key)
        if expiry is not None and expiry > now:
            return False  # key still live -> NX fails
        self._store[key] = now + (ex or 0)
        return True


class RaisingRedis:
    def set(self, *args, **kwargs):
        raise redis.exceptions.ConnectionError("boom")


class TestExtractHost:
    def test_extracts_lowercased_hostname(self):
        assert extract_host("https://Boards.Greenhouse.io/acme/jobs/123") == "boards.greenhouse.io"

    def test_returns_empty_string_for_unparseable_url(self):
        assert extract_host("not a url") == ""


class TestDomainRateLimiter:
    def test_first_fetch_to_a_host_acquires_immediately(self):
        limiter = DomainRateLimiter(r=FakeRedis())
        start = time.monotonic()
        acquired = limiter.wait_and_acquire(
            "https://boards.greenhouse.io/acme/jobs/1", min_interval_seconds=2.0, max_wait_seconds=5.0
        )
        assert acquired is True
        assert time.monotonic() - start < 0.1

    def test_second_fetch_to_same_host_waits_then_acquires(self):
        fake = FakeRedis()
        limiter = DomainRateLimiter(r=fake)
        url = "https://boards.greenhouse.io/acme/jobs/1"
        limiter.wait_and_acquire(url, min_interval_seconds=0.5, max_wait_seconds=5.0)

        start = time.monotonic()
        acquired = limiter.wait_and_acquire(url, min_interval_seconds=0.5, max_wait_seconds=5.0)
        elapsed = time.monotonic() - start

        assert acquired is True
        assert elapsed >= 0.4  # had to wait roughly one interval

    def test_different_hosts_do_not_block_each_other(self):
        fake = FakeRedis()
        limiter = DomainRateLimiter(r=fake)
        limiter.wait_and_acquire(
            "https://boards.greenhouse.io/acme/jobs/1", min_interval_seconds=5.0, max_wait_seconds=5.0
        )
        start = time.monotonic()
        acquired = limiter.wait_and_acquire(
            "https://jobs.lever.co/acme/jobs/2", min_interval_seconds=5.0, max_wait_seconds=5.0
        )
        assert acquired is True
        assert time.monotonic() - start < 0.1

    def test_gives_up_after_max_wait_and_fails_open(self):
        fake = FakeRedis()
        limiter = DomainRateLimiter(r=fake)
        url = "https://boards.greenhouse.io/acme/jobs/1"
        limiter.wait_and_acquire(url, min_interval_seconds=5.0, max_wait_seconds=5.0)

        acquired = limiter.wait_and_acquire(url, min_interval_seconds=5.0, max_wait_seconds=0.5)
        assert acquired is False

    def test_unparseable_url_passes_through_without_limiting(self):
        limiter = DomainRateLimiter(r=FakeRedis())
        assert limiter.wait_and_acquire("not a url") is True

    def test_redis_error_fails_open(self):
        limiter = DomainRateLimiter(r=RaisingRedis())
        acquired = limiter.wait_and_acquire(
            "https://boards.greenhouse.io/acme/jobs/1", max_wait_seconds=1.0
        )
        assert acquired is False
