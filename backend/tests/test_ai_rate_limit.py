"""AI短窗口限流器测试。"""

import pytest

from app.ai_rate_limit import (
    AIRateLimitExceeded,
    InMemoryAIRateLimiter,
    enforce_ai_rate_limit,
)


def test_limiter_blocks_after_configured_number_of_requests():
    limiter = InMemoryAIRateLimiter()
    limiter.check("user:1", max_requests=2, window_seconds=60)
    limiter.check("user:1", max_requests=2, window_seconds=60)
    with pytest.raises(AIRateLimitExceeded):
        limiter.check("user:1", max_requests=2, window_seconds=60)


def test_limiter_isolated_by_key_and_can_be_disabled():
    limiter = InMemoryAIRateLimiter()
    limiter.check("user:1", max_requests=1, window_seconds=60)
    limiter.check("user:2", max_requests=1, window_seconds=60)
    # 关闭开关时不触碰进程内限流器，适合本地测试和离线管理任务。
    enforce_ai_rate_limit(
        1, enabled=False, max_requests=1, window_seconds=60
    )


def test_reset_clears_counter():
    limiter = InMemoryAIRateLimiter()
    limiter.check("user:1", max_requests=1, window_seconds=60)
    limiter.reset()
    limiter.check("user:1", max_requests=1, window_seconds=60)
