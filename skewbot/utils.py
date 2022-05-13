import asyncio as aio
import functools
from typing import Any, Callable, Coroutine, TypeVar


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
