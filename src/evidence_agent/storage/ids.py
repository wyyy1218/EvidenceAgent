"""ID generators."""
from __future__ import annotations

import secrets
import time


def new_id(prefix: str) -> str:
    ts = int(time.time() * 1000) % 10_000_000
    return f"{prefix}_{ts:07d}_{secrets.token_hex(4)}"
