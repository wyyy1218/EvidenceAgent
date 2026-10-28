"""Hard budget executor — check before call; reserve Writer/Verifier output (S20)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BudgetConfig:
    tool_calls: int = 8
    live_search: int = 3
    input_tokens: int = 48000
    output_tokens: int = 4096
    final_output_reserve: int = 1536  # Writer+Verifier
    wall_seconds: float = 240.0
    model_call_timeout_seconds: float = 60.0
    max_model_len: int = 8192
    invalid_action_repairs: int = 1


@dataclass
class BudgetState:
    cfg: BudgetConfig = field(default_factory=BudgetConfig)
    tool_calls_used: int = 0
    live_search_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    started_at: float = field(default_factory=time.monotonic)
    stopped_reason: str | None = None

    def remaining_wall(self) -> float:
        return max(0.0, self.cfg.wall_seconds - (time.monotonic() - self.started_at))

    def model_timeout(self) -> float:
        return min(self.cfg.model_call_timeout_seconds, self.remaining_wall())

    def output_left_including_reserve(self, *, for_final: bool) -> int:
        left = self.cfg.output_tokens - self.output_tokens_used
        if for_final:
            return left
        # Non-final calls must leave reserve for Writer/Verifier
        return left - self.cfg.final_output_reserve

    def can_call_tool(self, *, live_search: bool = False) -> tuple[bool, str | None]:
        if self.stopped_reason:
            return False, self.stopped_reason
        if self.remaining_wall() <= 0:
            return False, "timeout"
        if self.tool_calls_used >= self.cfg.tool_calls:
            return False, "tool_budget_exhausted"
        if live_search and self.live_search_used >= self.cfg.live_search:
            return False, "live_search_exhausted"
        # Need reserve for final write/verify
        if self.output_left_including_reserve(for_final=False) < 0:
            return False, "output_reserve_blocked"
        return True, None

    def can_call_model(
        self,
        *,
        max_input: int,
        max_output: int,
        is_final_writer_or_verifier: bool = False,
    ) -> tuple[bool, str | None]:
        if self.stopped_reason:
            return False, self.stopped_reason
        if self.remaining_wall() <= 0:
            return False, "timeout"
        if max_input + max_output > self.cfg.max_model_len:
            return False, "context_too_large"
        if self.input_tokens_used + max_input > self.cfg.input_tokens:
            return False, "input_token_budget"
        out_left = self.output_left_including_reserve(for_final=is_final_writer_or_verifier)
        if max_output > out_left:
            return False, "output_token_budget_or_reserve"
        return True, None

    def record_tool(self, *, live_search: bool = False) -> None:
        self.tool_calls_used += 1
        if live_search:
            self.live_search_used += 1

    def record_tokens(self, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens_used += int(input_tokens)
        self.output_tokens_used += int(output_tokens)

    def stop(self, reason: str) -> None:
        self.stopped_reason = reason

    def snapshot(self) -> dict[str, Any]:
        return {
            "tool_calls_used": self.tool_calls_used,
            "tool_calls_limit": self.cfg.tool_calls,
            "live_search_used": self.live_search_used,
            "live_search_limit": self.cfg.live_search,
            "input_tokens_used": self.input_tokens_used,
            "output_tokens_used": self.output_tokens_used,
            "final_output_reserve": self.cfg.final_output_reserve,
            "remaining_wall_seconds": self.remaining_wall(),
            "stopped_reason": self.stopped_reason,
            "output_left_non_final": self.output_left_including_reserve(for_final=False),
        }

    def visible_budget(self) -> dict[str, Any]:
        return {
            "tool_calls_left": max(0, self.cfg.tool_calls - self.tool_calls_used),
            "live_search_left": max(0, self.cfg.live_search - self.live_search_used),
            "input_tokens_left": max(0, self.cfg.input_tokens - self.input_tokens_used),
            "output_tokens_left": max(0, self.cfg.output_tokens - self.output_tokens_used),
            "final_output_reserve": self.cfg.final_output_reserve,
            "remaining_wall_seconds": round(self.remaining_wall(), 1),
        }


def load_budget_from_project(cfg: dict[str, Any] | None = None) -> BudgetConfig:
    cfg = cfg or {}
    b = cfg.get("budget") or {}
    g = cfg.get("generation") or {}
    w = cfg.get("web") or {}
    return BudgetConfig(
        tool_calls=int(b.get("tool_calls", 8)),
        live_search=int(w.get("max_live_search_calls", 3)),
        input_tokens=int(b.get("input_tokens", 48000)),
        output_tokens=int(b.get("output_tokens", 4096)),
        final_output_reserve=int(b.get("final_output_reserve", 1536)),
        wall_seconds=float(b.get("wall_seconds", 240)),
        model_call_timeout_seconds=float(b.get("model_call_timeout_seconds", 60)),
        max_model_len=int(g.get("max_model_len", 8192)),
        invalid_action_repairs=int(b.get("invalid_action_repairs", 1)),
    )
