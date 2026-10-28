"""Ingestion errors with stable codes."""
from __future__ import annotations


class IngestError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)
