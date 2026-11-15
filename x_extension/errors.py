"""Safe SDK error envelopes."""

from typing import Any


def failure(code: str, message: str, *, unknown: bool = False, **extra: Any) -> dict:
    return {
        "ok": False,
        "result": {},
        "error_code": code,
        "error": message,
        "errors": [{"code": code, "message": message}],
        "external_effect_status": "timeout_unknown" if unknown else "failed",
        "definitely_no_external_effect": not unknown,
        **extra,
    }
