"""Stable public operability contracts shared by the HTTP API and CLI."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import IntEnum
from typing import Any
from uuid import uuid4

API_MAJOR_VERSION = 1
API_CONTRACT_VERSION = "1.0"
API_VERSION_HEADER = "X-CFR-API-Version"
REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"

INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
SERVICE_NOT_READY = "SERVICE_NOT_READY"
UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
REQUEST_VALIDATION_FAILED = "REQUEST_VALIDATION_FAILED"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"


class CliExitCode(IntEnum):
    """Documented process results; values are stable within API major version 1."""

    SUCCESS = 0
    INVALID_REQUEST = 2
    MORE_INPUT = 10
    UNRESOLVED = 11
    INTERNAL_FAILURE = 70


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def request_id(value: Any = None) -> str:
    """Return a safe caller ID or a generated opaque ID without reflecting arbitrary text."""

    candidate = str(value or "").strip()
    return candidate if _SAFE_ID.fullmatch(candidate) else str(uuid4())


def error_detail(reason_code: str, message: str) -> dict[str, str]:
    return {"reason_code": reason_code, "message": message}


def cli_exit_code(payload: Mapping[str, Any]) -> CliExitCode:
    status = str(payload.get("status", "")).casefold()
    if status in {"recommendation_ready", "locked", "reference_review_required"}:
        return CliExitCode.SUCCESS
    if status == "more_input_needed":
        return CliExitCode.MORE_INPUT
    return CliExitCode.UNRESOLVED


__all__ = [
    "API_CONTRACT_VERSION",
    "API_MAJOR_VERSION",
    "API_VERSION_HEADER",
    "CORRELATION_ID_HEADER",
    "CliExitCode",
    "INTERNAL_SERVER_ERROR",
    "REQUEST_VALIDATION_FAILED",
    "REQUEST_ID_HEADER",
    "RESOURCE_NOT_FOUND",
    "SERVICE_NOT_READY",
    "UNSUPPORTED_MEDIA_TYPE",
    "cli_exit_code",
    "error_detail",
    "request_id",
]
