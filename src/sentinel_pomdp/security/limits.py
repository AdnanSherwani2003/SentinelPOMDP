"""Input and process-local request-rate limits."""
from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from .errors import ResourceLimitError
from .models import SecurityLimits


class InMemoryRateLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, principal_id: str) -> None:
        with self._lock:
            now = monotonic()
            entries = self._requests[principal_id]
            while entries and entries[0] <= now - 60:
                entries.popleft()
            if len(entries) >= self.limit:
                raise ResourceLimitError("Request limit exceeded")
            entries.append(now)


def validate_request_limits(question: str, horizon: int, max_tool_calls: int,
                            budget: float, limits: SecurityLimits) -> None:
    if not question.strip() or len(question) > limits.max_question_chars:
        raise ResourceLimitError("Question length is outside the allowed range")
    if horizon < 0 or horizon > limits.max_horizon:
        raise ResourceLimitError("Planning horizon is outside the allowed range")
    if max_tool_calls < 0 or max_tool_calls > limits.max_tool_calls:
        raise ResourceLimitError("Tool-call limit is outside the allowed range")
    if budget < 0 or budget > limits.max_budget:
        raise ResourceLimitError("Investigation budget is outside the allowed range")
