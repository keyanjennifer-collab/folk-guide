"""AI 问答短窗口限流。

这是不依赖额外服务的开发/单实例实现，按用户 ID 统计最近窗口内的请求次数。
生产多 worker 或多副本部署时，应把同样的算法迁移到 Redis，并保留数据库中的
每日权益次数作为最终业务上限；本地字典不能作为分布式安全边界。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class AIRateLimitExceeded(RuntimeError):
    """用户在短时间内请求过于频繁。"""


class InMemoryAIRateLimiter:
    """线程安全的固定窗口近似滑动限流器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, max_requests: int, window_seconds: float) -> None:
        """记录一次请求，超过上限时抛出业务异常。"""
        limit = max(1, int(max_requests))
        window = max(1.0, float(window_seconds))
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            cutoff = now - window
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise AIRateLimitExceeded
            events.append(now)
            # 顺手回收长时间不再访问的键，避免用户量增长造成进程内存持续增长。
            if len(self._events) > 10000:
                stale_keys = [name for name, values in self._events.items() if not values]
                for stale_key in stale_keys[:2000]:
                    self._events.pop(stale_key, None)

    def reset(self) -> None:
        """测试和开发重启时清空计数。"""
        with self._lock:
            self._events.clear()


_limiter = InMemoryAIRateLimiter()


def enforce_ai_rate_limit(
    user_id: int,
    *,
    enabled: bool,
    max_requests: int,
    window_seconds: float,
) -> None:
    """按配置执行用户级短窗口限流；关闭时不创建任何外部依赖。"""
    if not enabled:
        return
    _limiter.check(
        f"user:{user_id}",
        max_requests=max_requests,
        window_seconds=window_seconds,
    )


def reset_ai_rate_limit_for_tests() -> None:
    """仅供自动化测试清理进程内计数。"""
    _limiter.reset()
