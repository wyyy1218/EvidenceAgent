"""SSRF guards: reject private/loopback/link-local/cloud-metadata targets (S15 / T11)."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata.google.internal",
        "metadata.google.com",
        "instance-data",
    }
)


def is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return True
    if addr.is_multicast or addr.is_unspecified:
        return True
    # Cloud metadata well-known
    if str(addr) in {"169.254.169.254", "169.254.170.2", "10.0.0.0"}:
        return True
    if addr.version == 4 and str(addr).startswith("169.254."):
        return True
    return False


def check_url_allowed(url: str, *, resolve: bool = True) -> tuple[bool, str]:
    """Return (allowed, reason). HTTP/HTTPS only; re-check after DNS."""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False, "malformed_url"
    if parsed.scheme not in ("http", "https"):
        return False, "scheme_not_allowed"
    host = parsed.hostname
    if not host:
        return False, "missing_host"
    if host.lower() in BLOCKED_HOSTNAMES:
        return False, "blocked_hostname"
    # Literal IP in URL
    try:
        if is_blocked_ip(host):
            return False, "blocked_ip"
    except Exception:  # noqa: BLE001
        pass
    if not resolve:
        return True, "ok_unresolved"
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return False, "dns_failed"
    for info in infos:
        ip = info[4][0]
        if is_blocked_ip(ip):
            return False, f"resolved_blocked_ip:{ip}"
    return True, "ok"


def validate_redirect_target(url: str) -> tuple[bool, str]:
    """Re-validate each redirect hop."""
    return check_url_allowed(url, resolve=True)
