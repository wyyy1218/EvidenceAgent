"""HTTP fetch + Trafilatura extract with SSRF / size / redirect limits."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from evidence_agent.tools.ssrf import check_url_allowed, validate_redirect_target
from evidence_agent.tools.types import ToolResult, ToolStatus, fail

DEFAULT_MAX_MIB = 5
DEFAULT_REDIRECT_LIMIT = 3
DEFAULT_TIMEOUT = 15.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_main_text(html: str, url: str) -> tuple[str, str | None]:
    """Return (text, canonical_url). Uses trafilatura when available."""
    try:
        import trafilatura

        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True) or ""
        meta = trafilatura.extract_metadata(html)
        canonical = None
        if meta is not None:
            canonical = getattr(meta, "url", None) or None
        return text.strip(), canonical
    except Exception:  # noqa: BLE001
        # Minimal fallback: strip tags poorly — mark as unsupported if empty
        import re

        text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text, None


def fetch_url(
    url: str,
    *,
    root: Path | None = None,
    max_mib: int = DEFAULT_MAX_MIB,
    redirect_limit: int = DEFAULT_REDIRECT_LIMIT,
    timeout: float = DEFAULT_TIMEOUT,
    save_snapshot: bool = True,
) -> ToolResult:
    tool = "web_fetch"
    allowed, reason = check_url_allowed(url)
    if not allowed:
        return fail(
            tool,
            ToolStatus.PERMISSION_DENIED,
            error_code="ssrf_blocked",
            error_message=reason,
            meta={"url": url},
        )

    max_bytes = max_mib * 1024 * 1024
    hops = 0
    current = url
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            max_redirects=0,
            headers={"User-Agent": "EvidenceAgent/0.1 (+research; not a browser-agent)"},
        ) as client:
            while True:
                resp = client.get(current)
                if resp.status_code in {301, 302, 303, 307, 308}:
                    hops += 1
                    if hops > redirect_limit:
                        return fail(
                            tool,
                            ToolStatus.INACCESSIBLE,
                            error_code="too_many_redirects",
                            error_message=f"exceeded {redirect_limit} redirects",
                            meta={"url": url, "last": current},
                        )
                    loc = resp.headers.get("location")
                    if not loc:
                        return fail(
                            tool,
                            ToolStatus.INACCESSIBLE,
                            error_code="redirect_without_location",
                            error_message="redirect missing Location",
                        )
                    # resolve relative
                    next_url = str(httpx.URL(current).join(loc))
                    ok, why = validate_redirect_target(next_url)
                    if not ok:
                        return fail(
                            tool,
                            ToolStatus.PERMISSION_DENIED,
                            error_code="ssrf_redirect_blocked",
                            error_message=why,
                            meta={"from": current, "to": next_url},
                        )
                    current = next_url
                    continue

                if resp.status_code in {401, 403}:
                    return fail(
                        tool,
                        ToolStatus.PERMISSION_DENIED,
                        error_code=f"http_{resp.status_code}",
                        error_message="auth / forbidden — not retried",
                        billing_status="n/a",
                        meta={"url": current},
                    )
                if resp.status_code >= 400:
                    return fail(
                        tool,
                        ToolStatus.INACCESSIBLE,
                        error_code=f"http_{resp.status_code}",
                        error_message=f"HTTP {resp.status_code}",
                        meta={"url": current},
                    )

                ctype = (resp.headers.get("content-type") or "").lower()
                if "html" not in ctype and "text" not in ctype and "xml" not in ctype:
                    return fail(
                        tool,
                        ToolStatus.UNSUPPORTED,
                        error_code="unsupported_content_type",
                        error_message=ctype or "unknown",
                        meta={"url": current},
                    )

                body = resp.content
                if len(body) > max_bytes:
                    return fail(
                        tool,
                        ToolStatus.UNSUPPORTED,
                        error_code="body_too_large",
                        error_message=f">{max_mib}MiB",
                        meta={"url": current, "bytes": len(body)},
                    )

                html = body.decode(resp.encoding or "utf-8", errors="replace")
                text, canonical = extract_main_text(html, current)
                if not text.strip():
                    return fail(
                        tool,
                        ToolStatus.INACCESSIBLE,
                        error_code="empty_body",
                        error_message="extracted body empty (login wall / dynamic page / extract fail)",
                        meta={"url": current, "note": "summary_must_not_become_evidence"},
                    )

                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                snap_meta = {
                    "url": url,
                    "final_url": current,
                    "canonical_url": canonical or current,
                    "fetched_at": _utc(),
                    "content_hash": content_hash,
                    "bytes": len(body),
                    "status": "ok",
                }
                snap_path = None
                if save_snapshot and root is not None:
                    snap_id = content_hash[:16]
                    dest = root / "data" / "snapshots" / snap_id
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / "content.txt").write_text(text, encoding="utf-8")
                    (dest / "meta.json").write_text(
                        json.dumps(snap_meta, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    snap_path = f"data/snapshots/{snap_id}"

                return ToolResult(
                    tool=tool,
                    status=ToolStatus.OK,
                    data={
                        "url": url,
                        "final_url": current,
                        "canonical_url": canonical or current,
                        "text": text,
                        "content_hash": content_hash,
                        "snapshot_path": snap_path,
                        "fetched_at": snap_meta["fetched_at"],
                    },
                    billing_status="n/a",
                    meta={"redirects": hops},
                )
    except httpx.TimeoutException:
        return fail(
            tool,
            ToolStatus.TIMEOUT,
            error_code="fetch_timeout",
            error_message=f"timeout after {timeout}s",
            meta={"url": url},
        )
    except httpx.HTTPError as exc:
        return fail(
            tool,
            ToolStatus.INACCESSIBLE,
            error_code="http_error",
            error_message=str(exc),
            meta={"url": url},
        )
