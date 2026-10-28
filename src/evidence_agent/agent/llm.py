"""Unified chat client — always base route unless adapter_id explicitly set."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

DEFAULT_BASE = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/")
DEFAULT_MODEL = os.environ.get("EVIDENCE_AGENT_BASE_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    model: str = ""
    route: str = "base"


@dataclass
class LLMResponse:
    content: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 768,
        temperature: float = 0.0,
        adapter_id: str | None = None,
    ) -> LLMResponse: ...


class HttpLLMClient:
    """OpenAI-compatible client against local vLLM. Default route is base (no LoRA)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 768,
        temperature: float = 0.0,
        adapter_id: str | None = None,
        seed: int | None = None,
        guided_json: dict | None = None,
    ) -> LLMResponse:
        import time

        # Policy/Writer/Verifier use base unless adapter_id is explicitly provided
        model = adapter_id or self.model
        route = "adapter" if adapter_id else "base"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            payload["seed"] = int(seed)
        if guided_json is not None:
            # vLLM 0.10.2 OpenAI-compatible guided decoding field (see S07/S33 probes).
            payload["guided_json"] = guided_json
        t0 = time.perf_counter()
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/chat/completions", json=payload)
            latency = int((time.perf_counter() - t0) * 1000)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage_raw = data.get("usage") or {}
        usage = LLMUsage(
            input_tokens=int(usage_raw.get("prompt_tokens") or 0),
            output_tokens=int(usage_raw.get("completion_tokens") or 0),
            latency_ms=latency,
            model=data.get("model") or model,
            route=route,
        )
        return LLMResponse(content=content, usage=usage, raw=data)


class MockLLMClient:
    """Deterministic fixture client for offline tests."""

    def __init__(self, responses: list[str] | None = None, default: str = "{}") -> None:
        self._queue = list(responses or [])
        self.default = default
        self.calls: list[list[dict[str, str]]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 768,
        temperature: float = 0.0,
        adapter_id: str | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        content = self._queue.pop(0) if self._queue else self.default
        # Rough token estimate for ledger tests
        from evidence_agent.agent.tokens import count_tokens

        prompt = "\n".join(m["content"] for m in messages)
        return LLMResponse(
            content=content,
            usage=LLMUsage(
                input_tokens=count_tokens(prompt),
                output_tokens=count_tokens(content),
                latency_ms=1,
                model=adapter_id or "mock-base",
                route="adapter" if adapter_id else "base",
            ),
        )


def load_prompt(name: str) -> str:
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "configs" / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Find outermost braces
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no_json_object")
