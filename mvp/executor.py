"""Thread pools sized for a 108-agent study.

asyncio's default pool has min(32, cpus + 4) workers (12 on the 8-CPU box).
Study 390909cf (zo_pf3) parked dozens of signup email waits in that pool
(``asyncio.to_thread(inbox.wait, ...)`` blocks 15-75s each). Every Gemini step
call starts with ``asyncio.to_thread(vertex_credentials)``, so those calls
queued behind the mail waits and hit the 10s/20s step timeout: 56 "model
action timed out" lines, 5 agents that never acted, and a 24s first action.

``ensure_default_executor`` swaps in a large default pool once per loop, and
``MAIL_POOL`` keeps long IMAP waits off it entirely.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_DONE: set[int] = set()


def _int_env(name: str, default: int) -> int:
    try:
        return max(4, int(os.environ.get(name) or default))
    except ValueError:
        return default


MAIL_POOL = ThreadPoolExecutor(
    max_workers=_int_env("MVP_MAIL_THREADS", 96), thread_name_prefix="mvp-mail"
)


def ensure_default_executor(loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """Give ``loop`` a big default pool (MVP_THREADS, default 256). Idempotent."""
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        return False
    key = id(loop)
    if key in _DONE:
        return False
    size = _int_env("MVP_THREADS", 256)
    loop.set_default_executor(ThreadPoolExecutor(max_workers=size, thread_name_prefix="mvp"))
    _DONE.add(key)
    print(f"[executor] default thread pool set to {size} workers", flush=True)
    return True


async def run_mail(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a blocking mail call on the dedicated mail pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(MAIL_POOL, lambda: fn(*args))
