"""One error type for every expected failure, so the API, the agent tools and the UI report it the same way."""

from __future__ import annotations

from typing import Any

from .hoard_link.agentkit import AppError


class DarwinError(AppError):
    STATUS = {"not_found": 404, "invalid": 400, "conflict": 409, "unavailable": 503, "failed": 500}

    def __init__(self, code: str, message: str, hint: str = "", *, status: int | None = None, **details: Any):
        super().__init__(code, message, hint=hint, status=status or self.STATUS.get(code, 400), details=details)
