from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock


class LoginRateLimiter:
    def __init__(self, attempts: int = 5, window: timedelta = timedelta(minutes=5)) -> None:
        self.attempts = attempts
        self.window = window
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def is_limited(self, key: str) -> bool:
        with self._lock:
            failures = self._recent_failures(key)
            return len(failures) >= self.attempts

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent_failures(key).append(datetime.now(UTC))

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _recent_failures(self, key: str) -> deque[datetime]:
        failures = self._failures[key]
        cutoff = datetime.now(UTC) - self.window
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures
