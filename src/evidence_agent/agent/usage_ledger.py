"""Usage / billing ledger — logical tools, physical requests, cache, credits (S20)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from evidence_agent.storage.ids import new_id
from evidence_agent.storage import repositories as repo


@dataclass
class UsageLedger:
    run_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    logical_tool_calls: int = 0
    physical_requests: int = 0
    cache_hits: int = 0
    api_credits: float = 0.0
    billing_unknown_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(
        self,
        conn,
        *,
        kind: str,
        step_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        logical_tool_call: bool = False,
        physical_request: bool = False,
        cache_hit: bool = False,
        credits: float = 0.0,
        billing_status: str | None = "n/a",
        meta: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> str:
        eid = new_id("usage")
        if logical_tool_call:
            self.logical_tool_calls += 1
        if physical_request:
            self.physical_requests += 1
        if cache_hit:
            self.cache_hits += 1
        if billing_status == "billing_unknown" or billing_status == "unknown":
            self.billing_unknown_count += 1
        self.api_credits += float(credits or 0)
        self.input_tokens += int(input_tokens)
        self.output_tokens += int(output_tokens)
        ev = {
            "id": eid,
            "kind": kind,
            "step_id": step_id,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "logical_tool_call": logical_tool_call,
            "physical_request": physical_request,
            "cache_hit": cache_hit,
            "credits": credits,
            "billing_status": billing_status,
            "meta": meta or {},
        }
        self.events.append(ev)
        if persist and conn is not None:
            conn.execute(
                "INSERT INTO usage_events("
                "id, run_id, provider, model, tokens, latency, credits, billing_status, "
                "created_at, step_id, kind, input_tokens, output_tokens, logical_tool_call, "
                "physical_request, cache_hit, meta_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    eid,
                    self.run_id,
                    provider,
                    model,
                    int(input_tokens) + int(output_tokens),
                    None,
                    credits,
                    billing_status,
                    repo.utc_now(),
                    step_id,
                    kind,
                    input_tokens,
                    output_tokens,
                    1 if logical_tool_call else 0,
                    1 if physical_request else 0,
                    1 if cache_hit else 0,
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
        return eid

    def summary(self) -> dict[str, Any]:
        return {
            "logical_tool_calls": self.logical_tool_calls,
            "physical_requests": self.physical_requests,
            "cache_hits": self.cache_hits,
            "api_credits": self.api_credits,
            "billing_unknown_count": self.billing_unknown_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "event_count": len(self.events),
        }
