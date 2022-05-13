import asyncio as aio
import functools
import time
from collections import deque
from typing import Callable, Coroutine, Dict, Generic, Hashable, TypeVar


T = TypeVar("T", bound=Callable[..., Coroutine])

def semaphore(value: int):
    def decorator(f: T) -> T:
        sem_ = []
        @functools.wraps(f)
        async def wrapped(*args, **kwargs):
            if not sem_:
                sem_.append(aio.Semaphore(value))
            sem = sem_[0]

            async with sem:
                return await f(*args, **kwargs)

        return wrapped  # type: ignore  # The typing works regardless.
    return decorator


USER = TypeVar("USER", bound=Hashable)
class RateLimit(Generic[USER]):
    def __init__(self, limit:int, bucket_time: int):
        self.limit = limit
        self.bucket_time = bucket_time
        self._buckets: Dict[USER, deque[float]] = {}

    def add(self, user: USER) -> bool:
        "Add a user action to the rate limit bucket and return True, or return False if the bucket is full."
        if self.is_limited(user):
            return False
        else:
            self._buckets.setdefault(user, deque(maxlen=self.limit)).append(time.monotonic())
            return True

    def is_limited(self, user: USER):
        if user not in self._buckets or len(self._buckets[user]) < self.limit:
            return False
        else:
            return time.monotonic() - self._buckets[user][0] < self.bucket_time
