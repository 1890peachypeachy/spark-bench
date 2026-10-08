"""KV prefill catch-up: hash, roll, color, warmup."""

from .service import (
    COLORS,
    REASONS,
    CatchupService,
    SessionState,
    apply_rolling_window,
    color_for,
    estimate_prompt_tokens,
    hash_snapshot,
    normalize_snapshot,
)
from .switch import CatchupSwitch

__all__ = [
    "CatchupSwitch",
    "COLORS",
    "REASONS",
    "CatchupService",
    "SessionState",
    "apply_rolling_window",
    "color_for",
    "estimate_prompt_tokens",
    "hash_snapshot",
    "normalize_snapshot",
]
